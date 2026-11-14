from xml.etree import ElementTree

from eval.charts import curve_svg, recovery_svg


def points(*values: float) -> list[dict]:
    return [{"issues": issues, "top1": value, "moved_top1": value} for issues, value in zip((0, 500, 1000), values)]


NO_GRAPH = {"lines": {"naive_bayes": {"points": points(0.4, 0.6, 0.66), "recovery": points(0.2, 0.2, 0.7)}}}


def test_curve_svg_draws_one_line_per_series_plus_the_no_graph_baseline():
    curve = {"meta": {"test_issues": 300}, "lines": {"baton": points(0.0, 0.6, 0.67), "count_only": points(0.0, 0.55, 0.58), "frozen": points(0.5, 0.5, 0.5)}}
    drawn = curve_svg(curve, NO_GRAPH)
    assert len(ElementTree.fromstring(drawn).findall("{http://www.w3.org/2000/svg}polyline")) == 4
    assert "67.0% top-1" in drawn and "66.0% top-1" in drawn


def test_recovery_svg_marks_the_reorg():
    meta = {"reorg_at": 500, "from_team": "sig/a", "to_team": "sig/b", "moved_test_issues": 10}
    recovery = {"meta": meta, "lines": {"baton": points(0.2, 0.3, 0.8), "count_only": points(0.2, 0.2, 0.6)}}
    svg = recovery_svg(recovery, NO_GRAPH)
    ElementTree.fromstring(svg)
    assert ">reorg<" in svg and "80% at the end" in svg and "70% at the end" in svg
