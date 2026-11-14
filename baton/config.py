"""Shared paths, connection settings, ID ranges and learning parameters."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
SNAPSHOT_DIR = RESULTS_DIR / "snapshots"

ISSUES_FILE = DATA_DIR / "issues.jsonl"
RESERVE_FILE = DATA_DIR / "reserve.jsonl"
ENTITY_TABLE_FILE = DATA_DIR / "entity_ids.json"
CURVE_FILE = RESULTS_DIR / "curve.json"

HYDRADB_HOME = Path(os.environ.get("BATON_HYDRADB_HOME", Path.home() / "Projects" / "hydradb"))
HYDRADB_URI = os.environ.get("BATON_HYDRADB_URI", "bolt://127.0.0.1:7687")
HYDRADB_TOKEN = os.environ.get("BATON_HYDRADB_TOKEN", "local-development-token-32-bytes")
HYDRADB_DATABASE = os.environ.get("BATON_HYDRADB_DATABASE", "default")

TEAM_ID_BASE = 1
TEAM_ID_MAX = 999
ENTITY_ID_BASE = 100_000
ISSUE_ID_BASE = 1_000_000

TOTAL_ISSUES = 2_000
LEARNING_SIZE = 1_700
TEST_SIZE = 300
RESERVE_SIZE = 3_000
BATCH_SIZE = 100
FROZEN_SIZE = 200
MIN_ENTITY_ISSUES = 3
SNAPSHOT_POINTS = (0, 500, 1_000, 1_700)

HISTORY_COST = 1.0
SAME_AS_COST = 0.1


@dataclass(frozen=True)
class Techniques:
    """Switches for each learning technique, so every line on the chart is reproducible."""

    reweight: bool = True
    shortcuts: bool = True
    merging: bool = True
    splitting: bool = True
    gap_filling: bool = True


COUNT_ONLY = Techniques(reweight=False, shortcuts=False, merging=False, splitting=False, gap_filling=False)
BATON = Techniques()


@dataclass(frozen=True)
class LearnParams:
    """Starting values for the learning rules. Tune on the learning stream only."""

    reward: float = 0.5
    penalty: float = 0.8
    floor: float = 0.05
    shortcut_min_paths: int = 3
    shortcut_scale: float = 2.0
    history_keep: int = 500
    merge_min_hits: int = 10
    merge_similarity: float = 0.9
    split_min_misses: int = 10
    split_dominance: float = 0.5
    split_min_support: int = 3
    gap_confidence: float = 0.4
    gap_min_known: int = 2
    gap_pull: int = 20
