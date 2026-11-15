import { createRootRoute, createRoute, createRouter, Link, Outlet, RouterProvider } from "@tanstack/react-router";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { onServiceUnavailable, STAGES, type Metric, type Stage } from "./api";
import { CurvePage } from "./routes/CurvePage";
import { GraphPage } from "./routes/GraphPage";
import { TryPage } from "./routes/TryPage";
import "./styles.css";
import { Counters, ThemeKey } from "./ui";

type Theme = "auto" | "light" | "dark";
const THEMES: Theme[] = ["auto", "light", "dark"];
const THEME_LABELS: Record<Theme, string> = { auto: "Auto theme", light: "Light", dark: "Dark" };

function applyTheme(theme: Theme) {
  if (theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try {
    if (theme === "auto") localStorage.removeItem("baton-theme");
    else localStorage.setItem("baton-theme", theme);
  } catch {}
}

function Layout() {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme as Theme) || "auto");
  const [systemDark, setSystemDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => onServiceUnavailable(setBanner), []);
  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);

  const cycleTheme = () => {
    const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    applyTheme(next);
    setTheme(next);
  };

  return (
    <ThemeKey.Provider value={`${theme}-${systemDark}`}>
      {banner && (
        <div className="banner" role="status">
          <strong>Baton service unavailable.</strong>
          <span>{banner}</span>
        </div>
      )}
      <header className="masthead">
        <div className="brand">
          <span className="mark" aria-hidden="true" />
          <div>
            <h1>Baton</h1>
            <p className="tagline">Routes each Kubernetes issue to the team that owns it, and learns ownership from what actually gets fixed.</p>
          </div>
        </div>
        <button className="ghost-btn" type="button" aria-label="Switch colour theme" onClick={cycleTheme}>
          {THEME_LABELS[theme]}
        </button>
      </header>
      <Counters />
      <nav className="tabs" aria-label="Pages">
        <Link to="/" className="tab" activeOptions={{ exact: true, includeSearch: false }}>Learning curve</Link>
        <Link to="/try" className="tab" activeOptions={{ includeSearch: false }}>Try an issue</Link>
        <Link to="/explore" className="tab" activeOptions={{ includeSearch: false }}>Ownership graph</Link>
      </nav>
      <main>
        <Outlet />
      </main>
      <footer className="footer">
        Trained on 1,700 real kubernetes/kubernetes issues, scored on the 300 newest ones it never saw. Graph stored in a self-hosted HydraDB node.
      </footer>
    </ThemeKey.Provider>
  );
}

const rootRoute = createRootRoute({ component: Layout });

const curveRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: (search: Record<string, unknown>): { metric?: Metric } => (search.metric === "top3" ? { metric: "top3" } : {}),
  component: function CurveRoute() {
    const { metric = "top1" } = curveRoute.useSearch();
    const navigate = curveRoute.useNavigate();
    return <CurvePage metric={metric} onMetric={(next) => navigate({ search: next === "top1" ? {} : { metric: next }, replace: true })} />;
  },
});

const tryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/try",
  validateSearch: (search: Record<string, unknown>): { as_of?: Stage } => {
    const asOf = Number(search.as_of);
    return STAGES.includes(asOf as Stage) && asOf !== 1700 ? { as_of: asOf as Stage } : {};
  },
  component: function TryRoute() {
    const { as_of = 1700 } = tryRoute.useSearch();
    const navigate = tryRoute.useNavigate();
    return <TryPage stage={as_of} onStage={(next) => navigate({ search: next === 1700 ? {} : { as_of: next }, replace: true })} />;
  },
});

const exploreRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/explore",
  validateSearch: (search: Record<string, unknown>): { entity?: string } => (typeof search.entity === "string" && search.entity.trim() ? { entity: search.entity.trim().slice(0, 200) } : {}),
  component: function ExploreRoute() {
    const { entity = "kubelet" } = exploreRoute.useSearch();
    const navigate = exploreRoute.useNavigate();
    return <GraphPage entity={entity} onEntity={(next) => navigate({ search: { entity: next } })} />;
  },
});

const router = createRouter({ routeTree: rootRoute.addChildren([curveRoute, tryRoute, exploreRoute]) });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
