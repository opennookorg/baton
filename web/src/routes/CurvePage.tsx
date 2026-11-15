import Chart, { type ChartDataset, type Plugin } from "chart.js/auto";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api, color, fmt, pct, REDUCED_MOTION, token, type Curve, type Metric } from "../api";
import { errorState, StateOverlay, useThemeKey, type LoadState } from "../ui";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

type Line = { key: string; label: string; color: string; width: number; dash: number[]; technique?: boolean };

const LINES: Line[] = [
  { key: "baton", label: "Baton", color: "--line-baton", width: 3, dash: [] },
  { key: "count_only", label: "Count-only", color: "--line-count-only", width: 2, dash: [] },
  { key: "frozen", label: "Frozen", color: "--line-frozen", width: 2, dash: [6, 4] },
  { key: "reweight", label: "Reweighting", color: "--line-reweight", width: 1.75, dash: [2, 3], technique: true },
  { key: "shortcuts", label: "Shortcuts", color: "--line-shortcuts", width: 1.75, dash: [8, 3], technique: true },
  { key: "merging", label: "Name merging", color: "--line-merging", width: 1.75, dash: [8, 3, 2, 3], technique: true },
  { key: "splitting", label: "Splitting", color: "--line-splitting", width: 1.75, dash: [3, 5], technique: true },
  { key: "gap_filling", label: "Gap filling", color: "--line-gap-filling", width: 1.75, dash: [12, 4], technique: true },
];

type LineDataset = ChartDataset<"line", { x: number; y: number }[]> & { lineKey: string };

const endLabels: Plugin<"line"> = {
  id: "endLabels",
  afterDatasetsDraw(chart) {
    const { ctx, chartArea } = chart;
    const labels = chart.data.datasets
      .map((dataset, i) => {
        const meta = chart.getDatasetMeta(i);
        const last = meta.data[meta.data.length - 1];
        const points = dataset.data as { y: number }[];
        if (!last || meta.hidden) return null;
        return { y: last.y, text: `${dataset.label} ${pct(points[points.length - 1].y)}`, color: dataset.borderColor as string, strong: (dataset as LineDataset).lineKey === "baton" };
      })
      .filter((label) => label !== null)
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 14);
    ctx.save();
    ctx.textBaseline = "middle";
    labels.forEach((label) => {
      ctx.fillStyle = label.color;
      ctx.beginPath();
      ctx.arc(chartArea.right + 10, label.y, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = `${label.strong ? 600 : 500} 11.5px ${token("--geist")}`;
      ctx.fillStyle = label.strong ? color("--foreground") : color("--muted-foreground");
      ctx.fillText(label.text, chartArea.right + 18, label.y);
    });
    ctx.restore();
  },
};

const crosshair: Plugin<"line"> = {
  id: "crosshair",
  afterDraw(chart) {
    const active = chart.tooltip?.getActiveElements() ?? [];
    if (!active.length) return;
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.strokeStyle = color("--input");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(active[0].element.x, chartArea.top);
    ctx.lineTo(active[0].element.x, chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

function yRange(sets: LineDataset[]) {
  const values = sets.flatMap((set) => set.data.map((point) => point.y));
  if (!values.length) return { min: 0, max: 1 };
  return {
    min: Math.max(0, Math.floor((Math.min(...values) - 0.05) * 10) / 10),
    max: Math.min(1, Math.ceil((Math.max(...values) + 0.05) * 10) / 10),
  };
}

function CurveChart({ curve, lines, metric }: { curve: Curve; lines: Line[]; metric: Metric }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const chart = useRef<Chart<"line", { x: number; y: number }[]> | null>(null);
  const themeKey = useThemeKey();

  useEffect(() => {
    const sets: LineDataset[] = lines.map((line) => ({
      label: line.label,
      lineKey: line.key,
      data: curve.lines[line.key].map((point) => ({ x: point.issues, y: point[metric] })),
      borderColor: color(line.color),
      backgroundColor: color(line.color),
      borderWidth: line.width,
      borderDash: line.dash,
      pointRadius: 0,
      pointHoverRadius: 4,
      pointHoverBorderWidth: 2,
      pointHoverBorderColor: color("--card"),
      tension: 0.25,
      order: line.key === "baton" ? 0 : 1,
    }));
    const grid = color("--border");
    const muted = color("--muted-foreground");
    const mono = { family: token("--geist-mono"), size: 11 };
    Chart.defaults.font.family = token("--geist");
    chart.current?.destroy();
    chart.current = new Chart<"line", { x: number; y: number }[]>(canvas.current!, {
      type: "line",
      data: { datasets: sets },
      plugins: [endLabels, crosshair],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: REDUCED_MOTION ? false : { duration: 500, easing: "easeOutCubic" },
        layout: { padding: { top: 12, right: 128 } },
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            type: "linear",
            min: 0,
            max: 1700,
            ticks: { stepSize: 100, autoSkip: false, maxRotation: 0, color: muted, font: mono, callback: (value) => ((Number(value) % 500 === 0 && !(value === 1500 && window.innerWidth < 640)) || value === 1700 ? fmt(Number(value)) : "") },
            grid: { color: grid, drawTicks: false },
            border: { display: false },
            title: { display: true, text: "Learning issues seen", color: muted, font: { size: 11.5 } },
          },
          y: {
            ...yRange(sets),
            ticks: { color: muted, font: mono, stepSize: 0.1, callback: (value) => pct(Number(value)) },
            grid: { color: grid, drawTicks: false },
            border: { display: false },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: color("--popover"),
            borderColor: color("--border"),
            borderWidth: 1,
            titleColor: color("--foreground"),
            bodyColor: color("--foreground"),
            padding: 10,
            cornerRadius: 6,
            boxPadding: 4,
            usePointStyle: true,
            itemSort: (a, b) => b.parsed.y! - a.parsed.y!,
            callbacks: {
              title: (items) => `After ${fmt(items[0].parsed.x!)} issues`,
              label: (item) => ` ${item.dataset.label}: ${(item.parsed.y! * 100).toFixed(1)}%`,
            },
          },
        },
      },
    });
  }, [curve, lines, metric, themeKey]);

  useEffect(() => () => chart.current?.destroy(), []);

  return <canvas ref={canvas} aria-label="Accuracy chart" role="img" />;
}

