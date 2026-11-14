from baton.models import Issue, RouteResult, TeamScore


def test_issue_from_json_defaults_missing_body():
    issue = Issue.from_json(
        {"number": 7, "title": "t", "body": None, "created_at": "2024-01-01T00:00:00Z", "reporter": "r", "sigs": ["sig/node"]}
    )
    assert issue.body == ""
    assert issue.sigs == ("sig/node",)


def test_route_result_shape():
    result = RouteResult(teams=[TeamScore("sig/node", 0.62, ["kubelet", "sig/node"])], confidence=0.62, entities_found=3, entities_unknown=1)
    assert result.top_team == "sig/node"
    assert result.to_dict() == {
        "teams": [{"team": "sig/node", "share": 0.62, "path": ["kubelet", "sig/node"]}],
        "confidence": 0.62,
        "entities_found": 3,
        "entities_unknown": 1,
    }
