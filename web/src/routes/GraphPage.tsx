import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-2d";
import { api, color, token, type Graph, type GraphLink, type GraphNode } from "../api";
import { errorState, StateOverlay, useThemeKey, type LoadState } from "../ui";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Node = NodeObject<GraphNode & { focus: boolean }>;
type Link = LinkObject<Node, Omit<GraphLink, "source" | "target">>;
type Data = { nodes: Node[]; links: Link[] };
type ForceFn = ((alpha: number) => void) & { initialize?: (nodes: Node[]) => void };

const endId = (end: Link["source"]) => (typeof end === "object" ? end.id : end) ?? "";

function palette() {
  return {
    ink: color("--foreground"),
    muted: color("--muted-foreground"),
    surface: color("--graph-surface"),
    entity: color("--graph-entity"),
    team: color("--graph-team"),
    teamInk: color("--graph-team-ink"),
    issue: color("--graph-issue"),
    history: color("--graph-history"),
    learned: color("--line-count-only"),
    shortcut: color("--line-shortcuts"),
    merged: color("--line-merging"),
    brand: color("--brand"),
    brandSoft: color("--brand-soft"),
    mono: token("--geist-mono") || "monospace",
  };
}

function toData(graph: Graph, focusName: string): Data {
  const focus = graph.nodes.find((node) => node.name.toLowerCase() === focusName.toLowerCase()) ?? graph.nodes.find((node) => node.label === "Entity");
  const seenPairs = new Set<string>();
  const links = graph.links.filter((link) => {
    if (link.type !== "SAME_AS") return true;
    const pair = [link.source, link.target].map(String).sort().join("|");
    if (seenPairs.has(pair)) return false;
    seenPairs.add(pair);
    return true;
  });
  return {
    nodes: graph.nodes.map((node) => ({ ...node, focus: node.id === focus?.id, ...(node.id === focus?.id ? { fx: 0, fy: 0 } : {}) })),
    links: links.map((link) => ({ ...link })),
  };
}

function radiusOf(node: Node) {
  if (node.label === "Team") return ((node.__box as [number, number] | undefined)?.[0] ?? 90) / 2 + 4;
  return node.label === "Issue" ? 5 : node.focus ? 22 : 14;
}

function collide(): ForceFn {
  let nodes: Node[] = [];
  const force = (alpha: number) => {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const [a, b] = [nodes[i], nodes[j]];
        const dx = b.x! - a.x! || 0.01;
        const dy = (b.y! - a.y!) * 2.2 || 0.01;
        const distance = Math.hypot(dx, dy);
        const overlap = radiusOf(a) + radiusOf(b) - distance;
        if (overlap <= 0) continue;
        const push = (overlap / distance) * Math.max(alpha, 0.3) * 0.6;
        const share = a.fx === undefined ? (b.fx === undefined ? 0.5 : 1) : 0;
        a.x! -= dx * push * share;
        a.y! -= (dy / 2.2) * push * share;
        b.x! += dx * push * (1 - share);
        b.y! += (dy / 2.2) * push * (1 - share);
      }
    }
  };
  force.initialize = (next: Node[]) => (nodes = next);
  return force;
}

function pillWidth(ctx: CanvasRenderingContext2D, text: string, fontSize: number) {
  return ctx.measureText(text).width + fontSize * 1.4;
}

function drawLabel(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, fontSize: number, ink: string, surface: string) {
  const width = ctx.measureText(text).width;
  ctx.fillStyle = surface;
  ctx.globalAlpha *= 0.85;
  ctx.fillRect(x - width / 2 - 2, y - 1, width + 4, fontSize + 2);
  ctx.globalAlpha /= 0.85;
  ctx.fillStyle = ink;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText(text, x, y);
}

