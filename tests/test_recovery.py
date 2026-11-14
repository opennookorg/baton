from eval.recovery import relabel
from tests.test_router import ISSUES


def test_relabel_moves_one_team_and_leaves_others_alone():
    issue = ISSUES[0]
    old = issue.sigs[0]
    moved = relabel(issue, old, "sig/elsewhere")
    assert old not in moved.sigs and "sig/elsewhere" in moved.sigs and moved.number == issue.number
    assert relabel(issue, "sig/not-on-this-issue", "sig/elsewhere") is issue
    assert relabel(issue, old, old).sigs == issue.sigs
