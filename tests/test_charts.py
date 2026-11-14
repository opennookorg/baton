from xml.etree import ElementTree

from eval.charts import curve_svg, recovery_svg


def points(*values: float) -> list[dict]:
    return [{"issues": issues, "top1": value, "moved_top1": value} for issues, value in zip((0, 500, 1000), values)]


def test_curve_svg_draws_one_line_per_series():
    curve = {"meta": {"test_issues": 300}, "lines": {"baton": points(0.0, 0.6, 0.67), "count_only": points(0.0, 0.55, 0.58), "frozen": points(0.5, 0.5, 0.5)}}
    svg = ElementTree.fromstring(curve_svg(curve))
    assert len(svg.findall("{http://www.w3.org/2000/svg}polyline")) == 3
    assert "67.0% top-1" in curve_svg(curve)


def test_recovery_svg_marks_the_reorg():
    meta = {"reorg_at": 500, "from_team": "sig/a", "to_team": "sig/b", "moved_test_issues": 10}
    recovery = {"meta": meta, "lines": {"baton": points(0.2, 0.3, 0.8), "count_only": points(0.2, 0.2, 0.6)}}
    svg = recovery_svg(recovery)
    ElementTree.fromstring(svg)
    assert ">reorg<" in svg and "80% at the end" in svg
