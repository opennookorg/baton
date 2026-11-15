import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, fmt, pct, STAGES, type RouteResult, type Stage } from "../api";
import { errorState, type LoadState } from "../ui";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const PRESETS = [
  { label: "CSI attach timeout", title: "PVC stays Pending: volume attach timeout from the CSI driver", body: "" },
  { label: "kubelet OOM", title: "kubelet OOM kills pods even when cgroup memory is under the limit", body: "Seen in pkg/kubelet/cm/memory_manager.go after the upgrade." },
  { label: "kube-apiserver watch", title: "kube-apiserver drops watch events under load", body: "Clients log: context deadline exceeded" },
  { label: "kubectl flag", title: "kubectl apply ignores the server-side flag", body: "" },
];

type Outcome = { kind: "result"; result: RouteResult; stage: Stage } | { kind: "note"; text: string } | { kind: "error"; state: LoadState } | null;

function Chip({ name, isTeam }: { name: string; isTeam: boolean }) {
  if (isTeam) return <Badge className="max-w-full font-mono"><span className="truncate">{name}</span></Badge>;
  if (name.startsWith("#")) {
    return (
      <Badge variant="secondary" className="font-mono" asChild>
        <a href={`https://github.com/kubernetes/kubernetes/issues/${name.slice(1)}`} target="_blank" rel="noreferrer" title="A past issue that mentioned this and was fixed by this team">
          {name}
        </a>
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="max-w-full font-mono" asChild>
      <Link to="/explore" search={{ entity: name }} title={`Show ${name} in the graph`}>
        <span className="truncate">{name}</span>
      </Link>
    </Badge>
  );
}

function ShareBar({ share, lead }: { share: number; lead: boolean }) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setWidth(Math.max(2, share * 100)));
    return () => cancelAnimationFrame(frame);
  }, [share]);
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-muted">
      <div className={cn("h-full rounded-full transition-[width] duration-500 ease-out", lead ? "bg-brand" : "bg-brand/40")} style={{ width: `${width}%` }} />
    </div>
  );
}

