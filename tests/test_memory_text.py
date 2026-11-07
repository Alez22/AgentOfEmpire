"""Wording of a minister's memory: refused proposals are named."""

from server.council.memory import _outcome_text

FARM = {"action": "build", "building": "farm"}
SAWMILL = {"action": "build", "building": "sawmill"}


def _approved(raw):
    return {"raw": raw, "accepted": True, "code": None}


def test_refused_proposals_are_named():
    text = _outcome_text([_approved(FARM)], [SAWMILL, FARM])
    assert text == "Approved: build farm carried out. Not approved by the sovereign: build sawmill."


def test_all_approved_has_no_refusal_line():
    assert _outcome_text([_approved(FARM)], [FARM]) == "Approved: build farm carried out."


def test_nothing_approved():
    assert _outcome_text([], [SAWMILL]) == "None approved by the sovereign."
