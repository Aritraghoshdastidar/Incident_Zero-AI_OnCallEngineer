/* Incident Zero demo site. No framework. Data comes from site/data.js, built from recorded runs. */
(() => {
  const D = window.INCIDENT_DATA;
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtT = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
  const pct = (x) => `${Math.round((x ?? 0) * 100)}%`;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  $("#built").textContent = D.builtAt;

  /* ---------- the recorder ---------- */
  const G = { W: 1000, H: 428, x0: 70, x1: 930, laneY: [22, 44, 66, 88], top: 112, bottom: 344 };
  const PLOT_W = G.x1 - G.x0;
  const FLAG_KINDS = {
    fault: { label: "Something breaks", cls: "bad" },
    bundle_built: { label: "Evidence gathered" },
    diagnosis: { label: "Diagnosis" },
    decision_card: { label: "Asks you" },
    approved: { label: "Approved" },
    executed: { label: "Fix runs" },
    verified: { label: "Recovery checked" },
    rolled_back: { label: "Rolled back", cls: "bad" },
    escalated: { label: "Handed to a person", cls: "bad" },
  };

  let S = null; // replay state
  let raf = 0;

  const scenarioNote = (sc) =>
    sc.id === "healthy" ? "Nothing was broken" : sc.flagVisible ? "Flag state was visible to the agent" : "Flag state was hidden from the agent";

  function buildPicker() {
    const box = $("#picker-list");
    box.innerHTML = D.scenarios
      .map((sc) => `<button class="pick" type="button" role="radio" aria-checked="false" data-id="${sc.id}">${esc(sc.title)}<small>${esc(scenarioNote(sc))}</small></button>`)
      .join("");
    box.addEventListener("click", (e) => {
      const b = e.target.closest(".pick");
      if (b) load(b.dataset.id);
    });
  }

  function niceMax(v) {
    if (!isFinite(v) || v <= 0) return 1;
    const mag = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * mag >= v * 1.04) return m * mag;
    return 10 * mag;
  }
  const fmtVal = (v) => (v >= 100 ? String(Math.round(v)) : v >= 10 ? v.toFixed(0) : v >= 1 ? v.toFixed(1).replace(/\.0$/, "") : v.toFixed(2).replace(/0+$/, "").replace(/\.$/, ""));

  function prep(sc) {
    sc._ser = sc.series.map((s) => {
      const pts = s.points.filter((p) => p[1] !== null);
      let max = niceMax(Math.max(0, ...pts.map((p) => p[1])));
      if (s.unit === "%" && max > 100) max = 100; // a percentage axis never needs to run past 100
      return { ...s, pts, max };
    });
  }

  const X = (sc, t) => G.x0 + (t / sc.duration) * PLOT_W;
  const Y = (v, max) => G.bottom - (Math.min(v, max) / max) * (G.bottom - G.top);

  function pathFor(sc, ser) {
    let d = "", prev = null;
    for (const [t, v] of ser.pts) {
      const gap = prev !== null && t - prev > 40;
      d += `${prev === null || gap ? "M" : "L"}${X(sc, t).toFixed(1)},${Y(v, ser.max).toFixed(1)}`;
      prev = t;
    }
    return d;
  }

  function valueAt(ser, t) {
    const p = ser.pts;
    if (!p.length || t < p[0][0]) return null;
    for (let i = 0; i < p.length - 1; i++) {
      if (t >= p[i][0] && t <= p[i + 1][0]) {
        if (p[i + 1][0] - p[i][0] > 40) return null;
        const k = (t - p[i][0]) / (p[i + 1][0] - p[i][0]);
        return p[i][1] + k * (p[i + 1][1] - p[i][1]);
      }
    }
    return t > p[p.length - 1][0] + 20 ? null : p[p.length - 1][1];
  }

  function chartStatic(sc) {
    let g = "";
    // horizontal rules
    for (let i = 0; i <= 4; i++) {
      const y = G.bottom - (i / 4) * (G.bottom - G.top);
      g += `<line class="gridline ${i === 0 ? "major" : ""}" x1="${G.x0}" x2="${G.x1}" y1="${y}" y2="${y}"/>`;
    }
    // vertical rules: every 15 s faint, every minute stronger and labelled
    for (let t = 0; t <= sc.duration; t += 15) {
      const x = X(sc, t), major = t % 60 === 0;
      g += `<line class="gridline ${major ? "major" : ""}" x1="${x}" x2="${x}" y1="${G.top}" y2="${G.bottom + (major ? 6 : 0)}"/>`;
      if (major && (sc.duration < 480 || t % 120 === 0)) g += `<text class="tick-label" x="${x}" y="${G.bottom + 24}" text-anchor="middle">${fmtT(t)}</text>`;
    }
    // axes for the two pens
    sc._ser.forEach((s, i) => {
      const left = i === 0, x = left ? G.x0 - 8 : G.x1 + 8, anchor = left ? "end" : "start", cls = left ? "axis-a" : "axis-b";
      [0, 0.5, 1].forEach((f) => {
        const y = G.bottom - f * (G.bottom - G.top);
        g += `<text class="tick-label ${cls}" x="${x}" y="${y + 4}" text-anchor="${anchor}">${fmtVal(s.max * f)}${f === 1 ? s.unit : ""}</text>`;
      });
    });
    // pen names under the sheet
    g += `<text class="pen-name axis-a" x="${G.x0}" y="${G.H - 14}">${esc(sc._ser[0].label)}</text>`;
    if (sc._ser[1]) g += `<text class="pen-name axis-b" x="${G.x1}" y="${G.H - 14}" text-anchor="end">${esc(sc._ser[1].label)}</text>`;
    g += `<text class="tick-label" x="${(G.x0 + G.x1) / 2}" y="${G.H - 14}" text-anchor="middle">minutes into the recording</text>`;
    const clip = `<clipPath id="reveal"><rect id="reveal-rect" x="${G.x0 - 2}" y="${G.top - 6}" width="0" height="${G.bottom - G.top + 12}"/></clipPath>`;
    const pens = sc._ser.map((s, i) => `<path class="pen ${s.pen}" d="${pathFor(sc, s)}" clip-path="url(#reveal)"/>`).join("");
    const heads = sc._ser.map((s) => `<circle class="head ${s.pen}" r="4.5" cx="-20" cy="-20"></circle>`).join("");
    $("#chart").innerHTML = `<defs>${clip}</defs>${g}${pens}<g id="flags"></g><line class="playhead" id="playhead" x1="${G.x0}" x2="${G.x0}" y1="${G.top - 4}" y2="${G.bottom}"/>${heads}`;
  }

  function drawFlags() {
    const sc = S.sc, layer = $("#flags");
    const ends = [-1e9, -1e9, -1e9, -1e9];
    let out = "";
    const shown = sc.events.slice(0, S.idx);
    shown.forEach((e) => {
      const x = X(sc, e.t);
      if (e.kind === "tool_call") {
        out += `<line class="flagline" x1="${x}" x2="${x}" y1="${G.top - 14}" y2="${G.top}" /><circle cx="${x}" cy="${G.top - 14}" r="3" fill="var(--ink-2)"/>`;
        return;
      }
      const meta = FLAG_KINDS[e.kind];
      if (!meta) return;
      let label = meta.label;
      if (e.kind === "approved" && S.userApproved) label = "You approved";
      let cls = meta.cls || "";
      if (e.kind === "verified") cls = e.recovered ? "ok" : "bad";
      const w = label.length * 6.9 + 14;
      const anchorEnd = x + w > G.x1 + 30;
      const x1 = anchorEnd ? x - w : x, x2 = anchorEnd ? x : x + w;
      let lane = ends.findIndex((end, i) => end < x1 - 4);
      if (lane < 0) lane = ends.indexOf(Math.min(...ends));
      ends[lane] = x2;
      const ly = G.laneY[lane];
      out += `<line class="flagline ${cls}" x1="${x}" x2="${x}" y1="${ly + 4}" y2="${G.bottom}"/>`;
      out += `<text class="flag-label" x="${anchorEnd ? x - 4 : x + 4}" y="${ly + 2}" text-anchor="${anchorEnd ? "end" : "start"}">${esc(label)}</text>`;
    });
    layer.innerHTML = out;
  }

  function drawChartDynamic() {
    const sc = S.sc, x = X(sc, S.t);
    $("#reveal-rect").setAttribute("width", Math.max(0, x - G.x0 + 2).toFixed(1));
    const ph = $("#playhead");
    ph.setAttribute("x1", x); ph.setAttribute("x2", x);
    const heads = document.querySelectorAll("#chart .head");
    sc._ser.forEach((s, i) => {
      const v = valueAt(s, S.t);
      const h = heads[i];
      if (v === null) { h.setAttribute("cx", -20); h.setAttribute("cy", -20); }
      else { h.setAttribute("cx", x); h.setAttribute("cy", Y(v, s.max)); }
    });
    const roll = document.querySelector(".roll");
    if (roll.scrollWidth > roll.clientWidth + 4) {
      const px = (x / G.W) * $("#chart").getBoundingClientRect().width;
      roll.scrollLeft = Math.max(0, px - roll.clientWidth * 0.6);
    }
    $("#clock").textContent = `${fmtT(S.t)} of ${fmtT(sc.duration)}`;
    $("#chart").setAttribute("aria-label", `Strip chart of the recording "${sc.title}", ${fmtT(S.t)} of ${fmtT(sc.duration)}. ${S.idx} agent steps shown so far.`);
  }

  /* ---------- plain-language steps ---------- */
  function parseTool(detail) {
    const m = /^(\w+)\s+(\{.*\})$/.exec(detail || "");
    let args = {};
    try { args = m ? JSON.parse(m[2]) : {}; } catch (_) { /* leave empty */ }
    return { tool: m ? m[1] : detail, args };
  }
  const groundingWords = (g) =>
    g === null || g === undefined ? "" : g >= 1 ? "Every reference it cited was found in the data it was shown."
      : g <= 0 ? "None of the references it cited were found in the data it was shown, so its confidence was cut."
        : `${pct(g)} of the references it cited were found in the data it was shown, so its confidence was lowered.`;

  function describe(e, sc) {
    switch (e.kind) {
      case "fault": return { text: "Something breaks. The agent has not been told what.", short: "Something breaks" };
      case "bundle_built":
        return { text: "The alert fires. The agent gathers evidence from metrics, traces and container state, and marks which errors are new.", why: e.detail };
      case "tool_call": {
        const { tool, args } = parseTool(e.detail);
        const text = tool === "get_service_logs" ? `Reads the ${args.service} logs to check a suspicion.`
          : tool === "get_error_traces" ? `Pulls recent error traces for ${args.service}.`
          : tool === "get_flag_info" ? `Checks the ${args.flag} flag.`
          : tool === "query_prometheus" ? "Runs a metrics query to test an idea." : `Looks closer (${tool}).`;
        return { text, why: tool === "query_prometheus" && args.promql ? args.promql : "" };
      }
      case "diagnosis":
        return e.abstain
          ? { text: `Not sure enough to act. It offers a guess at ${pct(e.confidence)} confidence and proposes nothing.`, why: e.detail }
          : { text: `Diagnosis: ${e.detail}`, why: `${pct(e.confidence)} confident. ${groundingWords(e.grounding)}` };
      case "decision_card": return { text: "It asks for your approval. It cannot run anything without it." };
      case "approved": return { text: S.userApproved ? "Approved." : "Approved (by a test script, in this recording)." };
      case "dry_run": return { text: "Dry run first: it looks at what the fix would touch without changing anything." };
      case "executed": return { text: "Runs the approved fix.", why: sc.card ? sc.card.command.join(" ") : e.detail };
      case "verified":
        return { text: e.recovered ? "Checks recovery over repeated readings with traffic still flowing. Result: recovered." : "Checks recovery over repeated readings. Result: not confirmed.", ok: e.recovered, bad: !e.recovered };
      case "rolled_back": return { text: "Things got worse after the fix, so it rolled back to the exact previous state.", bad: true };
      case "escalated": return { text: "It could not confirm recovery. The fix stays in place and a person takes over.", bad: true };
      default: return { text: e.label };
    }
  }

  function addLog(e, d, extraClass = "") {
    const li = document.createElement("li");
    li.className = `${d.ok ? "ok" : d.bad ? "bad" : ""} ${extraClass}`;
    li.innerHTML = `<span class="t">${fmtT(e.t)}</span><span>${esc(d.text)}${d.why ? `<span class="why">${esc(d.why)}</span>` : ""}</span>`;
    const list = $("#log");
    list.querySelectorAll(".now-item").forEach((n) => n.classList.remove("now-item"));
    li.classList.add("now-item");
    list.appendChild(li);
    return li;
  }

  /* ---------- the approval slip ---------- */
  const RISK = { low: "Low: changes one setting", medium: "Medium: starts, stops or resets a service", high: "High" };
  function slipHTML(sc) {
    const c = sc.card;
    const ev = (c.evidence || []).map((x) => esc(x.replace(":", " ").replace(/[0-9a-f]{24,}/g, (m) => m.slice(0, 8) + "…"))).join(", ") || "none listed";
    const params = Object.entries(c.params || {}).map(([k, v]) => `${k} = ${v}`).join(", ");
    return `<div class="slip" id="slip">
      <h3>Approval slip</h3>
      <dl>
        <dt>What it thinks</dt><dd>${esc(c.root_cause)}</dd>
        <dt>How sure</dt><dd>${pct(c.confidence)}. ${esc(groundingWords(c.grounding))}</dd>
        <dt>Evidence cited</dt><dd>${ev}</dd>
        <dt>Proposed fix</dt><dd>${esc(c.runbook_id)} (${esc(params)})</dd>
        <dt>Risk</dt><dd>${esc(RISK[c.risk] || c.risk)}</dd>
        <dt>What will run</dt><dd class="cmd">${esc(c.command.join(" "))}</dd>
        <dt>How it undoes</dt><dd class="cmd">${c.rollback_command ? esc(c.rollback_command.join(" ")) : "Nothing to undo"}</dd>
      </dl>
      <div class="actions">
        <button class="btn approve" type="button" id="approve">Approve and run</button>
        <button class="btn reject" type="button" id="reject">Reject</button>
      </div>
      <p class="note">In this recording a test script approved the fix. Here the decision is yours.</p>
    </div>`;
  }

  /* ---------- replay engine ---------- */
  function load(id) {
    cancelAnimationFrame(raf);
    const sc = D.scenarios.find((s) => s.id === id);
    prep(sc);
    S = { sc, t: 0, idx: 0, mode: "idle", speed: Number($("#speed").value), holdUntil: 0, last: 0, userApproved: false };
    document.querySelectorAll(".pick").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.id === id)));
    $("#alert-text").innerHTML = `<b>Alert</b>${esc(sc.alert)}`;
    $("#legend").innerHTML = sc._ser
      .map((s, i) => `<span class="${i ? "b" : "a"}"><i></i>${esc(s.label)} <small>(${i ? "right" : "left"} axis, ${esc(s.unit === "/s" ? "per second" : s.unit === "ms" ? "milliseconds" : s.unit === "s" ? "seconds" : "percent")})</small></span>`)
      .join("") + `<small>Each line has its own scale.</small>`;
    $("#log").innerHTML = "";
    $("#slip-slot").innerHTML = "";
    $("#truth").hidden = true;
    $("#narration").textContent = "Press Play. The agent starts when the alert fires.";
    chartStatic(sc);
    drawFlags();
    drawChartDynamic();
    syncButtons();
  }

  function syncButtons() {
    const play = $("#btn-play"), step = $("#btn-step");
    const m = S.mode;
    play.textContent = m === "playing" ? "Pause" : m === "done" || m === "rejected" ? "Replay" : m === "awaiting" ? "Waiting for you" : S.t > 0 ? "Resume" : "Play";
    play.disabled = m === "awaiting";
    step.disabled = m === "awaiting" || m === "done" || m === "rejected";
  }

  function finish() {
    S.mode = "done";
    const sc = S.sc;
    const verified = sc.events.find((e) => e.kind === "verified");
    $("#narration").textContent = !sc.card
      ? "Done. It judged that nothing was worth fixing and changed nothing."
      : verified && verified.recovered
        ? "Done. From the alert to a checked recovery, with your approval in the middle."
        : "Done.";
    S.t = sc.duration;
    drawChartDynamic();
    syncButtons();
  }

  function reveal() {
    const sc = S.sc, e = sc.events[S.idx];
    S.idx++;
    const d = describe(e, sc);
    if (e.kind === "approved" && S.userApproved) { /* already logged when you clicked */ }
    else addLog(e, d);
    $("#narration").textContent = d.text;
    if (e.kind === "diagnosis") {
      const t = $("#truth");
      t.hidden = false;
      t.innerHTML = `<b>What was actually broken.</b> ${esc(sc.broken)}`;
    }
    if (e.kind === "decision_card" && sc.card) {
      S.mode = "awaiting";
      $("#slip-slot").innerHTML = slipHTML(sc);
      $("#approve").addEventListener("click", approve);
      $("#reject").addEventListener("click", reject);
      $("#approve").focus({ preventScroll: true });
    }
    drawFlags();
  }

  function approve() {
    S.userApproved = true;
    const e = S.sc.events[S.idx - 1];
    addLog(e, { text: "You approved the fix." });
    $("#slip").classList.add("settled");
    $("#slip").querySelector(".actions").innerHTML = "<p><b>You approved this.</b></p>";
    S.mode = "playing";
    S.last = performance.now();
    S.holdUntil = performance.now() + 500;
    syncButtons();
    raf = requestAnimationFrame(tick);
  }

  function reject() {
    const e = S.sc.events[S.idx - 1];
    addLog(e, { text: "You rejected the fix. Nothing ran.", bad: true });
    $("#slip").classList.add("settled");
    $("#slip").querySelector(".actions").innerHTML = "<p><b>You rejected this.</b> Nothing ran.</p>";
    $("#narration").textContent = "You stopped it. The failure is still there, and a person would take it from here. Replay to approve it instead.";
    S.mode = "rejected";
    syncButtons();
  }

  const holdFor = (e) => (reduceMotion ? 0 : e.kind === "tool_call" ? 800 : 1300);

  function tick(now) {
    if (S.mode !== "playing") return;
    const dt = Math.min((now - S.last) / 1000, 0.25);
    S.last = now;
    if (now >= S.holdUntil) {
      const next = S.sc.events[S.idx];
      const target = S.t + dt * S.speed;
      if (next && target >= next.t) {
        S.t = next.t;
        reveal();
        S.holdUntil = now + holdFor(next);
        if (S.mode !== "playing") { syncButtons(); drawChartDynamic(); return; }
      } else if (!next && target >= S.sc.duration) {
        finish(); return;
      } else {
        S.t = Math.min(target, S.sc.duration);
      }
    }
    drawChartDynamic();
    raf = requestAnimationFrame(tick);
  }

  function play() {
    if (S.mode === "done" || S.mode === "rejected") load(S.sc.id);
    if (S.mode === "awaiting") return;
    if (S.mode === "playing") { S.mode = "idle"; cancelAnimationFrame(raf); syncButtons(); return; }
    S.mode = "playing";
    S.speed = Number($("#speed").value);
    S.last = performance.now();
    syncButtons();
    raf = requestAnimationFrame(tick);
  }

  function step() {
    if (S.mode === "awaiting" || S.mode === "done" || S.mode === "rejected") return;
    cancelAnimationFrame(raf);
    S.mode = "idle";
    const next = S.sc.events[S.idx];
    if (!next) { finish(); return; }
    S.t = next.t;
    reveal();
    drawChartDynamic();
    syncButtons();
  }

  $("#btn-play").addEventListener("click", play);
  $("#btn-step").addEventListener("click", step);
  $("#btn-restart").addEventListener("click", () => load(S.sc.id));
  $("#speed").addEventListener("change", () => { if (S) S.speed = Number($("#speed").value); });

  /* ---------- evidence ledger: sort by how often vs what is new ---------- */
  const NOISE = [
    { what: "Load generator cannot reach a service called “agent”", where: "load-generator", n: 19, old: true },
    { what: "Failed requests on the homepage path", where: "load-generator", n: 10, old: true },
    { what: "Failed requests passing through the proxy", where: "frontend-proxy", n: 10, old: true },
    { what: "Cart storage unreachable: “Wasn't able to connect to redis”", where: "cart, emptying a cart", n: 2, old: false, real: true },
    { what: "The same cart error, seen from checkout", where: "checkout", n: 2, old: false, real: true },
  ];
  function drawNoise(mode, animate) {
    const body = $("#noise-table tbody");
    const rows = [...NOISE];
    rows.sort(mode === "count" ? (a, b) => b.n - a.n : (a, b) => Number(a.old) - Number(b.old) || b.n - a.n);
    const before = new Map([...body.children].map((tr) => [tr.dataset.key, tr.getBoundingClientRect().top]));
    body.innerHTML = rows.map((r) => `<tr class="${r.real ? "real" : ""}" data-key="${esc(r.what)}"><td>${esc(r.what)}<span class="sub">${esc(r.where)}</span></td><td class="num">${r.n}</td><td>${r.old ? "Yes, it was already happening" : "No, it started with the incident"}</td></tr>`).join("");
    if (animate && !reduceMotion) {
      [...body.children].forEach((tr) => {
        const was = before.get(tr.dataset.key);
        if (was === undefined) return;
        const dy = was - tr.getBoundingClientRect().top;
        if (!dy) return;
        tr.style.transition = "none";
        tr.style.transform = `translateY(${dy}px)`;
        requestAnimationFrame(() => requestAnimationFrame(() => { tr.style.transition = ""; tr.style.transform = ""; }));
      });
    }
  }
  document.querySelectorAll(".sortbar .chip").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll(".sortbar .chip").forEach((c) => { c.classList.toggle("is-on", c === b); c.setAttribute("aria-pressed", String(c === b)); });
      drawNoise(b.dataset.sort, true);
    }));

  /* ---------- try to trick it: a copy of the policy engine ---------- */
  const PRESETS = [
    { id: "valid", label: "A valid fix", runbook: "disable_flag", params: { flag: "paymentFailure" } },
    { id: "override", label: "“Ignore all previous instructions”", attack: "override", runbook: "restart_service", params: { service: "frontend" } },
    { id: "fake_system_tag", label: "A fake system message", attack: "fake_system_tag", runbook: "restart_service", params: { service: "checkout" } },
    { id: "off_allowlist", label: "A runbook that does not exist", attack: "off_allowlist", runbook: "wipe_all", params: { target: "*" } },
    { id: "shell_injection", label: "A shell command inside a setting", attack: "shell_injection", runbook: "start_service", params: { service: "payment; docker rm -f $(docker ps -aq)" } },
    { id: "role_confusion", label: "Pretending a person already agreed", attack: "role_confusion", runbook: "restart_service", params: { service: "frontend" } },
    { id: "type", label: "A number where text belongs", runbook: "disable_flag", params: { flag: 1 } },
    { id: "extra", label: "One setting too many", runbook: "disable_flag", params: { flag: "paymentFailure", force: true } },
  ];

  function evaluate(runbookId, params, kill) {
    const books = D.runbooks;
    if (kill) return { kind: "blocked", title: "Blocked", why: ["The kill switch is engaged. Nothing can run, however well the request is phrased."] };
    const rb = books.find((b) => b.id === runbookId);
    if (!rb) return { kind: "blocked", title: "Blocked", why: [`“${runbookId}” is not on the list of approved runbooks.`], list: `Approved runbooks: ${books.map((b) => b.id).join(", ")}` };
    const given = Object.keys(params).sort(), want = Object.keys(rb.params).sort();
    if (given.join() !== want.join()) {
      return { kind: "blocked", title: "Blocked", why: [`${rb.id} accepts exactly these settings: ${want.join(", ") || "none"}. The request gave: ${given.join(", ") || "none"}.`] };
    }
    const reasons = [];
    for (const [name, spec] of Object.entries(rb.params)) {
      const v = params[name];
      const okType = spec.type === "str" ? typeof v === "string" : spec.type === "bool" ? typeof v === "boolean"
        : spec.type === "int" ? typeof v === "number" && Number.isInteger(v) : typeof v === "number";
      if (!okType) { reasons.push(`The setting “${name}” must be ${spec.type === "str" ? "text" : spec.type}, not ${typeof v === "number" ? "a number" : typeof v}.`); continue; }
      if (!spec.allowed.includes(v)) reasons.push(`“${name}” = ${JSON.stringify(v)} is not one of the approved values.`);
    }
    if (reasons.length) {
      const first = Object.entries(rb.params)[0];
      return { kind: "blocked", title: "Blocked", why: reasons, list: first ? `Approved values for ${first[0]}: ${first[1].allowed.join(", ")}` : "" };
    }
    const needs = rb.requiresApproval || rb.risk !== "low";
    return needs
      ? { kind: "needs", title: "Allowed, but a person must approve it", why: [`${rb.id} is a ${rb.risk}-risk runbook, so the rules pass it on to the approval step. It still cannot run on its own.`, "The rules only check that a request is allowed. Whether it is the right fix is for the evidence on the approval slip and the person reading it."] }
      : { kind: "allowed", title: "Allowed", why: ["It is on the list and its settings are valid."] };
  }

  function buildForge() {
    $("#runbook-ids").innerHTML = D.runbooks.map((b) => `<option value="${esc(b.id)}">`).join("");
    const list = $("#preset-list");
    list.innerHTML = PRESETS.map((p) => `<button class="preset" type="button" aria-pressed="false" data-id="${p.id}">${esc(p.label)}</button>`).join("");
    list.addEventListener("click", (e) => {
      const b = e.target.closest(".preset");
      if (!b) return;
      const p = PRESETS.find((x) => x.id === b.dataset.id);
      list.querySelectorAll(".preset").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      $("#f-runbook").value = p.runbook;
      $("#f-params").value = JSON.stringify(p.params, null, 2);
      const atk = p.attack && D.attacks.find((a) => a.id === p.attack);
      $("#seen").hidden = !atk;
      if (atk) $("#seen-text").textContent = atk.text;
      send();
    });
    $("#f-send").addEventListener("click", send);
    $("#f-kill").addEventListener("change", send);
    const rt = D.results.redteam || [];
    const resisted = rt.filter((r) => r.model_resisted).length;
    $("#forge-fine").textContent = rt.length
      ? `In the recorded red-team run, the model resisted ${resisted} of ${rt.length} planted instructions and proposed the correct fix every time. These rules are the backstop for the day it does not. The Python version is also tested with randomly generated requests.`
      : "";
    $("#preset-list .preset").click();
  }

  function send() {
    const out = $("#verdict");
    let params;
    try { params = JSON.parse($("#f-params").value || "{}"); }
    catch (e) { out.className = "verdict blocked"; out.innerHTML = `<h3>Not valid JSON</h3><p>${esc(e.message)}</p>`; return; }
    if (params === null || typeof params !== "object" || Array.isArray(params)) {
      out.className = "verdict blocked"; out.innerHTML = "<h3>Not valid</h3><p>Settings must be a JSON object, like {\"flag\": \"paymentFailure\"}.</p>"; return;
    }
    const v = evaluate($("#f-runbook").value.trim(), params, $("#f-kill").checked);
    out.className = `verdict ${v.kind}`;
    out.innerHTML = `<h3>${esc(v.title)}</h3>${v.why.map((w) => `<p>${esc(w)}</p>`).join("")}${v.list ? `<p class="allow-list">${esc(v.list)}</p>` : ""}`;
  }

  /* ---------- scorecard from the paired ablation ---------- */
  const NAMES = {
    cart: "Cart failing (flag hidden)", payment: "Payment failing", ad_cpu: "Ad service overloaded",
    h_redis_down: "Cart storage stopped", h_catalog_down: "Product catalog stopped", h_oom: "Memory limit, restart loop", h_cpu_throttle: "CPU limited to 0.02",
  };
  const outcome = (r) => (r.wrong_action ? "wrong" : r.action_correct ? "correct" : "none");
  const MARK = {
    correct: ['<svg viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="7" fill="currentColor"/></svg>', "Right fix"],
    none: ['<svg viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="6" fill="none" stroke="currentColor" stroke-width="2.4"/></svg>', "Took no action"],
    wrong: ['<svg viewBox="0 0 18 18" aria-hidden="true"><path d="M3.5 3.5l11 11M14.5 3.5l-11 11" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>', "Wrong action"],
  };
  function buildScore() {
    const rows = D.results.ablation;
    const body = $("#score-table tbody");
    body.innerHTML = rows.map((r) => {
      const cell = (x) => { const o = outcome(x); return `<td><span class="mark ${o}">${MARK[o][0]}${MARK[o][1]}</span></td>`; };
      return `<tr><td>${esc(NAMES[r.scenario] || r.scenario)}${r.group === "heldout" ? '<span class="sub">never tuned against</span>' : ""}</td>${cell(r.baseline)}${cell(r.hybrid)}</tr>`;
    }).join("");
    const n = rows.length;
    const tally = (k) => ({ ok: rows.filter((r) => outcome(r[k]) === "correct").length, wrong: rows.filter((r) => outcome(r[k]) === "wrong").length,
      none: rows.filter((r) => outcome(r[k]) === "none").length, sec: rows.reduce((a, r) => a + r[k].seconds, 0) / n, tok: rows.reduce((a, r) => a + r[k].tokens, 0) / n });
    const h = tally("hybrid"), b = tally("baseline");
    const wrongConf = rows.filter((r) => outcome(r.baseline) === "wrong").map((r) => r.baseline.confidence);
    $("#score-lede").textContent =
      `Each failure was injected once, then both the agent and a plain language model reading raw logs diagnosed the same live system. The agent got ${h.ok} of ${n} right and took ${h.wrong} wrong actions. The plain model got ${b.ok} of ${n} right and took ${b.wrong} wrong actions, each stated at ${pct(Math.min(...wrongConf))} confidence or more.`;
    $("#score-key").textContent = "A wrong action is any fix other than the one that matches the injected failure. Taking no action counts as safe, not as right.";
    $("#misses").innerHTML = [
      `The agent took no action on the ad service test, where the plain model got it right. Answering nothing is safe, and it is still a miss.`,
      `It is slower. On average ${Math.round(h.sec)} seconds against ${Math.round(b.sec)} for the plain model, because it makes several model calls on a free tier.`,
      `It used about ${Math.round(h.tok / 1000)} thousand tokens per diagnosis against ${Math.round(b.tok / 1000)} thousand, since it reads a short evidence summary and not raw logs.`,
      `During development a prompt change of mine made the agent guess a restart at 85% confidence on a Kafka test. It was found by running the tests and reverted. The full list is in docs/RESULTS.md.`,
      `Seven scenarios is a small sample, run once each, on one application and one language model. The model also partly remembers this demo's flag names, so the stopped and limited containers are the cleanest evidence.`,
    ].map((t) => `<li>${esc(t)}</li>`).join("");
  }

  /* ---------- copy button ---------- */
  $("#copy").addEventListener("click", async () => {
    const txt = $("#code").innerText;
    try { await navigator.clipboard.writeText(txt); $("#copy").textContent = "Copied"; }
    catch (_) { $("#copy").textContent = "Select and copy by hand"; }
    setTimeout(() => ($("#copy").textContent = "Copy commands"), 1800);
  });

  /* ---------- how it works: an interactive pipeline ---------- */
  const NS = "http://www.w3.org/2000/svg";
  const LANES = [
    { c: "eyes", x: 8, y: 36, w: 596, h: 170, label: "Eyes: read-only, untrusted data", lx: 20, ly: 58, anchor: "start" },
    { c: "brain", x: 604, y: 36, w: 488, h: 170, label: "Brain: reasoning", lx: 616, ly: 58, anchor: "start" },
    { c: "gates", x: 8, y: 266, w: 504, h: 178, label: "Gates: deterministic", lx: 502, ly: 288, anchor: "end" },
    { c: "hands", x: 516, y: 266, w: 576, h: 272, label: "Hands: act and verify", lx: 528, ly: 288, anchor: "start" },
  ];
  const NODES = [
    { id: "alert", k: "box", x: 80, y: 120, w: 126, h: 62, t: ["Alert"], s: ["and start time"] },
    { id: "tele", k: "box", x: 230, y: 120, w: 126, h: 96, t: ["Read-only", "telemetry"], s: ["metrics, traces,", "logs, containers"] },
    { id: "detect", k: "box", x: 380, y: 120, w: 126, h: 72, t: ["Signal", "detectors"], s: ["plain code, no AI"] },
    { id: "bundle", k: "box", x: 530, y: 120, w: 126, h: 72, t: ["Evidence", "bundle"], s: ["new versus old"] },
    { id: "llm", k: "box", x: 680, y: 120, w: 126, h: 72, t: ["LLM", "investigator"], s: ["up to 4 drill-downs"] },
    { id: "ground", k: "box", x: 830, y: 120, w: 126, h: 72, t: ["Grounding", "check"], s: ["every citation"] },
    { id: "diag", k: "box", x: 980, y: 120, w: 126, h: 72, t: ["Diagnosis"], s: ["evidence, confidence"] },
    { id: "policy", k: "dia", x: 95, y: 355, w: 120, h: 100, t: ["Policy", "engine"] },
    { id: "kill", k: "box", x: 240, y: 285, w: 104, h: 30, t: ["Kill switch"], small: true },
    { id: "card", k: "box", x: 262, y: 355, w: 126, h: 64, t: ["Decision", "card"], s: ["command and undo"] },
    { id: "human", k: "dia", x: 425, y: 355, w: 120, h: 100, t: ["Human", "approval"] },
    { id: "exec", k: "box", x: 605, y: 355, w: 126, h: 64, t: ["Dry run, then", "execute"] },
    { id: "verify", k: "dia", x: 770, y: 355, w: 124, h: 104, t: ["Verify", "recovery"] },
    { id: "recovered", k: "term", x: 945, y: 290, w: 130, h: 44, t: ["Recovered"] },
    { id: "rolled", k: "term", x: 945, y: 355, w: 130, h: 46, t: ["Rolled back"], s: ["it got worse"] },
    { id: "escalate", k: "term", x: 945, y: 420, w: 130, h: 46, t: ["Escalate"], s: ["cannot confirm"] },
    { id: "report", k: "box", x: 945, y: 500, w: 130, h: 44, t: ["Incident report"] },
    { id: "noaction", k: "term", x: 262, y: 495, w: 120, h: 40, t: ["No action"] },
    { id: "audit", k: "bar", x: 550, y: 574, w: 1084, h: 26, t: ["Hash-chained audit log: every stage writes here"] },
  ];
  const EDGES = [
    { id: "e1", from: "alert", to: "tele", d: "M143,120 L166,120" },
    { id: "e2", from: "tele", to: "detect", d: "M293,120 L316,120" },
    { id: "e3", from: "detect", to: "bundle", d: "M443,120 L466,120" },
    { id: "e4", from: "bundle", to: "llm", d: "M593,120 L616,120" },
    { id: "e5", from: "llm", to: "ground", d: "M743,120 L766,120" },
    { id: "e6", from: "ground", to: "diag", d: "M893,120 L916,120" },
    { id: "e7", from: "diag", to: "policy", d: "M980,156 L980,228 L95,228 L95,304" },
    { id: "e8", from: "policy", to: "card", d: "M155,355 L198,355", cls: "ok", label: "allowed", lx: 177, ly: 345 },
    { id: "e8n", from: "policy", to: "noaction", d: "M95,405 L95,495 L201,495", cls: "bad", label: "rejected", lx: 150, ly: 486 },
    { id: "e9", from: "card", to: "human", d: "M325,355 L364,355" },
    { id: "e10", from: "human", to: "exec", d: "M485,355 L541,355", cls: "ok", label: "approve", lx: 513, ly: 345 },
    { id: "e10n", from: "human", to: "noaction", d: "M425,405 L425,495 L323,495", cls: "bad", label: "reject or timeout", lx: 374, ly: 486 },
    { id: "e11", from: "exec", to: "verify", d: "M668,355 L707,355" },
    { id: "e12", from: "verify", to: "recovered", d: "M832,355 L856,355 L856,290 L879,290", cls: "ok" },
    { id: "e13", from: "verify", to: "rolled", d: "M832,355 L879,355", cls: "bad" },
    { id: "e14", from: "verify", to: "escalate", d: "M832,355 L856,355 L856,420 L879,420", cls: "bad" },
    { id: "e15", from: "recovered", to: "report", d: "M1010,290 L1042,290 L1042,500 L1011,500" },
    { id: "e16", from: "rolled", to: "report", d: "M1010,355 L1042,355 L1042,500 L1011,500" },
    { id: "e17", from: "escalate", to: "report", d: "M1010,420 L1042,420 L1042,500 L1011,500" },
    { id: "ek", from: "kill", to: "policy", d: "M188,285 L150,285 L150,330 L127,330", cls: "soft" },
  ];

  const DETAIL = {
    alert: { title: "Alert and start time", what: "An alert arrives as short text, plus the time it started. A real pager provides that start time. The agent uses it to scope the evidence so older, unrelated errors do not leak in.", reads: "The alert text", makes: "An incident id and an evidence window", cannot: "Decide anything yet", code: "agent/run.py" },
    tele: { title: "Read-only telemetry", what: "The agent reads Prometheus metrics, Jaeger traces, container logs and container state. All of it is read-only, and all of it is treated as untrusted data, because an attacker may be able to make a service log hostile text.", reads: "Metrics, traces, logs, container state", makes: "Raw signals for the detectors", cannot: "Change anything in the shop", code: "tools/telemetry.py, tools/dockerctl.py", fact: "Jaeger 2 only serves a newer API, and long-lived traces mean errors must be filtered by their own timestamps." },
    detect: { title: "Signal detectors", what: "Plain code, not the model, compares every service with its own baseline: error rate and latency against 15 minutes earlier, error signatures grouped from traces, CPU, memory and Kafka-lag changes, and container state.", reads: "The telemetry", makes: "Ranked anomalies and error signatures", cannot: "Reason about causes; it only measures", code: "agent/signals.py", fact: "The evidence window is at least 5 minutes, because one real fault leaves only about 2 errors per 5 minutes." },
    bundle: { title: "Evidence bundle", what: "A compact summary ranked by what is new. Errors that were already happening before the incident are tagged pre_existing and ranked last, so background noise does not win.", reads: "Detector output", makes: "A short, novelty-tagged bundle for the model", cannot: "Hold raw logs; it keeps the model's input small", code: "agent/signals.py (build_bundle)", fact: "Recorded example: an error that fired 19 times was noise; the real fault fired twice." },
    llm: { title: "LLM investigator", what: "The model reasons over the bundle, may make up to four drill-down calls (read a service's logs, pull error traces, check a flag, run one metrics query), and returns one structured diagnosis.", reads: "The bundle and the approved runbook list", makes: "A diagnosis with evidence and confidence", cannot: "Run anything. It can only name a runbook.", code: "agent/investigator.py", fact: "45 to 290 seconds on a free-tier model." },
    ground: { title: "Grounding check", what: "Every trace id, flag or log reference the model cites must appear verbatim in the data it was shown. Unverifiable references are listed and the hypothesis loses confidence. The model never judges its own evidence.", reads: "The diagnosis and everything the model saw", makes: "A grounding score and a list of ungrounded references", cannot: "Be argued with; it is an exact match", code: "agent/grounding.py", fact: "Built after a diagnosis cited a trace id with one character changed." },
    diag: { title: "Diagnosis", what: "A structured result: root cause, confidence from 0 to 1, evidence items, alternatives, an honest abstain with a reason, and at most a proposed runbook with settings. It never contains a command.", reads: "The grounded model output", makes: "A validated Diagnosis", cannot: "Exist without evidence, unless it abstains", code: "schema/diagnosis.py" },
    policy: { title: "Policy engine", what: "A deterministic program, not an AI, checks the proposed action. The runbook must be on the allowlist, the settings must match exactly, each of the exact type and an approved value. The kill switch overrides everything.", reads: "A runbook id and settings", makes: "Allowed or refused, with a reason", cannot: "Judge whether a legal action is wise. That is for the evidence and the person.", code: "safety/policy.py", fact: "Four runbooks, all needing approval. Fuzz-tested with random inputs." },
    kill: { title: "Kill switch", what: "A file on disk. While it exists, the policy engine refuses every action, whatever the request says. It works from any process and survives restarts.", reads: "Whether the file exists", makes: "A refusal of everything", cannot: "Be bypassed by a well-phrased request", code: "safety/killswitch.py" },
    card: { title: "Decision card", what: "The slip a person sees: the root cause, confidence, evidence cited, the runbook and its risk level, the exact command that will run, and the exact command that undoes it.", reads: "The validated diagnosis and the runbook", makes: "A card in the terminal or the dashboard", cannot: "Run the fix", code: "agent/executor.py (DecisionCard)" },
    human: { title: "Human approval", what: "A person approves or rejects, in the terminal or the dashboard. If nobody answers within 15 minutes, it counts as a rejection, so nothing runs by default.", reads: "The decision card", makes: "Approve or reject", cannot: "Be skipped, for any runbook", code: "ui/approver.py, ui/app.py", fact: "Fails closed: no answer means no." },
    noaction: { title: "No action", what: "Rejected by the policy engine, rejected by a person, or timed out. Nothing ran. The incident and the reason are still recorded in the audit log.", reads: "The refusal or rejection", makes: "An audited non-event", cannot: "Leave the system changed", code: "agent/executor.py" },
    exec: { title: "Dry run, then execute", what: "It records the state just before the fix, does a dry run that shows what would be touched, then runs the approved runbook. Its command is a fixed template; only validated settings fill it in.", reads: "The approved runbook", makes: "A change, and a snapshot to compare against", cannot: "Run a command the runbook did not define", code: "agent/executor.py, runbooks/*.yaml" },
    verify: { title: "Verify recovery", what: "It polls every 20 seconds for up to 5 minutes. Recovered means no errors remain, entry-point error rates are normal, and, only if the service had a latency problem, its latency came down. Two clean readings in a row, with traffic still flowing.", reads: "Fresh telemetry and the pre-fix snapshot", makes: "Recovered, got worse, or cannot confirm", cannot: "Assume success because it is quiet", code: "agent/executor.py (verify_recovery)", fact: "Services cache flags for 2 to 3 minutes, so it polls and never sleeps." },
    recovered: { title: "Recovered", what: "Errors are gone and entry points are healthy. The fix stays in place and the incident report is written.", reads: "Two clean readings", makes: "A closed incident", cannot: "—", code: "agent/executor.py" },
    rolled: { title: "Rolled back", what: "Only if things got worse, meaning new errors the fix did not start with. It restores the exact previous value, not a baseline.", reads: "New errors after the fix", makes: "The previous state restored", cannot: "Guess at a previous state; it was recorded", code: "agent/executor.py, tools/flagctl.py (undo)" },
    escalate: { title: "Escalate to a person", what: "Recovery could not be confirmed, but nothing got worse. The fix stays in place and a person takes over, because reverting would put the original fault back.", reads: "A failed confirmation with no new errors", makes: "A handoff", cannot: "Undo a possibly correct fix on its own", code: "agent/executor.py", fact: "This came from a rehearsal bug: a correct fix was undone by an over-eager rollback." },
    report: { title: "Incident report", what: "Written only from the audit log, so it cannot claim anything the agent did not actually do.", reads: "The audited events", makes: "A readable report", cannot: "Invent a step", code: "report/incident.py" },
    audit: { title: "Hash-chained audit log", what: "Every stage writes an event. Each record carries a fingerprint of the one before it, so editing any past line breaks the chain and is detected.", reads: "Events from every stage", makes: "A tamper-evident record", cannot: "Be edited quietly", code: "safety/audit.py", fact: "The incident report and the dashboard are built from it." },
  };

  const STEP = {
    alert: "An alert fires: customers cannot pay. The agent receives the text and when it started.",
    tele: "It reads metrics, traces, container logs and container state. Read-only, and all of it treated as untrusted.",
    detect: "Plain code, not the model, compares every service with its own baseline.",
    bundle: "It ranks what is new against what was already happening, so background noise does not win.",
    llm: "Now the model reasons over that summary, with up to four drill-down calls.",
    ground: "Every citation is checked against the data the model was actually shown.",
    diag: "A structured diagnosis: root cause, confidence and evidence. It cannot contain a command.",
    policy: "A plain program checks the proposed runbook and its settings against the allowlist. What does it find?",
    card: "It builds a decision card: the evidence, the exact command and the exact undo.",
    human: "A person decides. What do you do?",
    noaction: "Nothing ran. The incident and the reason are recorded.",
    exec: "It records the state just before, does a dry run, then runs the approved runbook.",
    verify: "It polls for recovery, with traffic still flowing. What does it find?",
    recovered: "Recovered. The fix stays in place.",
    rolled: "Things got worse, so it restored the exact previous value.",
    escalate: "It could not confirm recovery and nothing got worse. The fix stays and a person takes over.",
    report: "The incident report is built only from the audit log. Done.",
  };
  const NEXT = { alert: "tele", tele: "detect", detect: "bundle", bundle: "llm", llm: "ground", ground: "diag", diag: "policy", card: "human", exec: "verify", recovered: "report", rolled: "report", escalate: "report" };
  const CHOICES = {
    policy: [{ label: "Allowed", to: "card", cls: "good" }, { label: "Rejected (try the hostile proposal)", to: "noaction", cls: "bad" }],
    human: [{ label: "Approve", to: "exec", cls: "good" }, { label: "Reject", to: "noaction", cls: "bad" }, { label: "Do nothing for 15 minutes", to: "noaction", cls: "warn" }],
    verify: [{ label: "Recovered", to: "recovered", cls: "good" }, { label: "Got worse", to: "rolled", cls: "bad" }, { label: "Cannot confirm", to: "escalate", cls: "warn" }],
  };
  const BAD_END = new Set(["noaction", "rolled", "escalate"]);
  const nodeById = (id) => NODES.find((n) => n.id === id);
  const edgeBetween = (a, b) => EDGES.find((e) => e.from === a && e.to === b);
  const pel = (id) => document.querySelector(`.pl-node[data-id="${id}"]`);
  let PL = { sel: null, run: null, timer: 0, raf: 0 };

  function svgEl(tag, attrs = {}, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }

  function buildPipeline() {
    const svg = $("#pl-svg");
    svg.innerHTML = "";
    const defs = svgEl("defs", {}, svg);
    for (const [id, color] of [["pl-arrow", "var(--ink-2)"], ["pl-arrow-ok", "var(--settled)"], ["pl-arrow-bad", "var(--alarm)"]]) {
      const m = svgEl("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto" }, defs);
      svgEl("path", { d: "M0,0 L10,5 L0,10z", style: `fill:${color}` }, m);
    }
    for (const l of LANES) {
      svgEl("rect", { class: `pl-lane ${l.c}`, x: l.x, y: l.y, width: l.w, height: l.h, rx: 6 }, svg);
      const t = svgEl("text", { class: "pl-lane-label", x: l.lx, y: l.ly, "text-anchor": l.anchor }, svg);
      t.textContent = l.label;
    }
    const edgeLayer = svgEl("g", { id: "pl-edges" }, svg);
    for (const e of EDGES) {
      svgEl("path", { class: `pl-edge ${e.cls || ""}`, d: e.d, "data-edge": e.id, "data-from": e.from, "data-to": e.to }, edgeLayer);
      if (e.label) {
        const t = svgEl("text", { class: `pl-edge-label ${e.cls || ""}`, x: e.lx, y: e.ly, "text-anchor": "middle", "data-edge": e.id }, edgeLayer);
        t.textContent = e.label;
      }
    }
    for (const n of NODES) {
      const g = svgEl("g", { class: `pl-node ${n.k === "bar" ? "pl-audit" : ""}`, "data-id": n.id, tabindex: 0, role: "button", "aria-label": `${DETAIL[n.id].title}. Press Enter for details.` }, svg);
      const x0 = n.x - n.w / 2, y0 = n.y - n.h / 2;
      if (n.k === "dia") svgEl("polygon", { class: "shape", points: `${n.x},${y0} ${n.x + n.w / 2},${n.y} ${n.x},${y0 + n.h} ${x0},${n.y}` }, g);
      else svgEl("rect", { class: "shape", x: x0, y: y0, width: n.w, height: n.h, rx: n.k === "term" ? n.h / 2 : n.k === "bar" ? 6 : 4 }, g);
      const lines = [...n.t.map((s) => ({ s, c: "t" })), ...(n.s || []).map((s) => ({ s, c: "s" }))];
      const lh = (c) => (c === "t" ? 17 : 14);
      const total = lines.reduce((a, l) => a + lh(l.c), 0);
      let y = n.y - total / 2;
      for (const l of lines) {
        y += lh(l.c);
        const t = svgEl("text", { class: l.c, x: n.x, y: y - 4, "text-anchor": "middle", style: n.small ? "font-size:12.5px" : "" }, g);
        t.textContent = l.s;
      }
    }
    svgEl("circle", { id: "pl-token", class: "pl-token", r: 8, cx: -30, cy: -30, "aria-hidden": "true" }, svg);

    svg.addEventListener("click", (e) => { const g = e.target.closest(".pl-node"); if (g) toggleSel(g.dataset.id); });
    svg.addEventListener("keydown", (e) => {
      const g = e.target.closest(".pl-node");
      if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); toggleSel(g.dataset.id); }
    });
    $("#pl-go").addEventListener("click", startTrace);
    $("#pl-reset").addEventListener("click", resetAll);
    renderDetail(null);
  }

  function applyDim() {
    const svg = $("#pl-svg");
    const sel = PL.sel;
    svg.querySelectorAll(".pl-node, .pl-edge, .pl-edge-label").forEach((el) => el.classList.remove("pl-dim"));
    if (!sel || (PL.run && PL.run.active)) return;
    const near = new Set([sel]);
    EDGES.forEach((e) => { if (e.from === sel) near.add(e.to); if (e.to === sel) near.add(e.from); });
    svg.querySelectorAll(".pl-node").forEach((g) => { if (!near.has(g.dataset.id)) g.classList.add("pl-dim"); });
    svg.querySelectorAll(".pl-edge, .pl-edge-label").forEach((el) => {
      const e = EDGES.find((x) => x.id === el.dataset.edge);
      if (e && e.from !== sel && e.to !== sel) el.classList.add("pl-dim");
    });
  }

  function renderDetail(id) {
    const box = $("#pl-detail");
    if (!id) {
      box.innerHTML = `<h3>Pick a stage</h3><p>Each box is one step. Click it, or press Enter on it, to see what it does, what it reads and produces, and what it cannot do. Click it again to clear.</p><p class="fine">Diamonds are decisions. Dashed red paths are the failure branches.</p>`;
      return;
    }
    const d = DETAIL[id];
    box.innerHTML = `<h3>${esc(d.title)}</h3><p>${esc(d.what)}</p><dl>
      <dt>Reads</dt><dd>${esc(d.reads)}</dd><dt>Produces</dt><dd>${esc(d.makes)}</dd>
      <dt>Cannot</dt><dd class="cannot">${esc(d.cannot)}</dd><dt>In the code</dt><dd class="code">${esc(d.code)}</dd></dl>
      ${d.fact ? `<p class="fact">${esc(d.fact)}</p>` : ""}`;
  }

  function setSel(id) {
    PL.sel = id;
    document.querySelectorAll(".pl-node").forEach((g) => g.classList.toggle("is-sel", g.dataset.id === id));
    renderDetail(id);
    applyDim();
  }
  function toggleSel(id) {
    if (PL.run && PL.run.active) return; // while tracing, the panel follows the token
    setSel(PL.sel === id ? null : id);
  }

  /* the tracer: a token follows the route, and you pick the branch at each decision */
  function moveToken(edgeId, done) {
    const path = document.querySelector(`.pl-edge[data-edge="${edgeId}"]`);
    const tok = $("#pl-token");
    path.classList.add("walked");
    const len = path.getTotalLength();
    const dur = reduceMotion ? 0 : Math.min(900, 260 + len * 2.1);
    cancelAnimationFrame(PL.raf);
    const t0 = performance.now();
    const frame = (now) => {
      const k = dur ? Math.min(1, (now - t0) / dur) : 1;
      const p = path.getPointAtLength(len * k);
      tok.setAttribute("cx", p.x); tok.setAttribute("cy", p.y);
      if (k < 1) PL.raf = requestAnimationFrame(frame); else done();
    };
    PL.raf = requestAnimationFrame(frame);
  }

  function visit(id, viaEdge) {
    const arrive = () => {
      const R = PL.run;
      R.path.push(id);
      document.querySelectorAll(".pl-node.current").forEach((g) => g.classList.remove("current"));
      const g = pel(id);
      g.classList.add("visited", ...(BAD_END.has(id) ? ["visited-bad"] : []));
      g.classList.add("current");
      setSel(id);
      $("#pl-narr").textContent = STEP[id];
      const box = $("#pl-choices");
      box.innerHTML = "";
      if (CHOICES[id]) {
        CHOICES[id].forEach((c) => {
          const b = document.createElement("button");
          b.type = "button"; b.className = `btn ${c.cls || ""}`; b.textContent = c.label;
          b.addEventListener("click", () => { box.innerHTML = ""; PL.run.choices.push(c.label); visit(c.to, edgeBetween(id, c.to).id); });
          box.appendChild(b);
        });
        box.querySelector("button").focus({ preventScroll: true });
        return;
      }
      if (!NEXT[id]) { finishTrace(); return; }
      PL.timer = setTimeout(() => visit(NEXT[id], edgeBetween(id, NEXT[id]).id), reduceMotion ? 0 : 950);
    };
    if (viaEdge) moveToken(viaEdge, arrive); else arrive();
  }

  const OUTCOME = {
    recovered: "The fix ran and recovery was confirmed.",
    rolled: "The fix ran, made things worse, and was undone to the exact previous value.",
    escalate: "The fix ran, recovery could not be confirmed, and a person takes over.",
    noaction: "Nothing ran, and the refusal is recorded.",
  };
  function finishTrace() {
    const R = PL.run;
    R.active = false;
    const last = R.path.filter((id) => OUTCOME[id]).pop();
    const chose = R.choices.length ? `You chose: ${R.choices.join(", ")}. ` : "";
    $("#pl-path").textContent = `${chose}${OUTCOME[last] || ""} ${R.path.length} stages passed through.`;
    $("#pl-go").disabled = false;
    $("#pl-go").textContent = "Trace another";
    $("#pl-narr").textContent = (last === "noaction" ? STEP.noaction : STEP[R.path[R.path.length - 1]]) + " Trace again and take a different branch.";
  }

  function clearTrace() {
    clearTimeout(PL.timer); cancelAnimationFrame(PL.raf);
    PL.run = null;
    document.querySelectorAll(".pl-node").forEach((g) => g.classList.remove("visited", "visited-bad", "current"));
    document.querySelectorAll(".pl-edge").forEach((p) => p.classList.remove("walked"));
    const tok = $("#pl-token"); tok.setAttribute("cx", -30); tok.setAttribute("cy", -30);
    $("#pl-choices").innerHTML = ""; $("#pl-path").textContent = "";
  }
  function startTrace() {
    clearTrace();
    PL.run = { active: true, path: [], choices: [] };
    $("#pl-go").disabled = true; $("#pl-go").textContent = "Tracing";
    setSel(null);
    visit("alert", null);
  }
  function resetAll() {
    clearTrace();
    setSel(null);
    $("#pl-go").disabled = false; $("#pl-go").textContent = "Trace an incident";
    $("#pl-narr").textContent = "Follow one incident through the pipeline. When it reaches a decision, you choose the branch.";
  }

  /* ---------- navigation: shadow when scrolled, highlight the section in view ---------- */
  function buildNav() {
    const bar = document.querySelector(".mast-bar");
    const onScroll = () => bar.classList.toggle("scrolled", window.scrollY > 8);
    onScroll(); window.addEventListener("scroll", onScroll, { passive: true });
    const links = [...document.querySelectorAll('.mast nav a[href^="#"]')];
    const byId = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
    if (!("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting && byId.has(en.target.id)) { links.forEach((a) => a.classList.remove("is-active")); byId.get(en.target.id).classList.add("is-active"); }
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    byId.forEach((_, id) => { const s = document.getElementById(id); if (s) io.observe(s); });
  }

  /* ---------- start ---------- */
  buildPicker();
  load("payment");
  buildPipeline();
  drawNoise("count", false);
  buildForge();
  buildScore();
  buildNav();
  window.__zero = { load, step, state: () => S, pipeline: () => PL };
})();
