"""Roads of the world, phase 1: the bandits as bands on the map
(docs/DESIGN.md, "Roads of the world"; engine/bands.py)."""

import copy
from dataclasses import replace

import pytest

from engine import new_game
from engine.bandits import Band, BanditPool, new_pool, pool_from_dict, pool_to_dict, resolve_world
from engine.bands import WOODS, RoadMap
from engine.migration import free_beds
from engine.state import Building, Event
from engine.territory import find_place, hex_distance
from engine.turn import TurnResult

SITE = 0  # top-left site of the ring: land x 4..15, y 4..15


@pytest.fixture
def realm(config):
    return new_game(config, seed=7, site_index=SITE)


def _pool(*bands):
    pool = BanditPool(seed=1, adults=0)
    for band in bands:
        band.id = pool.next_band_id
        pool.next_band_id += 1
        pool.bands.append(band)
    return pool


def _band(x, y, adults):
    return Band(0, x, y, x, y, adults)


def _world(pool, states, config, turn=5):
    results = {key: TurnResult(state, [], []) for key, state in states.items()}
    return resolve_world(pool, results, config, turn), results


def _events(result, kind):
    return [e.data for e in result.events if e.kind == kind]


def _free_hex(config, states, low, high, woods=False):
    """A free hex whose steps to the nearest realm's land are within [low, high]."""
    roads = RoadMap(config, states)
    for y in range(roads.size):
        for x in range(roads.size):
            steps = roads.steps_to_land.get((x, y))
            if steps is not None and low <= steps <= high and (not woods or roads.terrain[y][x] in WOODS):
                return x, y
    raise AssertionError("no such hex")


def _tower(state, config):
    place = find_place(state, config, "watchtower")
    state.buildings.append(Building("watchtower", 0, state.next_building_id, *place))
    state.next_building_id += 1
    return place


def test_the_start_wanderers_camp_as_bands_far_from_the_realms(config):
    states = [new_game(config, 7, site_index=i) for i in range(3)]
    pool = new_pool(config, 7, 3, states)
    without_bands = new_pool(replace(config, bands=None), 7, 3)
    assert pool.adults == 0 and sum(b.adults for b in pool.bands) == without_bands.adults
    roads = RoadMap(config, {str(i): s for i, s in enumerate(states)})
    for band in pool.bands:
        assert band.adults <= config.bandits.party_size
        assert roads.terrain[band.camp_y][band.camp_x] in WOODS
        assert roads.steps_to_land[(band.camp_x, band.camp_y)] > config.bands.start_gap
    assert pool_to_dict(new_pool(config, 7, 3, states)) == pool_to_dict(pool)  # the seed decides
    assert pool_to_dict(pool_from_dict(pool_to_dict(pool))) == pool_to_dict(pool)


def test_bands_need_the_start_states(config):
    with pytest.raises(ValueError):
        new_pool(config, 7, 3)


def test_an_old_pool_reads_with_no_bands():
    stored = {"seed": 1, "adults": 9, "children": 0, "food": 0, "grow_acc": 0, "decline_acc": 0, "seek_acc": [0, 0]}
    assert pool_from_dict(stored).bands == []


def test_a_band_near_an_unguarded_realm_raids_it_and_goes_home(config, realm):
    x, y = _free_hex(config, {"1": realm}, 5, 5)
    pool = _pool(_band(x, y, 8))
    food_before = realm.food
    after, results = _world(pool, {"1": realm}, config)
    raids = _events(results["1"], "raid")
    assert len(raids) == 1 and not raids[0]["repelled"]  # no guards: the odds are 8 / 8
    assert raids[0]["food"] == 8 * config.bandits.carry and realm.food == food_before - raids[0]["food"]
    band = after.bands[0]
    assert (band.x, band.y) == (x, y) and band.raided and band.target == "1"
    assert pool.bands[0].food == 0 and pool.bands[0].x == x  # the caller's pool is not changed


def test_rest_a_band_skips_the_realm_it_raided_last_month(config, realm):
    x, y = _free_hex(config, {"1": realm}, 5, 5)
    pool = _pool(_band(x, y, 8))
    raids = []
    for turn in (5, 6, 7):
        pool, results = _world(pool, {"1": realm}, config, turn)
        raids.append(len(_events(results["1"], "raid")))
    assert raids == [1, 0, 1]
    no_rest = replace(config, bands=replace(config.bands, rest=False))
    pool = _pool(_band(x, y, 8))
    for turn in (5, 6):
        pool, results = _world(pool, {"1": realm}, no_rest, turn)
        assert len(_events(results["1"], "raid")) == 1


