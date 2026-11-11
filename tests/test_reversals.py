"""The sovereign sees when a plan reverses one of its recent decisions (server/ui/reversals.py)."""

from server.ui.reversals import reversal_lines

NAMES = {"treasurer": "Gualtiero Bracci, il Tesoriere"}


def test_a_plan_that_changes_a_recent_law_is_flagged():
    """Game 34: the Treasurer brought the tax from 25 to 12 the month after the sovereign's order."""
    decisions = {"set_tax": (7, 25), "set_doors": (4, "open")}
    plan = [{"order": {"action": "set_tax", "rate": 12}, "proposer": "treasurer"},
            {"order": {"action": "set_doors", "doors": "normal"}, "proposer": "gastaldo"},
            {"order": {"action": "set_militia", "guards": 2}, "proposer": "gastaldo"}]
    lines = reversal_lines(decisions, plan, NAMES)
    assert lines == {
        0: "Gualtiero Bracci, il Tesoriere cambia una tua decisione di luglio: gabella dal 25% al 12%.",
        1: "Il Gastaldo cambia una tua decisione di aprile: porte da aperte a normali.",
    }


def test_no_line_without_a_recent_decision_or_a_change():
    plan = [{"order": {"action": "set_ration", "ration": "reduced"}, "proposer": "treasurer"},
            {"order": {"action": "set_merchant_tax", "rate": 10}, "proposer": "treasurer"}]
    assert reversal_lines({}, plan, NAMES) == {}
    assert reversal_lines({"set_merchant_tax": (3, 10)}, plan, NAMES) == {}
