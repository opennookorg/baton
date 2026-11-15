"""Repo profiles: which repo, which owner signal, scaled sizes, per-repo files and graph, and the active repo."""

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from baton.config import (
    BATCH_SIZE,
    CURVE_FILE,
    DATA_DIR,
    ENTITY_TABLE_FILE,
    FROZEN_SIZE,
    HYDRADB_DATABASE,
    ISSUES_FILE,
    LEARNING_SIZE,
    RESERVE_FILE,
    RESERVE_SIZE,
    RESULTS_DIR,
    SNAPSHOT_DIR,
    SNAPSHOT_POINTS,
    TEST_SIZE,
    TOTAL_ISSUES,
)

Signal = Literal["label_prefix", "labels", "fixer", "assignee"]
SIGNALS: tuple[Signal, ...] = ("label_prefix", "labels", "fixer", "assignee")
KUBERNETES = "kubernetes/kubernetes"
REPOS_DATA_DIR = DATA_DIR / "repos"
REPOS_RESULTS_DIR = RESULTS_DIR / "repos"
PROFILE_FILE = "profile.json"
TEST_SHARE = TEST_SIZE / TOTAL_ISSUES
MIN_BATCH = 10


@dataclass(frozen=True)
class Sizes:
    """Issue counts for one repo's split and learning stream, scaled from Kubernetes' 2,000 / 1,700 / 300."""

    total: int
    learning: int
    test: int
    reserve: int
    batch: int
    frozen: int
    snapshots: tuple[int, ...]

    @classmethod
    def scaled(cls, available: int) -> "Sizes":
        """Sizes for a repo with `available` owned issues: the newest TOTAL_ISSUES (or all) split 85/15, the rest as reserve."""
        total = min(available, TOTAL_ISSUES)
        test = round(total * TEST_SHARE)
        learning = total - test
        reserve = min(max(available - total, 0), RESERVE_SIZE)
        batch = max(MIN_BATCH, round(learning * BATCH_SIZE / LEARNING_SIZE))
        frozen = round(learning * FROZEN_SIZE / LEARNING_SIZE)
        middle = {min(round(learning * point / LEARNING_SIZE / batch) * batch, learning) for point in SNAPSHOT_POINTS}
        snapshots = tuple(sorted(middle | {0, learning}))
        return cls(total, learning, test, reserve, batch, frozen, snapshots)