def test_guards_turn_the_odds_and_some_raiders_stay(config, realm):
    x, y = _free_hex(config, {"1": realm}, 5, 5)
    _tower(realm, config)
    realm.militia = realm.adults  # 8 raiders against 3 x all the adults: the odds are a few in a hundred
    repelled = stayed = 0
    for turn in range(1, 13):
        state = copy.deepcopy(realm)
        adults_before = state.adults
        _, results = _world(_pool(_band(x, y, 8)), {"1": state}, config, turn)
        raid = _events(results["1"], "raid")[0]
        repelled += raid["repelled"]
        stayed += raid.get("stayed", 0)
        assert state.adults == adults_before + raid.get("stayed", 0)
        assert raid.get("stayed", 0) <= free_beds(realm, config)
    assert repelled >= 10
    assert stayed <= repelled * 8 * 30 // 100  # about 10 % of the raiders, never most of them


def test_a_realm_out_of_range_is_left_alone(config, realm):
    x, y = _free_hex(config, {"1": realm}, 30, 40)
    after, results = _world(_pool(_band(x, y, 8)), {"1": realm}, config)
    assert not _events(results["1"], "raid") and after.bands[0].target is None


def test_a_small_band_near_the_land_is_seen(config, realm):
    x, y = _free_hex(config, {"1": realm}, 3, 3)
    _, results = _world(_pool(_band(x, y, 2)), {"1": realm}, config)  # too small to raid: it stays
    seen = _events(results["1"], "band_seen")
    assert len(seen) == 1 and seen[0]["week"] == 1 and not seen[0]["tower"]


def test_the_watchtower_sees_further(config, realm):
    tower = _tower(realm, config)
    roads = RoadMap(config, {"1": realm})
    spot = next((x, y) for y in range(roads.size) for x in range(roads.size)
                if roads.steps_to_land.get((x, y), 0) > config.bands.see
                and hex_distance(x, y, *tower) <= config.bands.tower_see)
    _, results = _world(_pool(_band(*spot, 2)), {"1": realm}, config)
    assert _events(results["1"], "band_seen")[0]["tower"]
    no_tower = copy.deepcopy(realm)
    no_tower.buildings = [b for b in no_tower.buildings if b.kind != "watchtower"]
    _, results = _world(_pool(_band(*spot, 2)), {"1": no_tower}, config)
    assert not _events(results["1"], "band_seen")


def test_fugitives_found_a_band_in_the_woods_near_their_realm(config, realm):
    realm.low_mood_turns = config.bandits.flee_turns
    after, results = _world(_pool(), {"1": realm}, config)
    fled = _events(results["1"], "flight")[0]
    assert fled["adults"] > 0
    band = after.bands[0]
    roads = RoadMap(config, {"1": realm})
    assert roads.terrain[band.camp_y][band.camp_x] in WOODS
    assert roads.steps_to_land[(band.camp_x, band.camp_y)] > config.bands.camp_gap


def test_a_fallen_realm_founds_a_band_on_its_land(config, realm):
    realm.game_over = "revolt"
    adults = realm.adults
    results = {"1": TurnResult(realm, [], [Event("game_over", {"reason": "revolt"})])}
    after = resolve_world(_pool(), results, config, 5)
    band = after.bands[0]
    assert (band.x, band.y) == tuple(realm.square)
    assert band.adults == adults * config.bandits.fallen_adult_pct // 100


def test_big_bands_split_and_small_ones_merge(config, realm):
    far = _free_hex(config, {"1": realm}, 30, 40, woods=True)
    after, _ = _world(_pool(_band(*far, 30)), {"1": realm}, config)
    assert len(after.bands) == 2 and all(b.adults <= 15 for b in after.bands)
    near_far = (far[0] + 2, far[1])
    after, _ = _world(_pool(_band(*far, 8), _band(*near_far, 2)), {"1": realm}, config)
    assert len(after.bands) == 1


def test_the_same_month_twice_gives_the_same_world(config, realm):
    x, y = _free_hex(config, {"1": realm}, 5, 5)
    realm.low_mood_turns = config.bandits.flee_turns
    first, _ = _world(_pool(_band(x, y, 8)), {"1": copy.deepcopy(realm)}, config)
    second, _ = _world(_pool(_band(x, y, 8)), {"1": copy.deepcopy(realm)}, config)
    assert pool_to_dict(first) == pool_to_dict(second)
