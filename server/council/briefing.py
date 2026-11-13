"""@brief Role briefings: compact text with every number computed by the engine.

The models read words and numbers here; they never compute anything.
Pure functions: no database access (the meeting module passes the data in).
"""

import copy
import json
from collections import Counter

from engine import migration
from engine.config import Config
from engine.market import GOODS, MarketState, buy_price, market_status, sell_price, stock, trade_capacity
from engine.state import GameState
from engine.turn import (
    expected_output,
    firewood_needed,
    food_needed,
    stone_upkeep,
    housing_capacity,
    jobs_in_sector,
    monthly_tax_income,
    monthly_upkeep,
    season_of,
)
from server.council import map_text
from server.council.llm import PROPOSALS_MARKER

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


def months_until_winter(turn: int) -> int:
    """@brief 0 while it is winter (January-March), else months to January."""
    month_index = (turn - 1) % 12
    return 0 if month_index < 3 else 12 - month_index


def _reserve_months_text(state: GameState, config: Config) -> str:
    needed = food_needed(state, config)
    if needed == 0:
        return "unlimited"
    tenths = state.food * 10 // needed
    return f"{tenths // 10}.{tenths % 10}"


def header_lines(state: GameState) -> list[str]:
    month = MONTHS[(state.turn - 1) % 12]
    winter = months_until_winter(state.turn)
    winter_text = "it is winter now" if winter == 0 else f"winter in {winter} months"
    return [f"# Briefing, turn {state.turn}: {month}, {season_of(state.turn)}; {winter_text}"]


def _farm_season_pct(turn: int, config: Config) -> int:
    economy = config.economy
    return {"winter": economy.farm_winter_pct, "spring": economy.farm_spring_pct,
            "summer": economy.farm_summer_pct, "autumn": economy.farm_autumn_pct}[season_of(turn)]


def food_outlook_line(state: GameState, config: Config, people=None) -> str:
    """@brief This month's harvest and where the store would end, if nothing changes."""
    harvest = expected_output(state, config, people)["food"]  # the people's effort included
    needed = food_needed(state, config)
    left = max(0, state.food + harvest - needed)
    left -= left * config.economy.food_spoilage_pct // 100
    trend = "it grows" if left > state.food else "it shrinks" if left < state.food else "it holds"
    return (f"- Harvest expected this month if nothing changes: {harvest} food "
            f"({season_of(state.turn)}: farms yield {_farm_season_pct(state.turn, config)}%). "
            f"After eating and rot the store would go from {state.food} to about {left}: {trend}.\n"
            + season_outlook_line(state, config, harvest))


def season_outlook_line(state: GameState, config: Config, harvest: int) -> str:
    """@brief The farm yield of the coming seasons, with today's farmers.
    Game 4: seeing only this month, the Treasurer asked in May to cut the
    ration "to save for winter" while summer and autumn were about to fill
    the granary."""
    this_pct = _farm_season_pct(state.turn, config)
    full = harvest * 100 // this_pct if this_pct else 0
    parts = []
    for months_ahead in (3, 6, 9):
        turn = state.turn + months_ahead
        pct = _farm_season_pct(turn, config)
        parts.append(f"{season_of(turn)} {pct}% (about {full * pct // 100} a month)")
    return ("- Coming seasons, with today's farmers: " + "; ".join(parts)
            + f". Months left in this season: {3 - (state.turn - 1) % 3}.")


def ration_lines(state: GameState, config: Config) -> list[str]:
    """@brief The Treasurer's craft needs the consumption at every ration
    (game 8: the abundant ration was proposed with 344 food in store)."""
    needed = {}
    for ration in ("reduced", "normal", "abundant"):
        trial = copy.copy(state)
        trial.ration = ration
        needed[ration] = food_needed(trial, config)
    return [f"- Eaten per month at each ration: reduced {needed['reduced']}, "
            f"normal {needed['normal']}, abundant {needed['abundant']}."]


def registry_lines(state: GameState, config: Config) -> list[str]:
    """@brief The registry the Treasurer reads: hands and mouths to come."""
    coming = (state.aging_acc[0] + 3 * state.children * config.demography.child_to_adult_permille) // 1000
    places = housing_capacity(state, config)
    return [f"- Registry: about {coming} children will come of age in the next three months. "
            f"Housing: {state.population()} people, {places} places, {max(0, places - state.population())} free."]


