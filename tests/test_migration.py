"""The doors and acceptance (docs/DESIGN.md, "The doors and acceptance",
village block B+C, stage 2): raids turned into immigration, seekers settling,
the natives' grumbling, set_doors."""

import copy
from dataclasses import replace

from engine import parse_order
from engine.bandits import BanditPool, resolve_world
from engine.migration import doors_in_force, empty_jobs, free_beds, resolve_arrivals
from engine.snapshot import state_from_dict, state_to_dict
from engine.state import Building, Event
from engine.territory import find_place
from engine.turn import TurnResult, food_needed
from engine.validator import apply_orders
from server.db.games import EVENT_VISIBILITY


def _order(raw):
    order, code, message = parse_order(raw)
    assert order is not None, message
    return order


def _tower(state, config):
    place = find_place(state, config, "watchtower")
    state.buildings.append(Building("watchtower", 0, state.next_building_id, *place))
    state.next_building_id += 1


def _world(pool, states, config, turn=5):
    results = {key: TurnResult(state, [], []) for key, state in states.items()}
    return resolve_world(pool, results, config, turn), results


def _arrivals(result):
    return [e.data for e in result.events if e.kind == "arrival"]


def _guarded(state, config, doors, guards=4):
    """@brief A realm with a finished watchtower, guards and the given doors."""
    _tower(state, config)
    state.militia, state.doors = guards, doors
    state.food = 5000


# ---- set_doors ----------------------------------------------------------------------

def test_no_doors_without_a_finished_watchtower(start_state, config):
    result = apply_orders(start_state, [_order({"action": "set_doors", "doors": "open"})], config)[0]
    assert not result.accepted and result.code == "NO_WATCHTOWER"
    assert start_state.doors == "normal"
    _tower(start_state, config)
    assert apply_orders(start_state, [_order({"action": "set_doors", "doors": "open"})], config)[0].accepted
    assert start_state.doors == "open"


def test_a_game_without_migration_refuses_the_doors(start_state, config):
    _tower(start_state, config)
    result = apply_orders(start_state, [_order({"action": "set_doors", "doors": "closed"})],
                          replace(config, migration=None))[0]
    assert not result.accepted and result.code == "NO_MIGRATION"


def test_demolishing_the_watchtower_opens_the_doors_to_normal(start_state, config):
    _tower(start_state, config)
    start_state.doors, start_state.gold = "closed", 100
    tower = start_state.buildings[-1]
    assert apply_orders(start_state, [_order({"action": "demolish", "building_id": tower.id})], config)[0].accepted
    assert start_state.doors == "normal"


def test_closed_doors_need_guards(start_state, config):
    rules = config.migration
    start_state.doors = "closed"
    start_state.militia = rules.closed_min_guards
    assert doors_in_force(start_state, rules) == "closed"
    start_state.militia = rules.closed_min_guards - 1
    assert doors_in_force(start_state, rules) == "normal"


def test_the_doors_survive_a_snapshot_and_old_snapshots_load_at_normal(start_state):
    start_state.doors = "open"
    data = state_to_dict(start_state)
    assert state_from_dict(data).doors == "open"
    del data["doors"]
    assert state_from_dict(data).doors == "normal"


# ---- raids turned into immigration ---------------------------------------------------

def _stopped_party(state, config, doors):
    """@brief A party of 8 fully stopped by 4 guards at the given doors; the
    pool has nobody else, so nobody seeks a home. Returns (pool, arrivals)."""
    _guarded(state, config, doors)
    pool = BanditPool(seed=1, adults=config.bandits.party_size)
    pool, results = _world(pool, {"1": state}, config)
    return pool, _arrivals(results["1"])


def test_stopped_raiders_stay_by_the_doors(start_state, config):
    rules, party = config.migration, config.bandits.party_size
    for doors, pct in (("normal", rules.keep_normal_pct), ("open", rules.keep_open_pct)):
        state = copy.deepcopy(start_state)
        _, arrivals = _stopped_party(state, config, doors)
        assert arrivals[0]["from_raids"] == party * pct // 100
        assert state.adults == start_state.adults + arrivals[0]["adults"]
    state = copy.deepcopy(start_state)
    _, arrivals = _stopped_party(state, config, "closed")
    assert arrivals == [] and state.adults == start_state.adults


def test_raiders_who_stay_never_exceed_the_free_beds(start_state, config):
    start_state.children += free_beds(start_state, config) - 1  # one bed left
    _, arrivals = _stopped_party(start_state, config, "open")
    assert arrivals[0]["from_raids"] == 1


def test_a_game_without_migration_takes_nobody_in(start_state, config):
    _guarded(start_state, config, "open")
    no_migration = replace(config, migration=None)
    _, results = _world(BanditPool(seed=1, adults=40), {"1": start_state}, no_migration)
    assert _arrivals(results["1"]) == []


# ---- seekers ------------------------------------------------------------------------

PLENTY = 10 ** 7  # food no raid of the test can empty


def _seek(states, config, adults=100, children=0):
    pool, results = _world(BanditPool(seed=2, adults=adults, children=children), states, config)
    return pool, {key: _arrivals(result) for key, result in results.items()}


def _extra_house(state):
    """@brief One more finished house: more free beds than empty jobs."""
    state.buildings.append(Building("house", 0))


