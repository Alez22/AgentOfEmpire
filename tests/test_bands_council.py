"""Roads of the world, phase 1, step 3: what the council is told of the bands
(manual, the Gastaldo's briefing and craft, the Voice of the square)."""

from dataclasses import replace

from engine import new_game
from server.council import briefing, manual, voice
from server.council.meeting import expertise_block


def test_the_manual_tells_the_odds_with_bands_and_the_old_rule_without(config):
    with_bands = manual.prompt_text(config)
    assert "odds" in with_bands and f"plus {config.bands.guard_worth} for each guard" in with_bands
    assert "stops 2 raiders" not in with_bands and "Of the raiders the guards stop" not in with_bands
    assert "whatever the doors" in with_bands
    without = manual.prompt_text(replace(config, bands=None))
    assert f"each guard stops {config.bandits.repel_per_guard} raiders" in without and "odds" not in without
    page = " ".join(" ".join(s["notes"]) for s in manual.page_sections(config))
    assert "azzardo" in page and "qualunque siano le porte" in page


def test_the_gastaldo_reads_the_odds_and_the_bands_seen(config):
    state = new_game(config, seed=7, site_index=0)
    seen = {"band": 3, "adults": 9, "week": 2, "x": 18, "y": 8, "tower": True}
    stayed = {"raiders": 8, "guards": 4, "repelled": True, "food": 0, "wood": 0, "stayed": 1}
    text = "\n".join(briefing.gate_lines(state, config, [(4, "band_seen", seen), (5, "raid", stayed)]))
    assert "8 in 20" in text and "stops about" not in text
    assert "a band of about ten seen from the watchtower (week 2)" in text
    assert "1 of them stayed as citizens" in text
    old = "\n".join(briefing.gate_lines(state, replace(config, bands=None), []))
    assert f"stops about {config.bandits.repel_per_guard} raiders" in old and "band seen" not in old


def test_the_gastaldo_s_craft_has_a_bands_variant():
    bands = expertise_block("gastaldo", with_doors=True, with_bands=True)
    old = expertise_block("gastaldo", with_doors=True)
    assert "a gamble" in bands and "whatever the doors" in bands and "two of them" not in bands
    assert "two of them" in old and "a gamble" not in old
    assert expertise_block("treasurer", with_bands=True) == expertise_block("treasurer")  # no variant: unchanged


def test_the_square_hears_of_bands_seen():
    assert "band_seen" in voice.TOLD_EVENTS
