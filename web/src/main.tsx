import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { createRootRoute, createRoute, createRouter, Link, Outlet, RouterProvider, useRouterState } from "@tanstack/react-router";
import { ArrowRight, BookOpen, Info, ChartLine, FlaskConical, Monitor, Moon, Plug, Route as RouteIcon, Sun, Waypoints } from "lucide-react";
import { lazy, StrictMode, Suspense, useEffect, useLayoutEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, onServiceUnavailable, STAGES, type Metric, type Stage } from "./api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { CLIENT_IDS, ConnectPage, type ClientId } from "./routes/ConnectPage";
import { CurvePage } from "./routes/CurvePage";
import { TryPage } from "./routes/TryPage";
import "./index.css";
import { Counters, ThemeKey } from "./ui";

const GraphPage = lazy(() => import("./routes/GraphPage").then((module) => ({ default: module.GraphPage })));

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
  { to: "/", label: "Learning curve", icon: ChartLine, group: "Dashboard", stats: true, about: "Routes each Kubernetes issue to the team that owns it, and learns ownership from what actually gets fixed." },
  { to: "/try", label: "Try an issue", icon: FlaskConical, group: "Dashboard", stats: true, about: "Paste an issue and see which team Baton picks, and the graph path behind it." },
  { to: "/explore", label: "Ownership graph", icon: Waypoints, group: "Dashboard", stats: true, about: "Walk the learned graph: entities, the teams they lead to, and how strong each link is." },
  { to: "/connect", label: "MCP connector", icon: Plug, group: "Integrations", stats: false, about: "Give any agent Baton's routing tools: Claude Code, ChatGPT, Codex, Cursor, OpenCode, Hermes Agent, OpenClaw and other MCP clients." },
] as const;
const GROUPS = ["Dashboard", "Integrations"] as const;
const DOCS_URL = "https://baton-docs-134858271117.us-central1.run.app/docs";
const DASHBOARD_REPO = "kubernetes/kubernetes";

function RepoNotice() {
  const { data } = useQuery({ queryKey: ["repos"], queryFn: api.repos });
  const others = (data?.repos ?? []).map((row) => row.repo).filter((repo) => repo !== DASHBOARD_REPO);
  return (
    <Alert className="max-w-3xl" role="note">
      <Info aria-hidden="true" />
      <AlertTitle>
        This dashboard shows {DASHBOARD_REPO} only{data ? `, one of the ${data.repos.length} repos Baton has learned` : ""}.
      </AlertTitle>
      <AlertDescription className="text-muted-foreground">
        <p>
          {others.length > 0 && (
            <>
              The others ({others.join(", ")}) answer through the <Link to="/connect" className="underline underline-offset-2">MCP tools</Link> and the API when you pass{" "}
              <code>repo</code>.{" "}
            </>
          )}
          Any other repo returns "unknown repo" here. To route your own repo, self-host Baton and onboard it.{" "}
          <a href={`${DOCS_URL}/repos`} target="_blank" rel="noreferrer" className="underline underline-offset-2">
            Which repos work
          </a>
        </p>
      </AlertDescription>
    </Alert>
  );
}

function AppSidebar({ pathname }: { pathname: string }) {
  const { setOpenMobile } = useSidebar();
  return (
    <Sidebar variant="inset" collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild tooltip="Baton">
              <Link to="/" onClick={() => setOpenMobile(false)}>
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand text-white" aria-hidden="true">
                  <RouteIcon className="size-4" />
                </span>
                <span className="grid leading-tight">
                  <span className="font-semibold tracking-tight">Baton</span>
                  <span className="text-xs text-muted-foreground">Issue router</span>
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {GROUPS.map((group) => (
          <SidebarGroup key={group}>
            <SidebarGroupLabel>{group}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV.filter((item) => item.group === group).map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton asChild isActive={pathname === item.to} tooltip={item.label}>
                      <Link to={item.to} onClick={() => setOpenMobile(false)}>
                        <item.icon />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
        <SidebarGroup>
          <SidebarGroupLabel>Resources</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="Documentation">
                  <a href={DOCS_URL} target="_blank" rel="noreferrer">
                    <BookOpen />
                    <span>Documentation</span>
                  </a>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="group-data-[collapsible=icon]:hidden">
        <div className="rounded-lg border bg-card p-3 text-xs shadow-xs">
          <p className="font-medium">Use Baton from your agent</p>
          <p className="mt-0.5 text-muted-foreground">Five MCP tools for routing and triage.</p>
          <Button size="sm" className="mt-2.5 w-full" asChild>
            <Link to="/connect" onClick={() => setOpenMobile(false)}>
              Connect a client <ArrowRight />
            </Link>
          </Button>
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}

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

  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const page = NAV.find((item) => item.to === pathname) ?? NAV[0];

  return (
    <ThemeKey.Provider value={`${theme}-${systemDark}`}>
      <TooltipProvider delayDuration={0}>
        <SidebarProvider>
          <AppSidebar pathname={pathname} />
          <SidebarInset className="min-w-0">
            <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b bg-background/90 px-4 backdrop-blur-sm md:rounded-t-xl">
              <SidebarTrigger className="-ml-1" />
              <Separator orientation="vertical" className="mr-1 data-vertical:h-4 data-vertical:self-center" />
              <h1 className="truncate text-sm font-medium">{page.label}</h1>
              <div className="ml-auto">
                <ThemeMenu theme={theme} onTheme={chooseTheme} />
              </div>
            </header>
            <main className="flex-1 space-y-6 px-4 py-6 sm:px-6">
              {banner && (
                <Alert variant="destructive" role="status">
                  <AlertTitle>Baton service unavailable.</AlertTitle>
                  <AlertDescription>{banner}</AlertDescription>
                </Alert>
              )}
              <p className="max-w-2xl text-balance text-muted-foreground">{page.about}</p>
              <RepoNotice />
              {page.stats && <Counters />}
              <Suspense>
                <Outlet />
              </Suspense>
            </main>
            <footer className="border-t px-4 py-5 text-xs text-muted-foreground sm:px-6">
              Trained on 1,700 real kubernetes/kubernetes issues, scored on the 300 newest ones it never saw. Graph stored in a self-hosted HydraDB node.
            </footer>
          </SidebarInset>
        </SidebarProvider>
      </TooltipProvider>
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

const connectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/connect",
  validateSearch: (search: Record<string, unknown>): { client?: ClientId } => (CLIENT_IDS.includes(search.client as ClientId) && search.client !== "claude-code" ? { client: search.client as ClientId } : {}),
  component: function ConnectRoute() {
    const { client = "claude-code" } = connectRoute.useSearch();
    const navigate = connectRoute.useNavigate();
    return <ConnectPage client={client} onClient={(next) => navigate({ search: next === "claude-code" ? {} : { client: next }, replace: true })} />;
  },
});

const router = createRouter({ routeTree: rootRoute.addChildren([curveRoute, tryRoute, exploreRoute, connectRoute]) });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 5 * 60_000, refetchOnWindowFocus: false, retry: 1 } } });
queryClient.prefetchQuery({ queryKey: ["stats"], queryFn: api.stats });
queryClient.prefetchQuery({ queryKey: ["curve"], queryFn: api.curve });
queryClient.prefetchQuery({ queryKey: ["repos"], queryFn: api.repos });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