function Result({ outcome }: { outcome: Outcome }) {
  if (!outcome) return <p className="py-10 text-center text-sm text-muted-foreground">Pick an example or write an issue. The owning team and the path Baton followed show up here.</p>;
  if (outcome.kind === "note") return <p className="text-sm text-muted-foreground">{outcome.text}</p>;
  if (outcome.kind === "error") {
    return (
      <Alert variant="destructive">
        <AlertTitle>{outcome.state?.title}.</AlertTitle>
        <AlertDescription>{outcome.state?.detail}</AlertDescription>
      </Alert>
    );
  }
  const { result, stage } = outcome;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <div className="font-mono text-4xl font-medium tracking-tight tabular-nums">{pct(result.confidence)}</div>
          <div className="text-xs text-muted-foreground">confidence at issue {fmt(stage)}</div>
        </div>
        <div className="text-xs text-muted-foreground">
          <span className="font-mono font-medium text-foreground tabular-nums">{result.entities_found}</span> entities known ·{" "}
          <span className="font-mono font-medium text-foreground tabular-nums">{result.entities_unknown}</span> unknown
        </div>
      </div>
      <Separator />
      {result.teams.length ? (
        <ol className="divide-y">
          {result.teams.map((team, index) => (
            <li key={team.team} className="space-y-2.5 py-3.5 first:pt-0 last:pb-0">
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(64px,1.5fr)_3rem] items-center gap-3">
                <span className={cn("truncate font-mono text-sm", index === 0 && "font-medium")}>{team.team}</span>
                <ShareBar share={team.share} lead={index === 0} />
                <span className={cn("text-right font-mono text-sm tabular-nums", index === 0 ? "font-medium" : "text-muted-foreground")}>{pct(team.share)}</span>
              </div>
              <div className="flex flex-wrap items-center gap-1">
                {team.path.map((name, i) => (
                  <span key={`${name}-${i}`} className="inline-flex max-w-full items-center gap-1">
                    {i > 0 && <ChevronRight className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />}
                    <Chip name={name} isTeam={i === team.path.length - 1} />
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">No entity in this issue is in the graph as of issue {fmt(stage)}. Add a component, file path or error message, or move the slider later.</p>
      )}
    </div>
  );
}

export function TryPage({ stage, onStage }: { stage: Stage; onStage: (stage: Stage) => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [submitted, setSubmitted] = useState<{ title: string; body: string } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const titleInput = useRef<HTMLInputElement>(null);
  const routed = useQuery({
    queryKey: ["route", submitted?.title, submitted?.body, stage],
    queryFn: async () => ({ result: await api.route(submitted!.title, submitted!.body, stage), stage }),
    enabled: submitted !== null,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });
  const busy = routed.isFetching;
  const outcome: Outcome = note
    ? { kind: "note", text: note }
    : routed.error
      ? { kind: "error", state: errorState(routed.error) }
      : routed.data
        ? { kind: "result", ...routed.data }
        : null;

  function route(nextTitle = title, nextBody = body) {
    const trimmed = nextTitle.trim();
    if (!trimmed) {
      setNote("Add a title to route the issue.");
      titleInput.current?.focus();
      return;
    }
    setNote(null);
    if (submitted?.title === trimmed && submitted.body === nextBody) {
      if (routed.isError) routed.refetch();
      return;
    }
    setSubmitted({ title: trimmed, body: nextBody });
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    route();
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:items-start">
      <Card aria-labelledby="try-title">
        <CardHeader>
          <CardTitle>
            <h2 id="try-title">Try an issue</h2>
          </CardTitle>
          <CardDescription>Paste a kubernetes/kubernetes bug report. Baton names the owning SIG and shows the path it followed through the graph.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <span className="text-xs text-muted-foreground" id="presets-label">Examples</span>
            <div className="flex flex-wrap gap-2" role="group" aria-labelledby="presets-label">
              {PRESETS.map((preset) => (
                <Button
                  key={preset.label}
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setTitle(preset.title);
                    setBody(preset.body);
                    route(preset.title, preset.body);
                  }}
                >
                  {preset.label}
                </Button>
              ))}
            </div>
          </div>
          <form className="space-y-5" noValidate onSubmit={submit}>
            <div className="space-y-2">
              <Label htmlFor="issue-title">Title</Label>
              <Input id="issue-title" ref={titleInput} value={title} onChange={(e) => setTitle(e.target.value)} type="text" maxLength={500} placeholder="kubelet OOM kills pods even when cgroup memory is under the limit" required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="issue-body">
                Body <span className="font-normal text-muted-foreground">optional</span>
              </Label>
              <Textarea id="issue-body" value={body} onChange={(e) => setBody(e.target.value)} rows={3} maxLength={50000} placeholder="Logs, file paths, error messages" />
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <Label id="stage-label" htmlFor="stage-slider">Graph as of learning issue</Label>
                <output htmlFor="stage-slider" className="font-mono text-sm font-medium tabular-nums">{fmt(stage)}</output>
              </div>
              <Slider
                min={0}
                max={STAGES.length - 1}
                step={1}
                value={[STAGES.indexOf(stage)]}
                onValueChange={([index]) => onStage(STAGES[index])}
                thumbProps={{ id: "stage-slider", "aria-labelledby": "stage-label", "aria-valuetext": `issue ${fmt(stage)}` }}
              />
              <div className="flex justify-between font-mono text-xs text-muted-foreground tabular-nums" aria-hidden="true">
                {STAGES.map((s) => (
                  <span key={s}>{fmt(s)}</span>
                ))}
              </div>
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy && <LoaderCircle className="animate-spin" aria-hidden="true" />}
              {busy ? "Routing" : "Route issue"}
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card aria-labelledby="result-title">
        <CardHeader>
          <CardTitle>
            <h2 id="result-title">Routing result</h2>
          </CardTitle>
        </CardHeader>
        <CardContent aria-live="polite">
          <Result outcome={outcome} />
        </CardContent>
      </Card>
    </div>
  );
}
