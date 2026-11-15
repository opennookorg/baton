"""Inspect a repo's recent closed issues and recommend the owner signal Baton should learn from."""

import re
from collections import Counter
from dataclasses import asdict, dataclass

from baton.repos import TEST_SHARE, RepoProfile

MIN_OWNED = 300
MAX_LARGEST_SHARE = 0.8
MIN_OWNERS = 2
MIN_FAMILY_LABELS = 2
MIN_OWNER_ISSUES = 3
PREFIX_SEPARATOR = re.compile(r"^(.+?(?:: |/|:|-))\S")
TRIAGE_FAMILIES = {
    "type", "kind", "status", "state", "resolution", "size", "priority", "prio", "p", "difficulty", "needs",
    "triage", "lifecycle", "cause", "from", "sweeper", "clawsweeper", "ci", "os", "browser", "release",
    "backport", "good", "help", "pr", "do", "cla", "ok", "approved", "lgtm", "stale", "i", "s", "e", "a",
    "beta", "stable", "regression", "relnotes", "rla", "perf", "merged", "close", "duplicate", "invalid",
    "impact", "severity", "sev", "bug", "issue", "rating", "feature", "enhancement", "question",
}


@dataclass(frozen=True)
class Candidate:
    """One possible owner signal measured on the sample."""

    signal: str
    prefix: str
    coverage: float
    owners: int
    effective_owners: float
    largest_share: float
    seen_share: float
    estimated_owned: int

    @property
    def score(self) -> float:
        """Coverage times evenness times seen share: most issues owned, no owner dominating, and later owners already seen earlier."""
        return self.coverage * (1 - self.largest_share) * self.seen_share

    def profile(self, repo: str) -> RepoProfile:
        """The profile this candidate stands for."""
        return RepoProfile(repo=repo, signal=self.signal, prefix=self.prefix)


def family(label: str) -> str:
    """The label's prefix up to its first separator, or empty when it has none."""
    match = PREFIX_SEPARATOR.match(label)
    return match.group(1) if match else ""


def label_families(records: list[dict]) -> list[str]:
    """Label prefixes shared by at least MIN_FAMILY_LABELS distinct labels, minus triage families."""
    labels_by_family: dict[str, set[str]] = {}
    for record in records:
        for label in record["labels"]:
            prefix = family(label)
            if prefix:
                labels_by_family.setdefault(prefix, set()).add(label)
    return sorted(
        prefix
        for prefix, labels in labels_by_family.items()
        if len(labels) >= MIN_FAMILY_LABELS and re.split(r"[:/\- ]", prefix.lower())[0] not in TRIAGE_FAMILIES
    )


def measure(profile: RepoProfile, records: list[dict], closed_issues: int) -> Candidate:
    """Coverage, owner spread and how many test-period owners the learning period already saw, for one signal."""
    owned = [profile.owners(r["labels"], r["fixer"], tuple(r["assignees"])) for r in records]
    owned = [owners for owners in owned if owners]
    counts = Counter(owner for owners in owned for owner in owners)
    total = sum(counts.values()) or 1
    shares = [count / total for count in counts.values()]
    cut = len(owned) - round(len(owned) * TEST_SHARE)
    learned = {owner for owners in owned[:cut] for owner in owners}
    test = owned[cut:]
    coverage = len(owned) / len(records) if records else 0.0
    return Candidate(
        signal=profile.signal,
        prefix=profile.prefix,
        coverage=round(coverage, 3),
        owners=sum(count >= MIN_OWNER_ISSUES for count in counts.values()),
        effective_owners=round(1 / sum(s * s for s in shares), 2) if shares else 0.0,
        largest_share=round(max(shares, default=1.0), 3),
        seen_share=round(sum(all(o in learned for o in owners) for owners in test) / len(test), 3) if test else 0.0,
        estimated_owned=round(coverage * closed_issues),
    )


def candidates(repo: str, records: list[dict], closed_issues: int) -> list[Candidate]:
    """Every label family plus the fixer and assignee signals, best score first."""
    profiles = [RepoProfile(repo=repo, signal="label_prefix", prefix=prefix) for prefix in label_families(records)]
    profiles += [RepoProfile(repo=repo, signal="fixer"), RepoProfile(repo=repo, signal="assignee")]
    measured = [measure(profile, records, closed_issues) for profile in profiles]
    return sorted(measured, key=lambda c: c.score, reverse=True)


def verdict(candidate: Candidate | None) -> str:
    """Why a candidate cannot be routed on, or "ok"."""
    if candidate is None:
        return "no owner signal: no label family, fixer or assignee covers any issue"
    if candidate.owners < MIN_OWNERS or candidate.largest_share >= MAX_LARGEST_SHARE:
        return f"one owner: the largest owner takes {candidate.largest_share:.0%} of issues, nothing to route"
    if candidate.estimated_owned < MIN_OWNED:
        return f"too small: about {candidate.estimated_owned} owned closed issues, Baton needs {MIN_OWNED}"
    return "ok"


def diagnose(repo: str, records: list[dict], info: dict) -> dict:
    """The doctor's report: every candidate, the recommended one and its verdict."""
    ranked = candidates(repo, records, info["closed_issues"])
    usable = [c for c in ranked if verdict(c) == "ok"]
    best = usable[0] if usable else (ranked[0] if ranked and ranked[0].coverage > 0 else None)
    return {
        "repo": repo,
        "closed_issues": info["closed_issues"],
        "sampled": len(records),
        "recommended": asdict(best) if best else None,
        "verdict": verdict(best),
        "candidates": [asdict(c) | {"score": round(c.score, 3), "verdict": verdict(c)} for c in ranked],
    }


def report_text(report: dict, top: int = 6) -> str:
    """The doctor's report as a short table for the terminal."""
    lines = [f"{report['repo']}: {report['closed_issues']} closed issues, {report['sampled']} sampled", ""]
    lines.append(f"{'signal':<28}{'coverage':>9}{'owners':>8}{'eff':>7}{'largest':>9}{'seen':>7}{'owned':>8}  verdict")
    for c in report["candidates"][:top]:
        name = f"{c['signal']} {c['prefix']!r}" if c["signal"] == "label_prefix" else c["signal"]
        lines.append(
            f"{name:<28}{c['coverage']:>9.0%}{c['owners']:>8}{c['effective_owners']:>7.1f}"
            f"{c['largest_share']:>9.0%}{c['seen_share']:>7.0%}{c['estimated_owned']:>8}  {c['verdict']}"
        )
    best = report["recommended"]
    choice = f"{best['signal']} {best['prefix']!r}".strip() if best else "none"
    lines += ["", f"recommended: {choice} ({report['verdict']})"]
    return "\n".join(lines)
