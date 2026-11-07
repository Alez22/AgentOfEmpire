"""@brief Resolve one turn (one month) of the city.

The step sequence is part of the specification: changing it changes the
results, so any change must be versioned. Integer arithmetic only.
Step order: orders -> fixed rules -> construction -> taxes and upkeep ->
production -> food consumption -> spoilage -> demography -> worker rescale -> mood
-> unrest -> closing.

Taxes and upkeep run BEFORE production (the design doc listed them
after): unpaid upkeep halves the output of the same month, so it must be
known before production is computed.
"""

import copy
from dataclasses import dataclass

from engine.config import Config
from engine.orders import Order
from engine.state import Event, GameState, Workers
from engine.validator import OrderResult, apply_orders

SEASONS = ("winter", "spring", "summer", "autumn")


@dataclass
class TurnResult:
    state: GameState
    order_results: list[OrderResult]
    events: list[Event]


def season_of(turn: int) -> str:
    """@brief Turn 1 is January; three months per season, winter first."""
    month_index = (turn - 1) % 12
    return SEASONS[month_index // 3]


def jobs_in_sector(state: GameState, config: Config, sector: str) -> int:
    """@brief Jobs offered by the active buildings of one sector."""
    return sum(
        config.buildings[b.kind].jobs
        for b in state.buildings
        if b.turns_left == 0 and config.buildings[b.kind].sector == sector
    )


def housing_capacity(state: GameState, config: Config) -> int:
    """@brief People the active houses can shelter."""
    return sum(
        config.buildings[b.kind].housing for b in state.buildings if b.turns_left == 0
    )


def monthly_tax_income(state: GameState, config: Config) -> int:
    """@brief Gold the taxes bring this month at the current rate."""
    return state.adults * state.tax_rate // config.economy.tax_divisor


def monthly_upkeep(state: GameState, config: Config) -> int:
    """@brief Gold owed this month for the active buildings."""
    active_buildings = sum(1 for b in state.buildings if b.turns_left == 0)
    return active_buildings * config.economy.upkeep_gold_per_building


def _ration_pct(state: GameState, config: Config) -> int:
    economy = config.economy
    return {
        "reduced": economy.ration_reduced_pct,
        "normal": economy.ration_normal_pct,
        "abundant": economy.ration_abundant_pct,
    }[state.ration]


def food_needed(state: GameState, config: Config) -> int:
    """@brief Food the population eats this month at the current ration."""
    economy = config.economy
    base_need = (
        state.children * economy.food_per_child
        + state.adults * economy.food_per_adult
        + state.elders * economy.food_per_elder
    )
    return base_need * _ration_pct(state, config) // 100


def _apply_fixed_rules(state: GameState, config: Config, events: list[Event]) -> None:
    """@brief Stand-in for Jev: if the reserve is low, idle adults go to food."""
    alert_level = config.economy.reserve_alert_months * food_needed(state, config)
    if state.food >= alert_level:
        return
    idle_adults = state.adults - state.workers.total()
    free_farm_jobs = jobs_in_sector(state, config, "food") - state.workers.food
    moved = min(idle_adults, free_farm_jobs)
    if moved <= 0:
        return
    state.workers.food += moved
    events.append(Event("rule_workers_to_food", {"moved": moved}))


def _advance_construction(state: GameState, events: list[Event]) -> None:
    for building in state.buildings:
        if building.turns_left == 0:
            continue
        building.turns_left -= 1
        if building.turns_left == 0:
            events.append(Event("building_completed", {"kind": building.kind}))


def _collect_taxes_and_upkeep(state: GameState, config: Config, events: list[Event]) -> bool:
    """@brief Add tax income, then pay upkeep of active buildings.
    @return True if the upkeep was paid in full.
    """
    state.gold += monthly_tax_income(state, config)
    upkeep = monthly_upkeep(state, config)
    if state.gold < upkeep:
        # Nothing is paid: keeping gold at zero would hide the problem.
        events.append(Event("upkeep_unpaid", {"upkeep": upkeep, "gold": state.gold}))
        return False
    state.gold -= upkeep
    return True


def _sector_output(
    state: GameState, config: Config, sector: str, building_kind: str, upkeep_paid: bool
) -> int:
    economy = config.economy
    employed = min(getattr(state.workers, sector), jobs_in_sector(state, config, sector))
    output = employed * config.buildings[building_kind].output_per_worker
    if sector == "food":
        season_pct = {
            "winter": economy.farm_winter_pct,
            "spring": economy.farm_spring_pct,
            "summer": economy.farm_summer_pct,
            "autumn": economy.farm_autumn_pct,
        }[season_of(state.turn)]
        output = output * season_pct // 100
    if state.unrest == "strike":
        output = output * config.unrest.strike_output_pct // 100
    if not upkeep_paid:
        output = output * economy.unpaid_upkeep_output_pct // 100
    return output


def _produce(state: GameState, config: Config, upkeep_paid: bool) -> None:
    state.food += _sector_output(state, config, "food", "farm", upkeep_paid)
    state.wood += _sector_output(state, config, "wood", "sawmill", upkeep_paid)
    state.stone += _sector_output(state, config, "stone", "quarry", upkeep_paid)


def _consume_food(state: GameState, config: Config, events: list[Event]) -> tuple[int, int]:
    """@brief Eat this month's food; a shortfall becomes famine.
    @return (food needed this month, missing food in percent 0..100).
    """
    needed = food_needed(state, config)
    if state.food >= needed:
        state.food -= needed
        return needed, 0
    # needed > food >= 0 here, so needed > 0 and the division is safe.
    missing_pct = (needed - state.food) * 100 // needed
    state.food = 0
    events.append(Event("famine", {"missing_pct": missing_pct}))
    return needed, missing_pct


def _spoil_food(state: GameState, config: Config, events: list[Event]) -> None:
    """@brief Stored food rots a little every month, so hoarding has a cost."""
    spoiled = state.food * config.economy.food_spoilage_pct // 100
    if spoiled == 0:
        return
    state.food -= spoiled
    events.append(Event("food_spoiled", {"amount": spoiled}))


def _take_from_accumulator(accumulators: list[int], index: int, milli_people: int) -> int:
    """@brief Add thousandths of a person and return the whole people reached."""
    accumulators[index] += milli_people
    whole_people = accumulators[index] // 1000
    accumulators[index] %= 1000
    return whole_people


def _apply_deaths(state: GameState, config: Config, missing_pct: int) -> int:
    demo = config.demography
    famine_extra = demo.famine_death_permille_per_missing_pct * missing_pct
    bands = [state.children, state.adults, state.elders]
    base_rates = [demo.death_child_permille, demo.death_adult_permille, demo.death_elder_permille]
    total_deaths = 0
    for index, band_size in enumerate(bands):
        deaths = _take_from_accumulator(
            state.death_acc, index, band_size * (base_rates[index] + famine_extra)
        )
        deaths = min(deaths, band_size)  # cannot lose more people than the band has
        bands[index] -= deaths
        total_deaths += deaths
    state.children, state.adults, state.elders = bands
    return total_deaths


def _apply_aging(state: GameState, config: Config) -> None:
    demo = config.demography
    grown_up = min(
        _take_from_accumulator(state.aging_acc, 0, state.children * demo.child_to_adult_permille),
        state.children,
    )
    grown_old = min(
        _take_from_accumulator(state.aging_acc, 1, state.adults * demo.adult_to_elder_permille),
        state.adults,
    )
    state.children -= grown_up
    state.adults += grown_up - grown_old
    state.elders += grown_old


def _birth_modifier_pct(state: GameState, config: Config) -> int:
    demo = config.demography
    if state.mood < demo.low_mood_births_below:
        return demo.low_mood_births_pct
    if state.mood > demo.high_mood_births_above:
        return demo.high_mood_births_pct
    return 100


def _apply_births(state: GameState, config: Config, missing_pct: int, housing_full: bool) -> int:
    if missing_pct > 0 or housing_full:
        return 0
    milli_births = (
        state.adults
        * config.demography.birth_permille_per_adult
        * _birth_modifier_pct(state, config)
        // 100
    )
    state.birth_acc += milli_births
    births = state.birth_acc // 1000
    state.birth_acc %= 1000
    state.children += births
    return births


def _update_demography(
    state: GameState, config: Config, missing_pct: int, events: list[Event]
) -> int:
    """@brief Deaths, then aging of the survivors, then births.
    @return Number of deaths this month (used by the mood step).
    """
    housing_full = state.population() >= housing_capacity(state, config)
    deaths = _apply_deaths(state, config, missing_pct)
    _apply_aging(state, config)
    births = _apply_births(state, config, missing_pct, housing_full)
    events.append(Event("demography", {"births": births, "deaths": deaths}))
    return deaths


def _rescale_workers(state: GameState, events: list[Event]) -> None:
    """@brief If deaths or aging left fewer adults than assigned workers,
    shrink every sector proportionally (largest remainder method, ties
    broken by the fixed SECTORS order, so the result is deterministic).
    """
    assigned = state.workers.total()
    if assigned <= state.adults:
        return
    counts = [state.workers.food, state.workers.wood, state.workers.stone]
    shares = [count * state.adults for count in counts]
    new_counts = [share // assigned for share in shares]
    remainders = [share % assigned for share in shares]
    leftover = state.adults - sum(new_counts)
    by_remainder = sorted(range(3), key=lambda i: -remainders[i])  # stable sort
    for index in by_remainder[:leftover]:
        new_counts[index] += 1
    state.workers = Workers(*new_counts)
    events.append(Event("workers_rescaled", {"workers": new_counts}))


def mood_factors(
    state: GameState, config: Config, needed: int, missing_pct: int, deaths: int
) -> dict[str, int]:
    """@brief The named parts of the target mood (base excluded), in per mille.

    Public so the Voice of the square can tell WHY the people feel as they
    do. _target_mood is their sum: changing a part here changes the game.
    @param missing_pct Share of the food that was missing this month.
    @param deaths Deaths of this month.
    """
    mood_cfg = config.mood
    ration = 0
    if state.ration == "reduced":
        ration = mood_cfg.ration_reduced
    if state.ration == "abundant":
        ration = mood_cfg.ration_abundant
    taxed_points = max(0, state.tax_rate - mood_cfg.tax_free_rate)
    reserve_ok = state.food > mood_cfg.reserve_bonus_months * needed
    housing_full = state.population() >= housing_capacity(state, config)
    return {
        "ration": ration,
        "taxes": taxed_points * mood_cfg.tax_per_point,
        "hunger": max(mood_cfg.famine_max, missing_pct * mood_cfg.famine_per_missing_pct),
        "reserve": mood_cfg.reserve_bonus if reserve_ok else 0,
        "housing": mood_cfg.housing_full if housing_full else 0,
        "deaths": deaths * mood_cfg.per_death,
    }


def _target_mood(
    state: GameState, config: Config, needed: int, missing_pct: int, deaths: int
) -> int:
    factors = mood_factors(state, config, needed, missing_pct, deaths)
    return max(0, min(1000, config.mood.base + sum(factors.values())))


def _feast_bonus(state: GameState, config: Config) -> int:
    mood_cfg = config.mood
    if state.feast_gold_this_turn == 0:
        return 0
    bonus = min(mood_cfg.feast_max, state.feast_gold_this_turn // mood_cfg.feast_gold_per_point)
    if state.last_feast_turn == state.turn - 1:
        bonus = bonus * mood_cfg.feast_repeat_pct // 100
    state.last_feast_turn = state.turn
    state.feast_gold_this_turn = 0
    return bonus


def _update_mood(
    state: GameState, config: Config, needed: int, missing_pct: int, deaths: int
) -> None:
    """@brief Move mood toward its target (inertia), then add the feast bonus."""
    target = _target_mood(state, config, needed, missing_pct, deaths)
    # Python's // floors negative numbers too, which is still deterministic.
    state.mood += (target - state.mood) * config.mood.approach_pct // 100
    state.mood += _feast_bonus(state, config)
    state.mood = max(0, min(1000, state.mood))


def _unrest_level(low_mood_turns: int, config: Config) -> str:
    unrest_cfg = config.unrest
    if low_mood_turns >= unrest_cfg.revolt_turns:
        return "revolt"
    if low_mood_turns >= unrest_cfg.strike_turns:
        return "strike"
    if low_mood_turns >= unrest_cfg.protest_turns:
        return "protests"
    return "calm"


def _update_unrest(state: GameState, config: Config, events: list[Event]) -> None:
    if state.mood < config.unrest.threshold:
        state.low_mood_turns += 1
    else:
        state.low_mood_turns = max(0, state.low_mood_turns - 1)
    new_level = _unrest_level(state.low_mood_turns, config)
    if new_level != state.unrest:
        events.append(Event("unrest_changed", {"from": state.unrest, "to": new_level}))
    state.unrest = new_level


def _check_game_over(state: GameState, events: list[Event]) -> None:
    if state.population() == 0:
        state.game_over = "extinction"
    elif state.unrest == "revolt":
        state.game_over = "revolt"
    if state.game_over:
        events.append(Event("game_over", {"reason": state.game_over}))


def resolve_turn(state: GameState, orders: list[Order], config: Config) -> TurnResult:
    """@brief Simulate one month. Pure function: the input state is not modified.
    @param state State at the start of the turn.
    @param orders Parsed orders of this turn (see orders.parse_order).
    @param config Balance values.
    @return New state, per-order verdicts and the events of the month.
    @throws ValueError if the game is already over.
    """
    if state.game_over:
        raise ValueError(f"game is over: {state.game_over}")
    new_state = copy.deepcopy(state)
    events: list[Event] = []

    order_results = apply_orders(new_state, orders, config)
    _apply_fixed_rules(new_state, config, events)
    _advance_construction(new_state, events)
    upkeep_paid = _collect_taxes_and_upkeep(new_state, config, events)
    _produce(new_state, config, upkeep_paid)
    needed, missing_pct = _consume_food(new_state, config, events)
    _spoil_food(new_state, config, events)
    deaths = _update_demography(new_state, config, missing_pct, events)
    _rescale_workers(new_state, events)
    _update_mood(new_state, config, needed, missing_pct, deaths)
    _update_unrest(new_state, config, events)
    _check_game_over(new_state, events)

    if new_state.turn % 3 == 0:
        events.append(Event("season_end", {"season": season_of(new_state.turn)}))
    new_state.turn += 1
    return TurnResult(new_state, order_results, events)
