import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from "cytoscape";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, color, token, type Graph, type GraphNode } from "../api";
import { errorState, StateOverlay, useThemeKey, type LoadState } from "../ui";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

function graphStyle(): StylesheetJson {
  const ink = color("--foreground");
  const ink2 = color("--muted-foreground");
  const surface = color("--graph-surface");
  const mono = token("--geist-mono");
  return [
    {
      selector: "node",
      style: {
        label: "data(name)",
        "font-family": mono,
        "font-size": 11,
        color: ink,
        "text-valign": "bottom",
        "text-margin-y": 5,
        "text-background-color": surface,
        "text-background-opacity": 0.85,
        "text-background-padding": "2",
        "text-background-shape": "roundrectangle",
      },
    },
    { selector: "node.entity", style: { width: 16, height: 16, "background-color": color("--graph-entity"), "border-width": 2, "border-color": ink2 } },
    { selector: "node.focus", style: { width: 28, height: 28, "background-color": color("--brand"), "border-width": 5, "border-color": color("--brand-soft"), "font-size": 13, "font-weight": 700 } },
    {
      selector: "node.team",
      style: {
        shape: "round-rectangle",
        width: "label",
        height: 24,
        padding: "8",
        "background-color": color("--graph-team"),
        color: color("--graph-team-ink"),
        "text-valign": "center",
        "text-margin-y": 0,
        "text-background-opacity": 0,
        "font-weight": 600,
      },
    },
    { selector: "node.issue", style: { width: 8, height: 8, "background-color": color("--graph-issue"), "font-size": 9, color: ink2, "text-margin-y": 3 } },
    { selector: "edge", style: { "curve-style": "bezier", "target-arrow-shape": "triangle", "arrow-scale": 0.8, width: 1.5, "line-color": color("--graph-history"), "target-arrow-color": color("--graph-history") } },
    {
      selector: "edge.learned",
      style: {
        width: "data(width)",
        "line-color": color("--line-count-only"),
        "target-arrow-color": color("--line-count-only"),
        "source-label": "data(strengthLabel)",
        "source-text-offset": 46,
        "font-family": mono,
        "font-size": 10,
        color: ink2,
        "text-background-color": surface,
        "text-background-opacity": 1,
        "text-background-padding": "2",
        "text-background-shape": "roundrectangle",
      },
    },
    { selector: "edge.shortcut", style: { "line-color": color("--line-shortcuts"), "target-arrow-color": color("--line-shortcuts") } },
    { selector: "edge.merged", style: { width: 3, "line-style": "dashed", "line-dash-pattern": [6, 4], "line-color": color("--line-merging"), "target-arrow-shape": "none" } },
    { selector: "node.entity:active, node.entity:selected", style: { "overlay-opacity": 0 } },
  ];
}

