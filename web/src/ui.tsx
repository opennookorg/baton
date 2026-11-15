import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, fmt, REDUCED_MOTION, type Stats } from "./api";

export const ThemeKey = createContext("auto");
export const useThemeKey = () => useContext(ThemeKey);

export type LoadState = { kind: "loading" | "empty" | "error"; title: string; detail?: ReactNode } | null;

export function StateOverlay({ state }: { state: LoadState }) {
  if (!state) return null;
  return (
    <div className={`state is-${state.kind}`}>
      <strong>{state.title}</strong>
      {state.detail && <span>{state.detail}</span>}
    </div>
  );
}

export function errorState(error: unknown): LoadState {
  if (error instanceof ApiError && error.status === 503) {
    return { kind: "error", title: "Waiting for the Baton service", detail: <>Run with <code>BATON_FAKE_SERVICE=1</code> to see demo data.</> };
  }
  return { kind: "error", title: "Could not load this", detail: error instanceof Error ? error.message : String(error) };
}

function AnimatedCount({ value }: { value: number | undefined }) {
  const [shown, setShown] = useState<number | undefined>(REDUCED_MOTION ? value : undefined);
  const frame = useRef(0);
  useEffect(() => {
    if (value === undefined || REDUCED_MOTION) return setShown(value);
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / 900);
      setShown(Math.round(value * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [value]);
  return <span className="counter-value">{shown === undefined ? "-" : fmt(shown)}</span>;
}

const COUNTERS: { key: keyof Stats; label: ReactNode; hero?: boolean }[] = [
  { key: "issues_learned", label: "Issues learned" },
  { key: "links_reweighted", label: "Links reweighted" },
  { key: "merges", label: "Names merged" },
  { key: "shortcuts", label: "Shortcuts created" },
  { key: "misroutes_avoided", label: <>Misroutes avoided <span className="muted">per 1,000 issues vs count-only</span></>, hero: true },
];

export function Counters() {
  const [stats, setStats] = useState<Stats>({});
  useEffect(() => {
    api.stats().then(setStats, () => setStats({}));
  }, []);
  return (
    <section className="counters" aria-label="What the graph has learned">
      {COUNTERS.map((counter) => (
        <div key={counter.key} className={counter.hero ? "counter counter-hero" : "counter"}>
          <AnimatedCount value={stats[counter.key]} />
          <span className="counter-label">{counter.label}</span>
        </div>
      ))}
    </section>
  );
}
