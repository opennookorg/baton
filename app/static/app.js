const STAGES = [0, 500, 1000, 1700];
const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const LINES = [
  { key: "baton", label: "Baton", color: "--baton", width: 3, dash: [] },
  { key: "count_only", label: "Count-only", color: "--count-only", width: 2, dash: [] },
  { key: "frozen", label: "Frozen", color: "--frozen", width: 2, dash: [6, 4] },
  { key: "reweight", label: "Reweighting", color: "--reweight", width: 1.75, dash: [2, 3], technique: true },
  { key: "shortcuts", label: "Shortcuts", color: "--shortcuts", width: 1.75, dash: [8, 3], technique: true },
  { key: "merging", label: "Name merging", color: "--merging", width: 1.75, dash: [8, 3, 2, 3], technique: true },
  { key: "splitting", label: "Splitting", color: "--splitting", width: 1.75, dash: [3, 5], technique: true },
  { key: "gap_filling", label: "Gap filling", color: "--gap-filling", width: 1.75, dash: [12, 4], technique: true },
];

const PRESETS = [
  { label: "CSI attach timeout", title: "PVC stays Pending: volume attach timeout from the CSI driver", body: "" },
  { label: "kubelet OOM", title: "kubelet OOM kills pods even when cgroup memory is under the limit", body: "Seen in pkg/kubelet/cm/memory_manager.go after the upgrade." },
  { label: "kube-apiserver watch", title: "kube-apiserver drops watch events under load", body: "Clients log: context deadline exceeded" },
  { label: "kubectl flag", title: "kubectl apply ignores the server-side flag", body: "" },
];

const state = {
  metric: "top1",
  stage: 1700,
  curve: null,
  techniques: new Set(),
  chart: null,
  cy: null,
  routeSeq: 0,
};

const $ = (selector) => document.querySelector(selector);
const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const pct = (value) => `${Math.round(value * 100)}%`;
const fmt = (value) => Number(value).toLocaleString("en-US");

class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  } catch {
    throw new ApiError(0, "The Baton API did not answer. Check that the server is running on this port.");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail) ? payload.detail.map((d) => d.msg).join("; ") : payload.detail;
    const error = new ApiError(response.status, detail || `Request failed with status ${response.status}.`);
    if (response.status === 503) showBanner(error.message);
    throw error;
  }
  return payload;
}

function showBanner(detail) {
  const banner = $("#service-banner");
  banner.innerHTML = "";
  const title = document.createElement("strong");
  title.textContent = "Baton service unavailable.";
  const text = document.createElement("span");
  text.textContent = detail;
  banner.append(title, text);
  banner.hidden = false;
}

function setState(element, kind, title, detail) {
  if (!kind) {
    element.hidden = true;
    return;
  }
  element.hidden = false;
  element.className = `state is-${kind}`;
  element.innerHTML = "";
  const heading = document.createElement("strong");
  heading.textContent = title;
  element.append(heading);
  if (detail) {
    const body = document.createElement("span");
    body.innerHTML = detail;
    element.append(body);
  }
}

function errorCopy(error) {
  if (error.status === 503) return ["Waiting for the Baton service", "Run with <code>BATON_FAKE_SERVICE=1</code> to see demo data."];
  return ["Could not load this", error.message];
}

