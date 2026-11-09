"""Bandits, the watchtower and the militia (docs/DESIGN.md, "Bandits, the
watchtower, the Gastaldo and the militia", village block B+C, step 2)."""

import copy

from engine import parse_order, resolve_turn
from engine.bandits import BanditPool, new_pool, pool_from_dict, pool_to_dict, resolve_world
from engine.state import Building, ClassState
from engine.territory import find_place
from engine.turn import TurnResult
from engine.validator import apply_orders


def _order(raw):
    order, code, message = parse_order(raw)
    assert order is not None, message
    return order


def _tower(state, config, finished=True):
    """@brief Give the realm a watchtower in its reserved place."""
    place = find_place(state, config, "watchtower")
    state.buildings.append(Building("watchtower", 0 if finished else 2, state.next_building_id, *place))
    state.next_building_id += 1


def _world(pool, states, config, turn=5):
    """@brief One world step on the given states; returns (pool, results)."""
    results = {key: TurnResult(state, [], []) for key, state in states.items()}
    return resolve_world(pool, results, config, turn), results


def _kinds(result, kind):
    return [e.data for e in result.events if e.kind == kind]


# ---- the pool ----------------------------------------------------------------------

def test_the_start_pool_is_seeded_and_in_proportion_to_the_realms(config):
    eight = new_pool(config, 7, 8)
    assert config.bandits.start_min <= eight.adults <= config.bandits.start_max
    assert new_pool(config, 7, 8) == eight  # the same seed, the same wanderers
    assert new_pool(config, 7, 4).adults == eight.adults * 4 // 8
    assert pool_from_dict(pool_to_dict(eight)) == eight


def test_a_game_without_bandits_has_no_pool(config):
    from dataclasses import replace
    assert new_pool(replace(config, bandits=None), 7, 3) is None
    assert resolve_world(None, {}, config, 1) is None


def test_the_world_step_is_pure_and_deterministic(start_state, config):
    pool = BanditPool(seed=3, adults=20)
    first, results_a = _world(pool, {"1": copy.deepcopy(start_state), "2": copy.deepcopy(start_state)}, config)
    second, results_b = _world(pool, {"1": copy.deepcopy(start_state), "2": copy.deepcopy(start_state)}, config)
    assert pool == BanditPool(seed=3, adults=20)  # the caller's pool is not changed
    assert first == second
    assert [r.events for r in results_a.values()] == [r.events for r in results_b.values()]


# ---- flight -----------------------------------------------------------------------

def test_long_discontent_makes_families_flee(start_state, config):
    rules = config.bandits
    start_state.low_mood_turns = rules.flee_turns - 1
    pool, results = _world(BanditPool(seed=1, adults=0), {"1": copy.deepcopy(start_state)}, config)
    assert not _kinds(results["1"], "flight")  # not yet
    start_state.low_mood_turns = rules.flee_turns
    adults, children = start_state.adults, start_state.children
    pool, results = _world(BanditPool(seed=1, adults=0), {"1": start_state}, config)
    fled = _kinds(results["1"], "flight")[0]
    assert fled["adults"] == adults * rules.flee_adult_pct // 100
    assert fled["children"] == children * rules.flee_child_pct // 100
    assert start_state.adults == adults - fled["adults"]
    assert start_state.workers.total() <= start_state.adults
    assert pool.adults + pool.children >= fled["adults"] + fled["children"] - 1  # the pool's own month may take one


def test_a_small_class_loses_someone_through_the_accumulator(start_state, config):
    start_state.low_mood_turns = config.bandits.flee_turns
    start_state.children = 10  # 1 % of 10 is 0.1 a month: one child leaves in the tenth month
    pool = BanditPool(seed=1, adults=0)
    gone = 0
    for _ in range(10):
        pool, results = _world(pool, {"1": start_state}, config)
        gone += sum(f["children"] for f in _kinds(results["1"], "flight"))
    assert gone == 1


def test_merchants_flee_by_their_own_discontent(start_state, config):
    start_state.workers.food -= 6
    start_state.workers.trade = 6
    start_state.classes["merchants"] = ClassState(mood=100, low_mood_turns=config.bandits.flee_turns,
                                                  flight_acc=99)  # one is about to go
    _, results = _world(BanditPool(seed=1, adults=0), {"1": start_state}, config)
    fled = _kinds(results["1"], "flight")[0]
    assert fled == {"adults": 0, "children": 0, "merchants": 1}  # the content peasants stay
    assert start_state.workers.trade == 5


# ---- raids ------------------------------------------------------------------------

def test_raiders_carry_away_food_then_wood(start_state, config):
    rules = config.bandits
    start_state.food, start_state.wood = 30, 500
    pool, results = _world(BanditPool(seed=1, adults=rules.party_size), {"1": start_state}, config)
    raid = _kinds(results["1"], "raid")[0]
    loot = rules.party_size * rules.carry
    assert raid == {"raiders": rules.party_size, "guards": 0, "repelled": False, "food": 30, "wood": loot - 30}
    assert start_state.food == 0 and start_state.wood == 500 - (loot - 30)