def treasury_lines(state: GameState, config: Config, people=None) -> list[str]:
    return [
        "## Treasury and people",
        f"- Gold: {state.gold}. Tax income per month at {state.tax_rate}%: "
        f"{monthly_tax_income(state, config)}. Building upkeep per month: {monthly_upkeep(state, config)}."
        + (f" Council salaries per month: {state.council_salary}, paid after the upkeep."
           if state.council_salary else ""),
        f"- Food in store: {state.food}. Eaten per month at '{state.ration}' ration: "
        f"{food_needed(state, config)}. Without any harvest it would last about "
        f"{_reserve_months_text(state, config)} months. "
        f"Stored food rots by {config.economy.food_spoilage_pct}% per month.",
        food_outlook_line(state, config, people),
        *ration_lines(state, config),
        f"- Tax rate: {state.tax_rate}% (maximum {config.economy.max_tax_rate}%). Ration: {state.ration}.",
        *([map_text.price_line(state, config)] if state.has_map() else []),
        # No mood number, threshold or months below it: the council, like the
        # sovereign, knows the people only from the square (see square_lines).
        # Protests and strikes are public facts, so the unrest level stays.
        f"- Unrest: {state.unrest} (calm, protests, strike, revolt).",
        f"- Population: {state.children} children, {state.adults} adults, {state.elders} elders.",
        *registry_lines(state, config),
    ]


def needs_line(state: GameState, config: Config) -> str:
    """@brief Firewood and stone upkeep ([needs]); "" for games without them."""
    if config.needs is None:
        return ""
    months = "/".join(MONTHS[m - 1][:3] for m in config.needs.firewood_months)
    now = firewood_needed(state, config)
    return (f"- Firewood: {state.population() // config.needs.firewood_people} wood a month in {months} "
            f"({now} this month). Stone upkeep: {stone_upkeep(state, config)} stone a month for the active "
            "buildings. Both are taken before this month's production.")


def market_lines(state: GameState, config: Config, market: MarketState | None, realm_key: str) -> list[str]:
    """@brief The Treasurer's market section: public prices, stock and totals,
    and this realm's own goods still on sale (never another realm's)."""
    if market is None or config.market is None:
        return []
    if market_status(state, config) == "unbuilt":
        return _no_market_lines(state, config)
    lot = config.market.lot_units
    lines = [f"## The market (shared with the other realms; lots of {lot})"]
    for good in GOODS:
        book = market.goods[good]
        lines.append(f"- {good}: buy {buy_price(market, config, good)}, sell {sell_price(market, config, good)} "
                     f"gold a lot; in the warehouse {stock(book)}; last month bought {book.last_bought}, "
                     f"put on sale {book.last_sold}.")
    own = {good: sum(c.units for c in market.goods[good].queue if c.seller == realm_key) for good in GOODS}
    waiting = ", ".join(f"{good} {units}" for good, units in own.items() if units)
    lines.append("- Your goods waiting in the warehouse: "
                 + (f"{waiting} (paid when someone buys them)." if waiting else "none."))
    lines += merchants_lines(state, config)
    lines.append(f"- Your stores: food {state.food}, wood {state.wood}, stone {state.stone}, gold {state.gold}.")
    if config.needs is not None:
        lines.append(needs_line(state, config))
    return lines


def _no_market_lines(state: GameState, config: Config) -> list[str]:
    """@brief Village block A: no market building finished, so no prices
    either (decided 2026-11-08: they come only with the travellers, later)."""
    site = next((b for b in state.buildings if b.kind == "market"), None)
    spec = config.buildings["market"]
    if site is not None:
        where = f"its building site is finished in {site.turns_left} months."
    else:
        where = (f"the Architect can build one ({spec.wood} wood, {spec.build_turns} months, in the market "
                 "zone).")
    return ["## The market",
            "- The realm has no market yet: no trade, and no news of the prices of the other realms; " + where]


def merchants_lines(state: GameState, config: Config) -> list[str]:
    """@brief The merchants and their tax (village block A); [] elsewhere.
    Their unrest is public, their mood is not."""
    if not config.market.needs_building:
        return []
    lots = trade_capacity(state, config)
    cls = state.classes.get("merchants")
    unrest = f" The merchants are in {cls.unrest}." if cls is not None and cls.unrest != "calm" else ""
    return [f"- Your merchants: {state.workers.trade} at the market ({jobs_in_sector(state, config, 'trade')} "
            f"places); this month they can handle {lots} lots in all, buying and selling "
            f"({config.market.lots_per_merchant} each; fewer when they are discontented, none on strike).{unrest}",
            f"- Merchants' tax: {state.merchant_tax_rate}% of the gold value of the month's trades, paid with "
            "the trades; they pay no ordinary tax."]