def test_seekers_go_only_to_a_calm_fed_realm(start_state, config):
    calm, angry, hungry = (copy.deepcopy(start_state) for _ in range(3))
    calm.food = angry.food = PLENTY
    angry.mood = config.unrest.threshold - 1
    hungry.food = hungry.wood = 0
    _, arrivals = _seek({"calm": calm, "angry": angry, "hungry": hungry}, config)
    assert arrivals["calm"][0]["adults"] > 0
    assert arrivals["angry"] == [] and arrivals["hungry"] == []


def test_normal_doors_take_no_more_than_the_empty_jobs(start_state, config):
    start_state.food = PLENTY
    _extra_house(start_state)
    jobs = empty_jobs(start_state, config)
    assert free_beds(start_state, config) > jobs
    _, arrivals = _seek({"1": start_state}, config, adults=5000)
    assert arrivals["1"][0]["adults"] == jobs


def test_open_doors_fill_the_beds_beyond_the_jobs(start_state, config):
    _guarded(start_state, config, "open", guards=0)
    start_state.food = PLENTY
    _extra_house(start_state)
    beds = free_beds(start_state, config)
    assert beds > empty_jobs(start_state, config)
    _, arrivals = _seek({"1": start_state}, config, adults=5000)
    assert arrivals["1"][0]["adults"] == beds
    assert free_beds(start_state, config) == 0


def test_seekers_are_shared_in_proportion_to_room_and_the_pool_shrinks(start_state, config):
    big, small = copy.deepcopy(start_state), copy.deepcopy(start_state)
    big.food = small.food = PLENTY
    small.children += free_beds(small, config) - 2  # two beds left
    pool, arrivals = _seek({"big": big, "small": small}, config, adults=100, children=50)
    # The seekers are counted after the pool's month, which takes its share first.
    seekers = 100 * config.migration.seek_pct // 100
    taken_big, taken_small = arrivals["big"][0]["adults"], arrivals["small"][0]["adults"]
    assert 0 < taken_small < taken_big and taken_big + taken_small <= seekers
    assert arrivals["small"][0]["adults"] + arrivals["small"][0]["children"] <= 2  # its two beds
    assert arrivals["big"][0]["children"] > 0  # children follow the adults
    assert pool.adults <= 100 - taken_big - taken_small  # they left the pool


def test_the_natives_grumble_only_in_scarcity(start_state, config):
    fed = copy.deepcopy(start_state)
    fed.food = PLENTY
    _, arrivals = _seek({"fed": fed}, config)
    assert not arrivals["fed"][0]["grumbled"]
    # Food between one and two months: it still draws people, but it is scarce.
    # Guards repel every party, so no raid eats into that food.
    scarce = copy.deepcopy(start_state)
    scarce.militia = config.bandits.party_size // config.bandits.repel_per_guard
    scarce.food = config.migration.scarce_food_months * food_needed(scarce, config) - 100
    mood = scarce.mood
    _, arrivals = _seek({"scarce": scarce}, config)
    assert arrivals["scarce"][0]["grumbled"]
    grumble = 100 * arrivals["scarce"][0]["adults"] // scarce.population() * config.migration.grumble_per_pct
    assert grumble > 0 and scarce.mood == mood - grumble


# ---- accumulators (game 32: a small pool sent nobody) -----------------------------

def _months_of_arrivals(state, config, months, pool, raid=None):
    """@brief resolve_arrivals alone, month after month (no pool's month, no
    real raid): the adults taken in each month."""
    taken = []
    for _ in range(months):
        events = {"1": [Event("raid", dict(raid))] if raid else []}
        resolve_arrivals(pool, {"1": state}, events, config)
        taken.append(sum(e.data["adults"] for e in events["1"] if e.kind == "arrival"))
    return taken


def test_a_small_pool_still_sends_a_seeker_every_few_months(start_state, config):
    start_state.food = PLENTY
    # 5 wanderers, 10 %: half a seeker a month, one every second month.
    pool = BanditPool(seed=1, adults=5)
    assert _months_of_arrivals(copy.deepcopy(start_state), config, 4, pool) == [0, 1, 0, 0]
    # Without the accumulators (games saved before) 10 % of 5 is never anybody.
    old = replace(config, migration=replace(config.migration, accumulate=False))
    assert _months_of_arrivals(copy.deepcopy(start_state), old, 4, BanditPool(seed=1, adults=5)) == [0] * 4


def test_of_a_band_of_two_one_stays_every_second_raid(start_state, config):
    _guarded(start_state, config, "normal")
    raid = {"raiders": 2, "guards": 4}  # 25 % of 2 stopped: half a raider a raid
    pool = BanditPool(seed=1, adults=2)
    assert _months_of_arrivals(start_state, config, 2, pool, raid) == [0, 1]
    assert start_state.keep_acc == 0 and pool.adults == 1


def test_the_arrival_is_public():
    assert EVENT_VISIBILITY["arrival"] == "public"


def test_the_chronicle_tells_an_arrival():
    from server.ui.labels import event_label
    text = event_label("arrival", {"adults": 3, "children": 1, "from_raids": 2, "grumbled": True})
    assert text.startswith("Sono arrivati a stabilirsi 3 adulti e 1 bambini, di cui 2 briganti")
    assert "mormorano" in text
    assert "mormorano" not in event_label("arrival", {"adults": 2, "children": 0, "from_raids": 0, "grumbled": False})
