"""The town hall seen by the council, the automatic sovereign and the pages
(docs/DESIGN.md, "The town hall site")."""

from dataclasses import replace

from engine import parse_order
from engine.market import new_market
from server.council import briefing, manual
from server.sovereign import rules
from server.ui import labels
from tests.test_town_hall import _ready


def test_the_briefing_lists_the_conditions_then_the_works(config):
    state = _ready(config)
    text = "\n".join(briefing.town_hall_lines(state, config))
    assert "build town_hall" in text and "NOT YET" not in text
    state.adults -= 1
    text = "\n".join(briefing.town_hall_lines(state, config))
    assert "population 119 of 120: NOT YET" in text
    state.town_hall_site, state.builders = 4, config.town_hall.builders
    assert "4 months of works left; 10 adults work on it" in "\n".join(briefing.town_hall_lines(state, config))
    state.era = "town"
    assert briefing.town_hall_lines(state, config) == ["- The realm is a town: the town hall stands."]
    assert briefing.town_hall_lines(state, replace(config, town_hall=None)) == []


def test_the_manual_tells_the_passage(config):
    assert "build town_hall" in manual.prompt_text(config)
    assert "town_hall" not in manual.prompt_text(replace(config, town_hall=None))
    titles = [section["title"] for section in manual.page_sections(config)]
    assert "Il municipio" in titles


def test_the_labels_in_italian(config):
    assert labels.event_label("era_reached", {"era": "town"}).startswith("Il municipio è finito")
    assert labels.order_label({"action": "build", "building": "town_hall"}) == "Costruire: municipio"
    state = _ready(config)
    state.buildings = [b for b in state.buildings if b.kind != "market"]
    conditions = dict(labels.town_hall_conditions_it(state, config))
    assert conditions["un mercato finito"] is False
    assert conditions["almeno 120 abitanti (oggi 120)"] is True


def _month(state, config):
    state.workers.food -= 3
    state.workers.trade = 3  # merchants at the market: R10's staffing directive stays silent
    return rules.Month(state, config, new_market(config, 1), "1")


def _r14(month, items=()) -> bool:
    found = rules.directive(month, list(items))
    return found is not None and "(R14)" in found[1]


def test_r14_opens_the_site_when_the_realm_is_ready(config):
    month = _month(_ready(config), config)
    text, _ = rules.directive(month, [])
    assert "municipio" in text and _r14(month)
    raw = {"action": "build", "building": "town_hall"}
    assert not _r14(month, [rules.Item(0, parse_order(raw)[0], raw, True)])  # the council planned it already


def test_r14_waits_for_the_conditions_and_the_cost(config):
    state = _ready(config)
    state.adults -= 1
    assert not _r14(_month(state, config))
    state = _ready(config)
    state.gold = config.town_hall.gold - 1
    assert not _r14(_month(state, config))
