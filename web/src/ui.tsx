import { CircleAlert, LoaderCircle } from "lucide-react";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, fmt, REDUCED_MOTION, type Stats } from "./api";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export const ThemeKey = createContext("auto");
export const useThemeKey = () => useContext(ThemeKey);

export type LoadState = { kind: "loading" | "empty" | "error"; title: string; detail?: ReactNode } | null;

export function StateOverlay({ state }: { state: LoadState }) {
  if (!state) return null;
  return (
    <div className="absolute inset-0 z-10 grid place-items-center bg-card/85 p-6 text-center" role={state.kind === "error" ? "alert" : "status"}>
      <div className="flex max-w-sm flex-col items-center gap-1.5 text-sm">
        {state.kind === "loading" && <LoaderCircle className="size-4 animate-spin text-muted-foreground" aria-hidden="true" />}
        {state.kind === "error" && <CircleAlert className="size-4 text-destructive" aria-hidden="true" />}
        <strong className="font-medium">{state.title}</strong>
        {state.detail && <span className="text-muted-foreground">{state.detail}</span>}
      </div>
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
  return <>{shown === undefined ? "-" : fmt(shown)}</>;
}

const COUNTERS: { key: keyof Stats; label: string; note?: string; hero?: boolean }[] = [
  { key: "issues_learned", label: "Issues learned" },
  { key: "links_reweighted", label: "Links reweighted" },
  { key: "merges", label: "Names merged" },
  { key: "shortcuts", label: "Shortcuts created" },
  { key: "misroutes_avoided", label: "Misroutes avoided", note: "per 1,000 issues vs count-only", hero: true },
];

export function Counters() {
  const [stats, setStats] = useState<Stats>({});
  useEffect(() => {
    api.stats().then(setStats, () => setStats({}));
  }, []);
  return (
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5" aria-label="What the graph has learned">
      {COUNTERS.map((counter) => (
        <Card key={counter.key} size="sm" className={cn("gap-1 px-4", counter.hero && "col-span-2 sm:col-span-2 lg:col-span-1")}>
          <span className="text-xs text-muted-foreground">
            {counter.label}
            {counter.note && <span className="text-muted-foreground/70"> {counter.note}</span>}
          </span>
          <span className={cn("font-mono text-2xl font-medium tracking-tight tabular-nums", counter.hero && "text-brand")}>
            <AnimatedCount value={stats[counter.key]} />
          </span>
        </Card>
      ))}
    </section>
  );
}