def test_enough_guards_repel_a_party_and_fewer_cut_the_loot(start_state, config):
    rules = config.bandits
    _tower(start_state, config)
    start_state.food = 5000
    start_state.militia = rules.party_size // rules.repel_per_guard
    _, results = _world(BanditPool(seed=1, adults=rules.party_size), {"1": start_state}, config)
    assert _kinds(results["1"], "raid")[0]["repelled"]
    assert start_state.food == 5000
    start_state.militia = 1
    _, results = _world(BanditPool(seed=1, adults=rules.party_size), {"1": start_state}, config)
    raid = _kinds(results["1"], "raid")[0]
    assert raid["food"] == (rules.party_size - rules.repel_per_guard) * rules.carry


def test_raiders_go_where_there_is_much_to_take(start_state, config):
    rich, poor = copy.deepcopy(start_state), copy.deepcopy(start_state)
    rich.food, poor.food, rich.wood, poor.wood = 9000, 10, 0, 0
    hits = {"rich": 0, "poor": 0}
    for turn in range(1, 41):
        _, results = _world(BanditPool(seed=2, adults=config.bandits.party_size),
                            {"rich": copy.deepcopy(rich), "poor": copy.deepcopy(poor)}, config, turn)
        for key in hits:
            hits[key] += len(_kinds(results[key], "raid"))
    assert hits["rich"] > 10 * hits["poor"]


def test_a_fallen_realm_is_not_raided(start_state, config):
    start_state.game_over = "revolt"
    _, results = _world(BanditPool(seed=1, adults=40), {"1": start_state}, config)
    assert not results["1"].events


# ---- the pool's month -------------------------------------------------------------

def test_a_hungry_pool_shrinks_faster_than_a_fed_one(config):
    fed = BanditPool(seed=1, adults=40, food=1000)
    hungry = BanditPool(seed=1, adults=40, food=0)
    fed, _ = _world(fed, {}, config, turn=5)
    hungry, _ = _world(hungry, {}, config, turn=5)
    assert fed.adults == 40 - 40 * config.bandits.decline_pct // 100
    assert hungry.adults < fed.adults


def test_children_in_the_pool_grow_up(config):
    pool = BanditPool(seed=1, adults=0, children=100, food=100_000)
    for turn in range(5, 11):
        pool, _ = _world(pool, {}, config, turn=turn)
    assert pool.adults > 0


# ---- the watchtower and the militia ------------------------------------------------

def test_no_militia_without_a_finished_watchtower(start_state, config):
    militia = _order({"action": "set_militia", "guards": 4})
    assert apply_orders(start_state, [militia], config)[0].code == "NO_WATCHTOWER"
    _tower(start_state, config, finished=False)
    assert apply_orders(start_state, [militia], config)[0].code == "NO_WATCHTOWER"
    start_state.buildings[-1].turns_left = 0
    assert apply_orders(start_state, [militia], config)[0].accepted
    assert start_state.militia == 4


def test_the_watchtower_is_one_per_realm_in_its_place(start_state, config):
    start_state.wood, start_state.stone = 1000, 1000
    build = _order({"action": "build", "building": "watchtower"})
    assert apply_orders(start_state, [build], config)[0].accepted
    tower = start_state.buildings[-1]
    assert next(z for z in start_state.zones if z.x1 <= tower.x <= z.x2 and z.y1 <= tower.y <= z.y2).purpose == "watch"
    assert apply_orders(start_state, [build], config)[0].code == "ONE_PER_REALM"


def test_the_guards_are_taken_before_the_workers(start_state, config):
    _tower(start_state, config)
    orders = [_order({"action": "assign_workers", "food": start_state.adults - 7, "wood": 4, "stone": 3}),
              _order({"action": "set_militia", "guards": 5})]  # the militia runs first anyway
    results = apply_orders(start_state, orders, config)
    assert [r.order.action for r in results] == ["set_militia", "assign_workers"]
    assert results[1].code == "NOT_ENOUGH_WORKERS" and "5 on guard" in results[1].message


def test_guards_called_up_leave_their_work_at_once(start_state, config):
    _tower(start_state, config)
    start_state.workers.food = start_state.adults - 7  # every adult at work
    after = resolve_turn(start_state, [_order({"action": "set_militia", "guards": 6})], config).state
    assert after.workers.total() <= after.adults - 6


def test_the_finished_watchtower_brings_the_gastaldos_salary(start_state, config):
    _tower(start_state, config, finished=False)
    start_state.buildings[-1].turns_left = 1
    salary = start_state.council_salary
    after = resolve_turn(start_state, [], config).state
    assert after.council_salary == salary + config.bandits.gastaldo_salary
    assert resolve_turn(after, [], config).state.council_salary == after.council_salary  # once


def test_demolishing_the_watchtower_disbands_the_militia(start_state, config):
    _tower(start_state, config)
    start_state.militia, start_state.gold = 4, 100
    tower = start_state.buildings[-1]
    assert apply_orders(start_state, [_order({"action": "demolish", "building_id": tower.id})], config)[0].accepted
    assert start_state.militia == 0