@dataclass(frozen=True)
class RepoProfile:
    """One repo and how to read its owner off a closed issue."""

    repo: str
    signal: Signal = "label_prefix"
    prefix: str = ""
    labels: tuple[str, ...] = ()
    available: int = TOTAL_ISSUES + RESERVE_SIZE
    path_roots: tuple[str, ...] = ()
    stop_words: tuple[str, ...] = ()
    hide_terms: tuple[str, ...] = ()
    doctor: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def slug(self) -> str:
        """The repo name safe for a directory: owner__name."""
        return self.repo.replace("/", "__")

    @property
    def is_kubernetes(self) -> bool:
        """Kubernetes keeps its original files, graph and extraction rules."""
        return self.repo == KUBERNETES

    @property
    def sizes(self) -> Sizes:
        """Split and stream sizes scaled to the owned issues this repo has."""
        return Sizes.scaled(self.available)

    @property
    def data_dir(self) -> Path:
        """Where this repo's fetched issues, ID table and profile live."""
        return DATA_DIR if self.is_kubernetes else REPOS_DATA_DIR / self.slug

    @property
    def results_dir(self) -> Path:
        """Where this repo's curve, baselines and snapshots live."""
        return RESULTS_DIR if self.is_kubernetes else REPOS_RESULTS_DIR / self.slug

    @property
    def issues_file(self) -> Path:
        return ISSUES_FILE if self.is_kubernetes else self.data_dir / "issues.jsonl"

    @property
    def reserve_file(self) -> Path:
        return RESERVE_FILE if self.is_kubernetes else self.data_dir / "reserve.jsonl"

    @property
    def raw_file(self) -> Path:
        return self.data_dir / "raw.jsonl.gz"

    @property
    def table_file(self) -> Path:
        return ENTITY_TABLE_FILE if self.is_kubernetes else self.data_dir / "entity_ids.json"

    @property
    def snapshot_dir(self) -> Path:
        return SNAPSHOT_DIR if self.is_kubernetes else self.results_dir / "snapshots"

    @property
    def curve_file(self) -> Path:
        return CURVE_FILE if self.is_kubernetes else self.results_dir / "curve.json"

    @property
    def no_graph_file(self) -> Path:
        return self.results_dir / "no_graph.json"

    @property
    def live_state_file(self) -> Path:
        return self.results_dir / "live_state.json"

    @property
    def database(self) -> str:
        """Kubernetes uses the base HydraDB database; every other repo gets its own scoped database."""
        if self.is_kubernetes:
            return HYDRADB_DATABASE
        tenant = base64.urlsafe_b64encode(self.repo.encode()).decode().rstrip("=")
        return f"{HYDRADB_DATABASE}.scope1.{tenant}._"

    @property
    def routable(self) -> bool:
        """True once the repo has a final snapshot to route with."""
        return (self.snapshot_dir / f"{self.sizes.snapshots[-1]}.json").exists()

    def owners(self, labels: list[str], fixer: str = "", assignees: tuple[str, ...] = ()) -> list[str]:
        """The owners this profile's signal reads off one closed issue."""
        if self.signal == "label_prefix":
            return sorted(label for label in labels if label.startswith(self.prefix))
        if self.signal == "labels":
            return sorted(label for label in labels if label in self.labels)
        if self.signal == "fixer":
            return [fixer] if fixer else []
        return sorted(assignees)

    def save(self) -> Path:
        """Write profile.json next to the repo's data."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / PROFILE_FILE
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n")
        return path

    @classmethod
    def from_json(cls, row: dict) -> "RepoProfile":
        tuples = {key: tuple(row.get(key, ())) for key in ("labels", "path_roots", "stop_words", "hide_terms")}
        return cls(**{**row, **tuples})


KUBERNETES_PROFILE = RepoProfile(repo=KUBERNETES, signal="label_prefix", prefix="sig/")
_current: ContextVar[RepoProfile] = ContextVar("baton_repo", default=KUBERNETES_PROFILE)


def current() -> RepoProfile:
    """The repo the running code works on; Kubernetes unless set with `use`."""
    return _current.get()


@contextmanager
def use(profile: RepoProfile) -> Iterator[RepoProfile]:
    """Make `profile` the active repo for the enclosed code, then restore the previous one."""
    token = _current.set(profile)
    try:
        yield profile
    finally:
        _current.reset(token)


def profile_path(repo: str) -> Path:
    """Where a repo's profile lives, matching owner/name without regard to case as GitHub does."""
    slug = repo.replace("/", "__")
    found = next((path for path in REPOS_DATA_DIR.glob("*") if path.name.lower() == slug.lower()), None)
    return (found or REPOS_DATA_DIR / slug) / PROFILE_FILE


def load(repo: str | None = None) -> RepoProfile:
    """The saved profile for `owner/name`; Kubernetes for None, "kubernetes" or its full name."""
    if repo is None or repo.lower() in ("", "kubernetes", KUBERNETES):
        return KUBERNETES_PROFILE
    path = profile_path(repo)
    doctor_file = path.with_name("doctor.json")
    verdict = json.loads(doctor_file.read_text())["verdict"] if doctor_file.exists() else "ok"
    if not path.exists() and verdict != "ok":
        raise LookupError(f"{repo} cannot be routed: {verdict}")
    if not path.exists():
        raise LookupError(f"unknown repo {repo!r}; Baton routes for: {', '.join(loaded())}")
    profile = RepoProfile.from_json(json.loads(path.read_text()))
    if not profile.routable:
        raise LookupError(f"{repo} has no learned graph yet: run `uv run python -m eval.onboard onboard {repo}`")
    return profile


def loaded() -> list[str]:
    """Repos that have a final snapshot to route with, Kubernetes first."""
    profiles = (RepoProfile.from_json(json.loads(path.read_text())) for path in sorted(REPOS_DATA_DIR.glob(f"*/{PROFILE_FILE}")))
    return [KUBERNETES] + [profile.repo for profile in profiles if profile.routable]
