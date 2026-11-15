import json

import pytest

from baton import repos, service
from baton.config import CURVE_FILE, ENTITY_TABLE_FILE, HYDRADB_DATABASE, ISSUES_FILE, SNAPSHOT_DIR
from baton.models import RouteResult, TeamScore
from baton.repos import KUBERNETES_PROFILE, RepoProfile, Sizes


@pytest.fixture
def repo_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(repos, "REPOS_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(repos, "REPOS_RESULTS_DIR", tmp_path / "results")
    return tmp_path


def test_kubernetes_sizes_reproduce_the_original_run_exactly():
    assert KUBERNETES_PROFILE.sizes == Sizes(
        total=2000, learning=1700, test=300, reserve=3000, batch=100, frozen=200, snapshots=(0, 500, 1000, 1700)
    )


@pytest.mark.parametrize("available", [300, 612, 1100, 2400, 4999])
def test_scaled_sizes_keep_the_split_and_put_snapshots_on_batch_boundaries(available):
    sizes = Sizes.scaled(available)
    assert sizes.total == min(available, 2000)
    assert sizes.learning + sizes.test == sizes.total
    assert sizes.test == round(sizes.total * 0.15)
    assert sizes.reserve == min(available - sizes.total, 3000)
    assert sizes.snapshots[0] == 0 and sizes.snapshots[-1] == sizes.learning
    assert all(point % sizes.batch == 0 for point in sizes.snapshots[:-1])
    assert list(sizes.snapshots) == sorted(set(sizes.snapshots))


def test_kubernetes_keeps_its_files_and_base_database():
    assert KUBERNETES_PROFILE.issues_file == ISSUES_FILE
    assert KUBERNETES_PROFILE.table_file == ENTITY_TABLE_FILE
    assert KUBERNETES_PROFILE.snapshot_dir == SNAPSHOT_DIR
    assert KUBERNETES_PROFILE.curve_file == CURVE_FILE
    assert KUBERNETES_PROFILE.database == HYDRADB_DATABASE


def test_other_repos_get_their_own_files_and_scoped_database():
    rust, react = RepoProfile(repo="rust-lang/rust", prefix="T-"), RepoProfile(repo="react/react", prefix="Component: ")
    assert rust.data_dir.name == "rust-lang__rust" and rust.results_dir.name == "rust-lang__rust"
    assert rust.database.startswith(f"{HYDRADB_DATABASE}.scope1.") and rust.database.endswith("._")
    assert len({rust.database, react.database, KUBERNETES_PROFILE.database}) == 3


def test_owners_read_off_each_signal():
    labels = ["T-compiler", "T-libs", "C-bug"]
    assert RepoProfile(repo="a/b", signal="label_prefix", prefix="T-").owners(labels) == ["T-compiler", "T-libs"]
    assert RepoProfile(repo="a/b", signal="labels", labels=("C-bug",)).owners(labels) == ["C-bug"]
    assert RepoProfile(repo="a/b", signal="fixer").owners(labels, fixer="alice") == ["alice"]
    assert RepoProfile(repo="a/b", signal="fixer").owners(labels) == []
    assert RepoProfile(repo="a/b", signal="assignee").owners(labels, assignees=("bob", "amy")) == ["amy", "bob"]


def test_profile_round_trips_through_json(repo_dirs):
    profile = RepoProfile(repo="a/b", signal="labels", labels=("x", "y"), available=812, path_roots=("src",), doctor={"verdict": "ok"})
    assert RepoProfile.from_json(json.loads(json.dumps(json.loads(profile.save().read_text())))) == profile


def routable(profile: RepoProfile) -> RepoProfile:
    profile.save()
    profile.snapshot_dir.mkdir(parents=True, exist_ok=True)
    (profile.snapshot_dir / f"{profile.sizes.snapshots[-1]}.json").write_text("{}")
    return profile


def test_load_defaults_to_kubernetes(repo_dirs):
    assert repos.load(None) is KUBERNETES_PROFILE
    assert repos.load("Kubernetes/Kubernetes") is KUBERNETES_PROFILE


def test_load_explains_unknown_rejected_and_unlearned_repos(repo_dirs):
    with pytest.raises(LookupError, match="unknown repo 'nobody/nothing'; Baton routes for: kubernetes/kubernetes"):
        repos.load("nobody/nothing")
    rejected = RepoProfile(repo="tiny/repo")
    rejected.data_dir.mkdir(parents=True)
    (rejected.data_dir / "doctor.json").write_text(json.dumps({"verdict": "too small: about 69 owned closed issues, Baton needs 300"}))
    with pytest.raises(LookupError, match="tiny/repo cannot be routed: too small"):
        repos.load("tiny/repo")
    RepoProfile(repo="fresh/repo", signal="fixer", available=900).save()
    with pytest.raises(LookupError, match="no learned graph yet"):
        repos.load("fresh/repo")


def test_load_matches_names_without_case_and_lists_routable_repos(repo_dirs):
    profile = routable(RepoProfile(repo="Owner/Name", signal="fixer", available=900))
    RepoProfile(repo="fresh/repo", signal="fixer", available=900).save()
    assert repos.load("owner/name") == profile
    assert repos.loaded() == ["kubernetes/kubernetes", "Owner/Name"]


def test_service_calls_run_against_the_named_repo(repo_dirs, monkeypatch):
    profile = routable(RepoProfile(repo="rust-lang/rust", prefix="T-", available=900))
    seen = []

    def fake_route(title, body, reporter, table):
        seen.append(repos.current())
        return RouteResult(teams=[TeamScore("T-compiler", 1.0, ["borrowck", "T-compiler"])], confidence=1.0, entities_found=1, entities_unknown=0)

    monkeypatch.setattr(service, "route", fake_route)
    monkeypatch.setattr(service, "table", lambda: None)
    service.route_issue("borrowck ICE", "", repo="rust-lang/rust")
    service.route_issue("kubelet crash", "")
    assert seen == [profile, KUBERNETES_PROFILE]
    assert repos.current() is KUBERNETES_PROFILE


def test_route_with_no_match_says_why(repo_dirs, monkeypatch):
    monkeypatch.setattr(service, "route", lambda *args: RouteResult(teams=[], confidence=0.0, entities_found=0, entities_unknown=3))
    monkeypatch.setattr(service, "table", lambda: None)
    result = service.route_issue("zzz", "")
    assert result.message == "nothing in this issue matches what Baton learned from kubernetes/kubernetes, so it cannot be routed"


def test_snapshot_rejects_points_the_repo_does_not_have(repo_dirs):
    profile = routable(RepoProfile(repo="small/repo", signal="fixer", available=600))
    with pytest.raises(ValueError, match=r"as_of must be one of \[0, 150, 300, 510\] for small/repo"):
        service.repo_snapshot(profile, 500)
