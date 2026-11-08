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


HOUSE = {"action": "build", "building": "house"}


def test_the_chancellor_and_the_sovereign_are_told_apart():
    """Game 20: a house the Chancellor left out was remembered as refused by the sovereign."""
    text = _outcome_text([_approved(FARM)], [FARM, HOUSE, SAWMILL], planned=[FARM, SAWMILL])
    assert text == ("Approved: build farm carried out."
                    " Left out of the plan by the Chancellor (the sovereign never saw them): build house."
                    " Removed from the plan by the sovereign: build sawmill.")


def test_a_plan_without_this_minister():
    text = _outcome_text([], [HOUSE], planned=[])
    assert text == ("None approved by the sovereign."
                    " Left out of the plan by the Chancellor (the sovereign never saw them): build house.")


def test_a_changed_proposal_is_told_as_changed():
    proposed = {"action": "assign_workers", "food": 50, "wood": 4, "stone": 2, "clearing": 2}
    planned = {"action": "assign_workers", "food": 53, "wood": 3, "stone": 2, "clearing": 0}
    text = _outcome_text([_approved(planned)], [proposed], planned=[planned])
    assert text == ("Approved: assign_workers food 53 wood 3 stone 2 clearing 0 carried out."
                    " Changed by the Chancellor: assign_workers food 50 wood 4 stone 2 clearing 2"
                    " → assign_workers food 53 wood 3 stone 2 clearing 0.")


def test_a_build_reads_in_order():
    from server.council.memory import order_text
    assert order_text({"zone": "Campi", "action": "build", "building": "farm"}) == "build farm in Campi"
