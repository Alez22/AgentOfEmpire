"""When the sovereign plays in a seasonal game (server/sovereign/rhythm.py)."""

from server.sovereign.rhythm import alarms, next_season_start, why_sovereign


def test_the_first_month_of_each_season_is_the_sovereigns():
    assert [turn for turn in range(1, 14) if why_sovereign(turn, [], [])] == [1, 4, 7, 10, 13]
    assert why_sovereign(4, [], []) == "Inizio della primavera"
    assert why_sovereign(10, [], []) == "Inizio dell'autunno"


def test_next_season_start():
    assert next_season_start(1) == 4
    assert next_season_start(3) == 4
    assert next_season_start(10) == 13


def test_famine_and_an_unrepelled_raid_are_alarms():
    assert alarms([{"kind": "famine", "data": {"missing_pct": 5}}], []) == ["carestia"]
    assert alarms([{"kind": "raid", "data": {"repelled": False}}], []) == ["razzia non respinta"]
    assert alarms([{"kind": "raid", "data": {"repelled": True}}], []) == []
    assert why_sovereign(5, [{"kind": "famine", "data": {}}], []) == "Allarme ad aprile: carestia"


def test_unrest_is_an_alarm_only_when_it_climbs():
    up = {"kind": "unrest_changed", "data": {"from": "protests", "to": "strike"}}
    down = {"kind": "unrest_changed", "data": {"from": "strike", "to": "protests"}}
    assert alarms([up], []) == ["sciopero"]
    assert alarms([down], []) == []


def test_only_the_first_flight_of_a_stretch_is_an_alarm():
    """Game 37: flight came every month from the protests on and called the
    sovereign every month."""
    flight = {"kind": "flight", "data": {"adults": 1, "children": 0, "merchants": 0}}
    assert alarms([flight], []) == ["fuga dal regno"]
    assert alarms([flight], [flight]) == []
    assert why_sovereign(6, [flight], [flight]) is None


def test_quiet_events_call_nobody():
    assert why_sovereign(2, [{"kind": "demography", "data": {"births": 1}}], []) is None