export function CurvePage({ metric, onMetric }: { metric: Metric; onMetric: (metric: Metric) => void }) {
  const [curve, setCurve] = useState<Curve | null>(null);
  const [load, setLoad] = useState<LoadState>({ kind: "loading", title: "Loading accuracy points" });
  const [techniques, setTechniques] = useState<Set<string>>(new Set());
  useThemeKey();

  useEffect(() => {
    api.curve().then(
      (data) => {
        setCurve(data);
        const hasLines = Object.values(data.lines ?? {}).some((points) => points.length);
        setLoad(hasLines ? null : { kind: "empty", title: "No accuracy points yet", detail: <>Run <code>uv run python -m eval.run_curve</code> to score the test set, then reload.</> });
      },
      (error) => setLoad(errorState(error)),
    );
  }, []);

  const visible = useMemo(
    () => LINES.filter((line) => curve?.lines[line.key]?.length && (!line.technique || techniques.has(line.key))),
    [curve, techniques],
  );

  const toggle = (key: string) =>
    setTechniques((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <Card aria-labelledby="chart-title">
      <CardHeader>
        <CardTitle>
          <h2 id="chart-title">Accuracy on 300 unseen issues</h2>
        </CardTitle>
        <CardDescription>Scored after every 100 learning issues. The graph never learns from these.</CardDescription>
        <CardAction>
          <ToggleGroup type="single" variant="outline" size="sm" value={metric} onValueChange={(value) => value && onMetric(value as Metric)} aria-label="Accuracy measure">
            <ToggleGroupItem value="top1">Top 1</ToggleGroupItem>
            <ToggleGroupItem value="top3">Top 3</ToggleGroupItem>
          </ToggleGroup>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex min-h-5 flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground" aria-label="Lines on the chart">
          {curve &&
            visible.map((line) => {
              const points = curve.lines[line.key];
              return (
                <span key={line.key} className="inline-flex items-center gap-2">
                  <span className="w-4 border-t-2" style={{ borderColor: `var(${line.color})`, borderTopStyle: line.dash.length ? "dashed" : "solid" }} />
                  {line.label}
                  <span className="font-mono font-medium text-foreground tabular-nums">{pct(points[points.length - 1][metric])}</span>
                </span>
              );
            })}
        </div>
        <div className="relative h-[300px] sm:h-[420px]">
          {curve && !load && <CurveChart curve={curve} lines={visible} metric={metric} />}
          <StateOverlay state={load} />
        </div>
        <Separator />
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
          <span className="shrink-0 text-xs text-muted-foreground">Add one technique to count-only</span>
          <div className="flex flex-wrap gap-2">
            {LINES.filter((line) => line.technique).map((line) => (
              <Toggle
                key={line.key}
                variant="outline"
                size="sm"
                className="gap-2"
                style={{ "--dot": `var(${line.color})` } as CSSProperties}
                pressed={techniques.has(line.key)}
                disabled={!curve?.lines[line.key]?.length}
                onPressedChange={() => toggle(line.key)}
              >
                <span className="size-2 rounded-full border-2 border-(--dot) group-data-[state=on]/toggle:bg-(--dot)" aria-hidden="true" />
                {line.label}
              </Toggle>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
