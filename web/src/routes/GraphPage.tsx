import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from "cytoscape";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, token, type Graph, type GraphNode } from "../api";
import { errorState, StateOverlay, useThemeKey, type LoadState } from "../ui";

function graphStyle(): StylesheetJson {
  const ink = token("--ink");
  const ink2 = token("--ink-2");
  const surface = token("--surface-2");
  const mono = token("--mono");
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
    { selector: "node.entity", style: { width: 16, height: 16, "background-color": token("--entity-fill"), "border-width": 2, "border-color": ink2 } },
    { selector: "node.focus", style: { width: 28, height: 28, "background-color": token("--baton"), "border-width": 4, "border-color": token("--baton-soft"), "font-size": 13, "font-weight": 700 } },
    {
      selector: "node.team",
      style: {
        shape: "round-rectangle",
        width: "label",
        height: 24,
        padding: "8",
        "background-color": token("--team-fill"),
        color: token("--team-ink"),
        "text-valign": "center",
        "text-margin-y": 0,
        "text-background-opacity": 0,
        "font-weight": 600,
      },
    },
    { selector: "node.issue", style: { width: 8, height: 8, "background-color": token("--issue-fill"), "font-size": 9, color: token("--muted"), "text-margin-y": 3 } },
    { selector: "edge", style: { "curve-style": "bezier", "target-arrow-shape": "triangle", "arrow-scale": 0.8, width: 1.5, "line-color": token("--history"), "target-arrow-color": token("--history") } },
    {
      selector: "edge.learned",
      style: {
        width: "data(width)",
        "line-color": token("--count-only"),
        "target-arrow-color": token("--count-only"),
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
    { selector: "edge.shortcut", style: { "line-color": token("--shortcuts"), "target-arrow-color": token("--shortcuts") } },
    { selector: "edge.merged", style: { width: 3, "line-style": "dashed", "line-dash-pattern": [6, 4], "line-color": token("--merging"), "target-arrow-shape": "none" } },
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
    <section className="card graph-card" aria-labelledby="graph-title">
      <div className="card-head">
        <div>
          <h2 id="graph-title">Ownership graph</h2>
          <p className="sub">Links around one entity. Thicker links are stronger. Click any entity to move there.</p>
        </div>
        <form className="graph-form" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="graph-entity">
            Entity
          </label>
          <input id="graph-entity" type="text" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="kubelet" autoComplete="off" spellCheck={false} />
          <button type="submit" className="ghost-btn">
            Show
          </button>
        </form>
      </div>
      <div className="graph-body">
        <div className="graph-wrap">
          <div ref={container} className="graph-canvas" aria-label="Graph around the chosen entity" />
          <StateOverlay state={load} />
        </div>
        <ul className="graph-legend" aria-label="Graph legend">
          <li><span className="key key-learned" />Learned link <span className="muted">entity to team</span></li>
          <li><span className="key key-shortcut" />Shortcut <span className="muted">compressed from history</span></li>
          <li><span className="key key-merged" />Merged name <span className="muted">SAME_AS</span></li>
          <li><span className="key key-history" />History <span className="muted">past issue to fixing team</span></li>
          <li className="legend-gap"><span className="node-key node-entity" />Entity</li>
          <li><span className="node-key node-team" />Team</li>
          <li><span className="node-key node-issue" />Past issue</li>
        </ul>
      </div>
    </section>
  );
}
