"""Draw docs/assets/curve.png and recovery.png as plain SVG and turn them into PNG with headless Chrome (no plotting library)."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from html import escape
from pathlib import Path

from baton.config import CURVE_FILE
from baton.repos import KUBERNETES_PROFILE
from eval.recovery import RECOVERY_FILE

ASSETS = Path(__file__).resolve().parent.parent / "docs" / "assets"
WIDTH, HEIGHT = 960, 540
LEFT, RIGHT, TOP, BOTTOM = 64, 150, 92, 56
SURFACE, INK, INK_2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
BLUE, ORANGE, GRAY, GREEN = "#2a78d6", "#eb6834", "#8a8984", "#1f8a5b"
CHROME_CANDIDATES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chromium-browser")
FONT = "-apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif"


def line_chart(title: str, subtitle: str, series: list[dict], x_max: int, y_max: float = 1.0, marker: tuple[int, str] | None = None) -> str:
    """An SVG line chart: series are {name, points [(x, y)], color, dashed, label}; y is a share drawn as a percentage."""
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM

    def sx(x: float) -> float:
        return LEFT + plot_w * x / x_max

    def sy(y: float) -> float:
        return TOP + plot_h * (1 - y / y_max)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" font-family="{FONT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{SURFACE}"/>',
        f'<text x="{LEFT}" y="36" font-size="20" font-weight="600" fill="{INK}">{escape(title)}</text>',
        f'<text x="{LEFT}" y="60" font-size="14" fill="{INK_2}">{escape(subtitle)}</text>',
    ]
    for step in range(0, int(round(y_max * 10)) + 1, 2):
        y = step / 10
        parts.append(f'<line x1="{LEFT}" x2="{LEFT + plot_w}" y1="{sy(y):.1f}" y2="{sy(y):.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{LEFT - 10}" y="{sy(y) + 4:.1f}" font-size="12" fill="{MUTED}" text-anchor="end">{round(y * 100)}%</text>')
    for x in range(0, x_max + 1, max(x_max // 6 // 100 * 100, 100)):
        parts.append(f'<text x="{sx(x):.1f}" y="{TOP + plot_h + 22}" font-size="12" fill="{MUTED}" text-anchor="middle">{x:,}</text>')
    parts.append(f'<text x="{LEFT + plot_w / 2:.1f}" y="{HEIGHT - 12}" font-size="12" fill="{INK_2}" text-anchor="middle">learning issues streamed</text>')
    if marker:
        x, label = marker
        parts.append(f'<line x1="{sx(x):.1f}" x2="{sx(x):.1f}" y1="{TOP}" y2="{TOP + plot_h}" stroke="{INK_2}" stroke-width="1" stroke-dasharray="4 4"/>')
        parts.append(f'<text x="{sx(x) + 6:.1f}" y="{TOP + 14}" font-size="12" fill="{INK_2}">{escape(label)}</text>')
    label_ys: list[float] = []
    for line in sorted(series, key=lambda line: -line["points"][-1][1]):
        coords = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in line["points"])
        dash = ' stroke-dasharray="6 5"' if line.get("dashed") else ""
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{line["color"]}" stroke-width="2.5" stroke-linejoin="round"{dash}/>')
        end_x, end_y = line["points"][-1]
        parts.append(f'<circle cx="{sx(end_x):.1f}" cy="{sy(end_y):.1f}" r="4" fill="{line["color"]}" stroke="{SURFACE}" stroke-width="2"/>')
        label_y = sy(end_y) + 4
        while any(abs(label_y - other) < 30 for other in label_ys):
            label_y += 4
        label_ys.append(label_y)
        parts.append(f'<text x="{sx(end_x) + 10:.1f}" y="{label_y:.1f}" font-size="13" font-weight="600" fill="{line["color"]}">{escape(line["name"])}</text>')
        parts.append(f'<text x="{sx(end_x) + 10:.1f}" y="{label_y + 15:.1f}" font-size="12" fill="{INK_2}">{escape(line["label"])}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def no_graph_series(no_graph: dict, key: str, value: str, label: str) -> dict:
    """The naive Bayes baseline as a dashed series, from issue 0."""
    points = [(0, 0.0)] + [(point["issues"], point[value]) for point in no_graph["lines"]["naive_bayes"][key]]
    return {"name": "naive Bayes, no graph", "points": points, "color": GREEN, "dashed": True, "label": label.format(points[-1][1] * 100)}


def curve_svg(curve: dict, no_graph: dict) -> str:
    """Test top-1 against issues learned for frozen, count_only, baton and the no-graph naive Bayes baseline."""
    styles = {"baton": (BLUE, False), "count_only": (ORANGE, False), "frozen": (GRAY, True)}
    series = [
        {
            "name": name,
            "points": [(point["issues"], point["top1"]) for point in curve["lines"][name]],
            "color": color,
            "dashed": dashed,
            "label": f"{curve['lines'][name][-1]['top1'] * 100:.1f}% top-1",
        }
        for name, (color, dashed) in styles.items()
    ] + [no_graph_series(no_graph, "points", "top1", "{:.1f}% top-1")]
    x_max = max(point["issues"] for point in curve["lines"]["baton"])
    test = curve["meta"]["test_issues"]
    return line_chart("Baton keeps getting better as issues are fixed", f"Top-1 accuracy on {test} newer issues it never learns from (HydraDB, live)", series, x_max, 0.8)


def recovery_svg(recovery: dict, no_graph: dict) -> str:
    """Top-1 on the moved team's test issues, before and after the simulated reorg."""
    meta = recovery["meta"]
    styles = {"baton": BLUE, "count_only": ORANGE}
    series = [
        {
            "name": name,
            "points": [(0, 0.0)] + [(point["issues"], point["moved_top1"]) for point in recovery["lines"][name]],
            "color": color,
            "label": f"{recovery['lines'][name][-1]['moved_top1'] * 100:.0f}% at the end",
        }
        for name, color in styles.items()
    ] + [no_graph_series(no_graph, "recovery", "moved_top1", "{:.0f}% at the end")]
    x_max = recovery["lines"]["baton"][-1]["issues"]
    subtitle = f"Simulated: from issue {meta['reorg_at']:,}, {meta['from_team']} work goes to {meta['to_team']}. Top-1 on the {meta['moved_test_issues']} moved test issues (offline mirror)"
    return line_chart("After a reorg, baton relearns who owns the work", subtitle, series, x_max, 1.0, (meta["reorg_at"], "reorg"))