def market_summary_line(config: Config, market: MarketState | None, state: GameState | None = None) -> list[str]:
    """@brief One line of prices for the Chancellor's cost check (none for a
    realm that cannot trade yet: it does not know the prices)."""
    if market is None or config.market is None:
        return []
    if state is not None and market_status(state, config) == "unbuilt":
        return ["- The realm has no market yet: any trade would be refused."]
    prices = ", ".join(f"{good} {buy_price(market, config, good)}/{sell_price(market, config, good)}"
                       for good in GOODS)
    return [f"- Market prices (buy/sell a lot of {config.market.lot_units}): {prices}. "
            "Trades run first; the cost check assumes every purchase is filled in full."]


def _village(config: Config) -> bool:
    """@brief True where the market is a building (village block A)."""
    return config.market is not None and config.market.needs_building


def _vacant(state: GameState, config: Config, sector: str) -> int:
    return max(0, jobs_in_sector(state, config, sector) - getattr(state.workers, sector))


def _space_line(state: GameState, config: Config, territory_summary: bool) -> str:
    """@brief Free space: a count without a map, the territory summary with one
    (left out for the Architect, who gets the whole territory section)."""
    if not state.has_map():
        return f"- Free tiles for new buildings: {state.free_tiles}."
    if not territory_summary:
        return "- Territory: see \"The town and its land\" below."
    return map_text.summary_line(state, config)


def _clearing_part(state: GameState) -> str:
    return f", clearing {state.workers.clearing} (no jobs: they work the clearing queue)" if state.has_map() else ""


def _tools_line(state: GameState, config: Config) -> list[str]:
    """@brief Tools (docs/DESIGN.md, "Tools"): how many buildings of each kind
    have them; the ids and levels are in the Architect's list of buildings."""
    if config.tools is None:
        return []
    parts = []
    for kind in config.tools.levels:
        active = [b for b in state.buildings if b.kind == kind and b.turns_left == 0]
        if not active:
            continue
        improved = sum(1 for b in active if b.level)
        works = sum(1 for b in active if b.improving)
        parts.append(f"{kind} {improved} of {len(active)}" + (f" ({works} in works)" if works else ""))
    return ["- Buildings with tools: " + ", ".join(parts) + "."]


def works_lines(state: GameState, config: Config, people=None, territory_summary: bool = True) -> list[str]:
    active = Counter(b.kind for b in state.buildings if b.turns_left == 0)
    building = [f"{b.kind} ({b.turns_left} turns left)" for b in state.buildings if b.turns_left > 0]
    idle = state.free_adults() - state.workers.total()  # guards are not idle (village block B+C)
    output = expected_output(state, config, people)
    # Jobs (or housing) per building: without them a model once said "a farm
    # creates two jobs" (it has 15) and never built one (game 7).
    costs = [
        f"{kind}: wood {spec.wood}, stone {spec.stone}, gold {spec.gold}, {spec.build_turns} turns, "
        + (f"{spec.jobs} jobs" if spec.jobs else f"houses {spec.housing} people")
        for kind, spec in config.buildings.items()
        if spec.sector != "trade" or _village(config)
    ]
    trade_part = (f", trade {state.workers.trade}/{jobs_in_sector(state, config, 'trade')} (merchants)"
                  if _village(config) else "")
    trade_vacant = f", trade {_vacant(state, config, 'trade')}" if _village(config) else ""
    return [
        "## Works and workers",
        f"- Wood: {state.wood}. Stone: {state.stone}. Gold: {state.gold}.",
        "- Buildings in use: " + ", ".join(f"{count} {kind}" for kind, count in sorted(active.items())) + ".",
        "- Under construction: " + (", ".join(building) if building else "nothing") + ".",
        *_tools_line(state, config),
        _space_line(state, config, territory_summary),
        f"- Workers (assigned/jobs): food {state.workers.food}/{jobs_in_sector(state, config, 'food')}, "
        f"wood {state.workers.wood}/{jobs_in_sector(state, config, 'wood')}, "
        f"stone {state.workers.stone}/{jobs_in_sector(state, config, 'stone')}{trade_part}{_clearing_part(state)}. "
        f"Adults: {state.adults}, without work: {idle}. Workers beyond the jobs produce nothing.",
        f"- Jobs without workers: food {_vacant(state, config, 'food')}, wood {_vacant(state, config, 'wood')}, "
        f"stone {_vacant(state, config, 'stone')}{trade_vacant}.",
        f"- Expected this month if nothing changes: food +{output['food']}, wood +{output['wood']}, "
        f"stone +{output['stone']}.",
        f"- Housing: {state.population()} people, {housing_capacity(state, config)} places.",
        *([needs_line(state, config)] if config.needs is not None else []),
        "- Building costs: " + "; ".join(costs) + ".",
    ]