function cycleTheme() {
  const order = ["auto", "light", "dark"];
  const current = document.documentElement.dataset.theme || "auto";
  const next = order[(order.indexOf(current) + 1) % order.length];
  if (next === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = next;
  try {
    if (next === "auto") localStorage.removeItem("baton-theme");
    else localStorage.setItem("baton-theme", next);
  } catch {}
  applyTheme();
}

function applyTheme() {
  const current = document.documentElement.dataset.theme || "auto";
  $("#theme-label").textContent = { auto: "Auto theme", light: "Light", dark: "Dark" }[current];
  if (state.chart) renderChart();
  if (state.cy) state.cy.style(graphStyle());
}

function animateCount(element, target) {
  if (REDUCED_MOTION) {
    element.textContent = fmt(target);
    return;
  }
  const start = performance.now();
  const duration = 900;
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    element.textContent = fmt(Math.round(target * (1 - Math.pow(1 - t, 3))));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

async function loadStats() {
  const cells = document.querySelectorAll("[data-stat]");
  try {
    const stats = await api("/stats");
    cells.forEach((cell) => {
      const value = stats[cell.dataset.stat];
      if (typeof value === "number") animateCount(cell, value);
      else cell.textContent = "-";
    });
  } catch {
    cells.forEach((cell) => (cell.textContent = "-"));
  }
}

const stageMarker = {
  id: "stageMarker",
  afterDatasetsDraw(chart) {
    const { ctx, chartArea, scales } = chart;
    const x = scales.x.getPixelForValue(state.stage);
    ctx.save();
    ctx.strokeStyle = token("--baton");
    ctx.globalAlpha = 0.55;
    ctx.setLineDash([3, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.setLineDash([]);
    const text = `Try an issue: as of ${fmt(state.stage)}`;
    ctx.font = `500 11px ${token("--body")}`;
    const width = ctx.measureText(text).width + 12;
    const left = Math.min(Math.max(x - width / 2, chartArea.left), chartArea.right - width);
    ctx.fillStyle = token("--baton");
    ctx.beginPath();
    ctx.roundRect(left, chartArea.top - 22, width, 18, 5);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.textBaseline = "middle";
    ctx.fillText(text, left + 6, chartArea.top - 13);
    ctx.restore();
  },
};

const endLabels = {
  id: "endLabels",
  afterDatasetsDraw(chart) {
    const { ctx, chartArea } = chart;
    const labels = chart.data.datasets
      .map((dataset, i) => {
        const meta = chart.getDatasetMeta(i);
        const last = meta.data[meta.data.length - 1];
        if (!last || meta.hidden) return null;
        return { y: last.y, x: last.x, text: `${dataset.label} ${pct(dataset.data[dataset.data.length - 1].y)}`, color: dataset.borderColor, strong: dataset.lineKey === "baton" };
      })
      .filter(Boolean)
      .sort((a, b) => a.y - b.y);
    for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 14);
    ctx.save();
    ctx.textBaseline = "middle";
    labels.forEach((label) => {
      ctx.fillStyle = label.color;
      ctx.beginPath();
      ctx.arc(chartArea.right + 10, label.y, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.font = `${label.strong ? 600 : 500} 11.5px ${token("--body")}`;
      ctx.fillStyle = label.strong ? token("--ink") : token("--ink-2");
      ctx.fillText(label.text, chartArea.right + 18, label.y);
    });
    ctx.restore();
  },
};

const crosshair = {
  id: "crosshair",
  afterDraw(chart) {
    const active = chart.tooltip?.getActiveElements?.() || [];
    if (!active.length) return;
    const { ctx, chartArea } = chart;
    const x = active[0].element.x;
    ctx.save();
    ctx.strokeStyle = token("--axis");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

function visibleLines() {
  const lines = state.curve?.lines || {};
  return LINES.filter((line) => lines[line.key]?.length && (!line.technique || state.techniques.has(line.key)));
}

function datasets() {
  return visibleLines().map((line) => ({
    label: line.label,
    lineKey: line.key,
    data: state.curve.lines[line.key].map((point) => ({ x: point.issues, y: point[state.metric] })),
    borderColor: token(line.color),
    backgroundColor: token(line.color),
    borderWidth: line.width,
    borderDash: line.dash,
    pointRadius: 0,
    pointHoverRadius: 4,
    pointHoverBorderWidth: 2,
    pointHoverBorderColor: token("--surface"),
    tension: 0.25,
    order: line.key === "baton" ? 0 : 1,
  }));
}

function yRange(sets) {
  const values = sets.flatMap((set) => set.data.map((point) => point.y));
  if (!values.length) return { min: 0, max: 1 };
  return {
    min: Math.max(0, Math.floor((Math.min(...values) - 0.05) * 10) / 10),
    max: Math.min(1, Math.ceil((Math.max(...values) + 0.05) * 10) / 10),
  };
}

function renderLegend() {
  const legend = $("#chart-legend");
  legend.innerHTML = "";
  visibleLines().forEach((line) => {
    const points = state.curve.lines[line.key];
    const item = document.createElement("span");
    item.className = "legend-item";
    const swatch = document.createElement("span");
    swatch.className = line.dash.length ? "swatch dashed" : "swatch";
    swatch.style.color = token(line.color);
    const value = document.createElement("b");
    value.textContent = pct(points[points.length - 1][state.metric]);
    item.append(swatch, line.label, value);
    legend.append(item);
  });
}

function renderChart() {
  const sets = datasets();
  const range = yRange(sets);
  const grid = token("--hairline");
  const muted = token("--muted");
  renderLegend();
  if (state.chart) {
    state.chart.data.datasets = sets;
    Object.assign(state.chart.options.scales.y, range);
    state.chart.options.scales.x.grid.color = grid;
    state.chart.options.scales.y.grid.color = grid;
    state.chart.options.scales.x.ticks.color = muted;
    state.chart.options.scales.y.ticks.color = muted;
    state.chart.options.scales.x.title.color = muted;
    state.chart.options.plugins.tooltip.backgroundColor = token("--ink");
    state.chart.options.plugins.tooltip.titleColor = token("--surface");
    state.chart.options.plugins.tooltip.bodyColor = token("--surface");
    state.chart.update();
    return;
  }
  Chart.defaults.font.family = token("--body");
  state.chart = new Chart($("#curve-chart"), {
    type: "line",
    data: { datasets: sets },
    plugins: [stageMarker, endLabels, crosshair],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: REDUCED_MOTION ? false : { duration: 700, easing: "easeOutCubic" },
      layout: { padding: { top: 26, right: 128 } },
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          type: "linear",
          min: 0,
          max: 1700,
          ticks: { stepSize: 100, autoSkip: false, maxRotation: 0, color: muted, callback: (value) => ((value % 500 === 0 && !(value === 1500 && window.innerWidth < 640)) || value === 1700 ? fmt(value) : "") },
          grid: { color: grid, drawTicks: false },
          border: { display: false },
          title: { display: true, text: "Learning issues seen", color: muted, font: { size: 11.5 } },
        },
        y: {
          ...range,
          ticks: { color: muted, stepSize: 0.1, callback: (value) => pct(value) },
          grid: { color: grid, drawTicks: false },
          border: { display: false },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: token("--ink"),
          titleColor: token("--surface"),
          bodyColor: token("--surface"),
          padding: 10,
          cornerRadius: 8,
          boxPadding: 4,
          usePointStyle: true,
          itemSort: (a, b) => b.parsed.y - a.parsed.y,
          callbacks: {
            title: (items) => `After ${fmt(items[0].parsed.x)} issues`,
            label: (item) => ` ${item.dataset.label}: ${(item.parsed.y * 100).toFixed(1)}%`,
          },
        },
      },
    },
  });
}

function renderTechniqueToggles() {
  const container = $("#technique-toggles");
  container.innerHTML = "";
  LINES.filter((line) => line.technique).forEach((line) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "toggle";
    button.style.setProperty("--line", `var(${line.color})`);
    button.setAttribute("aria-pressed", String(state.techniques.has(line.key)));
    button.disabled = !state.curve?.lines?.[line.key]?.length;
    const dot = document.createElement("span");
    dot.className = "dot";
    button.append(dot, line.label);
    button.addEventListener("click", () => {
      if (state.techniques.has(line.key)) state.techniques.delete(line.key);
      else state.techniques.add(line.key);
      button.setAttribute("aria-pressed", String(state.techniques.has(line.key)));
      renderChart();
    });
    container.append(button);
  });
}

async function loadCurve() {
  const status = $("#chart-state");
  setState(status, "loading", "Loading accuracy points");
  try {
    state.curve = await api("/curve");
    const hasLines = Object.values(state.curve.lines || {}).some((points) => points.length);
    renderTechniqueToggles();
    if (!hasLines) {
      setState(status, "empty", "No accuracy points yet", "Run <code>uv run python -m eval.run_curve</code> to score the test set, then reload.");
      return;
    }
    setState(status, null);
    renderChart();
  } catch (error) {
    renderTechniqueToggles();
    setState(status, "error", ...errorCopy(error));
  }
}

function setStage(index) {
  state.stage = STAGES[index];
  $("#stage-output").textContent = fmt(state.stage);
  $("#stage-slider").setAttribute("aria-valuetext", `issue ${fmt(state.stage)}`);
  if (state.chart) state.chart.draw();
}

function chipFor(name, isTeam) {
  if (isTeam) {
    const chip = document.createElement("span");
    chip.className = "chip chip-team";
    chip.textContent = name;
    return chip;
  }
  if (name.startsWith("#")) {
    const chip = document.createElement("span");
    chip.className = "chip chip-issue";
    chip.textContent = name;
    chip.title = "A past issue that mentioned this and was fixed by this team";
    return chip;
  }
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "chip";
  chip.textContent = name;
  chip.title = `Show ${name} in the graph`;
  chip.addEventListener("click", () => {
    $("#graph-entity").value = name;
    loadGraph(name);
    $(".graph-card").scrollIntoView({ behavior: REDUCED_MOTION ? "auto" : "smooth", block: "nearest" });
  });
  return chip;
}

function renderPath(path) {
  const container = document.createElement("div");
  container.className = "path";
  path.forEach((name, i) => {
    if (i > 0) {
      const arrow = document.createElement("span");
      arrow.className = "arrow";
      arrow.textContent = "→";
      arrow.setAttribute("aria-hidden", "true");
      container.append(arrow);
    }
    container.append(chipFor(name, i === path.length - 1));
  });
  return container;
}

function renderRoute(result) {
  const output = $("#route-result");
  output.innerHTML = "";
  const head = document.createElement("div");
  head.className = "result-head";
  const confidence = document.createElement("div");
  confidence.className = "confidence";
  confidence.textContent = pct(result.confidence);
  const label = document.createElement("small");
  label.textContent = `confidence at issue ${fmt(state.stage)}`;
  confidence.append(label);
  const counts = document.createElement("div");
  counts.className = "entity-count";
  counts.innerHTML = `<b>${result.entities_found}</b> entities known · <b>${result.entities_unknown}</b> unknown`;
  head.append(confidence, counts);
  output.append(head);

  if (!result.teams.length) {
    const note = document.createElement("p");
    note.className = "result-note";
    note.textContent = `No entity in this issue is in the graph as of issue ${fmt(state.stage)}. Add a component, file path or error message, or move the slider later.`;
    output.append(note);
    return;
  }

  const list = document.createElement("ol");
  list.className = "team-list";
  result.teams.forEach((team) => {
    const row = document.createElement("li");
    row.className = "team-row";
    const line = document.createElement("div");
    line.className = "team-line";
    const name = document.createElement("span");
    name.className = "team-name";
    name.textContent = team.team;
    const track = document.createElement("div");
    track.className = "share-track";
    const fill = document.createElement("div");
    fill.className = "share-fill";
    fill.style.width = "0%";
    track.append(fill);
    const share = document.createElement("span");
    share.className = "share-value";
    share.textContent = pct(team.share);
    line.append(name, track, share);
    row.append(line, renderPath(team.path));
    list.append(row);
    requestAnimationFrame(() => requestAnimationFrame(() => (fill.style.width = `${Math.max(2, team.share * 100)}%`)));
  });
  output.append(list);
}

function renderRouteError(error) {
  const output = $("#route-result");
  output.innerHTML = "";
  const note = document.createElement("p");
  note.className = "result-note is-error";
  const [title, detail] = errorCopy(error);
  const strong = document.createElement("strong");
  strong.textContent = `${title}. `;
  const body = document.createElement("span");
  body.innerHTML = detail;
  note.append(strong, body);
  output.append(note);
}

async function routeIssue() {
  const title = $("#issue-title").value.trim();
  const output = $("#route-result");
  if (!title) {
    output.innerHTML = "";
    const note = document.createElement("p");
    note.className = "result-note";
    note.textContent = "Add a title to route the issue.";
    output.append(note);
    $("#issue-title").focus();
    return;
  }
  const seq = ++state.routeSeq;
  const button = $("#route-btn");
  button.disabled = true;
  button.textContent = "Routing";
  try {
    const result = await api("/route", {
      method: "POST",
      body: JSON.stringify({ title, body: $("#issue-body").value, as_of: state.stage }),
    });
    if (seq === state.routeSeq) renderRoute(result);
  } catch (error) {
    if (seq === state.routeSeq) renderRouteError(error);
  } finally {
    if (seq === state.routeSeq) {
      button.disabled = false;
      button.textContent = "Route issue";
    }
  }
}

function renderPresets() {
  const container = $("#presets");
  PRESETS.forEach((preset) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "preset";
    button.textContent = preset.label;
    button.addEventListener("click", () => {
      $("#issue-title").value = preset.title;
      $("#issue-body").value = preset.body;
      routeIssue();
    });
    container.append(button);
  });
}

function graphStyle() {
  const ink = token("--ink");
  const ink2 = token("--ink-2");
  const muted = token("--muted");
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
        "text-background-padding": 2,
        "text-background-shape": "roundrectangle",
      },
    },
    {
      selector: "node.entity",
      style: { width: 16, height: 16, "background-color": token("--entity-fill"), "border-width": 2, "border-color": ink2 },
    },
    {
      selector: "node.focus",
      style: { width: 28, height: 28, "background-color": token("--baton"), "border-width": 4, "border-color": token("--baton-soft"), "font-size": 13, "font-weight": 700 },
    },
    {
      selector: "node.team",
      style: {
        shape: "round-rectangle",
        width: "label",
        height: 24,
        padding: 8,
        "background-color": token("--team-fill"),
        color: token("--team-ink"),
        "text-valign": "center",
        "text-margin-y": 0,
        "text-background-opacity": 0,
        "font-weight": 600,
      },
    },
    {
      selector: "node.issue",
      style: { width: 8, height: 8, "background-color": token("--issue-fill"), "font-size": 9, color: muted, "text-margin-y": 3 },
    },
    {
      selector: "edge",
      style: {
        "curve-style": "bezier",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.8,
        width: 1.5,
        "line-color": token("--history"),
        "target-arrow-color": token("--history"),
      },
    },
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
        "text-background-padding": 2,
        "text-background-shape": "roundrectangle",
      },
    },
    {
      selector: "edge.shortcut",
      style: { "line-color": token("--shortcuts"), "target-arrow-color": token("--shortcuts") },
    },
    {
      selector: "edge.merged",
      style: {
        width: 3,
        "line-style": "dashed",
        "line-dash-pattern": [6, 4],
        "line-color": token("--merging"),
        "target-arrow-shape": "none",
      },
    },
    { selector: "node.entity:active, node.entity:selected", style: { "overlay-opacity": 0 } },
  ];
}

