from baton import doctor


def record(number: int, labels=(), fixer="", assignees=()) -> dict:
    return {"number": number, "labels": list(labels), "fixer": fixer, "assignees": list(assignees)}


def test_family_is_the_prefix_up_to_its_first_separator():
    assert doctor.family("sig/node") == "sig/"
    assert doctor.family("Component: DOM") == "Component: "
    assert doctor.family("T-compiler") == "T-"
    assert doctor.family("impact:crash-loop") == "impact:"
    assert doctor.family("bug") == ""


def test_label_families_drop_singletons_and_triage_families():
    records = [record(1, ["area/a", "area/b", "kind/bug", "kind/feature", "impact:data-loss", "impact:ux", "solo/x"])]
    assert doctor.label_families(records) == ["area/"]


def test_measure_reports_coverage_spread_and_seen_share():
    records = [record(i, [f"area/{'ab'[i % 2]}"]) for i in range(80)] + [record(80 + i) for i in range(20)]
    measured = doctor.measure(doctor.RepoProfile(repo="a/b", signal="label_prefix", prefix="area/"), records, closed_issues=1000)
    assert measured.coverage == 0.8
    assert measured.owners == 2 and measured.largest_share == 0.5 and measured.effective_owners == 2.0
    assert measured.seen_share == 1.0
    assert measured.estimated_owned == 800


def test_verdict_rejects_one_owner_and_small_repos():
    base = doctor.Candidate("fixer", "", 0.5, 10, 6.0, 0.3, 0.9, 5000)
    assert doctor.verdict(base) == "ok"
    assert doctor.verdict(base.__class__(**{**base.__dict__, "largest_share": 0.85})).startswith("one owner")
    assert doctor.verdict(base.__class__(**{**base.__dict__, "owners": 1})).startswith("one owner")
    assert doctor.verdict(base.__class__(**{**base.__dict__, "estimated_owned": 120})).startswith("too small")
    assert doctor.verdict(None).startswith("no owner signal")


def test_diagnose_prefers_an_even_signal_whose_owners_recur():
    teams = ["comp/gateway", "comp/cli", "comp/desktop", "comp/tools"]
    records = [record(i, [teams[i % 4], "type/bug" if i % 2 else "type/feature"], fixer=f"new-{i}") for i in range(200)]
    report = doctor.diagnose("a/b", records, {"closed_issues": 4000})
    assert report["recommended"]["prefix"] == "comp/"
    assert report["verdict"] == "ok"
    fixer = next(c for c in report["candidates"] if c["signal"] == "fixer")
    assert fixer["seen_share"] == 0.0


def test_diagnose_says_too_small_for_a_tiny_repo():
    records = [record(i, [f"area/{'ab'[i % 2]}"]) for i in range(60)]
    report = doctor.diagnose("tiny/repo", records, {"closed_issues": 69})
    assert report["verdict"].startswith("too small")