GATE_MEMORY_TURNS = 6  # months of raids and flights in the Gastaldo's briefing


def _gate_event_text(kind: str, data: dict) -> str:
    if kind == "arrival":  # stage 2
        children = f" and {data['children']} children" if data["children"] else ""
        raiders = f" ({data['from_raids']} of them stopped raiders)" if data["from_raids"] else ""
        grumbled = "; the people grumbled against them" if data["grumbled"] else ""
        return f"{data['adults']} adults{children} settled{raiders}{grumbled}"
    if kind == "flight":
        parts = [f"{data['adults']} adults" if data["adults"] else "",
                 f"{data['children']} children" if data["children"] else "",
                 f"{data['merchants']} merchants" if data["merchants"] else ""]
        return "families left for the woods: " + ", ".join(p for p in parts if p)
    if data["repelled"]:
        return f"a band of {data['raiders']} raiders was driven off by {data['guards']} guards"
    return (f"a band of {data['raiders']} raiders against {data['guards']} guards carried away "
            f"{data['food']} food and {data['wood']} wood")


def _doors_lines(state: GameState, config: Config) -> list[str]:
    """@brief The doors and the room for newcomers (village block B+C, stage 2)."""
    rules = config.migration
    doors = migration.doors_in_force(state, rules)
    held = ""
    if state.doors == "closed" and doors != "closed":
        held = f" (ordered closed, but with fewer than {rules.closed_min_guards} guards they count as normal)"
    return [f"- The doors: {doors}{held}. Free beds: {migration.free_beds(state, config)}; "
            f"empty jobs: {migration.empty_jobs(state, config)}."]


def gate_lines(state: GameState, config: Config, past: list[tuple[int, str, dict]]) -> list[str]:
    """@brief The Gastaldo's section (village block B+C): the guard, what lies
    in view of the bandits, the doors (stage 2), the raids, flights and arrivals of the last months.
    @param past (turn, kind, data) of the realm's own raid, flight and arrival events, oldest first."""
    rules = config.bandits
    lines = ["## The gate and the guard",
             f"- Guards on duty: {state.guards()} (the militia; every guard is an adult taken from work). "
             f"Adults: {state.adults}, {state.free_adults()} of them free for the Architect's work.",
             f"- Each guard stops about {rules.repel_per_guard} raiders; a band is about {rules.party_size}.",
             f"- In view of the bandits: food {state.food}, wood {state.wood} (they go where much lies exposed)."]
    if config.migration is not None:  # stage 2
        lines += _doors_lines(state, config)
    if not past:
        lines.append(f"- No raid, no family gone and nobody settled in the last {GATE_MEMORY_TURNS} months.")
    for turn, kind, data in past:
        lines.append(f"- {MONTHS[(turn - 1) % 12]} (turn {turn}): {_gate_event_text(kind, data)}.")
    return lines


def events_lines(events: list[dict]) -> list[str]:
    """@brief Events of the previous turn already filtered by row-level security:
    the realm's own, then the public news of the other realms under their name.
    @param events Rows of list_visible_events; one without "own" counts as the realm's."""
    own = [event for event in events if event.get("own", True)]
    others = [event for event in events if not event.get("own", True)]
    lines = ["## Last month"] + [
        f"- {event['kind']}: {json.dumps(event['data'], ensure_ascii=False)}" for event in own
    ]
    if not own:
        lines.append("- Nothing worth reporting.")
    if others:
        lines.append("## News from the other realms (public facts; not your realm)")
        lines += [f"- {event['realm']}: {event['kind']} {json.dumps(event['data'], ensure_ascii=False)}"
                  for event in others]
    return lines