function useSize(ref: React.RefObject<HTMLDivElement | null>) {
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

export function GraphPage({ entity, onEntity }: { entity: string; onEntity: (entity: string) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const graphRef = useRef<ForceGraphMethods<Node, Link> | undefined>(undefined);
  const fitted = useRef(false);
  const [draft, setDraft] = useState(entity);
  const [load, setLoad] = useState<LoadState>(null);
  const [data, setData] = useState<Data>({ nodes: [], links: [] });
  const [hover, setHover] = useState<Node | null>(null);
  const themeKey = useThemeKey();
  const { width, height } = useSize(container);
  const colors = useMemo(palette, [themeKey]);

  const neighbours = useMemo(() => {
    const map = new Map<Node["id"], Set<Node["id"]>>();
    data.links.forEach((link) => {
      const [a, b] = [endId(link.source), endId(link.target)];
      map.set(a, (map.get(a) ?? new Set()).add(b));
      map.set(b, (map.get(b) ?? new Set()).add(a));
    });
    return map;
  }, [data]);
  const lit = (id: Node["id"]) => !hover || id === hover.id || !!neighbours.get(hover.id)?.has(id);
  const linkLit = (link: Link) => !hover || endId(link.source) === hover.id || endId(link.target) === hover.id;

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    graph.d3Force("charge")?.strength(-220);
    graph.d3Force("link")?.distance((link: Link) => (link.type === "ROUTES_TO" ? 90 + 160 / (1 + (Number(link.strength) || 0)) : link.type === "SAME_AS" ? 70 : 55));
    graph.d3Force("collide", collide());
    fitted.current = false;
    graph.d3ReheatSimulation();
  }, [data]);

  useEffect(() => {
    setDraft(entity);
    const name = entity.trim();
    if (!name) {
      setData({ nodes: [], links: [] });
      setLoad({ kind: "empty", title: "Pick an entity", detail: <>Type a component, file path or word, such as <code>kubelet</code>.</> });
      return;
    }
    let live = true;
    setLoad({ kind: "loading", title: `Loading the graph around ${name}` });
    api.graph(name).then(
      (graph) => {
        if (!live) return;
        if (!graph.nodes?.length) {
          setData({ nodes: [], links: [] });
          setLoad({ kind: "empty", title: `${name} is not in the graph`, detail: <>Try <code>kubelet</code>, <code>csi</code> or <code>kube-apiserver</code>. Entities need at least 3 learning issues.</> });
          return;
        }
        setLoad(null);
        setHover(null);
        setData(toData(graph, name));
      },
      (error) => {
        if (!live) return;
        setData({ nodes: [], links: [] });
        setLoad(errorState(error));
      },
    );
    return () => {
      live = false;
    };
  }, [entity]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    onEntity(draft.trim());
  };

  return (
    <Card aria-labelledby="graph-title">
      <CardHeader className="md:grid-cols-[1fr_auto]">
        <CardTitle>
          <h2 id="graph-title">Ownership graph</h2>
        </CardTitle>
        <CardDescription>Links around one entity. Thicker links are stronger. Drag to rearrange, scroll to zoom, hover to trace, click an entity to move there.</CardDescription>
        <form className="mt-2 flex w-full gap-2 md:col-start-2 md:row-span-2 md:row-start-1 md:mt-0 md:w-72 md:self-start" onSubmit={submit} role="search">
          <label className="sr-only" htmlFor="graph-entity">
            Entity
          </label>
          <Input id="graph-entity" type="text" className="font-mono" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="kubelet" autoComplete="off" spellCheck={false} />
          <Button type="submit" variant="outline">
            Show
          </Button>
        </form>
      </CardHeader>
      <CardContent className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_200px]">
        <div className="relative h-[400px] overflow-hidden rounded-lg border bg-background sm:h-[560px]">
          <div ref={container} className="size-full" aria-label="Graph around the chosen entity">
            {width > 0 && (
              <ForceGraph2D<Node, Link>
                ref={graphRef}
                width={width}
                height={height}
                graphData={data}
                backgroundColor="rgba(0,0,0,0)"
                minZoom={0.3}
                maxZoom={6}
                warmupTicks={120}
                cooldownTicks={120}
                d3VelocityDecay={0.32}
                onEngineStop={() => {
                  if (fitted.current) return;
                  fitted.current = true;
                  graphRef.current?.zoomToFit(500, 40);
                }}
                onNodeHover={(node) => setHover(node)}
                onNodeClick={(node) => {
                  if (node.label === "Entity" && !node.focus) onEntity(node.name);
                }}
                showPointerCursor={(object) => !!object && "label" in object && object.label === "Entity" && !object.focus}
                nodeLabel={(node) => (node.label === "Issue" ? `Issue ${node.name}` : node.label === "Team" ? `Team ${node.name}` : node.name)}
                linkColor={(link) => {
                  const base = link.type === "ROUTES_TO" ? (link.shortcut ? colors.shortcut : colors.learned) : link.type === "SAME_AS" ? colors.merged : colors.history;
                  return linkLit(link) ? base : `color-mix(in oklab, ${base} 18%, transparent)`;
                }}
                linkWidth={(link) => (link.type === "ROUTES_TO" ? 1 + Math.min(Number(link.strength) || 0, 4) * 1.1 : link.type === "SAME_AS" ? 2.5 : 0.8)}
                linkLineDash={(link) => (link.type === "SAME_AS" ? [6, 4] : null)}
                linkDirectionalArrowLength={(link) => (link.type === "SAME_AS" ? 0 : link.type === "ROUTES_TO" ? 5 : 3)}
                linkDirectionalArrowRelPos={1}
                linkDirectionalParticles={(link) => (link.type === "ROUTES_TO" && linkLit(link) ? 2 : 0)}
                linkDirectionalParticleWidth={(link) => 1.5 + Math.min(Number(link.strength) || 0, 4) * 0.5}
                linkDirectionalParticleColor={(link) => (link.shortcut ? colors.shortcut : colors.brand)}
                linkDirectionalParticleSpeed={(link) => 0.003 + Math.min(Number(link.strength) || 0, 4) * 0.002}
                linkCanvasObjectMode={() => "after"}
                linkCanvasObject={(link, ctx, scale) => {
                  if (link.type !== "ROUTES_TO" || !linkLit(link) || scale < 0.7) return;
                  const [a, b] = [link.source, link.target];
                  if (typeof a !== "object" || typeof b !== "object") return;
                  const fontSize = 10 / scale;
                  ctx.font = `${fontSize}px ${colors.mono}`;
                  drawLabel(ctx, (Number(link.strength) || 0).toFixed(1), a.x! + (b.x! - a.x!) * 0.5, a.y! + (b.y! - a.y!) * 0.5 - fontSize / 2, fontSize, colors.muted, colors.surface);
                }}
                nodeCanvasObject={(node, ctx, scale) => {
                  const x = node.x!;
                  const y = node.y!;
                  ctx.globalAlpha = lit(node.id) ? 1 : 0.18;
                  if (node.label === "Team") {
                    const fontSize = Math.max(11 / scale, 4);
                    ctx.font = `600 ${fontSize}px ${colors.mono}`;
                    const w = pillWidth(ctx, node.name, fontSize);
                    const h = fontSize * 2;
                    ctx.fillStyle = colors.team;
                    ctx.beginPath();
                    ctx.roundRect(x - w / 2, y - h / 2, w, h, h / 2);
                    ctx.fill();
                    ctx.fillStyle = colors.teamInk;
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    ctx.fillText(node.name, x, y);
                    node.__box = [w, h];
                  } else if (node.label === "Issue") {
                    ctx.fillStyle = colors.issue;
                    ctx.beginPath();
                    ctx.arc(x, y, 3, 0, 2 * Math.PI);
                    ctx.fill();
                    if (scale > 1.6 || hover?.id === node.id) {
                      const fontSize = 9 / scale;
                      ctx.font = `${fontSize}px ${colors.mono}`;
                      drawLabel(ctx, node.name, x, y + 4, fontSize, colors.muted, colors.surface);
                    }
                  } else {
                    const radius = node.focus ? 10 : 6;
                    if (node.focus) {
                      ctx.fillStyle = colors.brandSoft;
                      ctx.beginPath();
                      ctx.arc(x, y, radius + 6, 0, 2 * Math.PI);
                      ctx.fill();
                    }
                    ctx.fillStyle = node.focus ? colors.brand : colors.entity;
                    ctx.strokeStyle = node.focus ? colors.brand : colors.muted;
                    ctx.lineWidth = 2 / scale;
                    ctx.beginPath();
                    ctx.arc(x, y, radius, 0, 2 * Math.PI);
                    ctx.fill();
                    ctx.stroke();
                    const fontSize = (node.focus ? 13 : 11) / scale;
                    ctx.font = `${node.focus ? 700 : 400} ${fontSize}px ${colors.mono}`;
                    drawLabel(ctx, node.name, x, y + radius + (node.focus ? 8 : 4), fontSize, colors.ink, colors.surface);
                  }
                  ctx.globalAlpha = 1;
                }}
                nodePointerAreaPaint={(node, paint, ctx) => {
                  ctx.fillStyle = paint;
                  if (node.label === "Team" && node.__box) {
                    const [w, h] = node.__box as [number, number];
                    ctx.fillRect(node.x! - w / 2, node.y! - h / 2, w, h);
                    return;
                  }
                  ctx.beginPath();
                  ctx.arc(node.x!, node.y!, node.label === "Issue" ? 5 : node.focus ? 16 : 9, 0, 2 * Math.PI);
                  ctx.fill();
                }}
              />
            )}
          </div>
          <StateOverlay state={load} />
        </div>
        <ul className="grid grid-cols-1 content-start gap-2.5 text-xs sm:grid-cols-2 lg:grid-cols-1" aria-label="Graph legend">
          {LEGEND_LINKS.map((item) => (
            <li key={item.label} className="flex items-center gap-3">
              <span className="w-7 shrink-0" style={{ borderTop: item.line }} aria-hidden="true" />
              <span>
                {item.label} <span className="text-muted-foreground">{item.note}</span>
              </span>
            </li>
          ))}
          <li className="flex items-center gap-3">
            <span className="flex w-7 shrink-0 justify-center" aria-hidden="true">
              <span className="size-3.5 rounded-full border-2 border-muted-foreground bg-card" />
            </span>
            Entity
          </li>
          <li className="flex items-center gap-3">
            <span className="flex w-7 shrink-0 justify-center" aria-hidden="true">
              <span className="h-3.5 w-6 rounded-sm bg-foreground" />
            </span>
            Team
          </li>
          <li className="flex items-center gap-3">
            <span className="flex w-7 shrink-0 justify-center" aria-hidden="true">
              <span className="size-2 rounded-full bg-(--graph-issue)" />
            </span>
            Past issue
          </li>
        </ul>
      </CardContent>
    </Card>
  );
}

const LEGEND_LINKS = [
  { label: "Learned link", note: "entity to team", line: "3px solid var(--line-count-only)" },
  { label: "Shortcut", note: "compressed from history", line: "3px solid var(--line-shortcuts)" },
  { label: "Merged name", note: "SAME_AS", line: "3px dashed var(--line-merging)" },
  { label: "History", note: "past issue to fixing team", line: "1.5px solid var(--graph-history)" },
];