function graphElements(graph: Graph, focusName: string): ElementDefinition[] {
  const focus = graph.nodes.find((node) => node.name.toLowerCase() === focusName.toLowerCase());
  const mergedWithFocus = new Set<GraphNode["id"]>();
  const seenPairs = new Set<string>();
  const edges: ElementDefinition[] = [];
  graph.links.forEach((link, i) => {
    if (link.type === "SAME_AS") {
      const pair = [link.source, link.target].map(String).sort().join("|");
      if (seenPairs.has(pair)) return;
      seenPairs.add(pair);
      if (focus && (link.source === focus.id || link.target === focus.id)) mergedWithFocus.add(link.source === focus.id ? link.target : link.source);
    }
    const strength = Number(link.strength) || 0;
    edges.push({
      group: "edges",
      data: { id: `e${i}`, source: String(link.source), target: String(link.target), width: 1 + Math.min(strength, 4) * 1.1, strengthLabel: strength.toFixed(1) },
      classes: link.type === "ROUTES_TO" ? (link.shortcut ? "learned shortcut" : "learned") : link.type === "SAME_AS" ? "merged" : "history",
    });
  });
  const strengthOf = (link: Graph["links"][number]) => Number(link.strength) || 0;
  const teamRank = new Map<GraphNode["id"], number>();
  graph.links
    .filter((link) => link.type === "ROUTES_TO" && focus && link.source === focus.id)
    .sort((a, b) => strengthOf(b) - strengthOf(a))
    .forEach((link) => teamRank.set(link.target, teamRank.size));
  graph.nodes.filter((node) => node.label === "Team" && !teamRank.has(node.id)).forEach((node) => teamRank.set(node.id, teamRank.size));
  const anchor = (node: GraphNode) => {
    if (node.label === "Team") return teamRank.get(node.id) ?? 0;
    const strongest = graph.links.filter((link) => link.source === node.id && teamRank.has(link.target)).sort((a, b) => strengthOf(b) - strengthOf(a))[0];
    if (strongest) return teamRank.get(strongest.target) ?? 0;
    const owner = graph.links.find((link) => link.source === node.id && link.type === "OWNED_BY");
    return owner ? (teamRank.get(owner.target) ?? 0) : 0;
  };
  const priority = (node: GraphNode) => (focus && node.id === focus.id ? 0 : mergedWithFocus.has(node.id) ? 1 : 2);
  const columnOf = (node: GraphNode) => (node.label === "Team" ? 2 : node.label === "Issue" ? 1 : 0);
  const columns: GraphNode[][] = [[], [], []];
  graph.nodes.forEach((node) => columns[columnOf(node)].push(node));
  const positions = new Map<GraphNode["id"], { x: number; y: number }>();
  const columnGap = window.innerWidth < 640 ? 200 : 360;
  columns.forEach((list, c) => {
    list.sort((a, b) => anchor(a) - anchor(b) || priority(a) - priority(b) || a.name.localeCompare(b.name));
    list.forEach((node, i) => positions.set(node.id, { x: c * columnGap, y: (i - (list.length - 1) / 2) * 66 }));
  });
  const nodes: ElementDefinition[] = graph.nodes.map((node) => ({
    group: "nodes",
    data: { id: String(node.id), name: node.name },
    position: positions.get(node.id),
    classes: [node.label.toLowerCase(), focus && node.id === focus.id ? "focus" : ""].join(" ").trim(),
  }));
  return [...nodes, ...edges];
}

export function GraphPage({ entity, onEntity }: { entity: string; onEntity: (entity: string) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const onEntityRef = useRef(onEntity);
  const [draft, setDraft] = useState(entity);
  const [load, setLoad] = useState<LoadState>(null);
  const themeKey = useThemeKey();
  onEntityRef.current = onEntity;

  useEffect(() => {
    const instance = cytoscape({ container: container.current, style: graphStyle(), minZoom: 0.4, maxZoom: 2.5, wheelSensitivity: 0.2, boxSelectionEnabled: false });
    instance.on("tap", "node.entity", (event) => {
      if (!event.target.hasClass("focus")) onEntityRef.current(event.target.data("name"));
    });
    instance.on("mouseover", "node.entity", () => (container.current!.style.cursor = "pointer"));
    instance.on("mouseout", "node.entity", () => (container.current!.style.cursor = ""));
    cy.current = instance;
    return () => instance.destroy();
  }, []);

  useEffect(() => {
    cy.current?.style(graphStyle());
  }, [themeKey]);

  useEffect(() => {
    setDraft(entity);
    const name = entity.trim();
    if (!name) {
      cy.current?.elements().remove();
      setLoad({ kind: "empty", title: "Pick an entity", detail: <>Type a component, file path or word, such as <code>kubelet</code>.</> });
      return;
    }
    let live = true;
    setLoad({ kind: "loading", title: `Loading the graph around ${name}` });
    api.graph(name).then(
      (graph) => {
        if (!live || !cy.current) return;
        cy.current.elements().remove();
        if (!graph.nodes?.length) {
          setLoad({ kind: "empty", title: `${name} is not in the graph`, detail: <>Try <code>kubelet</code>, <code>csi</code> or <code>kube-apiserver</code>. Entities need at least 3 learning issues.</> });
          return;
        }
        setLoad(null);
        cy.current.add(graphElements(graph, name));
        cy.current.fit(undefined, 48);
        if (cy.current.zoom() > 1.15) {
          cy.current.zoom(1.15);
          cy.current.center();
        }
      },
      (error) => {
        if (!live) return;
        cy.current?.elements().remove();
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
        <CardDescription>Links around one entity. Thicker links are stronger. Click any entity to move there.</CardDescription>
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
          <div ref={container} className="size-full" aria-label="Graph around the chosen entity" />
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
