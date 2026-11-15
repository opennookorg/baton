import { createRootRoute, createRoute, createRouter, Link, Outlet, RouterProvider } from "@tanstack/react-router";
import { Monitor, Moon, Route as RouteIcon, Sun } from "lucide-react";
import { StrictMode, useEffect, useLayoutEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { onServiceUnavailable, STAGES, type Metric, type Stage } from "./api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { CurvePage } from "./routes/CurvePage";
import { GraphPage } from "./routes/GraphPage";
import { TryPage } from "./routes/TryPage";
import "./index.css";
import { Counters, ThemeKey } from "./ui";

type Theme = "auto" | "light" | "dark";
const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "auto", label: "Auto", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

function storedTheme(): Theme {
  try {
    const theme = localStorage.getItem("baton-theme");
    return theme === "light" || theme === "dark" ? theme : "auto";
  } catch {
    return "auto";
  }
}

function saveTheme(theme: Theme) {
  try {
    if (theme === "auto") localStorage.removeItem("baton-theme");
    else localStorage.setItem("baton-theme", theme);
  } catch {}
}

const NAV = [
  { to: "/", label: "Learning curve", exact: true },
  { to: "/try", label: "Try an issue", exact: false },
  { to: "/explore", label: "Ownership graph", exact: false },
] as const;

function ThemeMenu({ theme, onTheme }: { theme: Theme; onTheme: (theme: Theme) => void }) {
  const Icon = THEMES.find((option) => option.value === theme)!.icon;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Switch colour theme" title="Colour theme">
          <Icon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-36">
        <DropdownMenuRadioGroup value={theme} onValueChange={(value) => onTheme(value as Theme)}>
          {THEMES.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              <option.icon />
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Layout() {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  const [systemDark, setSystemDark] = useState(darkQuery.matches);
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => onServiceUnavailable(setBanner), []);
  useEffect(() => {
    const listener = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    darkQuery.addEventListener("change", listener);
    return () => darkQuery.removeEventListener("change", listener);
  }, []);
  useLayoutEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark" || (theme === "auto" && systemDark));
  }, [theme, systemDark]);

  const chooseTheme = (next: Theme) => {
    saveTheme(next);
    setTheme(next);
  };

  return (
    <ThemeKey.Provider value={`${theme}-${systemDark}`}>
      <div className="flex min-h-svh flex-col">
        <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur-sm">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2.5 sm:px-6">
            <h1 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
              <span className="grid size-6 place-items-center rounded-md bg-brand text-white" aria-hidden="true">
                <RouteIcon className="size-3.5" />
              </span>
              Baton
            </h1>
            <nav className="order-last -mx-2.5 flex w-[calc(100%+1.25rem)] gap-0.5 sm:order-none sm:mx-0 sm:w-auto" aria-label="Pages">
              {NAV.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  activeOptions={{ exact: item.exact, includeSearch: false }}
                  className="rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground data-[status=active]:bg-muted data-[status=active]:font-medium data-[status=active]:text-foreground"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
            <div className="ml-auto">
              <ThemeMenu theme={theme} onTheme={chooseTheme} />
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 space-y-6 px-4 py-8 sm:px-6">
          {banner && (
            <Alert variant="destructive" role="status">
              <AlertTitle>Baton service unavailable.</AlertTitle>
              <AlertDescription>{banner}</AlertDescription>
            </Alert>
          )}
          <p className="max-w-2xl text-balance text-muted-foreground">Routes each Kubernetes issue to the team that owns it, and learns ownership from what actually gets fixed.</p>
          <Counters />
          <Outlet />
        </main>
        <footer className="border-t">
          <p className="mx-auto max-w-6xl px-4 py-6 text-xs text-muted-foreground sm:px-6">
            Trained on 1,700 real kubernetes/kubernetes issues, scored on the 300 newest ones it never saw. Graph stored in a self-hosted HydraDB node.
          </p>
        </footer>
      </div>
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