function ensureGraph() {
  if (state.cy) return state.cy;
  state.cy = cytoscape({
    container: $("#graph"),
    style: graphStyle(),
    minZoom: 0.4,
    maxZoom: 2.5,
    wheelSensitivity: 0.2,
    autoungrabify: false,
    boxSelectionEnabled: false,
  });
  state.cy.on("tap", "node.entity", (event) => {
    const name = event.target.data("name");
    if (event.target.hasClass("focus")) return;
    $("#graph-entity").value = name;
    loadGraph(name);
  });
  state.cy.on("mouseover", "node.entity", () => ($("#graph").style.cursor = "pointer"));
  state.cy.on("mouseout", "node.entity", () => ($("#graph").style.cursor = ""));
  return state.cy;
}

function graphElements(graph, focusName) {
  const focus = graph.nodes.find((node) => node.name.toLowerCase() === focusName.toLowerCase());
  const mergedWithFocus = new Set();
  const seenPairs = new Set();
  const edges = [];
  graph.links.forEach((link, i) => {
    if (link.type === "SAME_AS") {
      const pair = [link.source, link.target].sort().join("|");
      if (seenPairs.has(pair)) return;
      seenPairs.add(pair);
      if (focus && (link.source === focus.id || link.target === focus.id)) mergedWithFocus.add(link.source === focus.id ? link.target : link.source);
    }
    const classes = link.type === "ROUTES_TO" ? (link.shortcut ? "learned shortcut" : "learned") : link.type === "SAME_AS" ? "merged" : "history";
    edges.push({
      group: "edges",
      data: {
        id: `e${i}`,
        source: String(link.source),
        target: String(link.target),
        width: 1 + Math.min(Number(link.strength) || 0, 4) * 1.1,
        strengthLabel: (Number(link.strength) || 0).toFixed(1),
      },
      classes,
    });
  });
  const column = (node) => (node.label === "Team" ? 2 : node.label === "Issue" ? 1 : 0);
  const teamRank = new Map();
  graph.links
    .filter((link) => link.type === "ROUTES_TO" && focus && link.source === focus.id)
    .sort((a, b) => b.strength - a.strength)
    .forEach((link) => teamRank.set(link.target, teamRank.size));
  graph.nodes.filter((node) => node.label === "Team" && !teamRank.has(node.id)).forEach((node) => teamRank.set(node.id, teamRank.size));
  const anchor = (node) => {
    if (node.label === "Team") return teamRank.get(node.id);
    const out = graph.links.filter((link) => link.source === node.id && teamRank.has(link.target));
    const strongest = out.sort((a, b) => b.strength - a.strength)[0];
    if (strongest) return teamRank.get(strongest.target);
    const owner = graph.links.find((link) => link.source === node.id && link.type === "OWNED_BY");
    return owner ? teamRank.get(owner.target) ?? 0 : 0;
  };
  const priority = (node) => (focus && node.id === focus.id ? 0 : mergedWithFocus.has(node.id) ? 1 : 2);
  const columns = [[], [], []];
  graph.nodes.forEach((node) => columns[column(node)].push(node));
  const positions = new Map();
  const gap = 66;
  columns.forEach((list, c) => {
    list.sort((a, b) => anchor(a) - anchor(b) || priority(a) - priority(b) || a.name.localeCompare(b.name));
    list.forEach((node, i) => positions.set(node.id, { x: c * (window.innerWidth < 640 ? 200 : 360), y: (i - (list.length - 1) / 2) * gap }));
  });
  const nodes = graph.nodes.map((node) => ({
    group: "nodes",
    data: { id: String(node.id), name: node.name },
    position: positions.get(node.id),
    classes: [node.label.toLowerCase(), focus && node.id === focus.id ? "focus" : ""].join(" ").trim(),
  }));
  return [...nodes, ...edges];
}