def chrome() -> str | None:
    """The first headless-capable Chrome found on this machine."""
    return next((found for name in CHROME_CANDIDATES if (found := shutil.which(name) or (name if os.path.exists(name) else None))), None)


def screenshot(browser: str, url: str, out: Path, width: int, height: int, wait_ms: int = 0) -> None:
    """Save a PNG of a page at 2x with headless Chrome."""
    flags = ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2", f"--window-size={width},{height}"]
    if wait_ms:
        flags.append(f"--virtual-time-budget={wait_ms}")
    subprocess.run([browser, *flags, f"--screenshot={out}", url], check=True, capture_output=True, timeout=120)


def render_svg(browser: str, svg: str, out: Path) -> None:
    """Rasterise one SVG chart to PNG."""
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "chart.html"
        page.write_text(f'<!doctype html><html><body style="margin:0;background:{SURFACE}">{svg}</body></html>')
        screenshot(browser, page.as_uri(), out, WIDTH, HEIGHT)


def main() -> None:
    """Write the chart PNGs and, with --dashboard URL, a screenshot of the running dashboard."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dashboard", metavar="URL", help="also capture docs/assets/dashboard.png from a running API")
    args = parser.parse_args()
    browser = chrome()
    if browser is None:
        raise SystemExit("needs Google Chrome or Chromium for the PNG step")
    ASSETS.mkdir(parents=True, exist_ok=True)
    no_graph = json.loads(KUBERNETES_PROFILE.no_graph_file.read_text())
    render_svg(browser, curve_svg(json.loads(CURVE_FILE.read_text()), no_graph), ASSETS / "curve.png")
    if RECOVERY_FILE.exists():
        render_svg(browser, recovery_svg(json.loads(RECOVERY_FILE.read_text()), no_graph), ASSETS / "recovery.png")
    if args.dashboard:
        screenshot(browser, args.dashboard, ASSETS / "dashboard.png", 1440, 980, wait_ms=15000)
    print(sorted(path.name for path in ASSETS.glob("*.png")))


if __name__ == "__main__":
    main()
