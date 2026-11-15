import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, fmt, pct, STAGES, type RouteResult, type Stage } from "../api";
import { errorState, type LoadState } from "../ui";

const PRESETS = [
  { label: "CSI attach timeout", title: "PVC stays Pending: volume attach timeout from the CSI driver", body: "" },
  { label: "kubelet OOM", title: "kubelet OOM kills pods even when cgroup memory is under the limit", body: "Seen in pkg/kubelet/cm/memory_manager.go after the upgrade." },
  { label: "kube-apiserver watch", title: "kube-apiserver drops watch events under load", body: "Clients log: context deadline exceeded" },
  { label: "kubectl flag", title: "kubectl apply ignores the server-side flag", body: "" },
];

type Outcome = { kind: "result"; result: RouteResult; stage: Stage } | { kind: "note"; text: string } | { kind: "error"; state: LoadState } | null;

function Chip({ name, isTeam }: { name: string; isTeam: boolean }) {
  if (isTeam) return <span className="chip chip-team">{name}</span>;
  if (name.startsWith("#")) {
    return (
      <a className="chip chip-issue" href={`https://github.com/kubernetes/kubernetes/issues/${name.slice(1)}`} target="_blank" rel="noreferrer" title="A past issue that mentioned this and was fixed by this team">
        {name}
      </a>
    );
  }
  return (
    <Link className="chip" to="/explore" search={{ entity: name }} title={`Show ${name} in the graph`}>
      {name}
    </Link>
  );
}

function ShareBar({ share }: { share: number }) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setWidth(Math.max(2, share * 100)));
    return () => cancelAnimationFrame(frame);
  }, [share]);
  return (
    <div className="share-track">
      <div className="share-fill" style={{ width: `${width}%` }} />
    </div>
  );
}

function Result({ outcome }: { outcome: Outcome }) {
  if (!outcome) return null;
  if (outcome.kind === "note") return <p className="result-note">{outcome.text}</p>;
  if (outcome.kind === "error") {
    return (
      <p className="result-note is-error">
        <strong>{outcome.state?.title}. </strong>
        <span>{outcome.state?.detail}</span>
      </p>
    );
  }
  const { result, stage } = outcome;
  return (
    <>
      <div className="result-head">
        <div className="confidence">
          {pct(result.confidence)}
          <small>confidence at issue {fmt(stage)}</small>
        </div>
        <div className="entity-count">
          <b>{result.entities_found}</b> entities known · <b>{result.entities_unknown}</b> unknown
        </div>
      </div>
      {result.teams.length ? (
        <ol className="team-list">
          {result.teams.map((team) => (
            <li key={team.team} className="team-row">
              <div className="team-line">
                <span className="team-name">{team.team}</span>
                <ShareBar share={team.share} />
                <span className="share-value">{pct(team.share)}</span>
              </div>
              <div className="path">
                {team.path.map((name, i) => (
                  <span key={`${name}-${i}`} className="path-step">
                    {i > 0 && <span className="arrow" aria-hidden="true">→</span>}
                    <Chip name={name} isTeam={i === team.path.length - 1} />
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="result-note">No entity in this issue is in the graph as of issue {fmt(stage)}. Add a component, file path or error message, or move the slider later.</p>
      )}
    </>
  );
}

export function TryPage({ stage, onStage }: { stage: Stage; onStage: (stage: Stage) => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);
  const titleInput = useRef<HTMLInputElement>(null);

  async function route(nextTitle = title, nextBody = body, asOf = stage) {
    const trimmed = nextTitle.trim();
    if (!trimmed) {
      setOutcome({ kind: "note", text: "Add a title to route the issue." });
      titleInput.current?.focus();
      return;
    }
    const mine = ++seq.current;
    setBusy(true);
    try {
      const result = await api.route(trimmed, nextBody, asOf);
      if (mine === seq.current) setOutcome({ kind: "result", result, stage: asOf });
    } catch (error) {
      if (mine === seq.current) setOutcome({ kind: "error", state: errorState(error) });
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  }

  useEffect(() => {
    if (outcome?.kind !== "result" || outcome.stage === stage) return;
    const timer = setTimeout(() => route(), 120);
    return () => clearTimeout(timer);
  }, [stage]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    route();
  };

  return (
    <section className="card try-card" aria-labelledby="try-title">
      <div className="card-head">
        <div>
          <h2 id="try-title">Try an issue</h2>
          <p className="sub">Paste a bug report. Baton names the owning team and shows the path it followed through the graph.</p>
        </div>
      </div>
      <div className="presets" aria-label="Example issues">
        {PRESETS.map((preset) => (
          <button
            key={preset.label}
            type="button"
            className="preset"
            onClick={() => {
              setTitle(preset.title);
              setBody(preset.body);
              route(preset.title, preset.body);
            }}
          >
            {preset.label}
          </button>
        ))}
      </div>
      <form className="route-form" noValidate onSubmit={submit}>
        <label className="field">
          <span>Title</span>
          <input ref={titleInput} value={title} onChange={(e) => setTitle(e.target.value)} type="text" maxLength={500} placeholder="kubelet OOM kills pods even when cgroup memory is under the limit" required />
        </label>
        <label className="field">
          <span>
            Body <span className="muted">optional</span>
          </span>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} maxLength={50000} placeholder="Logs, file paths, error messages" />
        </label>
        <div className="stage">
          <div className="stage-head">
            <label htmlFor="stage-slider">Graph as of learning issue</label>
            <output htmlFor="stage-slider">{fmt(stage)}</output>
          </div>
          <input
            id="stage-slider"
            type="range"
            min={0}
            max={STAGES.length - 1}
            step={1}
            value={STAGES.indexOf(stage)}
            aria-valuetext={`issue ${fmt(stage)}`}
            onChange={(e) => onStage(STAGES[Number(e.target.value)])}
          />
          <div className="stage-ticks" aria-hidden="true">
            {STAGES.map((s) => (
              <span key={s}>{fmt(s)}</span>
            ))}
          </div>
        </div>
        <button type="submit" className="primary-btn" disabled={busy}>
          {busy ? "Routing" : "Route issue"}
        </button>
      </form>
      <div className="route-result" aria-live="polite">
        <Result outcome={outcome} />
      </div>
    </section>
  );
}
