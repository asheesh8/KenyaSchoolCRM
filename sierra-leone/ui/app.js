/* Sierra Leone Schools Directory — CRM front end. No build step; talks to /api/*. */
(() => {
  "use strict";

  // ------------------------------------------------------------ helpers
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nf = new Intl.NumberFormat("en-GB");
  const n = (v) => (v == null ? "—" : nf.format(Math.round(v)));
  const pct = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : "—");
  const ago = (ts) => {
    if (!ts) return "never";
    const d = (Date.now() / 1000 - ts) / 86400;
    if (d < 0) return `in ${until(ts)}`;
    if (d < 1 / 24) return "just now";
    if (d < 1) return `${Math.round(d * 24)} h ago`;
    if (d < 45) return `${Math.round(d)} d ago`;
    return new Date(ts * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  };
  const until = (ts) => {
    const s = ts - Date.now() / 1000;
    if (s <= 0) return "now";
    if (s < 3600) return `${Math.ceil(s / 60)} min`;
    if (s < 86400) return `${Math.round(s / 3600)} h`;
    return `${Math.round(s / 86400)} d`;
  };
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2600);
  }
  async function api(path, opts = {}) {
    const r = await fetch(`/api/${path}`, {
      method: opts.method || "GET", credentials: "same-origin",
      headers: opts.body ? { "Content-Type": "application/json" } : {},
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    if (r.status === 401) { showLogin(); throw new Error("sign_in"); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    if (data && data.error && !opts.allowError) throw new Error(data.error);
    return data;
  }

  const ICON = {
    email: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    phone: '<svg viewBox="0 0 24 24"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>',
    website: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>',
    person: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
    star: '<svg viewBox="0 0 24 24"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg>',
    close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  };

  // ------------------------------------------------------------ constants
  const STAGES = [["new", "New"], ["queued", "In sequence"], ["contacted", "Emailed"], ["replied", "Replied"],
    ["interested", "Interested"], ["partner", "Using the library"], ["not_interested", "Not interested"], ["do_not_contact", "Do not contact"]];
  const STAGE_LABEL = Object.fromEntries(STAGES);
  const LEVELS = [["pre_primary", "Nursery"], ["primary", "Primary"], ["junior_secondary", "JSS"], ["senior_secondary", "SSS"],
    ["tvet", "Technical / vocational"], ["tertiary", "University / college"], ["admin", "Education offices"]];
  const LEVEL_SHORT = Object.fromEntries(LEVELS);
  const OWNERSHIP = [["government", "Government"], ["government_assisted", "Gov't-assisted"], ["mission", "Mission / faith"],
    ["private", "Private"], ["community", "Community"], ["ngo", "NGO"], ["unknown", "Not recorded"]];
  const OWN_LABEL = Object.fromEntries(OWNERSHIP);
  const SEQ_LABEL = { active: "In sequence", paused: "Paused", done: "Sequence finished", replied: "Replied", unsubscribed: "Unsubscribed", bounced: "Bounced", failed: "Failed" };
  const CONF_LABEL = { high: "Confirmed source", medium: "Likely", low: "Check first" };

  const state = { f: {}, rows: [], total: 0, withEmail: 0, page: 1, per: 50, selected: new Set(), open: null, facets: null, outreach: null };

  // ------------------------------------------------------------ auth + routing
  function showLogin() { $("#login").hidden = false; $("#app").hidden = true; }
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("login", { method: "POST", body: { password: $("#pw").value } }); $("#login").hidden = true; boot(); }
    catch (err) { $("#login-error").textContent = err.message === "sign_in" ? "" : err.message; }
  });
  $("#logout").addEventListener("click", async () => { await api("logout", { method: "POST" }); location.reload(); });
  const theme = () => { try { return localStorage.getItem("sl-theme"); } catch { return null; } };
  function applyTheme(t) {
    document.documentElement.dataset.theme = t || "light";
    $("#theme-toggle").textContent = t === "dark" ? "Light screen" : "Dark screen";
  }
  $("#theme-toggle").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("sl-theme", t); } catch { /* private window */ }
    applyTheme(t);
  });
  applyTheme(theme());

  function parseHash() {
    const [view, qs] = (location.hash.replace(/^#\/?/, "") || "overview").split("?");
    return { view: view || "overview", params: new URLSearchParams(qs || "") };
  }
  function go(view, f) {
    if (f) { state.f = f; state.page = 1; }
    location.hash = `#/${view}${view === "schools" && f ? "?" + filterQS() : ""}`;
  }
  function filterQS(extra = {}) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...state.f, ...extra })) {
      if (Array.isArray(v) ? v.length : v) p.set(k, Array.isArray(v) ? v.join(",") : v);
    }
    return p.toString();
  }
  function route() {
    const { view, params } = parseHash();
    if (view !== state.view) { closeDrawer(); state.view = view; }
    $$(".rail a[data-view]").forEach((a) => a.classList.toggle("on", a.dataset.view === view));
    $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
    if (view === "schools") {
      const f = {};
      for (const [k, v] of params) f[k] = ["level", "district", "province", "ownership", "denomination", "status", "has", "missing", "confidence", "kind"].includes(k) ? v.split(",") : v;
      if (params.toString()) { state.f = f; }
      renderFilters(); loadSchools();
    } else if (view === "overview") renderOverview();
    else if (view === "outreach") renderOutreach();
    else if (view === "pipeline") renderPipeline();
    else if (view === "data") renderData();
  }
  window.addEventListener("hashchange", route);

  // ------------------------------------------------------------ overview
  async function renderOverview() {
    const el = $("#view-overview");
    el.innerHTML = `<div class="page"><p class="muted">Loading…</p></div>`;
    const s = await api("summary");
    const T = s.total || 1;
    const maxLv = Math.max(...s.by_level.map((l) => l.schools), 1);
    el.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Schools in Sierra Leone</h1>
        <p>Schools, colleges and education offices with publicly listed contacts, for the library outreach. The 2024/25 school census counts ${n(s.census_total)} pre-primary to senior secondary schools.</p></div>
        <a class="btn primary" href="#/outreach">Email outreach</a></div>
      <div class="hero">
        <div><div class="big">${n(s.total)}</div><div class="lbl">institutions on file (${n(s.schools)} schools, ${n(s.offices)} offices and networks)</div></div>
        <a class="hero-link" href="#/schools?has=email"><div class="mid">${n(s.with_email)}</div><div class="lbl">with an email · ${n(s.unique_emails)} addresses</div></a>
        <a class="hero-link" href="#/schools?has=phone"><div class="mid">${n(s.with_phone)}</div><div class="lbl">with a phone number</div></a>
        <a class="hero-link" href="#/schools?has=leader"><div class="mid">${n(s.with_leader)}</div><div class="lbl">with a named head or official</div></a>
      </div>
      <div class="grid-2">
        <div class="card"><h2>By level</h2><p class="sub">A school counts once for each level it teaches. Click a bar to list them.</p>
          <div class="stage-bars">${s.by_level.map((l) => `<div class="sbar" data-level="${l.key}" role="button" tabindex="0">
            <span class="k">${esc(l.short)}</span><span class="track"><span class="fill" style="display:block;width:${(100 * l.schools) / maxLv}%"></span></span>
            <span class="v">${n(l.schools)}<small class="muted"> · ${n(l.with_email)} email</small></span></div>`).join("")}</div></div>
        <div class="card"><h2>Outreach</h2><p class="sub">Schools at each stage, and emails sent so far (${n(s.sent_total)}).</p>
          <div class="stage-bars">${STAGES.map(([k, l]) => `<div class="sbar" data-status="${k}" role="button" tabindex="0"><span class="k">${l}</span>
            <span class="track"><span class="fill" style="display:block;width:${(100 * (s.statuses[k] || 0)) / T}%"></span></span><span class="v">${n(s.statuses[k] || 0)}</span></div>`).join("")}</div></div>
      </div>
      <div class="card" style="padding:0;overflow:auto"><table class="plain"><thead><tr><th>District</th><th>Province</th><th class="num">Schools on file</th><th class="num">Census total</th><th class="num">With email</th><th class="num">Emailed</th></tr></thead>
        <tbody>${s.by_district.map((d) => `<tr data-district="${esc(d.district)}" style="cursor:pointer"><td>${esc(d.district)}</td><td>${esc(d.province)}</td>
          <td class="num">${n(d.schools)} <small class="muted">${pct(d.schools, d.census)}</small></td><td class="num">${n(d.census)}</td><td class="num">${n(d.with_email)}</td><td class="num">${n(d.contacted)}</td></tr>`).join("")}</tbody></table></div>
      <div class="grid-2">
        <div class="card"><h2>Email quality</h2><p class="sub">How sure we are each address belongs to the institution.</p>
          <div class="stage-bars">${["high", "medium", "low"].map((k) => `<div class="sbar" data-conf="${k}" role="button" tabindex="0"><span class="k">${CONF_LABEL[k]}</span>
            <span class="track"><span class="fill" style="display:block;width:${(100 * (s.email_confidence[k] || 0)) / Math.max(s.unique_emails, 1)}%"></span></span><span class="v">${n(s.email_confidence[k] || 0)}</span></div>`).join("")}</div></div>
        <div class="card"><h2>Recent activity</h2><p class="sub">Emails, replies and notes.</p>
          <div class="recent">${s.recent.length ? s.recent.map((a) => `<a href="#" data-open="${a.school_id}"><span class="when">${ago(a.created_at)}</span><span class="body"><b>${esc(a.name)}</b> — ${esc(a.body || a.kind)}</span></a>`).join("") : `<p class="muted">Nothing yet.</p>`}</div></div>
      </div></div>`;
    $$(".sbar[data-level]", el).forEach((b) => b.addEventListener("click", () => go("schools", { level: [b.dataset.level] })));
    $$(".sbar[data-status]", el).forEach((b) => b.addEventListener("click", () => go("schools", { status: [b.dataset.status] })));
    $$(".sbar[data-conf]", el).forEach((b) => b.addEventListener("click", () => go("schools", { confidence: [b.dataset.conf] })));
    $$("tr[data-district]", el).forEach((r) => r.addEventListener("click", () => go("schools", { district: [r.dataset.district] })));
    $$("[data-open]", el).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openSchool(+a.dataset.open); }));
  }

  // ------------------------------------------------------------ filters + list
  function renderFilters() {
    const f = state.f, fc = state.facets;
    if (!fc) return;
    const pills = (key, opts) => `<div class="pills">${opts.map(([v, l]) =>
      `<button type="button" class="pill ${(f[key] || []).includes(v) ? "on" : ""}" data-k="${key}" data-v="${esc(v)}">${esc(l)}</button>`).join("")}</div>`;
    $("#filters").innerHTML = `<h2>Filters</h2>
      <div class="fgroup"><div class="flabel">Level</div>${pills("level", LEVELS)}</div>
      <div class="fgroup"><div class="flabel">Province</div>${pills("province", fc.provinces.map((p) => [p, p]))}</div>
      <div class="fgroup"><div class="flabel">District</div>
        <select id="f-district" class="big-select"><option value="">All 16 districts</option>${fc.districts.map((d) => `<option ${(f.district || []).includes(d.value) ? "selected" : ""}>${esc(d.value)}</option>`).join("")}</select></div>
      <div class="fgroup"><div class="flabel">How to reach them</div>${pills("has", [["email", "Has email"], ["phone", "Has phone"], ["leader", "Named head"], ["website", "Website"]])}</div>
      <div class="fgroup"><div class="flabel">Email quality</div>${pills("confidence", [["high", CONF_LABEL.high], ["medium", CONF_LABEL.medium], ["low", CONF_LABEL.low]])}</div>
      <div class="fgroup"><div class="flabel">Ownership</div>${pills("ownership", OWNERSHIP)}</div>
      <details class="fgroup more" ${f.denomination || f.status || f.sequence || f.kind ? "open" : ""}><summary>More filters</summary>
        <div class="flabel">Faith</div>${pills("denomination", fc.denominations.map((d) => [d, d]))}
        <div class="flabel">Stage</div>${pills("status", STAGES)}
        <div class="flabel">Type</div>${pills("kind", [["school", "Schools"], ["office", "Gov't offices"], ["secretariat", "Education secretariats"], ["association", "Associations"], ["ngo", "NGOs"]])}
        <div class="flabel">Email sequence</div>
        <select id="f-seq"><option value="">Any</option><option value="none" ${f.sequence === "none" ? "selected" : ""}>Not emailed yet</option>${Object.entries(SEQ_LABEL).map(([k, l]) => `<option value="${k}" ${f.sequence === k ? "selected" : ""}>${l}</option>`).join("")}</select>
        <label class="check-row"><input type="checkbox" id="f-star" ${f.starred === "1" ? "checked" : ""}> Starred only</label>
      </details>
      <button class="btn ghost" id="f-clear">Start over</button>`;
    $$("#filters .pill").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.k, v = b.dataset.v, cur = new Set(f[k] || []);
      cur.has(v) ? cur.delete(v) : cur.add(v);
      state.f = { ...f, [k]: [...cur] }; state.page = 1; sync();
    }));
    $("#f-district").onchange = (e) => { state.f = { ...f, district: e.target.value ? [e.target.value] : [] }; state.page = 1; sync(); };
    $("#f-seq").onchange = (e) => { state.f = { ...f, sequence: e.target.value }; state.page = 1; sync(); };
    $("#f-star").onchange = (e) => { state.f = { ...f, starred: e.target.checked ? "1" : "" }; state.page = 1; sync(); };
    $("#f-clear").onclick = () => { state.f = {}; state.page = 1; $("#q").value = ""; sync(); };
    $("#q").value = f.q || "";
    $("#sort").value = f.sort || "best";
  }
  function sync() { history.replaceState(null, "", `#/schools?${filterQS()}`); renderFilters(); loadSchools(); }
  $("#q").addEventListener("input", debounce((e) => { state.f = { ...state.f, q: e.target.value }; state.page = 1; sync(); }, 250));
  $("#sort").addEventListener("change", (e) => { state.f = { ...state.f, sort: e.target.value }; sync(); });
  $("#show-filters").addEventListener("click", () => $("#filters").classList.toggle("open"));
  $("#export").addEventListener("click", (e) => { e.preventDefault(); location.href = `/api/export.csv?${filterQS()}`; });

  async function loadSchools() {
    const d = await api(`schools?${filterQS({ page: state.page, per: state.per })}`);
    Object.assign(state, { rows: d.rows, total: d.total, withEmail: d.with_email });
    renderChips(); renderRows();
  }
  function renderChips() {
    const chips = [];
    for (const [k, v] of Object.entries(state.f)) {
      if (["sort", "q"].includes(k) || !(Array.isArray(v) ? v.length : v)) continue;
      for (const x of Array.isArray(v) ? v : [v]) {
        const label = LEVEL_SHORT[x] || STAGE_LABEL[x] || OWN_LABEL[x] || CONF_LABEL[x] || SEQ_LABEL[x] || ({ email: "Has email", phone: "Has phone", leader: "Named head", website: "Website", none: "Not emailed yet", 1: "Starred" })[x] || x;
        chips.push(`<span class="chip">${esc(label)}<button data-k="${k}" data-v="${esc(x)}" aria-label="Remove">×</button></span>`);
      }
    }
    $("#active-chips").innerHTML = chips.join("");
    $$("#active-chips button").forEach((b) => b.addEventListener("click", () => {
      const v = state.f[b.dataset.k];
      state.f = { ...state.f, [b.dataset.k]: Array.isArray(v) ? v.filter((x) => x !== b.dataset.v) : "" };
      state.page = 1; sync();
    }));
  }
  function levelText(r) { return r.level_keys.map((k) => LEVEL_SHORT[k]).join(", ") || "Level not recorded"; }
  function rowHTML(r) {
    const seq = r.sequence ? r.sequence.split(":")[0] : null;
    return `<tr data-id="${r.id}" class="${state.open === r.id ? "open" : ""}">
      <td class="c-check"><input type="checkbox" data-sel="${r.id}" ${state.selected.has(r.id) ? "checked" : ""} aria-label="Select ${esc(r.name)}"></td>
      <td><div class="s-name">${r.starred ? `<span class="star">★</span>` : ""}${esc(r.name)}</div>
        <div class="s-sub">${esc(levelText(r))}${r.ownership && r.ownership !== "unknown" ? " · " + esc(OWN_LABEL[r.ownership]) : ""}${r.denomination ? " · " + esc(r.denomination) : ""}</div></td>
      <td class="where">${esc(r.district || "—")}<div class="s-sub">${esc([r.town, r.chiefdom].filter(Boolean).join(", "))}</div></td>
      <td class="reach">${r.email ? `<div class="reach-line">${ICON.email}<span>${esc(r.email)}</span>${r.n_emails > 1 ? `<span class="badge">+${r.n_emails - 1}</span>` : ""}<span class="badge conf-${esc(r.confidence)}" title="${esc(CONF_LABEL[r.confidence] || "")}">${esc(r.confidence || "")}</span></div>` : ""}
        ${r.phone ? `<div class="reach-line">${ICON.phone}<span>${esc(r.phone)}</span></div>` : ""}
        ${!r.phone && !r.email ? `<span class="muted">${r.website ? "Website only" : "No details yet"}</span>` : ""}</td>
      <td class="head">${r.leader ? esc(r.leader) : `<span class="muted">—</span>`}</td>
      <td><span class="stage" data-s="${r.status}">${STAGE_LABEL[r.status]}</span>${seq ? `<div class="s-sub">${esc(SEQ_LABEL[seq] || seq)}</div>` : ""}</td></tr>`;
  }
  function renderRows() {
    const { rows, total, page, per } = state;
    $("#count").innerHTML = `<strong>${n(total)}</strong> match · <strong>${n(state.withEmail)}</strong> with email`;
    $("#rows").innerHTML = rows.length ? rows.map(rowHTML).join("") :
      `<tr><td colspan="6"><div class="empty"><h3>No schools match</h3>Remove one of your choices above, or press “Start over”.</div></td></tr>`;
    const from = (page - 1) * per;
    $("#pager").innerHTML = total > per ? `<span>${n(from + 1)}–${n(Math.min(from + per, total))} of ${n(total)}</span>
      <span><button class="btn small" id="prev" ${page > 1 ? "" : "disabled"}>Previous</button>
      <button class="btn small" id="next" ${from + per < total ? "" : "disabled"}>Next</button></span>` : "";
    $("#prev")?.addEventListener("click", () => { state.page--; loadSchools(); });
    $("#next")?.addEventListener("click", () => { state.page++; loadSchools(); });
    $$("#rows tr[data-id]").forEach((tr) => tr.addEventListener("click", (e) => {
      if (e.target.matches("input")) return;
      openSchool(+tr.dataset.id);
    }));
    $$("#rows input[data-sel]").forEach((c) => c.addEventListener("change", () => {
      const id = +c.dataset.sel; c.checked ? state.selected.add(id) : state.selected.delete(id); renderBulk();
    }));
    $("#check-all").checked = rows.length && rows.every((r) => state.selected.has(r.id));
    renderBulk();
  }
  $("#check-all").addEventListener("change", (e) => {
    state.rows.forEach((r) => (e.target.checked ? state.selected.add(r.id) : state.selected.delete(r.id)));
    renderRows();
  });
  function renderBulk() {
    const k = state.selected.size;
    $("#bulk").innerHTML = `${k ? `<b>${n(k)} selected</b> <button class="btn small primary" id="b-email">Email selected</button>
      <select id="b-stage" class="small"><option value="">Move to stage…</option>${STAGES.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
      <button class="btn small ghost" id="b-clear">Clear</button>` : ""}
      ${state.withEmail ? `<button class="btn small" id="b-email-all">Email all ${n(state.withEmail)} with an address</button>` : ""}`;
    $("#b-email")?.addEventListener("click", () => enrollDialog({ ids: [...state.selected] }));
    $("#b-email-all")?.addEventListener("click", () => enrollDialog({ filter: { ...state.f, has: [...new Set([...(state.f.has || []), "email"])].join(",") } }));
    $("#b-clear")?.addEventListener("click", () => { state.selected.clear(); renderRows(); });
    $("#b-stage")?.addEventListener("change", async (e) => {
      if (!e.target.value) return;
      await api("bulk", { method: "POST", body: { ids: [...state.selected], status: e.target.value } });
      toast(`Moved ${state.selected.size} to ${STAGE_LABEL[e.target.value]}`); loadSchools();
    });
  }

  // ------------------------------------------------------------ modal
  function modal(html, onReady) {
    const m = $("#modal");
    m.innerHTML = `<div class="modal-body">${html}</div>`;
    if (!m.open) m.showModal();
    $$("[data-close]", m).forEach((b) => b.addEventListener("click", () => m.close()));
    onReady && onReady(m);
    return m;
  }

  async function enrollDialog(target) {
    const [acc, pre] = await Promise.all([api("accounts"), api("enroll", { method: "POST", body: { ...target, dry_run: true } })]);
    const usable = acc.accounts.filter((a) => a.enabled);
    if (!acc.accounts.length) {
      modal(`<h2>Connect a sender email first</h2><p>Add at least one of your seven sender accounts on the Email outreach page, then come back and select schools.</p>
        <div class="modal-actions"><button class="btn ghost" data-close>Close</button><a class="btn primary" href="#/outreach" data-close>Add a sender account</a></div>`);
      return;
    }
    modal(`<h2>Start the 3-email sequence</h2>
      <p>${n(pre.schools)} school${pre.schools === 1 ? "" : "s"} chosen; ${n(pre.with_email)} have an email address. Email 1 goes out first, then the library offer and a follow-up, each only if they haven't replied or unsubscribed.</p>
      <label class="field">Send from
        <select id="e-acc"><option value="">Spread across all ${usable.length} active accounts (recommended)</option>
          ${acc.accounts.map((a) => `<option value="${a.id}">${esc(a.label)} — ${esc(a.from_email)}${a.enabled ? "" : " (paused)"}</option>`).join("")}</select></label>
      <label class="field">Who to email at each school
        <select id="e-mode"><option value="best">The main address only</option><option value="all">Every address on file (head, office, etc.)</option></select></label>
      <p class="muted small">Addresses that unsubscribed, bounced, or are already in a sequence are skipped. Nothing sends until sending is switched on, and then only inside each account's daily and hourly limits.</p>
      <div class="modal-actions"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="e-go">Add to sequence</button></div>`, (m) => {
      $("#e-go", m).onclick = async () => {
        const r = await api("enroll", { method: "POST", body: { ...target, account_id: $("#e-acc", m).value || null, mode: $("#e-mode", m).value } });
        m.close();
        toast(`${n(r.enrolled)} added to the sequence${r.already ? `, ${n(r.already)} already in it` : ""}${r.suppressed ? `, ${n(r.suppressed)} unsubscribed` : ""}`);
        state.selected.clear();
        if (parseHash().view === "schools") loadSchools();
      };
    });
  }

  // ------------------------------------------------------------ school drawer
  async function openSchool(id) {
    state.open = id;
    const d = $("#drawer"); d.hidden = false;
    d.innerHTML = `<div class="d-head"><div class="muted">Loading…</div></div>`;
    try { renderDrawer(await api(`schools/${id}`)); } catch (e) { d.innerHTML = `<div class="d-head">${esc(e.message)}</div>`; }
  }
  function closeDrawer() { state.open = null; $("#drawer").hidden = true; }
  function phoneLinks(value, msgs) {
    const num = value.replace(/[^\d+]/g, ""), wa = num.replace(/\D/g, "");
    // Sierra Leone mobile prefixes; landlines (22, 23, 31…) can't take WhatsApp.
    const mobile = /^232(25|3[0-4]|7\d|8[0-8]|99)/.test(wa);
    return `<a href="tel:${esc(num)}">${esc(value)}</a>${mobile && msgs ? ` <a class="btn small" target="_blank" rel="noopener" href="https://wa.me/${wa}?text=${encodeURIComponent(msgs.whatsapp)}">WhatsApp</a> <a class="btn small" href="sms:${esc(num)}?&body=${encodeURIComponent(msgs.sms)}">Text</a>` : ""}`;
  }
  function renderDrawer(s) {
    const d = $("#drawer");
    const kinds = ["person", "email", "phone", "website"];
    const contacts = s.contacts.slice().sort((a, b) => kinds.indexOf(a.kind) - kinds.indexOf(b.kind) || b.active - a.active);
    const val = (c) => c.kind === "email" ? `<a href="mailto:${esc(c.value)}">${esc(c.value)}</a>` : c.kind === "phone" ? phoneLinks(c.value, s.phone_messages)
      : c.kind === "website" ? `<a href="${esc(c.value)}" target="_blank" rel="noopener">${esc(c.value.replace(/^https?:\/\//, ""))}</a>` : esc(c.value);
    d.innerHTML = `
      <div class="d-head"><div class="d-top">
          <div><h2>${esc(s.name)}</h2><div class="s-sub">${esc(levelText(s))} · ${esc(s.district || "District not recorded")}</div></div>
          <div class="d-actions"><button class="icon-btn ${s.starred ? "on" : ""}" id="d-star" title="Star">${ICON.star}</button>
            <button class="icon-btn" id="d-close" title="Close (Esc)">${ICON.close}</button></div></div>
        <div class="stages">${STAGES.map(([v, l]) => `<button data-s="${v}" class="${s.status === v ? "on" : ""}">${l}</button>`).join("")}</div>
        ${s.email ? `<button class="btn primary" id="d-enroll" style="margin-top:10px">Add to email sequence</button>` : ""}
      </div>
      <div class="d-body">
        ${s.enrollments.length ? `<section class="d-sec"><h3>Email sequence</h3>${s.enrollments.map((e) => `<div class="contact"><span class="ci on">${ICON.email}</span>
          <div><div class="v">${esc(e.email)} <span class="badge">${esc(SEQ_LABEL[e.status] || e.status)}</span></div>
          <div class="meta">from ${esc(e.account_label || "a removed account")} · ${e.status === "active" ? `email ${e.next_step} due ${until(e.next_due_at) === "now" ? "now" : "in " + until(e.next_due_at)}` : `updated ${ago(e.updated_at)}`}</div></div>
          <div class="acts">${e.status === "active" ? `<button class="btn small" data-enr="${e.id}" data-a="pause">Pause</button>` : ""}${e.status === "paused" ? `<button class="btn small" data-enr="${e.id}" data-a="resume">Resume</button>` : ""}
            ${["active", "paused", "done"].includes(e.status) ? `<button class="btn small" data-enr="${e.id}" data-a="replied">They replied</button><button class="btn small" data-enr="${e.id}" data-a="unsubscribe">Unsubscribe</button>` : ""}</div></div>`).join("")}</section>` : ""}
        <section class="d-sec"><h3>Contacts</h3>
          ${contacts.length ? contacts.map((c) => `<div class="contact ${c.active ? "" : "stale"}">
            <span class="ci ${c.active ? "on" : ""}">${ICON[c.kind] || ICON.website}</span>
            <div><div class="v">${val(c)}${c.role && c.kind === "person" ? ` <span class="badge">${esc(c.role)}</span>` : ""}${c.person && c.kind !== "person" ? ` <span class="badge">${esc(c.person)}${c.role ? ", " + esc(c.role) : ""}</span>` : ""}${c.confidence ? ` <span class="badge conf-${esc(c.confidence)}">${esc(CONF_LABEL[c.confidence])}</span>` : ""}${c.suppressed ? ` <span class="badge warn">unsubscribed</span>` : ""}</div>
              <div class="meta">${c.source_url ? `source: <a href="${esc(c.source_url)}" target="_blank" rel="noopener">${esc(c.source_url.replace(/^https?:\/\/(www\.)?/, "").slice(0, 60))}</a>` : esc(c.source)} · ${c.active ? `added ${ago(c.first_seen)}` : "marked wrong / old"}</div></div>
            <div class="acts"><button class="btn small" data-active="${c.id}" data-to="${c.active ? 0 : 1}">${c.active ? "Wrong / old" : "Put back"}</button></div>
          </div>`).join("") : `<p class="muted">No contact details yet. Add what you find below.</p>`}
          <form class="add-contact" id="d-add">
            <select name="kind"><option value="email">Email</option><option value="phone">Phone</option><option value="person">Person</option><option value="website">Website</option></select>
            <input name="value" placeholder="principal@school.edu.sl, 076 123 456, …" required>
            <input name="role" placeholder="Role (optional)">
            <button class="btn" type="submit">Add</button>
          </form></section>
        <section class="d-sec"><h3>Log activity</h3>
          <form class="log-form" id="d-log"><select name="kind"><option value="note">Note</option><option value="call">Call</option><option value="email">Email</option><option value="meeting">Meeting</option><option value="visit">Visit</option></select>
            <textarea name="body" rows="2" placeholder="What happened?" required></textarea><button class="btn" type="submit">Save</button></form>
          ${s.activities.map((a) => `<div class="activity ${a.kind === "system" ? "system" : ""}"><span class="when">${ago(a.created_at)} · ${esc(a.kind)}</span><div class="body">${esc(a.body)}</div></div>`).join("")}</section>
        <section class="d-sec"><h3>About</h3><dl class="facts">
          <div><dt>Ownership</dt><dd>${esc(OWN_LABEL[s.ownership] || "Not recorded")}${s.denomination ? ` · ${esc(s.denomination)}` : ""}</dd></div>
          <div><dt>Where</dt><dd>${esc([s.town, s.chiefdom && s.chiefdom + " chiefdom", s.district, s.province].filter(Boolean).join(", ") || "—")}</dd></div>
          ${s.emis_code ? `<div><dt>EMIS code</dt><dd>${esc(s.emis_code)}</dd></div>` : ""}
          ${s.students ? `<div><dt>Pupils</dt><dd>${n(s.students)} <small>(Ministry subsidy headcount, 2019/20)</small></dd></div>` : ""}
          ${s.notes ? `<div><dt>Notes</dt><dd>${esc(s.notes)}</dd></div>` : ""}
        </dl></section>
        <section class="d-sec"><h3>Sources</h3>${s.sources.map((u) => u.startsWith("http") ? `<div class="src"><a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a></div>` : `<div class="src">${esc(u)}</div>`).join("")}</section>
      </div>`;
    $("#d-close").onclick = closeDrawer;
    $("#d-star").onclick = async () => renderDrawer(await api(`schools/${s.id}`, { method: "PATCH", body: { starred: !s.starred } }));
    $("#d-enroll")?.addEventListener("click", () => enrollDialog({ ids: [s.id] }));
    $$(".stages button", d).forEach((b) => (b.onclick = async () => { renderDrawer(await api(`schools/${s.id}`, { method: "PATCH", body: { status: b.dataset.s } })); toast(`Moved to ${STAGE_LABEL[b.dataset.s]}`); refreshList(); }));
    $$("[data-active]", d).forEach((b) => (b.onclick = async () => renderDrawer(await api(`contacts/${b.dataset.active}`, { method: "PATCH", body: { active: +b.dataset.to } }))));
    $$("[data-enr]", d).forEach((b) => (b.onclick = async () => { await api(`enrollments/${b.dataset.enr}`, { method: "POST", body: { action: b.dataset.a } }); openSchool(s.id); refreshList(); }));
    $("#d-add").onsubmit = async (e) => {
      e.preventDefault(); const f = new FormData(e.target);
      try { renderDrawer(await api(`schools/${s.id}/contacts`, { method: "POST", body: Object.fromEntries(f) })); toast("Added"); } catch (err) { toast(err.message); }
    };
    $("#d-log").onsubmit = async (e) => {
      e.preventDefault(); renderDrawer(await api(`schools/${s.id}/activities`, { method: "POST", body: Object.fromEntries(new FormData(e.target)) })); toast("Saved");
    };
  }
  function refreshList() { if (parseHash().view === "schools") loadSchools(); }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#modal").open) closeDrawer();
    if (e.key === "/" && !e.target.matches("input, textarea, select")) { e.preventDefault(); go("schools"); setTimeout(() => $("#q").focus(), 50); }
  });

  // ------------------------------------------------------------ outreach
  let ticker = null;
  async function renderOutreach() {
    const el = $("#view-outreach");
    if (!state.outreach) el.innerHTML = `<div class="page"><p class="muted">Loading…</p></div>`;
    const o = state.outreach = await api("outreach");
    const presets = (await api("accounts")).presets;
    const on = o.settings.sending;
    const seq = o.sequence;
    el.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Email outreach</h1>
        <p>Connect up to seven sender emails, pick schools on the Find schools page, and they move through three emails: introduction, library offer, follow-up. Replies, unsubscribes and bounces stop the sequence for that address.</p></div>
        <div class="send-switch ${on ? "on" : ""}"><div><b>${on ? "Sending is on" : "Sending is off"}</b><div class="s-sub">${on ? (o.on_vercel ? "Keep this page open; it sends as each account's limits allow." : "The CRM sends in the background as each account's limits allow.") : "Nothing is sent until you switch this on."}</div></div>
          <button class="btn ${on ? "" : "primary"}" id="o-toggle">${on ? "Pause sending" : "Start sending"}</button></div></div>

      <div class="hero">
        <div><div class="big">${n(seq.active || 0)}</div><div class="lbl">addresses in the sequence (${n(o.by_step[1] || 0)} waiting for email 1, ${n(o.by_step[2] || 0)} for 2, ${n(o.by_step[3] || 0)} for 3)</div></div>
        <div><div class="mid">${n((o.sent_by_step[1] || 0) + (o.sent_by_step[2] || 0) + (o.sent_by_step[3] || 0))}</div><div class="lbl">emails sent</div></div>
        <div><div class="mid">${n(seq.replied || 0)}</div><div class="lbl">replied</div></div>
        <div><div class="mid">${n(o.suppressed)}</div><div class="lbl">unsubscribed or bounced</div></div>
      </div>

      <div class="card"><h2>Sender accounts <small class="muted">${o.accounts.length} of 7</small></h2>
        <p class="sub">Each account sends one email at a time with a gap between messages, inside its own daily and hourly limits. New mailboxes start low and ramp up each day so they aren't flagged as spam.</p>
        <div class="acct-grid">${o.accounts.map((a) => `<div class="acct ${a.enabled ? "" : "off"}">
            <div class="acct-top"><div><b>${esc(a.label)}</b><div class="s-sub">${esc(a.from_email)}</div></div>
              <span class="badge ${a.ready ? "conf-high" : a.enabled ? "" : "warn"}">${esc(a.ready ? "ready" : a.state)}</span></div>
            <div class="meter"><span style="width:${Math.min(100, (100 * a.sent_today) / Math.max(a.cap_today, 1))}%"></span></div>
            <div class="s-sub">${n(a.sent_today)} of ${n(a.cap_today)} today${a.warmup && a.cap_today < a.daily_cap ? ` (warming up to ${a.daily_cap})` : ""} · ${n(a.sent_hour)}/${a.hourly_cap} this hour · ${n(a.active)} in sequence, ${n(a.due)} due</div>
            ${a.last_error ? `<div class="error small">${esc(a.last_error)}</div>` : ""}
            ${!a.has_password ? `<div class="error small">No password saved. Edit the account and paste its app password.</div>` : ""}
            <div class="acct-acts"><button class="btn small" data-edit="${a.id}">Edit</button><button class="btn small" data-test="${a.id}">Test sign-in</button>
              ${a.imap_host ? `<button class="btn small" data-replies="${a.id}">Check replies</button>` : ""}
              <button class="btn small" data-pause="${a.id}" data-to="${a.enabled ? 0 : 1}">${a.enabled ? "Pause" : "Resume"}</button></div></div>`).join("")}
          ${o.accounts.length < 7 ? `<button class="acct add" id="o-add"><span>+</span>Connect a sender email</button>` : ""}</div></div>

      <div class="card"><h2>The three emails</h2>
        <p class="sub">Placeholders: {{greeting}} {{school}} {{person}} {{role}} {{district}} {{town}} {{sender_name}} {{org}} {{library_link}} {{signature}}. Leave a subject blank to send it as a reply in the same thread. An unsubscribe line is always added at the bottom.</p>
        <div class="settings-row">
          <label class="field">Organisation name<input id="s-org" value="${esc(o.settings.org === "our ministry" ? "" : o.settings.org)}" placeholder="e.g. Bible Transfer 123"></label>
          <label class="field">Library link<input id="s-link" value="${esc(o.settings.library_link)}" placeholder="https://…"></label>
          <label class="check-row"><input type="checkbox" id="s-weekdays" ${o.settings.weekdays_only ? "checked" : ""}> Weekdays only</label>
          <button class="btn" id="s-save">Save</button></div>
        ${o.templates.map((t) => `<details class="tmpl" ${t.step === 1 ? "open" : ""}><summary><b>Email ${t.step}: ${esc(t.name)}</b> <span class="muted">${t.step === 1 ? "sent first" : `${t.delay_days} days after email ${t.step - 1}`}</span></summary>
          <div class="tmpl-grid"><label class="field">Name<input data-t="${t.step}" data-f="name" value="${esc(t.name)}"></label>
            ${t.step > 1 ? `<label class="field">Days after previous<input type="number" min="0" step="1" data-t="${t.step}" data-f="delay_days" value="${t.delay_days}"></label>` : ""}</div>
          <label class="field">Subject<input data-t="${t.step}" data-f="subject" value="${esc(t.subject)}" placeholder="${t.step > 1 ? "(blank = Re: email 1's subject)" : ""}"></label>
          <label class="field">Body<textarea rows="11" data-t="${t.step}" data-f="body">${esc(t.body)}</textarea></label>
          <button class="btn small" data-save-t="${t.step}">Save email ${t.step}</button></details>`).join("")}
        <button class="btn" id="o-preview">Preview with a real school</button>
        ${o.public_url ? "" : `<p class="muted small">Set PUBLIC_URL (the CRM's web address) to add a one-click unsubscribe link. Until then the footer asks people to reply "unsubscribe", and replies are caught when you check replies.</p>`}
      </div>

      <div class="card"><h2>WhatsApp and text messages</h2>
        <p class="sub">Most schools have a phone number but no email. Open a school and press <b>WhatsApp</b> or <b>Text</b> next to its number: the message below opens ready to send from your phone or WhatsApp Web. Placeholders: {{hello}} (“Good day Mrs Kamara,” or “Good day,”) {{school}} {{person}} {{district}} {{town}} {{sender_name}} {{org}} {{library_link}}.</p>
        <div class="settings-row"><label class="field">Your name<input id="p-sender" value="${esc(o.settings.phone_sender)}" placeholder="e.g. Ashish"></label></div>
        <label class="field">WhatsApp message<textarea rows="7" id="p-wa">${esc(o.settings.whatsapp_message)}</textarea></label>
        <label class="field">Text message (keep it short)<textarea rows="3" id="p-sms">${esc(o.settings.sms_message)}</textarea></label>
        <button class="btn small" id="p-save">Save messages</button></div>

      <div class="grid-2">
        <div class="card"><h2>Next up</h2><p class="sub">Who gets which email next.</p>
          ${o.upcoming.length ? `<table class="plain"><tbody>${o.upcoming.map((e) => `<tr><td><a href="#" data-open="${e.school_id}">${esc(e.school)}</a><div class="s-sub">${esc(e.email)}</div></td><td>Email ${e.next_step}</td><td>${esc(e.account || "")}</td><td class="num">${until(e.next_due_at) === "now" ? "due" : "in " + until(e.next_due_at)}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">Nobody in the sequence yet. Select schools on <a href="#/schools?has=email">Find schools</a> and press “Email selected”.</p>`}</div>
        <div class="card"><h2>Recently sent</h2><p class="sub">The last 40 sends and failures.</p>
          ${o.recent.length ? `<table class="plain"><tbody>${o.recent.map((m) => `<tr><td><a href="#" data-open="${m.school_id}">${esc(m.school || "")}</a><div class="s-sub">${esc(m.to_email)}</div></td><td>Email ${m.step}</td><td>${esc(m.account || "")}</td><td>${m.status === "sent" ? ago(m.created_at) : `<span class="error small" title="${esc(m.error)}">failed</span>`}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">Nothing sent yet.</p>`}</div>
      </div>
      <div class="card"><h2>Unsubscribed and bounced</h2><p class="sub">These addresses are never emailed. Paste addresses to add them (one per line or comma-separated).</p>
        <div class="settings-row"><textarea id="sup-in" rows="2" placeholder="someone@example.com"></textarea><button class="btn" id="sup-add">Add to do-not-email list</button><button class="btn ghost" id="sup-show">Show list</button></div><div id="sup-list"></div></div>
    </div>`;

    $("#o-toggle").onclick = async () => {
      if (!on && !o.accounts.some((a) => a.enabled && a.has_password)) { toast("Connect a sender account with its password first."); return; }
      await api("sending", { method: "POST", body: { on: !on } }); toast(on ? "Sending paused" : "Sending started"); renderOutreach();
    };
    $("#o-add")?.addEventListener("click", () => accountDialog(null, presets));
    $$("[data-edit]", el).forEach((b) => b.addEventListener("click", () => accountDialog(o.accounts.find((a) => a.id === +b.dataset.edit), presets)));
    $$("[data-test]", el).forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true; b.textContent = "Testing…";
      const r = await api(`accounts/${b.dataset.test}/test`, { method: "POST" });
      modal(`<h2>Sign-in test</h2><p><b>Sending (SMTP):</b> ${esc(r.smtp)}</p>${r.imap ? `<p><b>Reading replies (IMAP):</b> ${esc(r.imap)}</p>` : ""}<p class="muted small">No email was sent.</p><div class="modal-actions"><button class="btn primary" data-close>OK</button></div>`);
      b.disabled = false; b.textContent = "Test sign-in";
    }));
    $$("[data-replies]", el).forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true; b.textContent = "Checking…";
      const r = await api(`accounts/${b.dataset.replies}/check-replies`, { method: "POST", allowError: true });
      toast(r.error ? r.error : `${r.replied} replies, ${r.unsubscribed} unsubscribes, ${r.bounced} bounces found`); renderOutreach();
    }));
    $$("[data-pause]", el).forEach((b) => b.addEventListener("click", async () => { await api(`accounts/${b.dataset.pause}`, { method: "PATCH", body: { enabled: +b.dataset.to } }); renderOutreach(); }));
    $("#s-save").onclick = async () => { await api("settings", { method: "POST", body: { org_name: $("#s-org").value, library_link: $("#s-link").value, weekdays_only: $("#s-weekdays").checked } }); toast("Saved"); };
    $("#p-save").onclick = async () => { await api("settings", { method: "POST", body: { phone_sender: $("#p-sender").value, whatsapp_message: $("#p-wa").value, sms_message: $("#p-sms").value } }); toast("Messages saved"); };
    $$("[data-save-t]", el).forEach((b) => b.addEventListener("click", async () => {
      const step = b.dataset.saveT, body = {};
      $$(`[data-t="${step}"]`, el).forEach((i) => (body[i.dataset.f] = i.value));
      await api(`templates/${step}`, { method: "PUT", body }); toast(`Email ${step} saved`);
    }));
    $("#o-preview").onclick = async () => {
      const p = await api("preview", { method: "POST", body: {}, allowError: true });
      if (p.error) { toast(p.error); return; }
      modal(`<h2>Preview: ${esc(p.school)}</h2><p class="muted">To ${esc(p.to || "—")}</p>${p.emails.map((e) => `<div class="preview"><div class="muted small">Email ${e.step}</div><b>${esc(e.subject)}</b><pre>${esc(e.body)}</pre></div>`).join("")}<div class="modal-actions"><button class="btn primary" data-close>Close</button></div>`);
    };
    $("#sup-add").onclick = async () => { const r = await api("suppressions", { method: "POST", body: { emails: $("#sup-in").value } }); toast(`${r.added} added`); renderOutreach(); };
    $("#sup-show").onclick = async () => {
      const r = await api("suppressions");
      $("#sup-list").innerHTML = r.rows.length ? `<table class="plain"><tbody>${r.rows.map((x) => `<tr><td>${esc(x.email)}</td><td>${esc(x.reason)}</td><td>${ago(x.created_at)}</td><td><button class="btn small ghost" data-unsup="${esc(x.email)}">Remove</button></td></tr>`).join("")}</tbody></table>` : `<p class="muted">Empty.</p>`;
      $$("[data-unsup]").forEach((b) => (b.onclick = async () => { await api(`suppressions/${encodeURIComponent(b.dataset.unsup)}`, { method: "DELETE" }); $("#sup-show").click(); }));
    };
    $$("[data-open]", el).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openSchool(+a.dataset.open); }));

    // On Vercel there is no background process: this page drives sending while it's open.
    clearInterval(ticker);
    if (on && o.on_vercel) {
      ticker = setInterval(async () => {
        if (parseHash().view !== "outreach") { clearInterval(ticker); return; }
        try { const r = await api("send/tick", { method: "POST" }); if (r.accounts?.some((a) => String(a.status).startsWith("sent"))) renderOutreach(); } catch { /* retry next tick */ }
      }, 20000);
    } else if (on) {
      ticker = setInterval(() => { if (parseHash().view === "outreach" && !$("#modal").open) renderOutreach(); else clearInterval(ticker); }, 30000);
    }
  }

  function accountDialog(a, presets) {
    const v = (k, d = "") => esc(a ? a[k] ?? d : d);
    const prov = a?.provider || "gmail";
    modal(`<h2>${a ? "Edit sender account" : "Connect a sender email"}</h2>
      <form id="acc-form" class="acc-form">
        <label class="field">Email provider<select name="provider">${Object.keys(presets).map((k) => `<option value="${k}" ${k === prov ? "selected" : ""}>${({ gmail: "Gmail", workspace: "Google Workspace", outlook: "Outlook / Microsoft 365", zoho: "Zoho Mail", yahoo: "Yahoo Mail", custom: "Other (SMTP)" })[k]}</option>`).join("")}</select></label>
        <p class="hint" id="acc-help">${esc(presets[prov].help)}</p>
        <div class="tmpl-grid">
          <label class="field">Name on the account<input name="label" value="${v("label")}" placeholder="e.g. Ashish 1"></label>
          <label class="field">Your name (shown to schools)<input name="from_name" value="${v("from_name")}" placeholder="e.g. Ashish Subedi"></label>
          <label class="field">Email address<input name="from_email" type="email" value="${v("from_email")}" required></label>
          <label class="field">App password ${a?.has_password ? "<small>(saved; leave blank to keep)</small>" : ""}<input name="password" type="password" autocomplete="new-password" ${a ? "" : "required"}></label>
        </div>
        <label class="field">Signature<textarea name="signature" rows="3" placeholder="Name&#10;Organisation&#10;Phone / WhatsApp">${v("signature")}</textarea></label>
        <details class="tmpl"><summary>Sending limits</summary>
          <div class="tmpl-grid">
            <label class="field">Max emails a day<input type="number" name="daily_cap" value="${v("daily_cap", 40)}" min="1" max="500"></label>
            <label class="field">Max an hour<input type="number" name="hourly_cap" value="${v("hourly_cap", 10)}" min="1" max="100"></label>
            <label class="field">Seconds between emails (at least)<input type="number" name="min_gap_s" value="${v("min_gap_s", 120)}" min="30"></label>
            <label class="field">Sending hours (GMT)<span class="pair"><input type="number" name="window_start" value="${v("window_start", 8)}" min="0" max="23"> to <input type="number" name="window_end" value="${v("window_end", 18)}" min="1" max="24"></span></label>
            <label class="check-row"><input type="checkbox" name="warmup" ${!a || a.warmup ? "checked" : ""}> Warm up a new mailbox</label>
            <label class="field">Warm-up: start at / add per day<span class="pair"><input type="number" name="warmup_start" value="${v("warmup_start", 10)}" min="1"> / <input type="number" name="warmup_step" value="${v("warmup_step", 5)}" min="0"></span></label>
          </div>
          <p class="muted small">Safe defaults for a normal Gmail or Outlook mailbox: 40 a day, 10 an hour, 2+ minutes apart, warming up from 10 a day. Google Workspace and paid Outlook can go higher once the mailbox has a few weeks of good history.</p></details>
        <details class="tmpl"><summary>Server settings</summary>
          <div class="tmpl-grid">
            <label class="field">Sign-in username<input name="username" value="${v("username")}" placeholder="usually your email address"></label>
            <label class="field">Reply-to (optional)<input name="reply_to" value="${v("reply_to")}"></label>
            <label class="field">SMTP server<input name="smtp_host" value="${v("smtp_host", presets[prov].smtp_host)}"></label>
            <label class="field">SMTP port<input type="number" name="smtp_port" value="${v("smtp_port", presets[prov].smtp_port)}"></label>
            <label class="field">Security<select name="smtp_security">${["starttls", "ssl"].map((x) => `<option ${(a?.smtp_security || presets[prov].smtp_security) === x ? "selected" : ""}>${x}</option>`).join("")}</select></label>
            <label class="field">IMAP server (to catch replies)<input name="imap_host" value="${v("imap_host", presets[prov].imap_host)}"></label>
          </div></details>
        <p class="error" id="acc-err"></p>
        <div class="modal-actions">${a ? `<button type="button" class="btn ghost danger" id="acc-del">Remove account</button>` : ""}<span style="flex:1"></span><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn primary" type="submit">${a ? "Save" : "Connect"}</button></div>
      </form>`, (m) => {
      const f = $("#acc-form", m);
      f.provider.onchange = () => {
        const p = presets[f.provider.value];
        $("#acc-help", m).textContent = p.help;
        f.smtp_host.value = p.smtp_host; f.smtp_port.value = p.smtp_port; f.smtp_security.value = p.smtp_security; f.imap_host.value = p.imap_host;
      };
      f.onsubmit = async (e) => {
        e.preventDefault();
        const body = Object.fromEntries(new FormData(f));
        body.warmup = f.warmup.checked ? 1 : 0;
        if (!body.password) delete body.password;
        if (!body.username) body.username = body.from_email;
        if (!body.label) body.label = body.from_email;
        try {
          await api(a ? `accounts/${a.id}` : "accounts", { method: a ? "PATCH" : "POST", body });
          m.close(); toast(a ? "Saved" : "Connected. Press “Test sign-in” to check it."); renderOutreach();
        } catch (err) { $("#acc-err", m).textContent = err.message; }
      };
      $("#acc-del", m)?.addEventListener("click", async () => {
        if (!confirm("Remove this sender account? Contacts in its sequence must be moved first.")) return;
        const others = state.outreach.accounts.filter((x) => x.id !== a.id);
        try {
          await api(`accounts/${a.id}`, { method: "DELETE", body: a.active && others.length ? { move_to: others[0].id } : {} });
          m.close(); toast("Removed"); renderOutreach();
        } catch (err) { $("#acc-err", m).textContent = err.message; }
      });
    });
  }

  // ------------------------------------------------------------ pipeline
  async function renderPipeline() {
    const el = $("#view-pipeline");
    el.innerHTML = `<div class="page" style="max-width:none;padding-bottom:12px"><div class="page-head"><div><h1>Progress</h1><p>Schools at each stage. Filters from Find schools apply here too. Click a school to move it.</p></div></div></div><div class="board" id="board"><p class="muted">Loading…</p></div>`;
    const d = await api(`pipeline?${filterQS()}`);
    $("#board").innerHTML = STAGES.map(([k, l]) => `<div class="col" data-s="${k}"><h3><span class="stage" data-s="${k}">${l}</span><span class="n">${n(d[k].count)}</span></h3>
      ${d[k].rows.map((r) => `<div class="pcard" data-id="${r.id}"><div class="s-name">${esc(r.name)}</div><div class="s-sub">${esc(r.district || "")}${r.email ? " · " + esc(r.email) : ""}</div></div>`).join("")}
      ${d[k].count > d[k].rows.length ? `<a class="more" href="#/schools?status=${k}">See all ${n(d[k].count)}</a>` : ""}</div>`).join("");
    $$(".pcard").forEach((c) => c.addEventListener("click", () => openSchool(+c.dataset.id)));
  }

  // ------------------------------------------------------------ about the data
  function renderData() {
    $("#view-data").innerHTML = `<div class="page prose">
      <div class="page-head"><div><h1>About the data</h1><p>Where each record comes from and how sure we are of it.</p></div></div>
      <div class="card"><h2>Sources</h2>
        <p>Every email, phone number and named official links to the public page it was copied from (open a school to see it). Nothing is guessed: if an address didn't appear on a public page, it isn't here.</p>
        <ul><li><b>Ministry of Basic and Senior Secondary Education (MBSSE)</b>: published school lists (fee-subsidy schedules with EMIS codes), district education offices and the 2024/25 Annual School Census totals.</li>
          <li><b>Tertiary Education Commission, universities and colleges</b>: registrars, librarians, deans and general addresses from their own sites.</li>
          <li><b>Church and mission education secretariats</b>: Catholic, Methodist, UMC, Anglican, Wesleyan, Baptist, SDA, Islamic and others, plus networks like EducAid.</li>
          <li><b>School websites, alumni associations and NGO project lists</b> for individual schools, by district.</li>
          <li><b>OpenStreetMap</b> (run <code>python3 -m slcrm osm</code> on your computer) for mapped schools and any contacts on the map.</li></ul></div>
      <div class="card"><h2>Email quality</h2>
        <p><b>${CONF_LABEL.high}</b>: on the institution's own site or an official page from 2020 or later. <b>${CONF_LABEL.medium}</b>: a directory, news story, or an older official page. <b>${CONF_LABEL.low}</b>: old or ambiguous; check it before sending.</p></div>
      <div class="card"><h2>Before emailing</h2>
        <p>Sierra Leone's Data Protection Act 2023 covers personal details such as a head teacher's name and email. Email schools about school matters, say who you are, keep volumes modest, and honour every request to stop. The CRM adds an unsubscribe line to each email, stops the sequence when someone replies, and never emails an unsubscribed or bounced address again.</p></div>
    </div>`;
  }

  // ------------------------------------------------------------ boot
  async function boot() {
    const me = await api("me");
    if (me.missing?.length) { document.body.innerHTML = `<div class="page"><h1>Setup needed</h1><p>Set ${me.missing.map(esc).join(", ")} in the hosting settings.</p></div>`; return; }
    if (me.auth && !me.signed_in) { showLogin(); return; }
    $("#app").hidden = false; $("#logout").hidden = !me.auth;
    state.facets = await api("facets");
    route();
  }
  boot().catch((e) => { if (e.message !== "sign_in") console.error(e); });
})();