def history_lines(history: list[str]) -> list[str]:
    """@brief Past proposals with what followed (entries may span several lines)."""
    if not history:
        return []
    return ["## Your recent proposals and what followed"] + [f"- {entry}" for entry in history]


def audience_lines(dialogue: list[str]) -> list[str]:
    """@brief This actor's own private audiences; secret from everyone else."""
    if not dialogue:
        return []
    return ["## Your private audiences with the sovereign"] + [f"- {line}" for line in dialogue]


def square_lines(voices: list[tuple[int, str]]) -> list[str]:
    """@brief What the Voice of the square said in recent turns, oldest first.
    This is the council's only window on the people's mood.
    @param voices (turn, text) pairs; the Voice speaks at the start of a turn.
    """
    if not voices:
        return []
    lines = ["## What they say in the square"]
    for turn, text in voices:
        lines.append(f"- At the start of {MONTHS[(turn - 1) % 12]} (turn {turn}): {text}")
    return lines


def audience_fact_lines(facts: list[str]) -> list[str]:
    if not facts:
        return []
    return ["## Private audiences this month"] + [f"- {fact}" for fact in facts]


def lessons_lines(lessons: list[str]) -> list[str]:
    """@brief The minister's own lessons; secret from the sovereign."""
    if not lessons:
        return []
    return ["## What you have learned so far"] + [f"- {lesson}" for lesson in lessons]


def directive_lines(directives: list[str]) -> list[str]:
    if not directives:
        return []
    return ["## Directives of the sovereign this turn"] + [f"- {text}" for text in directives]


def minister_briefing(
    role: str, state: GameState, config: Config, events: list[dict],
    history: list[str], directives: list[str], lessons: list[str],
    audiences: list[str] = (), audience_facts: list[str] = (), square_voices: list = (),
    people=None, people_lines: list[str] = (), note_lines: list[str] = (), market: list[str] = (),
    gate: list[str] = (),
) -> str:
    """@brief Full briefing of a minister; each role sees only its own section.
    Lessons come first: they are the lens through which the numbers are read.
    @param market The Treasurer's market section (market_lines), if any.
    @param gate The Gastaldo's section (gate_lines), if any.
    """
    if role == "treasurer":
        section = treasury_lines(state, config, people) + list(market)
    elif role == "gastaldo":
        section = list(gate)
    else:
        section = works_lines(state, config, people, territory_summary=False)
        if state.has_map():
            section = section + map_text.architect_lines(state, config)
    lines = (header_lines(state) + lessons_lines(lessons) + section + events_lines(events)
             + square_lines(list(square_voices)) + list(people_lines)
             + history_lines(history) + audience_lines(list(audiences)) + list(note_lines)
             + audience_fact_lines(list(audience_facts)) + directive_lines(directives))
    return "\n".join(lines)


def chancellor_briefing(
    state: GameState, config: Config, events: list[dict], directives: list[str],
    reports: dict[str, str], proposals: list[dict], check_lines: list[str], lessons: list[str],
    audiences: list[str] = (), audience_facts: list[str] = (), square_voices: list = (),
    people=None, people_lines: list[str] = (), note_lines: list[str] = (), market: list[str] = (),
    gate: list[str] = (),
) -> str:
    """@brief The Chancellor sees both sections, the reports, the proposals
    (also as one JSON line, easy to quote back) and the scribes' cost check.
    @param market The prices line (market_summary_line), if any.
    @param gate The Gastaldo's section, once it sits (village block B+C).
    """
    lines = (header_lines(state) + lessons_lines(lessons)
             + treasury_lines(state, config, people) + works_lines(state, config, people) + list(gate))
    lines += (events_lines(events) + square_lines(list(square_voices)) + list(people_lines)
              + audience_lines(list(audiences)) + list(note_lines)
              + audience_fact_lines(list(audience_facts)) + directive_lines(directives))
    lines.append("## Reports of the ministers")
    lines += [f"- {role}: {text}" for role, text in reports.items()]
    lines.append("## Cost check of all proposals together, in this order")
    lines += list(market)
    lines += [f"- {line}" for line in check_lines] or ["- No proposals."]
    lines.append(PROPOSALS_MARKER + json.dumps(proposals, ensure_ascii=False))
    return "\n".join(lines)