async function loadGraph(entity) {
  const name = entity.trim();
  const status = $("#graph-state");
  if (!name) {
    setState(status, "empty", "Pick an entity", "Type a component, file path or word, such as <code>kubelet</code>.");
    return;
  }
  setState(status, "loading", `Loading the graph around ${name}`);
  try {
    const graph = await api(`/graph?entity=${encodeURIComponent(name)}`);
    const cy = ensureGraph();
    cy.elements().remove();
    if (!graph.nodes?.length) {
      const safe = name.replace(/[<>&"]/g, "");
      setState(status, "empty", `${safe} is not in the graph`, "Try <code>kubelet</code>, <code>csi</code> or <code>kube-apiserver</code>. Entities need at least 3 learning issues.");
      return;
    }
    setState(status, null);
    cy.add(graphElements(graph, name));
    cy.fit(undefined, 48);
    if (cy.zoom() > 1.15) {
      cy.zoom(1.15);
      cy.center();
    }
  } catch (error) {
    if (state.cy) state.cy.elements().remove();
    setState(status, "error", ...errorCopy(error));
  }
}

function bindEvents() {
  $("#theme-toggle").addEventListener("click", cycleTheme);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
  document.querySelectorAll(".seg").forEach((button) => {
    button.addEventListener("click", () => {
      state.metric = button.dataset.metric;
      document.querySelectorAll(".seg").forEach((b) => {
        b.classList.toggle("is-on", b === button);
        b.setAttribute("aria-pressed", String(b === button));
      });
      if (state.chart) renderChart();
    });
  });
  let debounce;
  $("#stage-slider").addEventListener("input", (event) => {
    setStage(Number(event.target.value));
    clearTimeout(debounce);
    if ($("#issue-title").value.trim() && $("#route-result").childElementCount) debounce = setTimeout(routeIssue, 120);
  });
  $("#route-form").addEventListener("submit", (event) => {
    event.preventDefault();
    routeIssue();
  });
  $("#graph-form").addEventListener("submit", (event) => {
    event.preventDefault();
    loadGraph($("#graph-entity").value);
  });
}

function init() {
  applyTheme();
  renderPresets();
  bindEvents();
  setStage(STAGES.indexOf(state.stage));
  loadStats();
  loadCurve();
  loadGraph($("#graph-entity").value);
}

init();
