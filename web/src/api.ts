export const STAGES = [0, 500, 1000, 1700] as const;
export type Stage = (typeof STAGES)[number];
export type Metric = "top1" | "top3";

export type Stats = Partial<Record<"issues_learned" | "links_reweighted" | "merges" | "shortcuts" | "misroutes_avoided", number>>;
export type CurvePoint = { issues: number; top1: number; top3: number };
export type Curve = { lines: Record<string, CurvePoint[]> };
export type TeamScore = { team: string; share: number; path: string[] };
export type RouteResult = { teams: TeamScore[]; confidence: number; entities_found: number; entities_unknown: number };
export type GraphNode = { id: number | string; name: string; label: "Team" | "Entity" | "Issue" };
export type GraphLink = { source: number | string; target: number | string; type: "ROUTES_TO" | "SEEN_IN" | "OWNED_BY" | "SAME_AS"; strength?: number; shortcut?: boolean };
export type Graph = { nodes: GraphNode[]; links: GraphLink[] };

export class ApiError extends Error {
  constructor(readonly status: number, detail: string) {
    super(detail);
  }
}

const unavailableListeners = new Set<(detail: string) => void>();

export function onServiceUnavailable(listener: (detail: string) => void) {
  unavailableListeners.add(listener);
  return () => void unavailableListeners.delete(listener);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError(0, "The Baton API did not answer. Check that the server is running.");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail) ? payload.detail.map((d: { msg: string }) => d.msg).join("; ") : payload.detail;
    const error = new ApiError(response.status, detail || `Request failed with status ${response.status}.`);
    if (response.status === 503) unavailableListeners.forEach((listener) => listener(error.message));
    throw error;
  }
  return payload as T;
}

export const api = {
  stats: () => request<Stats>("/stats"),
  curve: () => request<Curve>("/curve"),
  graph: (entity: string) => request<Graph>(`/graph?entity=${encodeURIComponent(entity)}`),
  route: (title: string, body: string, asOf: Stage) => request<RouteResult>("/route", { method: "POST", body: JSON.stringify({ title, body, as_of: asOf }) }),
};

export const pct = (value: number) => `${Math.round(value * 100)}%`;
export const fmt = (value: number) => value.toLocaleString("en-US");
export const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const colorProbe = document.createElement("canvas").getContext("2d", { willReadFrequently: true })!;

export function color(name: string) {
  colorProbe.clearRect(0, 0, 1, 1);
  colorProbe.fillStyle = "#000";
  colorProbe.fillStyle = token(name);
  colorProbe.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = colorProbe.getImageData(0, 0, 1, 1).data;
  return `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
}
export const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
