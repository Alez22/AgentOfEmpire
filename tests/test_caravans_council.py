"""Roads of the world, phase 2, step 2: what the council is told of the
caravans (manual, the Treasurer's market section and craft, the Chancellor's
cost check, the Gastaldo's memory, the Voice of the square)."""

from dataclasses import replace

from engine import new_game
from engine.market import new_market
from server.council import briefing, manual, voice
from server.council.meeting import expertise_block


def test_the_manual_tells_the_latency_with_caravans_and_the_old_rule_without(config):
    with_caravans = manual.prompt_text(config)
    assert "reach the stores at the month's end" in with_caravans and "used the same month" not in with_caravans
    assert f"within {config.caravans.radius} hexes of a band" in with_caravans
    without = manual.prompt_text(replace(config, caravans=None))
    assert "used the same month" in without and "fair" not in without.split("Market:")[1].split("\n")[0]
    page = " ".join(" ".join(s["notes"]) for s in manual.page_sections(config))
    assert "si usa dal mese dopo" in page and "ciò che si compra si usa subito" not in page
    old_page = " ".join(" ".join(s["notes"]) for s in manual.page_sections(replace(config, caravans=None)))
    assert "ciò che si compra si usa subito" in old_page and "carovana" not in old_page


def test_the_treasurer_and_the_chancellor_hear_of_the_latency(config):
    open_market = replace(config, market=replace(config.market, needs_building=False))
    state = new_game(open_market, seed=7, site_index=0)
    market = new_market(open_market, 2)
    text = "\n".join(briefing.market_lines(state, open_market, market, "1"))
    assert "The warehouse is at the fair" in text
    old = replace(open_market, caravans=None)
    assert "at the fair" not in "\n".join(briefing.market_lines(state, old, market, "1"))
    assert "does not count them" in briefing.market_summary_line(open_market, market)[0]
    assert "filled in full" in briefing.market_summary_line(old, market)[0]


def test_the_gastaldo_remembers_a_robbed_caravan(config):
    state = new_game(config, seed=7, site_index=0)
    robbed = {"leg": "back", "goods": {"food": 100}, "band": 2, "adults": 6, "week": 3, "x": 30, "y": 30}
    seen = {"band": 2, "adults": 6, "week": 3, "x": 30, "y": 29, "tower": False, "road": True}
    text = "\n".join(briefing.gate_lines(state, config, [(4, "caravan_robbed", robbed), (4, "band_seen", seen)]))
    assert "a band of about ten robbed our caravan home from the fair of 100 food (week 3)" in text
    assert "seen on the road to the fair" in text
    assert "The last band at the gate" not in text  # a robbery is no raid: no odds on it


def test_the_treasurer_s_craft_adds_the_caravans_only_with_them():
    assert "goods bought arrive only at the month's end" in expertise_block("treasurer", with_market=True,
                                                                            with_caravans=True)
    assert "month's end" not in expertise_block("treasurer", with_market=True)


def test_the_square_hears_of_robbed_caravans():
    assert "caravan_robbed" in voice.TOLD_EVENTS
