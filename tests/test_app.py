"""API tests for app.server against the fake service and the unimplemented real service."""

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import fake_service
from app.server import create_app

LINES = ("frozen", "count_only", "baton", "reweight", "shortcuts", "merging", "splitting", "gap_filling")
CSI_TITLE = "PVC stays Pending: volume attach timeout from the CSI driver"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(fake_service))


def not_implemented(*args, **kwargs):
    raise NotImplementedError


@pytest.fixture
def stub_client() -> TestClient:
    stub = SimpleNamespace(**{name: not_implemented for name in ("route_issue", "record_outcome", "curve", "graph_around", "stats")})
    return TestClient(create_app(stub))


def test_route_returns_top_teams_with_paths(client):
    res = client.post("/route", json={"title": CSI_TITLE, "body": "", "reporter": "alice"})
    assert res.status_code == 200
    data = res.json()
    assert set(data) == {"teams", "confidence", "entities_found", "entities_unknown"}
    assert 1 <= len(data["teams"]) <= 3
    top = data["teams"][0]
    assert top["team"] == "sig/storage"
    assert top["path"][-1] == top["team"]
    assert data["confidence"] == top["share"]
    shares = [t["share"] for t in data["teams"]]
    assert shares == sorted(shares, reverse=True)


def test_route_as_of_changes_the_answer(client):
    early = client.post("/route", json={"title": CSI_TITLE, "as_of": 0}).json()
    late = client.post("/route", json={"title": CSI_TITLE, "as_of": 1700}).json()
    assert early["teams"][0]["team"] != late["teams"][0]["team"]
    assert any(step.startswith("#") for t in early["teams"] for step in t["path"])


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},
        {"body": "no title"},
        {"title": "x", "as_of": 250},
        {"title": "x" * 501},
    ],
)
def test_route_rejects_bad_input(client, payload):
    assert client.post("/route", json=payload).status_code == 422


def test_learn_reports_the_step(client):
    issue = {
        "number": 120001,
        "title": "kubelet OOM kills pods under cgroup v2",
        "body": "",
        "created_at": "2024-01-01T00:00:00Z",
        "reporter": "bob",
        "sigs": ["sig/node"],
        "team": "sig/node",
    }
    res = client.post("/learn", json=issue)
    assert res.status_code == 200
    data = res.json()
    assert data["team"] == "sig/node"
    assert isinstance(data["correct"], bool)


def test_learn_needs_the_token_when_one_is_set():
    locked = TestClient(create_app(fake_service, learn_token="s3cret"))
    issue = {"number": 120002, "title": "kubelet crash", "created_at": "2024-01-01T00:00:00Z", "team": "sig/node"}
    assert locked.post("/learn", json=issue).status_code == 401
    assert locked.post("/learn", json=issue, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert locked.post("/learn", json=issue, headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert locked.post("/route", json={"title": "kubelet crash"}).status_code == 200


@pytest.mark.parametrize(
    "drop_or_change",
    [{"team": None}, {"number": 0}, {"title": ""}, {"created_at": None}],
)
def test_learn_rejects_bad_input(client, drop_or_change):
    issue = {"number": 1, "title": "t", "created_at": "2024-01-01", "team": "sig/node"}
    for key, value in drop_or_change.items():
        if value is None:
            issue.pop(key)
        else:
            issue[key] = value
    assert client.post("/learn", json=issue).status_code == 422


def test_curve_has_every_line_with_eighteen_points(client):
    lines = client.get("/curve").json()["lines"]
    assert set(lines) == set(LINES)
    for points in lines.values():
        assert len(points) == 18
        assert [p["issues"] for p in points] == list(range(0, 1800, 100))
        assert all(0 <= p["top1"] <= p["top3"] <= 1 for p in points)
    assert lines["baton"][-1]["top1"] > lines["count_only"][-1]["top1"] > lines["frozen"][-1]["top1"]


def test_graph_has_merged_name_and_shortcut(client):
    merged = client.get("/graph", params={"entity": "apiserver"}).json()
    ids = {n["id"] for n in merged["nodes"]}
    assert {n["label"] for n in merged["nodes"]} <= {"Team", "Entity", "Issue"}
    assert all(link["source"] in ids and link["target"] in ids for link in merged["links"])
    assert any(link["type"] == "SAME_AS" for link in merged["links"])
    shortcut = client.get("/graph", params={"entity": "oom"}).json()
    assert any(link["shortcut"] for link in shortcut["links"])


def test_graph_unknown_entity_is_empty(client):
    res = client.get("/graph", params={"entity": "nosuchthing"})
    assert res.status_code == 200
    assert res.json() == {"nodes": [], "links": []}


def test_graph_requires_entity(client):
    assert client.get("/graph").status_code == 422
    assert client.get("/graph", params={"entity": ""}).status_code == 422


def test_stats_has_counter_keys(client):
    data = client.get("/stats").json()
    for key in ("issues_learned", "links_reweighted", "merges", "shortcuts", "misroutes_avoided"):
        assert isinstance(data[key], int)


def test_every_dashboard_page_serves_the_built_app(client):
    for path in ("/", "/try", "/explore?entity=kubelet", "/connect?client=chatgpt"):
        page = client.get(path)
        assert page.status_code == 200
        assert '<div id="root">' in page.text
    asset = re.search(r'src="(/assets/[^"]+\.js)"', client.get("/").text).group(1)
    assert client.get(asset).status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/route", {"json": {"title": "kubelet crash"}}),
        ("post", "/learn", {"json": {"number": 1, "title": "t", "created_at": "2024-01-01", "team": "sig/node"}}),
        ("get", "/curve", {}),
        ("get", "/graph", {"params": {"entity": "kubelet"}}),
        ("get", "/stats", {}),
    ],
)
def test_unimplemented_service_returns_503(stub_client, method, path, kwargs):
    res = getattr(stub_client, method)(path, **kwargs)
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "service_unavailable"
    assert path in body["detail"]
