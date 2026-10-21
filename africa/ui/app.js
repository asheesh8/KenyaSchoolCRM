/* Africa Schools CRM — front end. No build step; talks to /api/*. */
(() => {
  "use strict";

  // ------------------------------------------------------------ helpers
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nf = new Intl.NumberFormat("en-GB");
  const n = (v) => (v == null ? "—" : nf.format(Math.round(v)));
  const pct = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : "—");
  const plural = (k, one, many) => `${n(k)} ${k === 1 ? one : many || one + "s"}`;
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
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private window */ } },
  };
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2800);
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
  const withCountry = (path) => (state.country ? `${path}${path.includes("?") ? "&" : "?"}country=${state.country}` : path);

  const ICON = {
    email: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    phone: '<svg viewBox="0 0 24 24"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>',
    wa: '<svg viewBox="0 0 24 24"><path d="M4 20l1.3-3.9A8 8 0 1 1 8 19.1z"/></svg>',
    website: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>',
    person: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
    star: '<svg viewBox="0 0 24 24"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg>',
    close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="m5 12 4 4 10-10"/></svg>',
  };

  // ------------------------------------------------------------ constants
  const STAGES = [["new", "New"], ["queued", "In email sequence"], ["contacted", "Contacted"], ["replied", "Replied"],
    ["interested", "Interested"], ["partner", "Partner"], ["not_interested", "Not interested"], ["do_not_contact", "Do not contact"]];
  const STAGE_LABEL = Object.fromEntries(STAGES);
  const GENERIC_LEVELS = [["pre_primary", "Nursery"], ["primary", "Primary"], ["lower_secondary", "Lower secondary"], ["upper_secondary", "Upper secondary"],
    ["tvet", "Technical / vocational"], ["tertiary", "University / college"], ["admin", "Education offices"]];
  const OWNERSHIP = [["government", "Government"], ["government_assisted", "Gov't-assisted"], ["mission", "Mission / faith"],
    ["private", "Private"], ["community", "Community"], ["ngo", "NGO"], ["unknown", "Not recorded"]];
  const OWN_LABEL = Object.fromEntries(OWNERSHIP);
  const SEQ_LABEL = { active: "In sequence", paused: "Paused", done: "Sequence finished", replied: "Replied", unsubscribed: "Unsubscribed", bounced: "Bounced" };
  const CONF_LABEL = { high: "Confirmed source", medium: "Likely", low: "Check first" };
  const WA_LABEL = { sent: "WhatsApp sent", replied: "Replied on WhatsApp", not_on_whatsapp: "Not on WhatsApp", wrong_number: "Wrong number", skipped: "Skipped" };
  const PROVIDERS = { gmail: "Gmail", workspace: "Google Workspace", outlook: "Outlook / Microsoft 365", zoho: "Zoho Mail", yahoo: "Yahoo Mail", custom: "Other (SMTP)" };

  const state = {
    country: (store.get("africa-country") || "").toUpperCase(), countries: [], C: {}, counts: {},
    f: {}, rows: [], total: 0, withEmail: 0, withMobile: 0, page: 1, per: 50, selected: new Set(), open: null,
    facets: null, outreach: null, tmplCountry: "", wa: { f: {}, list: [], i: 0 },
  };
  const cty = () => state.C[state.country] || null;
  const flag = (code) => (state.C[code] ? state.C[code].flag : "");
  const cname = (code) => (state.C[code] ? state.C[code].name : code);
  function levelOptions(code = state.country) {
    const c = state.C[code];
    return c ? c.levels.map((l) => [l.value, l.label, l.detail]) : GENERIC_LEVELS;
  }
  function levelText(keys, code) {
    const m = Object.fromEntries(levelOptions(code));
    return keys.map((k) => m[k] || k).join(", ") || "Level not recorded";
  }
  const label = (key, code = state.country) => (state.C[code] ? state.C[code][key] : ({ district_label: "District", province_label: "Province / region", area_label: "Area" })[key]);

  // ------------------------------------------------------------ auth, theme
  function showLogin() { $("#login").hidden = false; $("#app").hidden = true; }
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("login", { method: "POST", body: { password: $("#pw").value } }); $("#login").hidden = true; boot(); }
    catch (err) { $("#login-error").textContent = err.message === "sign_in" ? "" : err.message; }
  });
  $("#logout").addEventListener("click", async () => { await api("logout", { method: "POST" }); location.reload(); });
  function applyTheme(t) {
    document.documentElement.dataset.theme = t || "light";
    $("#theme-toggle").textContent = t === "dark" ? "Light screen" : "Dark screen";
  }
  $("#theme-toggle").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    store.set("africa-theme", t); applyTheme(t);
  });
  applyTheme(store.get("africa-theme"));

  // ------------------------------------------------------------ country switcher
  function renderCountryTabs() {
    const tabs = [["", "🌍", "All countries", state.counts.total]].concat(state.countries.map((c) => [c.code, c.flag, c.name, state.counts[c.code]]));
    $("#country-tabs").innerHTML = tabs.map(([code, fl, name, k]) => `<button role="tab" aria-selected="${state.country === code}" class="ctab ${state.country === code ? "on" : ""}" data-c="${code}">
      <span class="flag" aria-hidden="true">${fl}</span><span>${esc(name)}</span>${k != null ? `<small>${n(k)}</small>` : ""}</button>`).join("");
    $$("#country-tabs .ctab").forEach((b) => (b.onclick = () => setCountry(b.dataset.c)));
  }
  async function setCountry(code) {
    if (code === state.country) return;
    state.country = code; store.set("africa-country", code);
    // District and level choices belong to one country, so they reset when it changes.
    const { q, sort, has, status, starred, confidence, sequence } = state.f;
    state.f = Object.fromEntries(Object.entries({ q, sort, has, status, starred, confidence, sequence }).filter(([, v]) => v && (!Array.isArray(v) || v.length)));
    state.selected.clear(); state.page = 1; state.wa = { f: {}, list: [], i: 0 };
    state.facets = await api(withCountry("facets"));
    renderCountryTabs();
    route(true);
  }

  // ------------------------------------------------------------ routing
  function parseHash() {
    const [view, qs] = (location.hash.replace(/^#\/?/, "") || "home").split("?");
    return { view: view || "home", params: new URLSearchParams(qs || "") };
  }
  const MULTI_KEYS = ["level", "district", "province", "ownership", "denomination", "status", "has", "missing", "confidence", "kind", "country", "whatsapp", "setting", "gender", "boarding"];
  function go(view, f) {
    if (f) { state.f = f; state.page = 1; }
    const qs = view === "schools" && f ? filterQS() : "";
    const target = `#/${view}${qs ? "?" + qs : ""}`;
    if (location.hash === target) route(true); else location.hash = target;
  }
  function filterQS(extra = {}, f = state.f) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...f, ...extra })) {
      if (Array.isArray(v) ? v.length : v) p.set(k, Array.isArray(v) ? v.join(",") : v);
    }
    if (state.country) p.set("country", state.country);
    return p.toString();
  }
  function route(force) {
    const { view, params } = parseHash();
    if (view !== state.view) { closeDrawer(); state.view = view; }
    $$(".rail a[data-view]").forEach((a) => a.classList.toggle("on", a.dataset.view === view));
    $$(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
    if (view === "schools") {
      if (params.toString() && !force) {
        const f = {};
        for (const [k, v] of params) if (k !== "country") f[k] = MULTI_KEYS.includes(k) ? v.split(",") : v;
        state.f = f;
      }
      renderFilters(); loadSchools();
    } else if (view === "home") renderHome();
    else if (view === "email") renderEmail();
    else if (view === "whatsapp") renderWhatsApp();
    else if (view === "replies") renderReplies();
    else if (view === "progress") renderProgress();
    else if (view === "data") renderData();
  }
  window.addEventListener("hashchange", () => route());

  // ------------------------------------------------------------ home
  async function renderHome() {
    const el = $("#view-home");
    el.innerHTML = `<div class="page"><p class="muted">Loading…</p></div>`;
    const [s, o] = await Promise.all([api(withCountry("summary")), api(withCountry("outreach"))]);
    const c = cty();
    const setupDone = {
      accounts: o.accounts.length > 0, details: o.settings.org !== "our ministry" && !!o.settings.library_link,
      campaign: Object.values(o.sequence).reduce((a, b) => a + b, 0) > 0, sending: o.settings.sending,
      whatsapp: Object.entries(s.whatsapp).some(([k, v]) => k !== "not yet" && v > 0),
    };
    const setup = `<div class="card setup"><h2>Getting started</h2><p class="sub">Five steps, in order. Each one links to where you do it.</p>
      <ol class="steps">
        ${[["accounts", "#/email", `Connect your email accounts`, `${o.accounts.length} of ${o.max_accounts} connected`],
          ["details", "#/email", "Add your name, organisation and library link", setupDone.details ? "done" : "used in every email and WhatsApp message"],
          ["campaign", "#/email", "Choose schools to email", setupDone.campaign ? `${n(Object.values(o.sequence).reduce((a, b) => a + b, 0))} addresses in the sequence` : "pick a country, level and district"],
          ["sending", "#/email", "Switch sending on", setupDone.sending ? "sending now, inside each account's limits" : "nothing is sent until you do"],
          ["whatsapp", "#/whatsapp", "Work through the WhatsApp list", `${n(s.with_mobile)} schools have a mobile number`]]
          .map(([k, href, t, sub], i) => `<li class="${setupDone[k] ? "done" : ""}"><a href="${href}"><span class="num">${setupDone[k] ? ICON.check : i + 1}</span><span><b>${t}</b><small>${esc(sub)}</small></span></a></li>`).join("")}
      </ol></div>`;
    const hero = `<div class="hero">
        <div><div class="big">${n(s.total)}</div><div class="lbl">${c ? `schools and offices in ${esc(c.name)}` : "schools and offices on file"}</div></div>
        <a class="hero-link" href="#/schools?has=email"><div class="mid">${n(s.with_email)}</div><div class="lbl">with an email</div></a>
        <a class="hero-link" href="#/schools?has=mobile"><div class="mid">${n(s.with_mobile)}</div><div class="lbl">with a WhatsApp-able mobile</div></a>
        <a class="hero-link" href="#/schools?status=contacted"><div class="mid">${n(s.contacted)}</div><div class="lbl">contacted</div></a>
        <a class="hero-link" href="#/replies"><div class="mid">${n(s.replied)}</div><div class="lbl">replied</div></a></div>`;
    const recent = `<div class="card"><h2>Recent activity</h2><p class="sub">Emails, WhatsApp messages, replies and notes.</p>
      <div class="recent">${s.recent.length ? s.recent.map((a) => `<a href="#" data-open="${a.school_id}"><span class="body-top"><b>${flag(a.country)} ${esc(a.name)}</b></span><span class="when">${ago(a.created_at)}</span><span class="body">${esc(a.body || a.kind)}</span></a>`).join("") : `<p class="muted">Nothing yet.</p>`}</div></div>`;
    const T = s.total || 1;
    const stages = `<div class="card"><h2>Outreach stages</h2><p class="sub">Click a stage to list its schools. ${n(s.sent_total)} emails sent so far.</p>
      <div class="stage-bars">${STAGES.map(([k, l]) => `<div class="sbar" data-status="${k}" role="button" tabindex="0"><span class="k">${l}</span>
        <span class="track"><span class="fill" style="width:${(100 * (s.statuses[k] || 0)) / T}%"></span></span><span class="v">${n(s.statuses[k] || 0)}</span></div>`).join("")}</div></div>`;
    if (!c) {
      el.innerHTML = `<div class="page">
        <div class="page-head"><div><h1>Schools across Africa</h1><p>One list of schools, colleges and education offices in ${state.countries.map((x) => esc(x.name)).join(", ").replace(/, ([^,]*)$/, " and $1")}, with email and WhatsApp outreach from one place. Pick a country above to work on just that country.</p></div></div>
        ${hero}
        <div class="country-cards">${s.countries.map((k) => `<div class="ccard">
          <div class="ccard-top"><span class="flag big">${k.flag}</span><div><h2>${esc(k.name)}</h2><div class="s-sub">${n(k.total)} on file</div></div></div>
          <dl class="ccard-stats"><div><dt>With email</dt><dd>${n(k.with_email)}</dd></div><div><dt>Mobiles</dt><dd>${n(k.with_mobile)}</dd></div>
            <div><dt>Emailed</dt><dd>${n(k.emailed)}</dd></div><div><dt>WhatsApp sent</dt><dd>${n(k.whatsapped)}</dd></div><div><dt>Replied</dt><dd>${n(k.replied)}</dd></div></dl>
          ${k.total ? `<button class="btn primary" data-country="${k.code}">Open ${esc(k.name)}</button>` : `<p class="muted small">No data loaded yet. See <a href="#/data">Data &amp; help</a>.</p>`}</div>`).join("")}</div>
        <div class="grid-2">${setup}${stages}</div>
        ${recent}</div>`;
    } else {
      const maxLv = Math.max(...s.by_level.map((l) => l.schools), 1);
      const hasCensus = s.by_district.some((d) => d.census), hasPop = s.by_district.some((d) => d.population);
      el.innerHTML = `<div class="page">
        <div class="page-head"><div><h1>${c.flag} Schools in ${esc(c.name)}</h1><p>${c.census_total ? `The ${esc(c.census_note)} counts ${n(c.census_total)} schools. ` : ""}Emails go out in ${esc(c.timezone)}.</p></div>
          <div class="head-acts"><a class="btn" href="#/whatsapp">WhatsApp list</a><a class="btn primary" href="#/email">Email schools</a></div></div>
        ${hero}
        <div class="grid-2">
          <div class="card"><h2>By level</h2><p class="sub">A school counts once for each level it teaches. Click a bar to list them.</p>
            <div class="stage-bars">${s.by_level.map((l) => `<div class="sbar" data-level="${l.key}" role="button" tabindex="0">
              <span class="k">${esc(l.label)}${l.detail ? `<small>${esc(l.detail)}</small>` : ""}</span><span class="track"><span class="fill" style="width:${(100 * l.schools) / maxLv}%"></span></span>
              <span class="v">${n(l.schools)}<small> · ${n(l.with_email)} email</small></span></div>`).join("")}</div></div>
          ${stages}
        </div>
        <div class="card flush"><table class="plain"><thead><tr><th>${esc(c.district_label)}</th><th>${esc(c.province_label)}</th><th class="num">On file</th>${hasCensus ? `<th class="num">Census</th>` : ""}${hasPop ? `<th class="num">People</th>` : ""}<th class="num">With email</th><th class="num">WhatsApp-able</th><th class="num">Contacted</th><th class="num">Replied</th></tr></thead>
          <tbody>${s.by_district.map((d) => `<tr data-district="${esc(d.district)}"><td>${esc(d.district || "Not recorded")}</td><td>${esc(d.province || "")}</td>
            <td class="num">${n(d.schools)}${d.census ? ` <small class="muted">${pct(d.schools, d.census)}</small>` : ""}</td>${hasCensus ? `<td class="num">${n(d.census)}</td>` : ""}${hasPop ? `<td class="num">${n(d.population)}</td>` : ""}
            <td class="num">${n(d.with_email)}</td><td class="num">${n(d.with_mobile)}</td><td class="num">${n(d.contacted)}</td><td class="num">${n(d.replied)}</td></tr>`).join("")}</tbody></table></div>
        <div class="grid-2">
          <div class="card"><h2>Email quality</h2><p class="sub">How sure we are each address belongs to the institution.</p>
            <div class="stage-bars">${["high", "medium", "low"].map((k) => `<div class="sbar" data-conf="${k}" role="button" tabindex="0"><span class="k">${CONF_LABEL[k]}</span>
              <span class="track"><span class="fill" style="width:${(100 * (s.email_confidence[k] || 0)) / Math.max(1, ...Object.values(s.email_confidence))}%"></span></span><span class="v">${n(s.email_confidence[k] || 0)}</span></div>`).join("")}</div></div>
          ${recent}</div>
        ${setup}</div>`;
    }
    $$("[data-country]", el).forEach((b) => (b.onclick = () => setCountry(b.dataset.country)));
    $$(".sbar[data-level]", el).forEach((b) => (b.onclick = () => go("schools", { level: [b.dataset.level] })));
    $$(".sbar[data-status]", el).forEach((b) => (b.onclick = () => go("schools", { status: [b.dataset.status] })));
    $$(".sbar[data-conf]", el).forEach((b) => (b.onclick = () => go("schools", { confidence: [b.dataset.conf] })));
    $$("tr[data-district]", el).forEach((r) => (r.onclick = () => go("schools", r.dataset.district ? { district: [r.dataset.district] } : { missing: [] })));
    $$("[data-open]", el).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openSchool(+a.dataset.open); }));
  }

  // ------------------------------------------------------------ schools: filters + list
  const pills = (key, opts, f = state.f) => `<div class="pills">${opts.map(([v, l, d]) =>
    `<button type="button" class="pill ${(f[key] || []).includes(v) ? "on" : ""}" data-k="${key}" data-v="${esc(v)}" ${d ? `title="${esc(d)}"` : ""}>${esc(l)}</button>`).join("")}</div>`;
  function renderFilters() {
    const f = state.f, fc = state.facets, c = cty();
    if (!fc) return;
    const ex = fc.has_extra || {};
    $("#filters").innerHTML = `<h2>Filters <button class="linklike only-narrow" id="f-done">Done</button></h2>
      ${c ? "" : `<div class="fgroup"><div class="flabel">Country</div>${pills("country", state.countries.map((x) => [x.code, `${x.flag} ${x.name}`]))}</div>`}
      <div class="fgroup"><div class="flabel">Level</div>${pills("level", levelOptions())}</div>
      ${c ? `<div class="fgroup"><div class="flabel">${esc(c.district_label)}</div>
        <select id="f-district" class="big-select"><option value="">All ${fc.districts.length} ${esc(c.district_label.toLowerCase())}${/y$/.test(c.district_label) ? "" : "s"}</option>${fc.districts.map((d) => `<option ${(f.district || []).includes(d.value) ? "selected" : ""}>${esc(d.value)}</option>`).join("")}</select>
        ${fc.provinces.length ? `<div class="flabel sub">${esc(c.province_label)}</div>${pills("province", fc.provinces.map((p) => [p, p]))}` : ""}</div>` : ""}
      <div class="fgroup"><div class="flabel">How to reach them</div>${pills("has", [["contact", "Any contact"], ["email", "Has email"], ["mobile", "WhatsApp-able mobile"], ["phone", "Any phone"], ["leader", "Named head"], ["website", "Website"]])}</div>
      <div class="fgroup"><div class="flabel">Email quality</div>${pills("confidence", [["high", CONF_LABEL.high], ["medium", CONF_LABEL.medium], ["low", CONF_LABEL.low]])}</div>
      <div class="fgroup"><div class="flabel">Ownership</div>${pills("ownership", OWNERSHIP)}</div>
      <details class="fgroup more" ${f.denomination || f.status || f.sequence || f.kind || f.whatsapp || f.campaign ? "open" : ""}><summary>More filters</summary>
        <div class="flabel">Stage</div>${pills("status", STAGES)}
        <div class="flabel">Faith</div>${pills("denomination", fc.denominations.map((d) => [d, d]))}
        <div class="flabel">Type</div>${pills("kind", [["school", "Schools"], ["office", "Gov't offices"], ["secretariat", "Education secretariats"], ["association", "Associations"], ["ngo", "NGOs"]])}
        <div class="flabel">WhatsApp</div>${pills("whatsapp", [["none", "Not messaged yet"], ...Object.entries(WA_LABEL)])}
        ${ex.setting ? `<div class="flabel">Town or countryside</div>${pills("setting", [["urban", "Town / city"], ["peri_urban", "Edge of town"], ["rural", "Countryside"]])}` : ""}
        ${ex.gender ? `<div class="flabel">Boys / girls</div>${pills("gender", [["boys", "Boys"], ["girls", "Girls"], ["mixed", "Mixed"]])}` : ""}
        ${ex.boarding ? `<div class="flabel">Boarding</div>${pills("boarding", [["boarding", "Boarding"], ["day", "Day"], ["day_boarding", "Day and boarding"]])}` : ""}
        <div class="flabel">Email sequence</div>
        <select id="f-seq"><option value="">Any</option><option value="none" ${f.sequence === "none" ? "selected" : ""}>Not emailed yet</option>${Object.entries(SEQ_LABEL).map(([k, l]) => `<option value="${k}" ${f.sequence === k ? "selected" : ""}>${l}</option>`).join("")}</select>
        ${fc.campaigns.length ? `<div class="flabel">Campaign</div><select id="f-camp"><option value="">Any</option>${fc.campaigns.map((x) => `<option ${f.campaign === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>` : ""}
        <label class="check-row"><input type="checkbox" id="f-star" ${f.starred === "1" ? "checked" : ""}> Starred only</label>
      </details>
      <button class="btn ghost" id="f-clear">Start over</button>`;
    $$("#filters .pill").forEach((b) => (b.onclick = () => {
      const k = b.dataset.k, v = b.dataset.v, cur = new Set(state.f[k] || []);
      cur.has(v) ? cur.delete(v) : cur.add(v);
      state.f = { ...state.f, [k]: [...cur] }; state.page = 1; sync();
    }));
    const on = (id, fn) => { const x = $(id); if (x) x.onchange = (e) => { fn(e.target); state.page = 1; sync(); }; };
    on("#f-district", (t) => (state.f = { ...state.f, district: t.value ? [t.value] : [] }));
    on("#f-seq", (t) => (state.f = { ...state.f, sequence: t.value }));
    on("#f-camp", (t) => (state.f = { ...state.f, campaign: t.value }));
    on("#f-star", (t) => (state.f = { ...state.f, starred: t.checked ? "1" : "" }));
    $("#f-clear").onclick = () => { state.f = {}; state.page = 1; $("#q").value = ""; sync(); };
    $("#f-done").onclick = () => $("#filters").classList.remove("show");
    $("#q").value = f.q || "";
    $("#sort").value = f.sort || "best";
  }
  function sync() { history.replaceState(null, "", `#/schools?${filterQS()}`); renderFilters(); loadSchools(); }
  $("#q").addEventListener("input", debounce((e) => { state.f = { ...state.f, q: e.target.value }; state.page = 1; sync(); }, 250));
  $("#sort").addEventListener("change", (e) => { state.f = { ...state.f, sort: e.target.value }; sync(); });
  $("#show-filters").addEventListener("click", () => $("#filters").classList.toggle("show"));
  $("#export").addEventListener("click", (e) => { e.preventDefault(); location.href = `/api/export.csv?${filterQS()}`; });

  async function loadSchools() {
    const d = await api(`schools?${filterQS({ page: state.page, per: state.per })}`);
    Object.assign(state, { rows: d.rows, total: d.total, withEmail: d.with_email, withMobile: d.with_mobile });
    renderChips(); renderRows();
  }
  function chipLabel(k, x) {
    if (k === "country") return `${flag(x)} ${cname(x)}`;
    if (k === "level") return Object.fromEntries(levelOptions())[x] || x;
    if (k === "whatsapp") return x === "none" ? "Not WhatsApped yet" : WA_LABEL[x];
    if (k === "has") return ({ contact: "Any contact", email: "Has email", mobile: "WhatsApp-able", phone: "Has phone", leader: "Named head", website: "Website" })[x];
    if (k === "sequence") return x === "none" ? "Not emailed yet" : SEQ_LABEL[x];
    if (k === "starred") return "Starred";
    if (k === "campaign") return `Campaign: ${x}`;
    return STAGE_LABEL[x] || OWN_LABEL[x] || CONF_LABEL[x] || x;
  }
  function renderChips() {
    const chips = [];
    for (const [k, v] of Object.entries(state.f)) {
      if (["sort", "q"].includes(k) || !(Array.isArray(v) ? v.length : v)) continue;
      for (const x of Array.isArray(v) ? v : [v]) chips.push(`<span class="chip">${esc(chipLabel(k, x))}<button data-k="${k}" data-v="${esc(x)}" aria-label="Remove">×</button></span>`);
    }
    $("#active-chips").innerHTML = chips.join("");
    $$("#active-chips button").forEach((b) => (b.onclick = () => {
      const v = state.f[b.dataset.k];
      state.f = { ...state.f, [b.dataset.k]: Array.isArray(v) ? v.filter((x) => x !== b.dataset.v) : "" };
      state.page = 1; sync();
    }));
  }
  function rowHTML(r) {
    const seq = r.sequence ? r.sequence.split(":")[0] : null;
    const all = !state.country;
    return `<tr data-id="${r.id}" class="${state.open === r.id ? "open" : ""}">
      <td class="c-check"><input type="checkbox" data-sel="${r.id}" ${state.selected.has(r.id) ? "checked" : ""} aria-label="Select ${esc(r.name)}"></td>
      <td><div class="s-name">${r.starred ? `<span class="star">★</span>` : ""}${all ? `<span class="flag" title="${esc(cname(r.country))}">${flag(r.country)}</span>` : ""}${esc(r.name)}</div>
        <div class="s-sub">${esc(levelText(r.level_keys, r.country))}${r.ownership && r.ownership !== "unknown" ? " · " + esc(OWN_LABEL[r.ownership]) : ""}${r.denomination ? " · " + esc(r.denomination) : ""}</div></td>
      <td class="where">${esc(r.district || "—")}<div class="s-sub">${esc([r.town, r.area].filter(Boolean).join(", "))}</div></td>
      <td class="reach">${r.email ? `<div class="reach-line">${ICON.email}<span>${esc(r.email)}</span>${r.n_emails > 1 ? `<span class="badge">+${r.n_emails - 1}</span>` : ""}<span class="badge conf-${esc(r.confidence)}" title="${esc(CONF_LABEL[r.confidence] || "")}">${esc(CONF_LABEL[r.confidence] || "")}</span></div>` : ""}
        ${r.mobile ? `<div class="reach-line wa">${ICON.wa}<span>${esc(r.mobile)}</span>${r.whatsapp_status ? `<span class="badge">${esc(WA_LABEL[r.whatsapp_status])}</span>` : ""}</div>` : r.phone ? `<div class="reach-line">${ICON.phone}<span>${esc(r.phone)}</span></div>` : ""}
        ${!r.phone && !r.email ? `<span class="muted">${r.website ? "Website only" : "No contact yet"}</span>` : ""}</td>
      <td class="head">${r.leader ? esc(r.leader) : `<span class="muted">—</span>`}</td>
      <td><span class="stage" data-s="${r.status}">${STAGE_LABEL[r.status]}</span>${seq ? `<div class="s-sub">${esc(SEQ_LABEL[seq] || seq)}</div>` : ""}</td></tr>`;
  }
  function renderRows() {
    const { rows, total, page, per } = state;
    $("#table-head").innerHTML = `<th class="c-check"><input type="checkbox" id="check-all" aria-label="Select all on this page"></th>
      <th>School</th><th>${esc(state.country ? cty().district_label : "Where")}</th><th>Email and WhatsApp</th><th>Head / official</th><th>Stage</th>`;
    $("#count").innerHTML = `<strong>${n(total)}</strong> match · <strong>${n(state.withEmail)}</strong> with email · <strong>${n(state.withMobile)}</strong> WhatsApp-able`;
    $("#rows").innerHTML = rows.length ? rows.map(rowHTML).join("") :
      `<tr><td colspan="6"><div class="empty"><h3>No schools match</h3>Remove one of your choices above, or press “Start over”.</div></td></tr>`;
    const from = (page - 1) * per;
    $("#pager").innerHTML = total > per ? `<span>${n(from + 1)}–${n(Math.min(from + per, total))} of ${n(total)}</span>
      <span><button class="btn small" id="prev" ${page > 1 ? "" : "disabled"}>Previous</button>
      <button class="btn small" id="next" ${from + per < total ? "" : "disabled"}>Next</button></span>` : "";
    $("#prev")?.addEventListener("click", () => { state.page--; loadSchools(); });
    $("#next")?.addEventListener("click", () => { state.page++; loadSchools(); });
    $$("#rows tr[data-id]").forEach((tr) => tr.addEventListener("click", (e) => { if (!e.target.matches("input")) openSchool(+tr.dataset.id); }));
    $$("#rows input[data-sel]").forEach((c) => c.addEventListener("change", () => {
      const id = +c.dataset.sel; c.checked ? state.selected.add(id) : state.selected.delete(id); renderBulk();
    }));
    const all = $("#check-all");
    all.checked = rows.length && rows.every((r) => state.selected.has(r.id));
    all.onchange = (e) => { state.rows.forEach((r) => (e.target.checked ? state.selected.add(r.id) : state.selected.delete(r.id))); renderRows(); };
    renderBulk();
  }
  function renderBulk() {
    const k = state.selected.size;
    $("#bulk").innerHTML = `${k ? `<b>${n(k)} selected</b> <button class="btn small primary" id="b-email">Email selected</button>
      <select id="b-stage" class="small"><option value="">Move to stage…</option>${STAGES.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
      <button class="btn small ghost" id="b-clear">Clear</button>` : ""}
      ${!k && state.withEmail ? `<button class="btn small" id="b-email-all">Email all ${n(state.withEmail)} with an address</button>` : ""}
      ${!k && state.withMobile ? `<button class="btn small" id="b-wa-all">WhatsApp these ${n(state.withMobile)}</button>` : ""}`;
    $("#b-email")?.addEventListener("click", () => enrollDialog({ ids: [...state.selected] }));
    $("#b-email-all")?.addEventListener("click", () => enrollDialog({ filter: Object.fromEntries(new URLSearchParams(filterQS())) }));
    $("#b-wa-all")?.addEventListener("click", () => { state.wa = { f: { ...state.f }, list: [], i: 0 }; go("whatsapp"); });
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
  function campaignName(filter) {
    const month = new Date().toLocaleDateString("en-GB", { month: "short", year: "numeric" });
    const code = (filter && filter.country) || state.country;
    const parts = [code && !code.includes(",") ? cname(code) : "Africa"];
    const lv = filter && filter.level ? String(filter.level).split(",").filter(Boolean) : [];
    if (lv.length) parts.push(levelText(lv, code && !code.includes(",") ? code : ""));
    if (filter && filter.district) parts.push(String(filter.district).split(",").join(", "));
    return `${parts.join(" · ")} · ${month}`;
  }
  async function enrollDialog(target) {
    const [acc, pre] = await Promise.all([api("accounts"), api("enroll", { method: "POST", body: { ...target, dry_run: true } })]);
    const usable = acc.accounts.filter((a) => a.enabled);
    if (!acc.accounts.length) {
      modal(`<h2>Connect an email account first</h2><p>Add at least one of your ${acc.max} sender accounts on the Email page, then come back and pick schools.</p>
        <div class="modal-actions"><button class="btn ghost" data-close>Close</button><a class="btn primary" href="#/email" data-close>Connect an account</a></div>`);
      return;
    }
    const byC = Object.entries(pre.by_country).map(([k, v]) => `${flag(k)} ${n(v)} in ${esc(cname(k))}`).join(" · ");
    modal(`<h2>Start the email sequence</h2>
      <p><b>${plural(pre.with_email, "school")}</b> with an email address ${target.ids ? `out of ${n(pre.schools)} selected` : ""}${byC ? ` (${byC})` : ""}. Email 1 goes first, then the follow-ups, each only if they haven't replied or unsubscribed.</p>
      <label class="field">Campaign name (to track replies)<input id="e-camp" value="${esc(campaignName(target.filter))}"></label>
      <label class="field">Send from
        <select id="e-acc"><option value="">Spread across all ${usable.length} active accounts (recommended)</option>
          ${acc.accounts.map((a) => `<option value="${a.id}">${esc(a.label)} — ${esc(a.from_email)}${a.enabled ? "" : " (paused)"}</option>`).join("")}</select></label>
      <label class="field">Who to email at each school
        <select id="e-mode"><option value="best">The main address only</option><option value="all">Every address on file (head, office, etc.)</option></select></label>
      <label class="field">When
        <select id="e-spread"><option value="0">As soon as each account's limits allow</option><option value="72">Spread the first emails over 3 days</option><option value="168">Spread the first emails over a week</option></select></label>
      <p class="muted small">Unsubscribed, bounced and already-emailed addresses are skipped. Nothing sends until sending is switched on, and then only inside each account's limits and each school's working hours.</p>
      <div class="modal-actions"><button class="btn ghost" data-close>Cancel</button><button class="btn primary" id="e-go" ${pre.with_email ? "" : "disabled"}>Add ${plural(pre.with_email, "school")}</button></div>`, (m) => {
      $("#e-go", m).onclick = async () => {
        const r = await api("enroll", { method: "POST", body: { ...target, account_id: $("#e-acc", m).value || null, mode: $("#e-mode", m).value, campaign: $("#e-camp", m).value, spread_hours: +$("#e-spread", m).value } });
        m.close();
        toast(`${n(r.enrolled)} added to the sequence${r.already ? `, ${n(r.already)} already in it` : ""}${r.suppressed ? `, ${n(r.suppressed)} unsubscribed` : ""}${r.no_account ? `, ${n(r.no_account)} with no account for their country` : ""}`);
        state.selected.clear();
        route(true);
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
  function phoneLinks(c) {
    const L = c.links;
    return `<a href="${esc(L.tel)}">${esc(c.value)}</a>${c.mobile ? ` <span class="badge wa">WhatsApp-able</span>` : ""}
      <div class="phone-acts">${c.mobile ? `<a class="btn small wa" target="_blank" rel="noopener" href="${esc(L.whatsapp)}" data-wa="${esc(c.value)}">WhatsApp</a>` : ""}
      <a class="btn small" href="${esc(L.sms)}" data-sms="${esc(c.value)}">Text</a><a class="btn small" href="${esc(L.tel)}">Call</a></div>`;
  }
  function renderDrawer(s) {
    const d = $("#drawer"), C = state.C[s.country];
    const kinds = ["person", "email", "phone", "website"];
    const contacts = s.contacts.slice().sort((a, b) => kinds.indexOf(a.kind) - kinds.indexOf(b.kind) || b.active - a.active || (b.mobile ? 1 : 0) - (a.mobile ? 1 : 0));
    const val = (c) => c.kind === "email" ? `<a href="mailto:${esc(c.value)}">${esc(c.value)}</a>` : c.kind === "phone" ? phoneLinks(c)
      : c.kind === "website" ? `<a href="${esc(c.value)}" target="_blank" rel="noopener">${esc(c.value.replace(/^https?:\/\//, ""))}</a>` : esc(c.value);
    d.innerHTML = `
      <div class="d-head"><div class="d-top">
          <div><h2>${esc(s.name)}</h2><div class="s-sub">${C.flag} ${esc(C.name)} · ${esc(levelText(s.level_keys, s.country))} · ${esc(s.district || `${C.district_label} not recorded`)}</div></div>
          <div class="d-actions"><button class="icon-btn ${s.starred ? "on" : ""}" id="d-star" title="Star">${ICON.star}</button>
            <button class="icon-btn" id="d-close" title="Close (Esc)">${ICON.close}</button></div></div>
        <div class="stage-q">Stage</div>
        <div class="stages">${STAGES.map(([v, l]) => `<button data-s="${v}" class="${s.status === v ? "on" : ""}">${l}</button>`).join("")}</div>
        <div class="quick">${s.email ? `<button class="btn primary" id="d-enroll">Add to email sequence</button>` : ""}
          ${s.mobile ? `<button class="btn wa" id="d-wa">Mark WhatsApp sent</button>` : ""}
          ${s.whatsapp_status ? `<span class="badge">${esc(WA_LABEL[s.whatsapp_status])} ${ago(s.whatsapp_at)}</span> <button class="linklike small" id="d-wa-reset">undo</button>` : ""}</div>
      </div>
      <div class="d-body">
        ${s.enrollments.length ? `<section class="d-sec"><h3>Email sequence</h3>${s.enrollments.map((e) => `<div class="contact"><span class="ci on">${ICON.email}</span>
          <div><div class="v">${esc(e.email)} <span class="badge">${esc(SEQ_LABEL[e.status] || e.status)}</span></div>
          <div class="meta">${e.campaign ? esc(e.campaign) + " · " : ""}from ${esc(e.account_label || "a removed account")} · ${e.status === "active" ? `email ${e.next_step} due ${until(e.next_due_at) === "now" ? "now" : "in " + until(e.next_due_at)}` : `updated ${ago(e.updated_at)}`}</div>
          ${e.reply_snippet ? `<div class="snippet">“${esc(e.reply_snippet)}”</div>` : ""}</div>
          <div class="acts">${e.status === "active" ? `<button class="btn small" data-enr="${e.id}" data-a="pause">Pause</button>` : ""}${e.status === "paused" ? `<button class="btn small" data-enr="${e.id}" data-a="resume">Resume</button>` : ""}
            ${["active", "paused", "done"].includes(e.status) ? `<button class="btn small" data-enr="${e.id}" data-a="replied">They replied</button><button class="btn small" data-enr="${e.id}" data-a="unsubscribe">Unsubscribe</button>` : ""}</div></div>`).join("")}</section>` : ""}
        <section class="d-sec"><h3>Contacts</h3>
          ${contacts.length ? contacts.map((c) => `<div class="contact ${c.active ? "" : "stale"}">
            <span class="ci ${c.active ? "on" : ""}">${ICON[c.kind] || ICON.website}</span>
            <div><div class="v">${val(c)}${c.role && c.kind === "person" ? ` <span class="badge">${esc(c.role)}</span>` : ""}${c.person && c.kind !== "person" ? ` <span class="badge">${esc(c.person)}${c.role ? ", " + esc(c.role) : ""}</span>` : ""}${c.confidence && c.kind === "email" ? ` <span class="badge conf-${esc(c.confidence)}">${esc(CONF_LABEL[c.confidence])}</span>` : ""}${c.suppressed ? ` <span class="badge warn">unsubscribed</span>` : ""}</div>
              <div class="meta">${c.source_url ? `source: <a href="${esc(c.source_url)}" target="_blank" rel="noopener">${esc(c.source_url.replace(/^https?:\/\/(www\.)?/, "").slice(0, 60))}</a>` : esc(c.source)} · ${c.active ? `added ${ago(c.first_seen)}` : "marked wrong / old"}</div></div>
            <div class="acts"><button class="btn small ghost" data-active="${c.id}" data-to="${c.active ? 0 : 1}">${c.active ? "Wrong / old" : "Put back"}</button></div>
          </div>`).join("") : `<p class="muted">No contact details yet. Add what you find below.</p>`}
          <form class="add-contact" id="d-add">
            <select name="kind"><option value="email">Email</option><option value="phone">Phone</option><option value="person">Person</option><option value="website">Website</option></select>
            <input name="value" placeholder="head@school.org, 0772 123 456, …" required>
            <input name="role" placeholder="Role (optional)">
            <button class="btn" type="submit">Add</button>
          </form></section>
        <section class="d-sec"><h3>Log activity</h3>
          <form class="log-form" id="d-log"><select name="kind"><option value="note">Note</option><option value="call">Call</option><option value="whatsapp">WhatsApp</option><option value="sms">Text message</option><option value="email">Email</option><option value="meeting">Meeting</option><option value="visit">Visit</option></select>
            <textarea name="body" rows="2" placeholder="What happened?" required></textarea><button class="btn" type="submit">Save</button></form>
          ${s.activities.map((a) => `<div class="activity ${a.kind === "system" ? "system" : ""}"><span class="when">${ago(a.created_at)} · ${esc(a.kind)}</span><div class="body">${esc(a.body)}</div></div>`).join("")}</section>
        <section class="d-sec"><h3>About</h3><dl class="facts">
          <div><dt>Ownership</dt><dd>${esc(OWN_LABEL[s.ownership] || "Not recorded")}${s.denomination ? ` · ${esc(s.denomination)}` : ""}</dd></div>
          <div><dt>Where</dt><dd>${esc([s.town, s.area && `${s.area} (${C.area_label.toLowerCase()})`, s.district, s.province].filter(Boolean).join(", ") || "—")}</dd></div>
          ${s.emis_code ? `<div><dt>School code</dt><dd>${esc(s.emis_code)}</dd></div>` : ""}
          ${s.students ? `<div><dt>Pupils</dt><dd>${n(s.students)}</dd></div>` : ""}
          ${s.address ? `<div><dt>Address</dt><dd>${esc(s.address)}</dd></div>` : ""}
          ${s.lat ? `<div><dt>Map</dt><dd><a target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${s.lat}&mlon=${s.lon}#map=16/${s.lat}/${s.lon}">Open map</a></dd></div>` : ""}
          ${s.notes ? `<div class="wide"><dt>Notes</dt><dd>${esc(s.notes)}</dd></div>` : ""}
        </dl></section>
        ${s.sources.length ? `<section class="d-sec"><h3>Sources</h3>${s.sources.map((u) => u.startsWith("http") ? `<div class="srcline"><a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a></div>` : `<div class="srcline">${esc(u)}</div>`).join("")}</section>` : ""}
      </div>`;
    $("#d-close").onclick = closeDrawer;
    $("#d-star").onclick = async () => renderDrawer(await api(`schools/${s.id}`, { method: "PATCH", body: { starred: !s.starred } }));
    $("#d-enroll")?.addEventListener("click", () => enrollDialog({ ids: [s.id] }));
    $("#d-wa")?.addEventListener("click", async () => { await api(`whatsapp/${s.id}`, { method: "POST", body: { outcome: "sent" } }); toast("Recorded"); openSchool(s.id); refreshList(); });
    $("#d-wa-reset")?.addEventListener("click", async () => { await api(`whatsapp/${s.id}`, { method: "DELETE" }); openSchool(s.id); refreshList(); });
    $$("[data-wa]", d).forEach((a) => a.addEventListener("click", () => setTimeout(() => askOutcome(s, a.dataset.wa), 600)));
    $$("[data-sms]", d).forEach((a) => a.addEventListener("click", () => setTimeout(() => askOutcome(s, a.dataset.sms, true), 600)));
    $$(".stages button", d).forEach((b) => (b.onclick = async () => { renderDrawer(await api(`schools/${s.id}`, { method: "PATCH", body: { status: b.dataset.s } })); toast(`Moved to ${STAGE_LABEL[b.dataset.s]}`); refreshList(); }));
    $$("[data-active]", d).forEach((b) => (b.onclick = async () => renderDrawer(await api(`contacts/${b.dataset.active}`, { method: "PATCH", body: { active: +b.dataset.to } }))));
    $$("[data-enr]", d).forEach((b) => (b.onclick = async () => { await api(`enrollments/${b.dataset.enr}`, { method: "POST", body: { action: b.dataset.a } }); openSchool(s.id); refreshList(); }));
    $("#d-add").onsubmit = async (e) => {
      e.preventDefault();
      try { renderDrawer(await api(`schools/${s.id}/contacts`, { method: "POST", body: Object.fromEntries(new FormData(e.target)) })); toast("Added"); } catch (err) { toast(err.message); }
    };
    $("#d-log").onsubmit = async (e) => {
      e.preventDefault(); renderDrawer(await api(`schools/${s.id}/activities`, { method: "POST", body: Object.fromEntries(new FormData(e.target)) })); toast("Saved");
    };
  }
  function askOutcome(s, number, sms) {
    modal(`<h2>Did the ${sms ? "text" : "WhatsApp message"} go?</h2><p>${esc(s.name)} · ${esc(number)}</p>
      <div class="outcomes">${sms ? `<button class="btn primary" data-o="sms">Yes, sent</button>` : `<button class="btn primary" data-o="sent">Yes, sent</button><button class="btn" data-o="not_on_whatsapp">Not on WhatsApp</button>`}
        <button class="btn" data-o="wrong_number">Wrong number</button><button class="btn ghost" data-close>Not yet</button></div>`, (m) => {
      $$("[data-o]", m).forEach((b) => (b.onclick = async () => { await api(`whatsapp/${s.id}`, { method: "POST", body: { outcome: b.dataset.o, number } }); m.close(); toast("Recorded"); openSchool(s.id); refreshList(); }));
    });
  }
  function refreshList() { if (parseHash().view === "schools") loadSchools(); }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#modal").open) closeDrawer();
    if (e.key === "/" && !e.target.matches("input, textarea, select")) { e.preventDefault(); go("schools"); setTimeout(() => $("#q").focus(), 50); }
  });

  // ------------------------------------------------------------ email
  async function renderEmail() {
    const el = $("#view-email");
    if (!state.outreach) el.innerHTML = `<div class="page"><p class="muted">Loading…</p></div>`;
    const [o, accs] = await Promise.all([api(withCountry("outreach")), api("accounts")]);
    state.outreach = o;
    const presets = accs.presets, on = o.settings.sending, seq = o.sequence, fc = o.forecast, c = cty();
    const tmplCountries = [...new Set(o.templates.map((t) => t.country))];
    if (!tmplCountries.includes(state.tmplCountry) && state.tmplCountry) state.tmplCountry = "";
    const tmpl = o.templates.filter((t) => t.country === state.tmplCountry);
    const needDetails = o.settings.org === "our ministry" || !o.settings.library_link;
    el.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Email outreach</h1>
        <p>Your ${o.max_accounts} email accounts are shared by every country. Pick schools, and they move through the emails below, sent in each school's own working hours. A reply, an unsubscribe or a bounce stops the emails to that address.</p></div>
        <div class="send-switch ${on ? "on" : ""}"><div><b>${on ? "Sending is on" : "Sending is off"}</b><div class="s-sub">${on ? (o.on_vercel && !o.cron ? "Keep the CRM open in a browser tab; it sends as each account's limits allow." : "Sending in the background, inside each account's limits.") : "Nothing is sent until you switch this on."}</div></div>
          <button class="btn ${on ? "" : "primary"}" id="o-toggle">${on ? "Pause sending" : "Start sending"}</button></div></div>

      <div class="hero">
        <div><div class="big">${n(seq.active || 0)}</div><div class="lbl">addresses waiting for an email (${n(o.by_step[1] || 0)} for email 1, ${n((o.by_step[2] || 0) + (o.by_step[3] || 0))} for follow-ups)</div></div>
        <div><div class="mid">${n(o.sent)}</div><div class="lbl">emails sent · ${n(o.sent_today)} today</div></div>
        <a class="hero-link" href="#/replies"><div class="mid">${n(seq.replied || 0)}</div><div class="lbl">replied</div></a>
        <div><div class="mid">${n(fc.per_day_now)}</div><div class="lbl">can send today${fc.per_day_full > fc.per_day_now ? `, rising to ${n(fc.per_day_full)} a day` : ""}</div></div>
        <div><div class="mid">${fc.days_first ? `${n(fc.days_first)} d` : "—"}</div><div class="lbl">${fc.first_emails ? `until everyone queued has email 1 (about)` : "nothing queued"}</div></div>
      </div>

      <div class="card step"><h2><span class="num">${o.accounts.length ? ICON.check : 1}</span>Email accounts <small class="muted">${o.accounts.length} of ${o.max_accounts}</small></h2>
        <p class="sub">Each account sends one email at a time with a gap between messages, inside its own daily and hourly limits. New mailboxes start low and ramp up each day so they aren't flagged as spam. An account can be kept to some countries (for example a Ugandan address for Ugandan schools).</p>
        <div class="acct-grid">${o.accounts.map((a) => `<div class="acct ${a.enabled ? "" : "off"}">
            <div class="acct-top"><div><b>${esc(a.label)}</b><div class="s-sub">${esc(a.from_email)}</div></div>
              <span class="badge ${a.ready ? "conf-high" : a.enabled ? "" : "warn"}">${esc(a.ready ? "ready" : a.state)}</span></div>
            <div class="meter"><span style="width:${Math.min(100, (100 * a.sent_today) / Math.max(a.cap_today, 1))}%"></span></div>
            <div class="s-sub">${n(a.sent_today)} of ${n(a.cap_today)} today${a.warmup && a.cap_today < a.daily_cap ? ` (warming up to ${a.daily_cap})` : ""} · ${n(a.active)} waiting · ${n(a.replied)} replied</div>
            <div class="s-sub">${a.countries ? a.country_list.map((k) => `${flag(k)} ${esc(cname(k))}`).join(", ") : "All countries"} · ${a.window_start}:00–${a.window_end}:00 local time</div>
            ${a.last_error ? `<div class="error small">${esc(a.last_error)}</div>` : ""}
            ${!a.has_password ? `<div class="error small">No password saved. Edit the account and paste its app password.</div>` : ""}
            <div class="acct-acts"><button class="btn small" data-edit="${a.id}">Edit</button><button class="btn small" data-test="${a.id}">Test sign-in</button>
              ${a.imap_host ? `<button class="btn small" data-replies="${a.id}">Check replies</button>` : ""}
              <button class="btn small" data-pause="${a.id}" data-to="${a.enabled ? 0 : 1}">${a.enabled ? "Pause" : "Resume"}</button></div></div>`).join("")}
          ${o.accounts.length < o.max_accounts ? `<button class="acct add" id="o-add"><span>+</span>Connect an email account</button>` : ""}</div></div>

      <div class="card step"><h2><span class="num">${needDetails ? 2 : ICON.check}</span>Your details</h2>
        <p class="sub">Used in every email and WhatsApp message.</p>
        <div class="settings-row">
          <label class="field">Organisation name<input id="s-org" value="${esc(o.settings.org === "our ministry" ? "" : o.settings.org)}" placeholder="e.g. Bible Transfer 123"></label>
          <label class="field">Library link<input id="s-link" value="${esc(o.settings.library_link)}" placeholder="https://…"></label>
          <label class="field">Your name (for WhatsApp)<input id="s-sender" value="${esc(o.settings.phone_sender)}" placeholder="e.g. Ashish"></label>
          <label class="check-row"><input type="checkbox" id="s-weekdays" ${o.settings.weekdays_only ? "checked" : ""}> Weekdays only</label>
          <button class="btn" id="s-save">Save</button></div></div>

      <div class="card step"><h2><span class="num">3</span>Choose who to email</h2>
        <p class="sub">Pick a country, the levels and the area. The count updates as you choose. You can also tick schools on the <a href="#/schools">Schools</a> page and press “Email selected”.</p>
        <div id="pick"></div></div>

      <div class="card step"><h2><span class="num">4</span>The emails</h2>
        <p class="sub">Placeholders: {{greeting}} {{school}} {{person}} {{role}} {{district}} {{town}} {{country}} {{sender_name}} {{org}} {{library_link}} {{signature}}. Leave a subject blank to send it as a reply in the same thread. An unsubscribe line is always added at the bottom.</p>
        <div class="metric-switch">${[["", "Every country"], ...state.countries.map((x) => [x.code, `${x.flag} ${x.name}`])].map(([k, l]) => `<button class="${state.tmplCountry === k ? "on" : ""}" data-tc="${k}">${esc(l)}${k && tmplCountries.includes(k) ? " · own version" : ""}</button>`).join("")}</div>
        ${state.tmplCountry && !tmpl.length ? `<p>${esc(cname(state.tmplCountry))} uses the same emails as every other country. <button class="btn small" id="t-own">Write a separate version for ${esc(cname(state.tmplCountry))}</button></p>` : `
          ${state.tmplCountry ? `<p class="muted small">${esc(cname(state.tmplCountry))} has its own version. <button class="linklike" id="t-shared">Go back to the shared emails</button></p>` : ""}
          ${tmpl.map((t) => `<details class="tmpl" ${t.step === 1 ? "open" : ""}><summary><b>Email ${t.step}: ${esc(t.name)}</b> <span class="muted">${t.step === 1 ? "sent first" : `${t.delay_days} days after email ${t.step - 1}`}</span></summary>
            <div class="tmpl-grid"><label class="field">Name<input data-t="${t.step}" data-f="name" value="${esc(t.name)}"></label>
              ${t.step > 1 ? `<label class="field">Days after previous<input type="number" min="0" step="1" data-t="${t.step}" data-f="delay_days" value="${t.delay_days}"></label>` : ""}</div>
            <label class="field">Subject<input data-t="${t.step}" data-f="subject" value="${esc(t.subject)}" placeholder="${t.step > 1 ? "(blank = Re: email 1's subject)" : ""}"></label>
            <label class="field">Body<textarea rows="11" data-t="${t.step}" data-f="body">${esc(t.body)}</textarea></label>
            <button class="btn small" data-save-t="${t.step}">Save email ${t.step}</button></details>`).join("")}`}
        <button class="btn" id="o-preview">Preview with a real school</button>
        ${o.public_url ? "" : `<p class="muted small">Set PUBLIC_URL (the CRM's web address) to add a one-click unsubscribe link. Until then the footer asks people to reply "unsubscribe", and those replies are caught when inboxes are checked.</p>`}
      </div>

      <div class="card"><h2>Campaigns</h2><p class="sub">Every batch of schools you add is a campaign, so you can see what each one got back.</p>
        ${o.campaigns.length ? `<div class="flush-x"><table class="plain"><thead><tr><th>Campaign</th><th class="num">Addresses</th><th class="num">Emails sent</th><th class="num">Replied</th><th class="num">Bounced</th><th class="num">Unsubscribed</th><th class="num">Still going</th><th></th></tr></thead><tbody>
          ${o.campaigns.map((k) => `<tr><td><a href="#" data-camp="${esc(k.campaign)}">${k.n_countries === 1 ? flag(k.country) + " " : ""}${esc(k.campaign)}</a><div class="s-sub">started ${ago(k.started)}</div></td><td class="num">${n(k.addresses)}</td><td class="num">${n(k.sent)}</td>
            <td class="num"><b>${n(k.replied)}</b> <small class="muted">${pct(k.replied, k.addresses)}</small></td><td class="num">${n(k.bounced)}</td><td class="num">${n(k.unsubscribed)}</td><td class="num">${n(k.active)}${k.paused ? ` <small class="muted">+${n(k.paused)} paused</small>` : ""}</td>
            <td>${k.active ? `<button class="btn small ghost" data-cpause="${esc(k.campaign)}">Pause</button>` : k.paused ? `<button class="btn small ghost" data-cresume="${esc(k.campaign)}">Resume</button>` : ""}</td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">None yet.</p>`}</div>

      <div class="grid-2">
        <div class="card"><h2>Next up</h2><p class="sub">Who gets which email next.</p>
          ${o.upcoming.length ? `<table class="plain"><tbody>${o.upcoming.map((e) => `<tr><td><a href="#" data-open="${e.school_id}">${flag(e.country)} ${esc(e.school)}</a><div class="s-sub">${esc(e.email)}</div></td><td>Email ${e.next_step}</td><td>${esc(e.account || "")}</td><td class="num">${until(e.next_due_at) === "now" ? "due" : "in " + until(e.next_due_at)}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">Nobody waiting. Choose schools in step 3.</p>`}</div>
        <div class="card"><h2>Recently sent</h2><p class="sub">The last 30 sends and failures.</p>
          ${o.recent.length ? `<table class="plain"><tbody>${o.recent.map((m) => `<tr><td><a href="#" data-open="${m.school_id}">${flag(m.country)} ${esc(m.school || "")}</a><div class="s-sub">${esc(m.to_email)}</div></td><td>Email ${m.step}</td><td>${esc(m.account || "")}</td><td>${m.status === "sent" ? ago(m.created_at) : `<span class="error small" title="${esc(m.error)}">failed</span>`}</td></tr>`).join("")}</tbody></table>` : `<p class="muted">Nothing sent yet.</p>`}</div>
      </div>
      <div class="card"><h2>Do-not-email list</h2><p class="sub">${n(o.suppressed)} addresses that unsubscribed, bounced or asked to stop. They are never emailed again, in any country. Paste addresses to add them.</p>
        <div class="settings-row"><textarea id="sup-in" rows="2" placeholder="someone@example.com"></textarea><button class="btn" id="sup-add">Add</button><button class="btn ghost" id="sup-show">Show list</button></div><div id="sup-list"></div></div>
    </div>`;

    renderPicker();
    $("#o-toggle").onclick = async () => {
      if (!on && !o.accounts.some((a) => a.enabled && a.has_password)) { toast("Connect an email account with its app password first."); return; }
      await api("sending", { method: "POST", body: { on: !on } }); toast(on ? "Sending paused" : "Sending started"); startTicker(!on); renderEmail();
    };
    $("#o-add")?.addEventListener("click", () => accountDialog(null, presets));
    $$("[data-edit]", el).forEach((b) => (b.onclick = () => accountDialog(o.accounts.find((a) => a.id === +b.dataset.edit), presets)));
    $$("[data-test]", el).forEach((b) => (b.onclick = async () => {
      b.disabled = true; b.textContent = "Testing…";
      const r = await api(`accounts/${b.dataset.test}/test`, { method: "POST" });
      modal(`<h2>Sign-in test</h2><p><b>Sending (SMTP):</b> ${esc(r.smtp)}</p>${r.imap ? `<p><b>Reading replies (IMAP):</b> ${esc(r.imap)}</p>` : ""}<p class="muted small">No email was sent.</p><div class="modal-actions"><button class="btn primary" data-close>OK</button></div>`);
      b.disabled = false; b.textContent = "Test sign-in";
    }));
    $$("[data-replies]", el).forEach((b) => (b.onclick = async () => {
      b.disabled = true; b.textContent = "Checking…";
      const r = await api(`accounts/${b.dataset.replies}/check-replies`, { method: "POST", allowError: true });
      toast(r.error ? r.error : `${r.replied} replies, ${r.unsubscribed} unsubscribes, ${r.bounced} bounces found`); renderEmail(); updateReplyCount();
    }));
    $$("[data-pause]", el).forEach((b) => (b.onclick = async () => { await api(`accounts/${b.dataset.pause}`, { method: "PATCH", body: { enabled: +b.dataset.to } }); renderEmail(); }));
    $("#s-save").onclick = async () => { await api("settings", { method: "POST", body: { org_name: $("#s-org").value, library_link: $("#s-link").value, phone_sender: $("#s-sender").value, weekdays_only: $("#s-weekdays").checked } }); toast("Saved"); renderEmail(); };
    $$("[data-tc]", el).forEach((b) => (b.onclick = () => { state.tmplCountry = b.dataset.tc; renderEmail(); }));
    $("#t-own")?.addEventListener("click", async () => { await api(`templates/${state.tmplCountry}`, { method: "POST" }); toast("Copied. Edit it below."); renderEmail(); });
    $("#t-shared")?.addEventListener("click", async () => { if (!confirm(`Delete ${cname(state.tmplCountry)}'s own emails and use the shared ones?`)) return; await api(`templates/${state.tmplCountry}`, { method: "DELETE" }); renderEmail(); });
    $$("[data-save-t]", el).forEach((b) => (b.onclick = async () => {
      const step = b.dataset.saveT, body = {};
      $$(`[data-t="${step}"]`, el).forEach((i) => (body[i.dataset.f] = i.value));
      await api(`templates/${state.tmplCountry || "_"}/${step}`, { method: "PUT", body }); toast(`Email ${step} saved`);
    }));
    $("#o-preview").onclick = async () => {
      const p = await api("preview", { method: "POST", body: { country: state.tmplCountry || state.country }, allowError: true });
      if (p.error) { toast(p.error); return; }
      modal(`<h2>Preview: ${esc(p.school)}</h2><p class="muted">${esc(p.country)} · to ${esc(p.to || "—")}</p>${p.emails.map((e) => `<div class="preview"><div class="muted small">Email ${e.step}</div><b>${esc(e.subject)}</b><pre>${esc(e.body)}</pre></div>`).join("")}<div class="modal-actions"><button class="btn primary" data-close>Close</button></div>`);
    };
    $$("[data-camp]", el).forEach((a) => (a.onclick = (e) => { e.preventDefault(); go("schools", { campaign: a.dataset.camp }); }));
    $$("[data-cpause]", el).forEach((b) => (b.onclick = async () => { await api("enrollments/bulk", { method: "POST", body: { campaign: b.dataset.cpause, action: "pause" } }); renderEmail(); }));
    $$("[data-cresume]", el).forEach((b) => (b.onclick = async () => { await api("enrollments/bulk", { method: "POST", body: { campaign: b.dataset.cresume, action: "resume" } }); renderEmail(); }));
    $("#sup-add").onclick = async () => { const r = await api("suppressions", { method: "POST", body: { emails: $("#sup-in").value } }); toast(`${r.added} added`); renderEmail(); };
    $("#sup-show").onclick = async () => {
      const r = await api("suppressions");
      $("#sup-list").innerHTML = r.rows.length ? `<table class="plain"><tbody>${r.rows.map((x) => `<tr><td>${esc(x.email)}</td><td>${esc(x.reason)}</td><td>${ago(x.created_at)}</td><td><button class="btn small ghost" data-unsup="${esc(x.email)}">Remove</button></td></tr>`).join("")}</tbody></table>` : `<p class="muted">Empty.</p>`;
      $$("[data-unsup]").forEach((b) => (b.onclick = async () => { await api(`suppressions/${encodeURIComponent(b.dataset.unsup)}`, { method: "DELETE" }); $("#sup-show").click(); }));
    };
    $$("[data-open]", el).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openSchool(+a.dataset.open); }));
  }

  // The campaign picker: a small, self-contained filter that counts as you choose.
  const pick = { f: {} };
  async function renderPicker() {
    const box = $("#pick");
    if (!box) return;
    const code = state.country || (pick.f.country || [])[0] || "";
    const fc = code ? await api(`facets?country=${code}`) : null;
    const C = state.C[code];
    const f = pick.f;
    box.innerHTML = `<div class="picker-grid">
      ${state.country ? "" : `<div><div class="flabel">Country</div>${pills("country", state.countries.map((x) => [x.code, `${x.flag} ${x.name}`]), f)}</div>`}
      <div><div class="flabel">Level</div>${pills("level", levelOptions(code), f)}</div>
      ${C ? `<div><div class="flabel">${esc(C.district_label)}</div><select id="p-district" class="big-select"><option value="">Everywhere in ${esc(C.name)}</option>${fc.districts.map((d) => `<option ${(f.district || []).includes(d.value) ? "selected" : ""}>${esc(d.value)}</option>`).join("")}</select></div>` : ""}
      <div><div class="flabel">Email quality</div>${pills("confidence", [["high", CONF_LABEL.high], ["medium", CONF_LABEL.medium], ["low", CONF_LABEL.low]], f)}</div>
      <div><div class="flabel">Ownership</div>${pills("ownership", OWNERSHIP.slice(0, 6), f)}</div>
    </div>
    <div class="pick-go"><span id="p-count" class="muted">Counting…</span><button class="btn primary" id="p-go" disabled>Add to the sequence</button></div>`;
    $$(".pill", box).forEach((b) => (b.onclick = () => {
      const k = b.dataset.k, v = b.dataset.v, cur = new Set(f[k] || []);
      if (k === "country") { cur.clear(); if (!(f.country || []).includes(v)) cur.add(v); pick.f = { country: [...cur] }; }
      else { cur.has(v) ? cur.delete(v) : cur.add(v); pick.f = { ...f, [k]: [...cur] }; }
      renderPicker();
    }));
    $("#p-district", box)?.addEventListener("change", (e) => { pick.f = { ...f, district: e.target.value ? [e.target.value] : [] }; renderPicker(); });
    const filter = { ...Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.join(",")]).filter(([, v]) => v)), sequence: "none" };
    if (state.country) filter.country = state.country;
    const pre = await api("enroll", { method: "POST", body: { filter, dry_run: true } });
    $("#p-count", box).innerHTML = `<b>${plural(pre.with_email, "school")}</b> with an email address, not emailed yet${Object.keys(pre.by_country).length > 1 ? ` (${Object.entries(pre.by_country).map(([k, v]) => `${flag(k)} ${n(v)}`).join(" · ")})` : ""}`;
    const go_ = $("#p-go", box);
    go_.disabled = !pre.with_email;
    go_.textContent = pre.with_email ? `Add ${plural(pre.with_email, "school")} to the sequence` : "Add to the sequence";
    go_.onclick = () => enrollDialog({ filter });
  }

  function accountDialog(a, presets) {
    const v = (k, d = "") => esc(a ? a[k] ?? d : d);
    const prov = a?.provider || "gmail";
    const chosen = new Set(a?.countries ? a.countries.split(",") : []);
    modal(`<h2>${a ? "Edit email account" : "Connect an email account"}</h2>
      <form id="acc-form" class="acc-form">
        <label class="field">Email provider<select name="provider">${Object.keys(presets).map((k) => `<option value="${k}" ${k === prov ? "selected" : ""}>${PROVIDERS[k] || k}</option>`).join("")}</select></label>
        <p class="hint" id="acc-help">${esc(presets[prov].help)}</p>
        <div class="tmpl-grid">
          <label class="field">Name for this account<input name="label" value="${v("label")}" placeholder="e.g. Ashish 1"></label>
          <label class="field">Your name (shown to schools)<input name="from_name" value="${v("from_name")}" placeholder="e.g. Ashish Subedi"></label>
          <label class="field">Email address<input name="from_email" type="email" value="${v("from_email")}" required></label>
          <label class="field">App password ${a?.has_password ? "<small>(saved; leave blank to keep)</small>" : ""}<input name="password" type="password" autocomplete="new-password" ${a ? "" : "required"}></label>
        </div>
        <label class="field">Signature<textarea name="signature" rows="3" placeholder="Name&#10;Organisation&#10;Phone / WhatsApp">${v("signature")}</textarea></label>
        <div class="field">Send to schools in<div class="pills">${state.countries.map((c) => `<label class="pill ${chosen.has(c.code) ? "on" : ""}"><input type="checkbox" name="countries" value="${c.code}" ${chosen.has(c.code) ? "checked" : ""} hidden>${c.flag} ${esc(c.name)}</label>`).join("")}</div><small class="muted">None ticked = every country.</small></div>
        <details class="tmpl"><summary>Sending limits</summary>
          <div class="tmpl-grid">
            <label class="field">Max emails a day<input type="number" name="daily_cap" value="${v("daily_cap", 40)}" min="1" max="500"></label>
            <label class="field">Max an hour<input type="number" name="hourly_cap" value="${v("hourly_cap", 10)}" min="1" max="100"></label>
            <label class="field">Seconds between emails (at least)<input type="number" name="min_gap_s" value="${v("min_gap_s", 120)}" min="30"></label>
            <label class="field">Sending hours, school's local time<span class="pair"><input type="number" name="window_start" value="${v("window_start", 8)}" min="0" max="23"> to <input type="number" name="window_end" value="${v("window_end", 17)}" min="1" max="24"></span></label>
            <label class="check-row"><input type="checkbox" name="warmup" ${!a || a.warmup ? "checked" : ""}> Warm up a new mailbox</label>
            <label class="field">Warm-up: start at / add per day<span class="pair"><input type="number" name="warmup_start" value="${v("warmup_start", 10)}" min="1"> / <input type="number" name="warmup_step" value="${v("warmup_step", 5)}" min="0"></span></label>
          </div>
          <p class="muted small">Safe defaults for a normal Gmail or Outlook mailbox: 40 a day, 10 an hour, 2+ minutes apart, warming up from 10 a day. Google Workspace and paid Microsoft 365 can go higher once the mailbox has a few weeks of good history.</p></details>
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
      $$("label.pill input", f).forEach((i) => (i.onchange = () => i.parentElement.classList.toggle("on", i.checked)));
      f.provider.onchange = () => {
        const p = presets[f.provider.value];
        $("#acc-help", m).textContent = p.help;
        f.smtp_host.value = p.smtp_host; f.smtp_port.value = p.smtp_port; f.smtp_security.value = p.smtp_security; f.imap_host.value = p.imap_host;
      };
      f.onsubmit = async (e) => {
        e.preventDefault();
        const fd = new FormData(f);
        const body = Object.fromEntries(fd);
        body.countries = fd.getAll("countries").join(",");
        body.warmup = f.warmup.checked ? 1 : 0;
        if (!body.password) delete body.password;
        if (!body.username) body.username = body.from_email;
        if (!body.label) body.label = body.from_email;
        try {
          await api(a ? `accounts/${a.id}` : "accounts", { method: a ? "PATCH" : "POST", body });
          m.close(); toast(a ? "Saved" : "Connected. Press “Test sign-in” to check it."); renderEmail();
        } catch (err) { $("#acc-err", m).textContent = err.message; }
      };
      $("#acc-del", m)?.addEventListener("click", async () => {
        if (!confirm("Remove this account? Schools waiting in its sequence move to another account.")) return;
        const others = state.outreach.accounts.filter((x) => x.id !== a.id);
        try {
          await api(`accounts/${a.id}`, { method: "DELETE", body: a.active && others.length ? { move_to: others[0].id } : {} });
          m.close(); toast("Removed"); renderEmail();
        } catch (err) { $("#acc-err", m).textContent = err.message; }
      });
    });
  }

  // Hosted on Vercel there is no background process, so an open tab drives sending.
  let ticker = null, lastInbox = 0;
  function startTicker(on) {
    clearInterval(ticker);
    if (!on || !state.me?.on_vercel_page) return;
    ticker = setInterval(async () => {
      try {
        const r = await api("send/tick", { method: "POST" });
        if (!r.sending) { clearInterval(ticker); return; }
        if (Date.now() - lastInbox > 5 * 60000) { lastInbox = Date.now(); await api("replies/check-next", { method: "POST", body: {} }); updateReplyCount(); }
        if (parseHash().view === "email" && !$("#modal").open && r.accounts?.some((a) => String(a.status).startsWith("sent"))) renderEmail();
      } catch { /* try again next tick */ }
    }, 20000);
  }

  // ------------------------------------------------------------ WhatsApp
  async function renderWhatsApp() {
    const el = $("#view-whatsapp");
    const c = cty(), wa = state.wa;
    el.innerHTML = `<div class="page"><p class="muted">Loading…</p></div>`;
    const [o, fc] = await Promise.all([api(withCountry("outreach")), state.facets]);
    const s = o.settings;
    const q = await api(`whatsapp/queue?${filterQS({ limit: 25 }, wa.f)}`);
    wa.list = q.rows; wa.i = Math.min(wa.i, Math.max(0, q.rows.length - 1));
    const own = c ? s.phone_overrides[c.code] : {};
    const cur = wa.list[wa.i];
    el.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>WhatsApp</h1>
        <p>Most schools have a mobile number but no email. Work down this list: press <b>Open WhatsApp</b>, the message opens ready to send from your own WhatsApp (phone or WhatsApp Web), then press what happened. Nothing is sent by the CRM itself.</p></div>
        <div class="wa-today"><div class="big">${n(q.today)}<small> / ${n(q.target)}</small></div><div class="s-sub">sent today${q.today >= q.target ? " · daily target reached, stop for today" : ""}</div></div></div>

      <div class="card"><div class="picker-grid">
        ${c ? "" : `<div><div class="flabel">Country</div>${pills("country", state.countries.map((x) => [x.code, `${x.flag} ${x.name}`]), wa.f)}</div>`}
        <div><div class="flabel">Level</div>${pills("level", levelOptions(), wa.f)}</div>
        ${c ? `<div><div class="flabel">${esc(c.district_label)}</div><select id="w-district" class="big-select"><option value="">Everywhere in ${esc(c.name)}</option>${fc.districts.map((d) => `<option ${(wa.f.district || []).includes(d.value) ? "selected" : ""}>${esc(d.value)}</option>`).join("")}</select></div>` : ""}
        <div><div class="flabel">Who first</div>${pills("status", [["new", "Not contacted yet"], ["contacted", "Emailed, no reply"], ["replied", "Replied"]], wa.f)}</div>
      </div><p class="muted small">${plural(q.total, "school")} with a WhatsApp-able mobile left to message.</p></div>

      ${!s.phone_sender || s.org === "our ministry" || !s.library_link ? `<p class="notice">Before you start, add your name, organisation and library link under <b>The WhatsApp message</b> below (or on the <a href="#/email">Email</a> page), so the message doesn't say “[your name]”.</p>` : ""}
      ${cur ? `<div class="wa-card">
        <div class="wa-head"><div><div class="s-sub">${flag(cur.country)} ${esc(cname(cur.country))} · ${esc([cur.town, cur.district].filter(Boolean).join(", "))} · ${wa.i + 1} of ${n(q.total)}</div>
          <h2><a href="#" data-open="${cur.id}">${esc(cur.name)}</a></h2>${cur.leader ? `<div class="s-sub">${esc(cur.leader)}</div>` : ""}</div>
          <div class="wa-num">${ICON.wa}<b>${esc(cur.number)}</b></div></div>
        <label class="field">Message (edit it for this school if you like)<textarea id="w-msg" rows="7">${esc(cur.messages.whatsapp)}</textarea></label>
        <div class="wa-acts"><a class="btn primary wa big" id="w-open" target="_blank" rel="noopener" href="${esc(cur.links.whatsapp)}">Open WhatsApp</a>
          <a class="btn" href="${esc(cur.links.sms)}" id="w-sms">Text instead</a><a class="btn ghost" href="${esc(cur.links.tel)}">Call</a></div>
        <div class="wa-outcome"><span class="flabel">What happened?</span>
          <button class="btn primary" data-o="sent">Sent ✓</button><button class="btn" data-o="not_on_whatsapp">Not on WhatsApp</button>
          <button class="btn" data-o="wrong_number">Wrong number</button><button class="btn ghost" data-o="skipped">Skip</button></div>
      </div>
      ${wa.list.length > 1 ? `<div class="card"><h2>Coming up</h2><table class="plain"><tbody>${wa.list.slice(wa.i + 1, wa.i + 11).map((r, j) => `<tr data-jump="${wa.i + 1 + j}"><td>${flag(r.country)} ${esc(r.name)}<div class="s-sub">${esc(r.leader || "")}</div></td><td>${esc(r.district || "")}</td><td>${esc(r.number)}</td></tr>`).join("")}</tbody></table></div>` : ""}`
      : `<div class="card empty"><h3>Nobody left to message here</h3>Choose another ${c ? esc(c.district_label.toLowerCase()) : "country"} or level above, or look at <a href="#/replies">replies</a>.</div>`}

      <details class="card" ${!s.phone_sender || s.org === "our ministry" ? "open" : ""}><summary><b>The WhatsApp message</b> <span class="muted">${c ? `for ${esc(c.name)}` : "for every country"}</span></summary>
        <p class="sub">Placeholders: {{hello}} (“Good day Mrs Kamara,” or “Good day,”) {{school}} {{person}} {{district}} {{town}} {{country}} {{sender_name}} {{org}} {{library_link}}.${c ? ` Leave blank to use the shared message.` : ""}</p>
        <div class="settings-row"><label class="field">Your name<input id="p-sender" value="${esc(s.phone_sender)}" placeholder="e.g. Ashish"></label>
          <label class="field">Organisation<input id="p-org" value="${esc(s.org === "our ministry" ? "" : s.org)}" placeholder="e.g. Bible Transfer 123"></label>
          <label class="field">Library link<input id="p-link" value="${esc(s.library_link)}" placeholder="https://…"></label>
          <label class="field">Daily target<input id="p-target" type="number" min="1" max="500" value="${s.whatsapp_daily_target}"></label></div>
        <label class="field">WhatsApp message${c ? ` for ${esc(c.name)}` : ""}<textarea rows="7" id="p-wa" placeholder="${esc(c ? s.whatsapp_message : "")}">${esc(c ? own.whatsapp_message : s.whatsapp_message)}</textarea></label>
        <label class="field">Text message (keep it short)<textarea rows="3" id="p-sms" placeholder="${esc(c ? s.sms_message : "")}">${esc(c ? own.sms_message : s.sms_message)}</textarea></label>
        <button class="btn small" id="p-save">Save messages</button></details>

      <div class="card"><h2>Staying safe on WhatsApp</h2><p class="sub">WhatsApp bans numbers that message many strangers who then block or report them.</p>
        <ul class="tight"><li>Use a WhatsApp Business app number with your organisation's name and logo, and keep to the daily target (about 30–50 new chats a day for a new number, more once people reply).</li>
          <li>Change the wording now and then, and personalise it: the head's name and the school's name are filled in for you.</li>
          <li>Anyone who says stop: open the school and set it to <b>Do not contact</b>.</li>
          <li>Sending automatically to thousands (the WhatsApp Business Platform / API) needs Meta approval, message templates and opted-in contacts. See <a href="#/data">Data &amp; help</a>.</li></ul></div>
    </div>`;
    $$(".picker-grid .pill", el).forEach((b) => (b.onclick = () => {
      const k = b.dataset.k, v = b.dataset.v, set = new Set(wa.f[k] || []);
      set.has(v) ? set.delete(v) : set.add(v);
      state.wa = { f: { ...wa.f, [k]: [...set] }, list: [], i: 0 }; renderWhatsApp();
    }));
    $("#w-district")?.addEventListener("change", (e) => { state.wa = { f: { ...wa.f, district: e.target.value ? [e.target.value] : [] }, list: [], i: 0 }; renderWhatsApp(); });
    $$("[data-open]", el).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openSchool(+a.dataset.open); }));
    $$("[data-jump]", el).forEach((r) => (r.onclick = () => { wa.i = +r.dataset.jump; renderWhatsApp(); }));
    if (cur) {
      const digits = cur.number.replace(/\D/g, "");
      const refresh = () => {
        const t = $("#w-msg").value;
        $("#w-open").href = `https://wa.me/${digits}?text=${encodeURIComponent(t)}`;
      };
      $("#w-msg").addEventListener("input", refresh);
      $$("[data-o]", el).forEach((b) => (b.onclick = async () => {
        await api(`whatsapp/${cur.id}`, { method: "POST", body: { outcome: b.dataset.o, number: cur.number } });
        toast(b.dataset.o === "skipped" ? "Skipped" : "Recorded");
        renderWhatsApp();
      }));
      $("#w-sms").addEventListener("click", () => setTimeout(() => { $$("[data-o]")[0].dataset.o = "sms"; $$("[data-o]")[0].textContent = "Text sent ✓"; }, 300));
    }
    $("#p-save").onclick = async () => {
      await api("settings", { method: "POST", body: { country: c ? c.code : "", phone_sender: $("#p-sender").value, org_name: $("#p-org").value, library_link: $("#p-link").value, whatsapp_daily_target: +$("#p-target").value, whatsapp_message: $("#p-wa").value, sms_message: $("#p-sms").value } });
      toast("Messages saved"); renderWhatsApp();
    };
  }

  // ------------------------------------------------------------ replies
  async function updateReplyCount() {
    try {
      const r = await api("replies");
      const k = r.email.filter((x) => x.status === "replied").length + r.whatsapp.filter((x) => x.status === "replied").length;
      const b = $("#reply-count"); b.hidden = !k; b.textContent = k;
      return r;
    } catch { return null; }
  }
  async function renderReplies() {
    const el = $("#view-replies");
    el.innerHTML = `<div class="page"><p class="muted">Loading…</p></div>`;
    const r = await api(withCountry("replies"));
    updateReplyCount();
    const row = (x, kind) => `<div class="reply ${x.status === "replied" ? "new" : ""}">
      <div class="reply-main"><div class="s-sub">${flag(x.country)} ${esc(x.district || cname(x.country))} · ${kind === "email" ? `${esc(x.email)}${x.person ? ` (${esc(x.person)})` : ""}` : `WhatsApp ${esc(x.mobile)}`} · ${ago(kind === "email" ? x.replied_at || x.updated_at : x.whatsapp_at)}</div>
        <h3><a href="#" data-open="${x.school_id}">${esc(x.school)}</a> <span class="stage" data-s="${x.status}">${STAGE_LABEL[x.status]}</span></h3>
        ${x.reply_snippet ? `<p class="snippet">“${esc(x.reply_snippet)}”</p>` : ""}
        ${kind === "email" ? `<div class="s-sub">${x.campaign ? esc(x.campaign) + " · " : ""}answer from ${esc(x.account_email || x.account || "your inbox")}</div>` : ""}</div>
      <div class="reply-acts"><button class="btn small primary" data-st="interested" data-id="${x.school_id}">Interested</button><button class="btn small" data-st="partner" data-id="${x.school_id}">Partner</button><button class="btn small ghost" data-st="not_interested" data-id="${x.school_id}">Not interested</button></div></div>`;
    el.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Replies</h1><p>Everyone who answered an email or a WhatsApp message. Reply to emails from the inbox they came to; this page shows who's waiting and lets you mark how it went. New replies (stage “Replied”) are highlighted.</p></div>
        <button class="btn" id="r-check">Check inboxes now</button></div>
      <div class="grid-2">
        <div class="card"><h2>Email replies <small class="muted">${n(r.email.length)}</small></h2><p class="sub">Found in your inboxes every 15 minutes while sending is on. ${n(r.stops)} people asked to stop and were taken off.</p>
          ${r.email.length ? r.email.map((x) => row(x, "email")).join("") : `<p class="muted">No email replies yet.</p>`}</div>
        <div class="card"><h2>WhatsApp replies <small class="muted">${n(r.whatsapp.length)}</small></h2><p class="sub">WhatsApp replies arrive on your phone. When one does, open the school and press “Replied”, or set its stage.</p>
          ${r.whatsapp.length ? r.whatsapp.map((x) => row(x, "wa")).join("") : `<p class="muted">None recorded yet.</p>`}</div>
      </div></div>`;
    $$("[data-open]", el).forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openSchool(+a.dataset.open); }));
    $$("[data-st]", el).forEach((b) => (b.onclick = async () => { await api(`schools/${b.dataset.id}`, { method: "PATCH", body: { status: b.dataset.st } }); toast(`Moved to ${STAGE_LABEL[b.dataset.st]}`); renderReplies(); }));
    $("#r-check").onclick = async (e) => {
      const b = e.target; b.disabled = true; b.textContent = "Checking…";
      const accs = (await api("accounts")).accounts.filter((a) => a.enabled && a.imap_host);
      let found = 0;
      for (let i = 0; i < accs.length; i++) {
        const x = await api("replies/check-next", { method: "POST", body: { max_age: 0 }, allowError: true });
        if (!x.account) break;
        found += x.replied || 0;
        b.textContent = `Checked ${i + 1} of ${accs.length}…`;
      }
      toast(accs.length ? `${found} new ${found === 1 ? "reply" : "replies"}` : "No account has an IMAP server set."); renderReplies();
    };
  }

  // ------------------------------------------------------------ progress
  async function renderProgress() {
    const el = $("#view-progress");
    el.innerHTML = `<div class="page wide"><div class="page-head"><div><h1>Progress</h1><p>Schools at each stage${state.country ? ` in ${esc(cty().name)}` : ""}. Filters from the Schools page apply here too. Click a school to open it.</p></div></div></div><div class="board" id="board"><p class="muted">Loading…</p></div>`;
    const d = await api(`pipeline?${filterQS()}`);
    $("#board").innerHTML = STAGES.map(([k, l]) => `<div class="col" data-s="${k}"><h3><span class="stage" data-s="${k}">${l}</span><span class="n">${n(d[k].count)}</span></h3>
      ${d[k].rows.map((r) => `<div class="pcard" data-id="${r.id}"><div class="s-name">${state.country ? "" : flag(r.country) + " "}${esc(r.name)}</div><div class="s-sub">${esc(r.district || "")}${r.email ? " · " + esc(r.email) : r.mobile ? " · " + esc(r.mobile) : ""}</div></div>`).join("")}
      ${d[k].count > d[k].rows.length ? `<a class="more" href="#/schools?status=${k}">See all ${n(d[k].count)}</a>` : ""}</div>`).join("");
    $$(".pcard").forEach((c) => (c.onclick = () => openSchool(+c.dataset.id)));
  }

  // ------------------------------------------------------------ data & help
  function renderData() {
    const list = state.country ? [cty()] : state.countries;
    $("#view-data").innerHTML = `<div class="page prose">
      <div class="page-head"><div><h1>Data &amp; help</h1><p>Where each country's records come from, how to add more, and how to reach schools safely.</p></div></div>
      ${list.map((c) => `<div class="card"><h2>${c.flag} ${esc(c.name)} <small class="muted">${n(state.counts[c.code] || 0)} on file</small></h2>
        <p>${esc(c.sources_note)}</p>
        <p><b>Before contacting:</b> ${esc(c.data_law)} covers personal details such as a head teacher's name and phone number. Contact schools about school matters, say who you are, and honour every request to stop.</p>
        <p class="muted small">Levels: ${c.levels.filter((l) => l.value !== "admin").map((l) => `${esc(l.label)}${l.detail ? ` (${esc(l.detail)})` : ""}`).join(" · ")}. Emails and WhatsApp messages go out in ${esc(c.timezone)}.</p></div>`).join("")}
      <div class="card"><h2>Email quality</h2>
        <p><b>${CONF_LABEL.high}</b>: on the institution's own site or an official page from 2020 or later. <b>${CONF_LABEL.medium}</b>: a directory, news story, or an older official page. <b>${CONF_LABEL.low}</b>: old or ambiguous; check it before sending. Every email, phone number and named official links to the page it was copied from (open a school to see it). Nothing is guessed.</p></div>
      <div class="card"><h2>Adding a country or refreshing data</h2>
        <p>Each country is one file in the shared format (one school per line). On your computer, in the <code>africa</code> folder:</p>
        <pre class="cmd">python3 -m africacrm load                      # every country file it can find
python3 -m africacrm load --country UG --file uganda-schools.jsonl
python3 -m africacrm import-kenya --db ../data/harvest.db   # the Kenya directory + its CRM history</pre>
        <p>Loading again keeps your stages, notes, sequences and the contacts you added by hand. A new country needs one small settings file (its districts, levels, phone format and time zone).</p></div>
      <div class="card"><h2>WhatsApp: today and later</h2>
        <p><b>Today: click to chat.</b> The WhatsApp page lines schools up one at a time with the message written; you send it from your own WhatsApp and record what happened. This works with a normal or WhatsApp Business app number and keeps you inside WhatsApp's rules, as long as volumes stay modest and people who say stop are left alone.</p>
        <p><b>Later: the WhatsApp Business Platform (Cloud API).</b> It sends from the CRM automatically and can receive replies into it, but Meta requires a verified business, a dedicated number, pre-approved message templates, and contacts who agreed to hear from you. Meta charges per message, by country and category, and blocks numbers whose messages get reported. So it suits schools that already replied or opted in (for example on the library sign-up form), not cold lists. Providers such as Twilio, 360dialog or Africa's Talking can host it.</p>
        <p><b>Text messages.</b> The Text button opens your phone's SMS app. For bulk SMS, providers such as Africa's Talking cover Kenya and Uganda; check coverage for Sierra Leone.</p></div>
    </div>`;
  }

  // ------------------------------------------------------------ boot
  async function boot() {
    const me = await api("me");
    if (me.missing?.length) { document.body.innerHTML = `<div class="page"><h1>Setup needed</h1><p>Set ${me.missing.map(esc).join(", ")} in the hosting settings.</p></div>`; return; }
    if (me.auth && !me.signed_in) { showLogin(); return; }
    $("#app").hidden = false; $("#logout").hidden = !me.auth;
    const [fc, sum] = await Promise.all([api(withCountry("facets")), api("summary")]);
    state.facets = fc;
    state.countries = fc.countries; state.C = Object.fromEntries(fc.countries.map((c) => [c.code, c]));
    state.counts = { total: sum.total, ...Object.fromEntries(sum.countries.map((c) => [c.code, c.total])) };
    if (state.country && !state.C[state.country]) state.country = "";
    renderCountryTabs();
    route();
    updateReplyCount();
    const o = await api("outreach");
    state.me = { on_vercel_page: o.on_vercel && !o.cron };
    startTicker(o.settings.sending);
  }
  boot().catch((e) => { if (e.message !== "sign_in") { console.error(e); toast(e.message); } });
})();
