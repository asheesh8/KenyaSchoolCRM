/* Kenya Schools Directory — CRM front end. No build step; talks to /api/*. */
(() => {
  "use strict";

  // ------------------------------------------------------------ helpers
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const nf = new Intl.NumberFormat("en-KE");
  const n = (v) => (v == null ? "—" : nf.format(Math.round(v)));
  const pct = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : "—");
  const compact = (v) => v == null ? "—" : v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)}M` : v >= 1e4 ? `${Math.round(v / 1e3)}k` : nf.format(Math.round(v));
  const ago = (ts) => {
    if (!ts) return "never";
    const d = (Date.now() / 1000 - ts) / 86400;
    if (d < 1 / 24) return "just now";
    if (d < 1) return `${Math.round(d * 24)} h ago`;
    if (d < 45) return `${Math.round(d)} d ago`;
    return new Date(ts * 1000).toLocaleDateString("en-KE", { day: "numeric", month: "short", year: "numeric" });
  };
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2200);
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
    return data;
  }

  const ICON = {
    email: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    phone: '<svg viewBox="0 0 24 24"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>',
    website: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>',
    person: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
    address: '<svg viewBox="0 0 24 24"><path d="M4 7h16v12H4zM4 7l3-3h10l3 3M9 12h6"/></svg>',
    facebook: '<svg viewBox="0 0 24 24"><path d="M14 8h3V4h-3a4 4 0 0 0-4 4v3H7v4h3v6h4v-6h3l1-4h-4V8"/></svg>',
    instagram: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.5"/></svg>',
    youtube: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="12" rx="3"/><path d="m10 9 5 3-5 3z"/></svg>',
    x: '<svg viewBox="0 0 24 24"><path d="M5 4l14 16M19 4 5 20"/></svg>',
    linkedin: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 11v5M8 8v.01M12 16v-5M12 13a2 2 0 0 1 4 0v3"/></svg>',
    tiktok: '<svg viewBox="0 0 24 24"><path d="M14 4v11a3 3 0 1 1-3-3M14 4c0 3 2 5 5 5"/></svg>',
    contact_form: '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 9h8M8 13h8M8 17h5"/></svg>',
    contact_page: '<svg viewBox="0 0 24 24"><path d="M7 3h7l5 5v13H7zM14 3v5h5"/></svg>',
    star: '<svg viewBox="0 0 24 24"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg>',
    close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    refresh: '<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2 6M20 5v6h-6"/></svg>',
  };

  // ------------------------------------------------------------ constants
  const STAGES = [
    ["new", "New"], ["queued", "Queued"], ["contacted", "Contacted"], ["replied", "Replied"],
    ["interested", "Interested"], ["visit", "Visit booked"], ["partner", "Partner"],
    ["not_interested", "Not interested"], ["do_not_contact", "Do not contact"],
  ];
  const STAGE_LABEL = Object.fromEntries(STAGES);
  const GRADES = [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13];
  const GRADE_SHORT = { "-1": "PP1", 0: "PP2", 13: "Post" };
  const GRADE_STAGE = (g) => (g <= 0 ? "ecde" : g <= 6 ? "primary" : g <= 9 ? "junior" : g <= 12 ? "senior" : "post");
  const STAGE_GROUPS = [["ecde", "Pre-primary", [-1, 0]], ["primary", "Primary", [1, 2, 3, 4, 5, 6]],
    ["junior", "Junior School", [7, 8, 9]], ["senior", "Senior School", [10, 11, 12]], ["post", "Post-sec.", [13]]];
  const BIT = { ecde: 1, primary: 2, junior: 4, senior: 8, tvet: 16, ttc: 32, university: 64, adult: 128, nonformal: 256 };
  const OTHER_LEVELS = [["tvet", "TVET / polytechnic"], ["ttc", "Teacher training"], ["university", "University"],
    ["nonformal", "Non-formal (APBET)"], ["adult", "Adult education"], ["unknown", "Level unknown"]];
  const SETTINGS = [["urban", "Urban"], ["peri_urban", "Peri-urban"], ["rural", "Rural"]];
  const SPONSOR_LABEL = { religious: "Religious organisation", community: "Community", government: "Government",
    local_authority: "County / local authority", ngo: "NGO / CBO", private: "Private owner", university: "University" };
  const GENDERS = [["mixed", "Mixed"], ["girls", "Girls"], ["boys", "Boys"]];
  const BOARDING = [["boarding", "Boarding"], ["day", "Day"], ["day_boarding", "Day & boarding"]];
  const HAS = [["email", "Email"], ["phone", "Phone"], ["website", "Website"], ["leader", "Named head"],
    ["postal_address", "P.O. Box"], ["whatsapp", "WhatsApp"], ["facebook", "Facebook"], ["size", "Size known"]];
  const MULTI = ["county", "const", "grades", "level", "ownership", "sponsor", "faith", "gender", "boarding",
    "setting", "has", "missing", "status"];
  const RANGES = [["county_pop", "County population"], ["const_pop", "Constituency population"],
    ["density", "People per km² around the school"], ["size", "Learners"]];

  // ------------------------------------------------------------ state
  const state = {
    view: "overview", f: {}, sort: "best", offset: 0, limit: 50, rows: [], total: 0, cursor: -1,
    selected: new Set(), open: null, facets: null, summary: null, map: null,
  };

  function paramsFromFilters(extra = {}) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(state.f)) {
      if (Array.isArray(v)) { if (v.length) p.set(k, v.join(",")); }
      else if (v !== "" && v != null && v !== false) p.set(k, v);
    }
    for (const [k, v] of Object.entries(extra)) if (v !== "" && v != null) p.set(k, v);
    return p;
  }
  function filtersFromHash(query) {
    const p = new URLSearchParams(query);
    const f = {};
    for (const [k, v] of p) {
      if (["sort", "offset", "open"].includes(k)) continue;
      f[k] = MULTI.includes(k) ? v.split(",").filter(Boolean) : v;
    }
    state.sort = p.get("sort") || state.sort;
    state.offset = +p.get("offset") || 0;
    return f;
  }
  function writeHash(replace = true) {
    const p = paramsFromFilters();
    if (state.sort !== "best") p.set("sort", state.sort);
    if (state.offset) p.set("offset", state.offset);
    const h = `#/${state.view}${p.toString() ? "?" + p.toString() : ""}`;
    if (location.hash !== h) (replace ? history.replaceState : history.pushState).call(history, null, "", h);
  }
  const setF = (k, v) => { state.f[k] = v; state.offset = 0; filtersChanged(); };
  const toggleIn = (k, v) => {
    const cur = new Set(state.f[k] || []);
    cur.has(v) ? cur.delete(v) : cur.add(v);
    setF(k, [...cur]);
  };

  window.addEventListener("unhandledrejection", (e) => {
    const m = String(e.reason && e.reason.message || e.reason || "");
    if (m === "sign_in") return;
    toast(/locked/i.test(m) ? "The database is busy. Please try again in a moment." : `Something went wrong: ${m}`);
  });

  // ------------------------------------------------------------ comfort settings
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
                  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private window */ } } };
  function applyTheme() {
    const t = store.get("theme") || "light";  // light by default: easiest to read
    document.documentElement.dataset.theme = t;
    $("#theme-toggle").textContent = t === "dark" ? "Light screen" : "Dark screen";
  }
  $("#theme-toggle").addEventListener("click", () => { store.set("theme", store.get("theme") === "dark" ? "light" : "dark"); applyTheme(); if (state.view === "overview") drawChoro(); });
  applyTheme();
  $("#hint-bar").hidden = store.get("hint-seen") === "1";
  $("#hint-close").addEventListener("click", () => { store.set("hint-seen", "1"); $("#hint-bar").hidden = true; });

  // ------------------------------------------------------------ auth
  function showLogin() { $("#app").hidden = true; $("#login").hidden = false; $("#pw").focus(); }
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#login-error").textContent = "";
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("#pw").value }) });
    if (!r.ok) { $("#login-error").textContent = (await r.json().catch(() => ({}))).error || "Couldn't sign in."; return; }
    $("#pw").value = "";
    start();
  });
  $("#logout").addEventListener("click", async () => { await fetch("/api/logout", { method: "POST" }); showLogin(); });

  async function boot() {
    const me = await fetch("/api/me").then((r) => r.json()).catch(() => ({}));
    if (me.missing && me.missing.length) {
      document.body.innerHTML = `<div class="login"><div class="login-card"><h1>Almost set up</h1>
        <p>Add these environment variables to the deployment, then redeploy: <strong>${me.missing.map(esc).join(", ")}</strong>.</p></div></div>`;
      return;
    }
    $("#logout").hidden = !me.auth;
    if (me.auth && !me.signed_in) return showLogin();
    start();
  }
  async function start() {
    $("#login").hidden = true;
    $("#app").hidden = false;
    state.facets = await api("facets");
    route();
  }

  // ------------------------------------------------------------ routing
  window.addEventListener("hashchange", route);
  function route() {
    const m = location.hash.match(/^#\/(\w+)(?:\?(.*))?/);
    const view = m ? m[1] : "overview";
    state.view = ["overview", "schools", "map", "pipeline", "areas", "data"].includes(view) ? view : "overview";
    if (["schools", "map", "pipeline"].includes(state.view)) state.f = filtersFromHash(m && m[2] || "");
    $$(".rail a[data-view]").forEach((a) => a.classList.toggle("on", a.dataset.view === state.view));
    $$(".view").forEach((v) => (v.hidden = v.id !== `view-${state.view}`));
    const open = new URLSearchParams(m && m[2] || "").get("open");
    ({ overview: renderOverview, schools: renderSchoolsView, map: renderMap, pipeline: renderPipeline,
       areas: renderAreas, data: renderData })[state.view]();
    if (open) openSchool(+open);
  }
  function go(view, f = {}) {
    state.f = f; state.offset = 0; state.view = view;
    const p = paramsFromFilters();
    location.hash = `#/${view}${p.toString() ? "?" + p : ""}`;
  }

  // ------------------------------------------------------------ grade ladder
  function ladderHTML(selected) {
    const sel = new Set(selected.map(Number));
    return `<div class="ladder" id="ladder">
      <div class="ladder-rungs">${GRADES.map((g) => `<button type="button" class="rung ${sel.has(g) ? "on" : ""}"
        data-g="${g}" data-stage="${GRADE_STAGE(g)}" aria-pressed="${sel.has(g)}"
        title="${g === 13 ? "Post-secondary: TVET, colleges, universities" : g <= 0 ? `Pre-primary ${GRADE_SHORT[g]}` : `Grade ${g}`}">${GRADE_SHORT[g] ?? g}</button>`).join("")}</div>
      <div class="ladder-stages">${STAGE_GROUPS.map(([k, label, gs]) => `<button type="button" data-stage="${k}" data-gs="${gs.join(",")}">${label}</button>`).join("")}</div>
    </div>`;
  }
  function bindLadder(root, onChange) {
    let dragFrom = null, dragMode = null, moved = false;
    const current = () => new Set((state.f.grades || []).map(Number));
    const apply = (set) => onChange([...set].sort((a, b) => a - b).map(String));
    root.addEventListener("pointerdown", (e) => {
      const r = e.target.closest(".rung"); if (!r) return;
      e.preventDefault();
      dragFrom = +r.dataset.g; moved = false;
      dragMode = !current().has(dragFrom);
      r.setPointerCapture?.(e.pointerId);
    });
    root.addEventListener("pointermove", (e) => {
      if (dragFrom == null) return;
      const el = document.elementFromPoint(e.clientX, e.clientY)?.closest?.(".rung");
      if (!el) return;
      const to = +el.dataset.g;
      if (to === dragFrom && !moved) return;
      moved = true;
      $$(".rung", root).forEach((b) => {
        const g = +b.dataset.g, inRange = g >= Math.min(dragFrom, to) && g <= Math.max(dragFrom, to);
        b.classList.toggle("on", inRange ? dragMode : current().has(g));
      });
    });
    root.addEventListener("pointerup", (e) => {
      if (dragFrom == null) return;
      const set = current();
      if (moved) {
        $$(".rung", root).forEach((b) => b.classList.contains("on") ? set.add(+b.dataset.g) : set.delete(+b.dataset.g));
      } else {
        set.has(dragFrom) ? set.delete(dragFrom) : set.add(dragFrom);
      }
      dragFrom = null;
      apply(set);
    });
    $$(".ladder-stages button", root).forEach((b) => b.addEventListener("click", () => {
      const gs = b.dataset.gs.split(",").map(Number);
      const set = current();
      const all = gs.every((g) => set.has(g));
      gs.forEach((g) => (all ? set.delete(g) : set.add(g)));
      apply(set);
    }));
  }
  function miniLadder(mask) {
    const has = (b) => (mask & BIT[b]) !== 0;
    const cls = (g) => {
      if (g <= 0) return has("ecde") ? "e" : "";
      if (g <= 6) return has("primary") || has("nonformal") ? "p" : "";
      if (g <= 9) return has("junior") ? "j" : (has("primary") ? "j maybe" : (has("nonformal") && g <= 8 ? "p" : ""));
      if (g <= 12) return has("senior") ? "s" : "";
      return has("tvet") || has("ttc") || has("university") || has("adult") ? "t" : "";
    };
    return `<div class="mini" aria-hidden="true">${GRADES.map((g) => `<i class="${cls(g)}"></i>`).join("")}</div>`;
  }
  function gradeSpan(r) {
    if (r.grade_min == null) return "Level unknown";
    const lab = (g) => (g === 13 ? "post-secondary" : g <= 0 ? GRADE_SHORT[g] : `G${g}`);
    if (r.grade_min === 13) return r.level_labels.filter((l) => !/Pre|Primary|Junior|Senior/.test(l)).join(", ") || "Post-secondary";
    let hi = r.grade_max;
    const jssLikely = (r.levels & BIT.primary) && !(r.levels & BIT.junior) && hi === 6;
    return `${lab(r.grade_min)}–${lab(hi)}${jssLikely ? " (+ JSS likely)" : ""}`;
  }

  // ------------------------------------------------------------ filters panel
  function renderFilters() {
    const f = state.f, F = state.facets;
    const pills = (key, opts, counts) => `<div class="pills">${opts.map(([v, l]) =>
      `<button type="button" class="pill ${(f[key] || []).includes(v) ? "on" : ""}" data-k="${key}" data-v="${esc(v)}">${esc(l)}${counts && counts[v] != null ? `<span class="n">${compact(counts[v])}</span>` : ""}</button>`).join("")}</div>`;
    const range = (key, label, presets) => `
      <div class="range-label">${label}</div>
      <div class="range"><input type="number" min="0" placeholder="Min" data-min="${key}" value="${esc(f["min_" + key] || "")}">
        <span class="muted">to</span><input type="number" min="0" placeholder="Max" data-max="${key}" value="${esc(f["max_" + key] || "")}"></div>
      ${presets ? `<div class="presets">${presets.map(([l, a, b]) => `<button type="button" data-preset="${key}" data-a="${a}" data-b="${b}">${l}</button>`).join("")}</div>` : ""}`;
    const selCounties = new Set(f.county || []);
    const consts = F.constituencies.filter((c) => !selCounties.size || selCounties.has(c.county_code));
    const countyName = Object.fromEntries(F.counties.map((c) => [c.code, c.name]));
    const faithOpts = [["any_religious", "Any faith sponsor"], ...F.faiths.slice(0, 14).map((x) => [x.value, x.value]), ["none", "No faith link"]];
    const activeCount = Object.values(f).filter((v) => (Array.isArray(v) ? v.length : v)).length;
    const moreActive = ["const", "setting", "sponsor", "faith", "gender", "boarding", "status", "level", "missing"].some((k) => (f[k] || []).length)
      || ["min_county_pop", "max_county_pop", "min_const_pop", "max_const_pop", "min_density", "max_density", "special", "starred", "tag"].some((k) => f[k]);
    const stageOn = (gs) => gs.every((g) => (f.grades || []).includes(String(g)));
    const sizeNow = `${f.min_size || ""}-${f.max_size || ""}`;
    $("#filters").innerHTML = `
      <h2>Find schools ${activeCount ? `<button class="linklike" id="clear-all">Start over</button>` : ""}</h2>
      <div class="fgroup">
        <div class="flabel">1. Which grades?</div>
        <div class="big-choices">${STAGE_GROUPS.map(([k, label, gs]) => `<button type="button" class="big-choice ${stageOn(gs) ? "on" : ""}" data-stagepick="${gs.join(",")}">
          <strong>${({ ecde: "Nursery", primary: "Primary", junior: "Junior School", senior: "Secondary", post: "College / University" })[k]}</strong>
          <span>${({ ecde: "PP1–PP2", primary: "Grades 1–6", junior: "Grades 7–9", senior: "Grades 10–12 (Form 1–4)", post: "After secondary" })[k]}</span></button>`).join("")}</div>
        <details class="more-inline" ${(f.grades || []).length && !STAGE_GROUPS.some(([, , gs]) => stageOn(gs)) ? "open" : ""}>
          <summary>Pick exact grades instead</summary>
          ${ladderHTML(f.grades || [])}
          <label class="ladder-note"><input type="checkbox" id="jss" ${f.jss === "0" ? "" : "checked"}>
            Include primary schools for Grades 7–9 (most now teach them)</label>
        </details>
      </div>
      <div class="fgroup">
        <div class="flabel">2. Which county?</div>
        <select id="county-select" class="big-select"><option value="">All of Kenya</option>${F.counties.map((c) => `<option value="${c.code}" ${(f.county || []).length === 1 && f.county[0] === c.code ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>
        ${(f.county || []).length > 1 ? `<p class="hint">${f.county.length} counties chosen. Pick one above to switch, or remove them in the list of choices.</p>` : ""}
      </div>
      <div class="fgroup">
        <div class="flabel">3. Public or private?</div>
        ${pills("ownership", [["public", "Public"], ["private", "Private"]])}
      </div>
      <div class="fgroup">
        <div class="flabel">4. How big?</div>
        <div class="pills">${[["", "", "Any size"], ["", "200", "Small (under 200)"], ["200", "600", "Medium (200–600)"], ["600", "", "Large (600+)"]].map(([a, b, l]) =>
          `<button type="button" class="pill ${sizeNow === `${a}-${b}` ? "on" : ""}" data-size="${a}-${b}">${l}</button>`).join("")}</div>
        <p class="hint">Number of pupils, or about 40 per classroom where only classrooms are known.</p>
      </div>
      <div class="fgroup">
        <div class="flabel">5. Only schools I can reach by…</div>
        ${pills("has", [["phone", "Phone"], ["email", "Email"], ["leader", "Head teacher's name"], ["website", "Website"], ["whatsapp", "WhatsApp"], ["postal_address", "P.O. Box"]])}
      </div>
      <details class="fgroup more" ${moreActive ? "open" : ""}>
        <summary>More filters</summary>
        ${selCounties.size ? `<div class="flabel" style="margin-top:12px">Constituency</div>
          <div class="picker"><div class="picker-list">${consts.map((c) => `<label>
            <input type="checkbox" data-const="${c.code}" ${(f.const || []).includes(c.code) ? "checked" : ""}>${esc(c.name)}
            <span class="n">${selCounties.size > 1 ? esc(countyName[c.county_code]) + " · " : ""}${compact(c.population)} people</span></label>`).join("")}</div></div>` : ""}
        <div class="flabel" style="margin-top:12px">Several counties at once</div>
        <div class="picker"><input type="search" placeholder="Type a county name" id="county-find">
          <div class="picker-list" id="county-list">${F.counties.map((c) => `<label data-name="${esc(c.name.toLowerCase())}">
            <input type="checkbox" data-county="${c.code}" ${selCounties.has(c.code) ? "checked" : ""}>${esc(c.name)}
            <span class="n">${compact(c.population)} people</span></label>`).join("")}</div></div>
        <div class="flabel" style="margin-top:14px">Town or countryside</div>
        ${pills("setting", [["urban", "Town / city"], ["peri_urban", "Edge of town"], ["rural", "Countryside"]])}
        <div class="flabel" style="margin-top:14px">Population of the area</div>
        ${range("county_pop", "County population", [["Under 500,000", "", 500000], ["500,000 – 1 million", 500000, 1000000], ["Over 1 million", 1000000, ""]])}
        ${range("const_pop", "Constituency population", [["Under 100,000", "", 100000], ["100,000 – 200,000", 100000, 200000], ["Over 200,000", 200000, ""]])}
        <div class="flabel" style="margin-top:14px">Exact number of pupils</div>
        ${range("size", "Pupils", null)}
        <div class="flabel" style="margin-top:14px">Church or faith sponsor</div>${pills("faith", faithOpts)}
        <div class="flabel" style="margin-top:14px">Run by</div>${pills("sponsor", Object.entries(SPONSOR_LABEL))}
        <div class="flabel" style="margin-top:14px">Boys or girls</div>${pills("gender", [["girls", "Girls only"], ["boys", "Boys only"], ["mixed", "Mixed"]])}
        <div style="margin-top:6px">${pills("boarding", BOARDING)}</div>
        <label class="check-row" style="margin-top:8px"><input type="checkbox" id="special" ${f.special === "1" ? "checked" : ""}> Special needs schools only</label>
        <div class="flabel" style="margin-top:14px">Other kinds of school</div>${pills("level", OTHER_LEVELS)}
        <div class="flabel" style="margin-top:14px">Where we are with them</div>${pills("status", STAGES)}
        <div style="margin-top:6px">${pills("missing", [["any_contact", "No contact details yet"], ["email", "No email yet"]])}</div>
        <label class="check-row" style="margin-top:8px"><input type="checkbox" id="starred" ${f.starred === "1" ? "checked" : ""}> Starred schools only</label>
        ${F.tags.length ? `<div class="flabel" style="margin-top:8px">Tag</div><select id="tag"><option value="">Any tag</option>${F.tags.map((t) => `<option ${f.tag === t ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>` : ""}
      </details>`;
    const root = $("#filters");
    bindLadder($("#ladder", root), (gs) => setF("grades", gs));
    $$("[data-stagepick]", root).forEach((b) => b.addEventListener("click", () => {
      const gs = b.dataset.stagepick.split(",");
      const cur = new Set(state.f.grades || []);
      const all = gs.every((g) => cur.has(g));
      gs.forEach((g) => (all ? cur.delete(g) : cur.add(g)));
      setF("grades", [...cur].sort((a, b) => a - b));
    }));
    $("#county-select", root).addEventListener("change", (e) => { state.f.const = []; setF("county", e.target.value ? [e.target.value] : []); });
    $$("[data-size]", root).forEach((b) => b.addEventListener("click", () => {
      const [a, z] = b.dataset.size.split("-"); state.f.min_size = a; state.f.max_size = z; state.offset = 0; filtersChanged();
    }));
    $("#jss", root).addEventListener("change", (e) => setF("jss", e.target.checked ? "" : "0"));
    $$(".pill[data-k]", root).forEach((b) => b.addEventListener("click", () => toggleIn(b.dataset.k, b.dataset.v)));
    $("#county-find", root).addEventListener("input", (e) => {
      const q = e.target.value.toLowerCase();
      $$("#county-list label", root).forEach((l) => (l.hidden = !l.dataset.name.includes(q)));
    });
    $$("[data-county]", root).forEach((c) => c.addEventListener("change", () => {
      toggleIn("county", c.dataset.county);
      if (!state.f.county.length) state.f.const = [];
    }));
    $$("[data-const]", root).forEach((c) => c.addEventListener("change", () => toggleIn("const", c.dataset.const)));
    const rangeSet = debounce((k, v) => setF(k, v), 450);
    $$("[data-min]", root).forEach((i) => i.addEventListener("input", () => rangeSet("min_" + i.dataset.min, i.value)));
    $$("[data-max]", root).forEach((i) => i.addEventListener("input", () => rangeSet("max_" + i.dataset.max, i.value)));
    $$("[data-preset]", root).forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.preset;
      state.f["min_" + k] = b.dataset.a; state.f["max_" + k] = b.dataset.b; state.offset = 0; filtersChanged();
    }));
    $("#special", root).addEventListener("change", (e) => setF("special", e.target.checked ? "1" : ""));
    $("#starred", root).addEventListener("change", (e) => setF("starred", e.target.checked ? "1" : ""));
    $("#tag", root)?.addEventListener("change", (e) => setF("tag", e.target.value));
    $("#clear-all", root)?.addEventListener("click", () => { state.f = {}; state.offset = 0; $("#q").value = ""; filtersChanged(); });
  }

  function chipsHTML() {
    const f = state.f, F = state.facets, chips = [];
    const cn = Object.fromEntries(F.counties.map((c) => [c.code, c.name]));
    const kn = Object.fromEntries(F.constituencies.map((c) => [c.code, c.name]));
    if (f.q) chips.push(["q", null, `“${f.q}”`]);
    if ((f.grades || []).length) {
      const g = f.grades.map(Number).sort((a, b) => a - b);
      const lab = (x) => (x === 13 ? "Post-secondary" : x <= 0 ? GRADE_SHORT[x] : `Grade ${x}`);
      const contiguous = g.every((x, i) => !i || x === g[i - 1] + 1);
      chips.push(["grades", null, contiguous && g.length > 1 ? `${lab(g[0])} – ${lab(g[g.length - 1])}` : g.map(lab).join(", ")]);
    }
    const labels = { level: Object.fromEntries(OTHER_LEVELS), setting: Object.fromEntries(SETTINGS), ownership: { public: "Public", private: "Private", none: "Ownership not recorded" },
      sponsor: SPONSOR_LABEL, gender: Object.fromEntries(GENDERS), boarding: Object.fromEntries(BOARDING),
      has: Object.fromEntries(HAS.map(([k, l]) => [k, `Has ${l.toLowerCase()}`])), missing: { any_contact: "No contact yet", email: "No email", leader: "No named head" },
      status: STAGE_LABEL, faith: { any_religious: "Any faith sponsor", none: "No faith link" }, county: cn, const: kn };
    for (const k of ["county", "const", "level", "setting", "ownership", "sponsor", "faith", "gender", "boarding", "has", "missing", "status"])
      for (const v of f[k] || []) chips.push([k, v, (labels[k] || {})[v] || v]);
    for (const [k, l] of RANGES) {
      const a = f["min_" + k], b = f["max_" + k];
      if (a || b) chips.push(["range", k, `${l}: ${a ? n(+a) : "0"}–${b ? n(+b) : "any"}`]);
    }
    if (f.special === "1") chips.push(["special", null, "Special needs"]);
    if (f.starred === "1") chips.push(["starred", null, "Starred"]);
    if (f.tag) chips.push(["tag", null, `Tag: ${f.tag}`]);
    if (f.bbox) chips.push(["bbox", null, "Map area"]);
    if (!chips.length) return "";
    return chips.map(([k, v, l]) => `<span class="chip">${esc(l)}<button aria-label="Remove ${esc(l)}" data-k="${k}" data-v="${esc(v ?? "")}">×</button></span>`).join("")
      + (chips.length > 1 ? `<span class="chip clear"><button class="linklike" data-k="__all">Clear all</button></span>` : "");
  }
  function bindChips(el) {
    $$("button", el).forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.k, v = b.dataset.v;
      if (k === "__all") { state.f = {}; $("#q").value = ""; }
      else if (k === "range") { delete state.f["min_" + v]; delete state.f["max_" + v]; }
      else if (MULTI.includes(k)) { state.f[k] = (state.f[k] || []).filter((x) => x !== v); if (k === "county" && !state.f.county.length) state.f.const = []; }
      else { delete state.f[k]; if (k === "q") $("#q").value = ""; }
      state.offset = 0; filtersChanged();
    }));
  }

  function filtersChanged() {
    writeHash(false);
    if (state.view === "schools") { renderFilters(); loadSchools(); }
    else if (state.view === "map") loadMapPoints();
    else if (state.view === "pipeline") renderPipeline();
  }

  // ------------------------------------------------------------ schools list
  function renderSchoolsView() {
    $("#q").value = state.f.q || "";
    $("#sort").value = state.sort;
    renderFilters();
    loadSchools();
  }
  $("#q").addEventListener("input", debounce((e) => { state.f.q = e.target.value.trim(); state.offset = 0; writeHash(); loadSchools(); }, 250));
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; state.offset = 0; writeHash(); loadSchools(); });
  $("#show-filters").addEventListener("click", () => $("#filters").classList.toggle("show"));
  $("#export").addEventListener("click", (e) => { e.preventDefault(); location.href = `/api/export.csv?${paramsFromFilters()}`; });

  let loadSeq = 0;
  async function loadSchools() {
    const seq = ++loadSeq;
    $("#active-chips").innerHTML = chipsHTML();
    bindChips($("#active-chips"));
    const p = paramsFromFilters({ sort: state.sort, offset: state.offset, limit: state.limit });
    $("#count").textContent = "Loading…";
    const d = await api(`schools?${p}`);
    if (seq !== loadSeq) return;
    state.rows = d.rows; state.total = d.total; state.cursor = -1;
    renderRows();
  }
  function sizeCell(r) {
    if (r.students) return `${n(r.students)}<div class="s-sub">learners</div>`;
    if (r.classrooms) return `~${n(r.classrooms * 40)}<div class="s-sub">${r.classrooms} classrooms</div>`;
    return `<span class="muted">—</span>`;
  }
  function contactIcons(r) {
    const on = (k, v, t) => `<span class="ci ${v ? "on" : ""}" title="${esc(v ? `${t}: ${v}` : `No ${t.toLowerCase()} yet`)}">${ICON[k]}</span>`;
    return `<div class="contact-icons">${on("email", r.email, "Email")}${on("phone", r.phone, "Phone")}${on("website", r.website, "Website")}${on("address", r.postal_address, "Postal address")}</div>
      ${r.leader ? `<div class="leader">${esc(r.leader)}</div>` : ""}`;
  }
  function rowHTML(r, i) {
    const bits = [
      r.ownership ? (r.ownership === "public" ? "Public" : "Private") : null,
      r.gender && r.gender !== "mixed" ? (r.gender === "girls" ? "Girls" : "Boys") : null,
      r.boarding === "boarding" ? "Boarding" : r.boarding === "day_boarding" ? "Day & boarding" : null,
      r.faith && r.faith !== "Religious (unspecified)" ? r.faith : null,
      r.special_needs ? "Special needs" : null,
    ].filter(Boolean);
    const plainLevels = r.level_labels.map((l) => l.replace("Pre-primary (ECDE)", "Nursery").replace("Senior / Secondary", "Secondary")
      .replace("Non-formal (APBET)", "Non-formal").replace("TVET / Polytechnic", "Polytechnic")).join(", ") || "Type not recorded";
    const size = r.students ? `${n(r.students)} pupils` : r.classrooms ? `about ${n(r.classrooms * 40)} pupils` : "";
    return `<tr data-i="${i}" data-id="${r.id}" class="${state.open === r.id ? "open" : ""}">
      <td class="c-check"><input type="checkbox" data-sel="${r.id}" ${state.selected.has(r.id) ? "checked" : ""} aria-label="Select ${esc(r.name)}"></td>
      <td><div class="s-name">${r.starred ? `<span class="star" title="Starred">★</span>` : ""}${esc(r.name)}</div>
        <div class="s-sub">${esc(plainLevels)}${bits.length ? " · " + esc(bits.join(", ")) : ""}</div>
        <div class="row-grades">${miniLadder(r.levels)}<span class="grade-span">${esc(gradeSpan(r))}</span></div></td>
      <td class="where">${esc(r.county || "—")}<div class="s-sub">${esc(r.address ? r.address.replace(/, [^,]+ County$/, "") : [r.subcounty, r.town || r.location].filter(Boolean).join(", "))}</div>
        ${r.postal_address ? `<div class="s-sub">${esc(r.postal_address)}</div>` : ""}
        ${size ? `<div class="s-sub">${size}</div>` : ""}</td>
      <td class="reach">${r.phone ? `<div class="reach-line">${ICON.phone}<span>${esc(r.phone)}</span></div>` : ""}
        ${r.email ? `<div class="reach-line">${ICON.email}<span>${esc(r.email)}</span></div>` : ""}
        ${!r.phone && !r.email ? `<span class="muted">${r.website ? "Website only" : "No details yet"}</span>` : ""}</td>
      <td class="head">${r.leader ? esc(r.leader) : `<span class="muted">—</span>`}</td>
      <td><span class="stage" data-s="${r.status}">${STAGE_LABEL[r.status]}</span></td></tr>`;
  }
  function renderRows() {
    const { rows, total, offset, limit } = { ...state, offset: state.offset, limit: state.limit };
    $("#count").innerHTML = `<strong>${n(total)}</strong> school${total === 1 ? "" : "s"}`;
    $("#rows").innerHTML = rows.length ? rows.map(rowHTML).join("") :
      `<tr><td colspan="6"><div class="empty"><h3>No schools match</h3>Try removing one of your choices above, or press “Start over”.</div></td></tr>`;
    $("#pager").innerHTML = total > limit ? `<span>${n(offset + 1)}–${n(Math.min(offset + limit, total))} of ${n(total)}</span>
      <span><button class="btn small" id="prev" ${offset ? "" : "disabled"}>Previous</button>
      <button class="btn small" id="next" ${offset + limit < total ? "" : "disabled"}>Next</button></span>` : "";
    $("#prev")?.addEventListener("click", () => { state.offset = Math.max(0, offset - limit); writeHash(); loadSchools(); $(".table-wrap").scrollTop = 0; });
    $("#next")?.addEventListener("click", () => { state.offset = offset + limit; writeHash(); loadSchools(); $(".table-wrap").scrollTop = 0; });
    renderBulk();
  }
  $("#rows").addEventListener("click", (e) => {
    const cb = e.target.closest("[data-sel]");
    if (cb) { const id = +cb.dataset.sel; cb.checked ? state.selected.add(id) : state.selected.delete(id); renderBulk(); return; }
    const tr = e.target.closest("tr[data-id]");
    if (tr) { state.cursor = +tr.dataset.i; openSchool(+tr.dataset.id); }
  });
  $("#check-all").addEventListener("change", (e) => {
    state.rows.forEach((r) => (e.target.checked ? state.selected.add(r.id) : state.selected.delete(r.id)));
    $$("[data-sel]").forEach((c) => (c.checked = e.target.checked));
    renderBulk();
  });
  function renderBulk() {
    const b = $("#bulk"), k = state.selected.size;
    b.hidden = !k;
    if (!k) return;
    b.innerHTML = `<strong>${k} selected</strong>
      <select id="bulk-stage"><option value="">Move to stage…</option>${STAGES.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
      <button class="btn small" id="bulk-tag">Tag…</button><button class="btn small" id="bulk-star">Star</button>
      <button class="btn small" id="bulk-copy">Copy emails</button><button class="linklike" id="bulk-clear">Clear</button>`;
    const ids = [...state.selected];
    $("#bulk-stage").addEventListener("change", async (e) => {
      if (!e.target.value) return;
      await api("bulk", { method: "POST", body: { ids, status: e.target.value } });
      toast(`Moved ${ids.length} to ${STAGE_LABEL[e.target.value]}`); loadSchools();
    });
    $("#bulk-tag").addEventListener("click", async () => {
      const tag = prompt("Tag to add to the selected schools:"); if (!tag) return;
      await api("bulk", { method: "POST", body: { ids, tag } }); toast(`Tagged ${ids.length}`);
      state.facets = await api("facets"); loadSchools();
    });
    $("#bulk-star").addEventListener("click", async () => { await api("bulk", { method: "POST", body: { ids, starred: true } }); toast("Starred"); loadSchools(); });
    $("#bulk-copy").addEventListener("click", async () => {
      const emails = state.rows.filter((r) => state.selected.has(r.id) && r.email).map((r) => r.email);
      if (!emails.length) return toast("None of the selected schools on this page has an email");
      await navigator.clipboard.writeText(emails.join(", ")); toast(`Copied ${emails.length} emails`);
    });
    $("#bulk-clear").addEventListener("click", () => { state.selected.clear(); $$("[data-sel]").forEach((c) => (c.checked = false)); $("#check-all").checked = false; renderBulk(); });
  }

  // ------------------------------------------------------------ record drawer
  let dMap = null;
  async function openSchool(id) {
    state.open = id;
    $$("#rows tr").forEach((tr) => tr.classList.toggle("open", +tr.dataset.id === id));
    const d = $("#drawer");
    d.hidden = false;
    d.innerHTML = `<div class="d-head"><div class="muted">Loading…</div></div>`;
    try { renderDrawer(await api(`schools/${id}`)); } catch (e) { d.innerHTML = `<div class="d-head">${esc(e.message)}</div>`; }
  }
  function closeDrawer() {
    $("#drawer").hidden = true; state.open = null;
    $$("#rows tr.open").forEach((tr) => tr.classList.remove("open"));
    if (dMap) { dMap.remove(); dMap = null; }
  }
  const CONTACT_LABEL = { email: "Email", phone: "Phone", website: "Website", person: "Head / staff", address: "Postal address",
    facebook: "Facebook", instagram: "Instagram", youtube: "YouTube", x: "X", linkedin: "LinkedIn", tiktok: "TikTok",
    contact_form: "Contact form", contact_page: "Contact page" };
  const SOURCE_LABEL = { moe: "Ministry list", osm: "OpenStreetMap", web: "school website", wikidata: "Wikidata",
    places: "Google", search: "web search", list: "published school list", manual: "you" };
  function contactValue(c) {
    const v = esc(c.value);
    if (c.kind === "email") return `<a href="mailto:${v}">${v}</a>`;
    if (c.kind === "phone") return `<a href="tel:${esc(c.value.replace(/\s/g, ""))}">${v}</a>${c.label === "WhatsApp" ? ` <a class="badge" target="_blank" rel="noopener" href="https://wa.me/${esc(c.value.replace(/\D/g, ""))}">WhatsApp</a>` : ""}`;
    if (["website", "facebook", "instagram", "youtube", "x", "linkedin", "tiktok", "contact_form", "contact_page"].includes(c.kind))
      return `<a href="${v}" target="_blank" rel="noopener">${esc(c.value.replace(/^https?:\/\/(www\.)?/, ""))}</a>`;
    return v;
  }
  function renderDrawer(s) {
    const d = $("#drawer");
    const x = s.extra || {};
    const osmx = x.osm || {};
    const main = { email: s.email, phone: s.phone, website: s.website };
    const kindsOrder = ["person", "email", "phone", "website", "address", "facebook", "instagram", "youtube", "x", "linkedin", "tiktok", "contact_page", "contact_form"];
    const contacts = s.contacts.slice().sort((a, b) => kindsOrder.indexOf(a.kind) - kindsOrder.indexOf(b.kind) || b.active - a.active);
    const size = s.students ? `${n(s.students)} learners` + (s.students_female ? ` <small>(${n(s.students_female)} girls, ${n(s.students_male)} boys)</small>` : "")
      : s.classrooms ? `~${n(s.classrooms * 40)} learners <small>estimated from ${s.classrooms} classrooms</small>` : "Not recorded";
    const webStudents = x.website_students ? `<small> · website says ${n(x.website_students.n)}</small>` : "";
    const settingLabel = { urban: "Urban", peri_urban: "Peri-urban", rural: "Rural" }[s.setting];
    d.innerHTML = `
      <div class="d-head">
        <div class="d-top">
          <div><h2>${esc(s.name)}</h2>
            <div class="s-sub">${esc(s.level_labels.join(" · ") || "Level unknown")} — ${esc(gradeSpan(s))}</div></div>
          <div class="d-actions">
            <button class="icon-btn ${s.starred ? "on" : ""}" id="d-star" title="Star (s)">${ICON.star}</button>
            <button class="icon-btn" id="d-close" title="Close (Esc)">${ICON.close}</button>
          </div>
        </div>
        <div class="quick">${quickActions(s)}</div>
        <div class="stage-q"><span>Where are we with this school?</span></div>
        <div class="stages">${STAGES.map(([v, l]) => `<button data-s="${v}" class="${s.status === v ? "on" : ""}">${l}</button>`).join("")}</div>
      </div>
      <div class="d-body">
        <section class="d-sec"><h3>Grades taught</h3>${miniLadderLarge(s.levels)}
          <div class="pills" style="margin-top:10px" id="d-levels">${Object.keys(BIT).map((k) => `<button class="pill ${s.levels & BIT[k] ? "on" : ""}" data-lv="${k}">${esc(({ ecde: "Pre-primary", primary: "Primary", junior: "Junior School", senior: "Senior", tvet: "TVET", ttc: "Teacher training", university: "University", adult: "Adult", nonformal: "Non-formal" })[k])}</button>`).join("")}</div>
          <p class="muted" style="font-size:12px;margin:6px 0 0">Wrong? Click the levels to correct them.</p></section>
        <section class="d-sec"><h3>Contacts <span><button class="btn small" id="d-refresh" ${s.website ? "" : "disabled"} title="${s.website ? "Read the school's website again now" : "Add a website first"}">${ICON.refresh} Re-check website</button></span></h3>
          ${contacts.length ? contacts.map((c) => `<div class="contact ${c.active ? "" : "stale"}">
            <span class="ci ${c.active ? "on" : ""}">${ICON[c.kind] || ICON.contact_page}</span>
            <div><div class="v">${contactValue(c)}${c.label && !["general", "office"].includes(c.label) ? `<span class="badge">${esc(c.label)}</span>` : ""}${c.active && main[c.kind] === c.value && contacts.filter((x) => x.kind === c.kind && x.active).length > 1 ? `<span class="badge main">main</span>` : ""}${c.kind === "email" && c.value === s.email && s.shared_email_count > 1 ? `<span class="badge warn" title="Also listed for other schools">shared ×${s.shared_email_count}</span>` : ""}</div>
              <div class="meta">${esc(CONTACT_LABEL[c.kind] || c.kind)} · from ${c.source_url ? `<a href="${esc(c.source_url)}" target="_blank" rel="noopener">${esc(SOURCE_LABEL[c.source] || c.source)}</a>` : esc(SOURCE_LABEL[c.source] || c.source)} · ${c.active ? `seen ${ago(c.last_seen)}` : "no longer listed"}</div></div>
            <div class="acts">${c.active && ["email", "phone", "website"].includes(c.kind) && main[c.kind] !== c.value ? `<button class="btn small" data-primary="${c.id}">Use this one</button>` : ""}
              <button class="btn small" data-active="${c.id}" data-to="${c.active ? 0 : 1}" title="${c.active ? "Mark this as wrong or out of date" : "Put this back"}">${c.active ? "Wrong / old" : "Put back"}</button></div>
          </div>`).join("") : `<p class="muted" style="margin:0">No contact details yet. Add what you find below${s.website ? "" : ", and once a website is on file its contact page is read automatically"}.</p>`}
          <form class="add-contact" id="d-add">
            <select name="kind">${Object.entries(CONTACT_LABEL).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
            <input name="value" placeholder="e.g. 0722 123 456, principal@school.sc.ke" required>
            <button class="btn" type="submit">Add</button>
          </form>
        </section>
        <section class="d-sec"><h3>Log activity</h3>
          <form class="log-form" id="d-log">
            <div class="log-kinds pills">${[["note", "Note"], ["call", "Call"], ["sms", "SMS / WhatsApp"], ["email", "Email"], ["meeting", "Meeting"], ["visit", "Visit"]].map(([k, l], i) => `<button type="button" class="pill ${i ? "" : "on"}" data-kind="${k}">${l}</button>`).join("")}</div>
            <textarea name="body" rows="3" placeholder="What happened? Who did you speak to?"></textarea>
            <div><button class="btn primary" type="submit">Save to log</button></div>
          </form>
          ${s.activities.map((a) => `<div class="activity ${a.kind === "system" ? "system" : ""}"><div class="when">${esc(a.kind === "system" ? "Update" : a.kind[0].toUpperCase() + a.kind.slice(1))} · ${ago(a.created_at)}</div><div class="body">${esc(a.body)}</div></div>`).join("")}
        </section>
        <section class="d-sec"><h3>School</h3>
          <dl class="facts">
            <div><dt>Size</dt><dd>${size}${webStudents}</dd></div>
            <div><dt>Teachers</dt><dd>${s.teachers ? n(s.teachers) : "Not recorded"}</dd></div>
            <div><dt>Ownership</dt><dd>${esc(s.ownership ? s.ownership[0].toUpperCase() + s.ownership.slice(1) : "Not recorded")}</dd></div>
            <div><dt>Sponsor</dt><dd>${esc(SPONSOR_LABEL[s.sponsor] || "Not recorded")}</dd></div>
            <div><dt>Faith link</dt><dd>${esc(s.faith || "None recorded")}</dd></div>
            <div><dt>Learners</dt><dd>${esc(({ mixed: "Mixed", girls: "Girls only", boys: "Boys only" })[s.gender] || "Not recorded")}${s.boarding ? ` · ${esc(({ boarding: "boarding", day: "day", day_boarding: "day & boarding" })[s.boarding])}` : ""}</dd></div>
            ${s.special_needs ? `<div><dt>Special needs</dt><dd>Special school or unit</dd></div>` : ""}
            ${osmx.curriculum ? `<div><dt>Curriculum</dt><dd>${esc(osmx.curriculum.replace(/_/g, "-").replace("2-6-3-3-3", "CBC (2-6-3-3-3)"))}</dd></div>` : ""}
            ${osmx.fees_per_year ? `<div><dt>Fees per year</dt><dd>KES ${esc(osmx.fees_per_year)}</dd></div>` : ""}
            ${x.category ? `<div><dt>School category</dt><dd>${esc(x.category)} school</dd></div>` : ""}
            ${s.nemis_code ? `<div><dt>NEMIS code</dt><dd>${esc(s.nemis_code)}</dd></div>` : ""}
          </dl>
          <div class="tags-edit" style="margin-top:14px" id="d-tags">${s.tags.map((t) => `<span class="chip">${esc(t)}<button data-tag="${esc(t)}" aria-label="Remove tag">×</button></span>`).join("")}
            <input placeholder="Add tag + Enter" id="d-tag-in"></div>
        </section>
        <section class="d-sec"><h3>Where</h3>
          <dl class="facts">
            <div><dt>County</dt><dd>${esc(s.county || "—")}<br><small>${compact(s.county_pop)} people · ${compact(s.county_school_age)} aged 5–19</small></dd></div>
            <div><dt>Constituency</dt><dd>${esc(s.subcounty || "—")}<br><small>${compact(s.const_pop)} people (2020 est.)</small></dd></div>
            <div><dt>Setting</dt><dd>${esc(settingLabel || "—")}<br><small>${s.pop_density != null ? `${n(s.pop_density)} people per km²` : ""}</small></dd></div>
            <div style="grid-column:1/-1"><dt>Address</dt><dd>${esc(s.address || "—")}</dd></div>
            <div><dt>Postal address</dt><dd>${esc(s.postal_address || "Not on file")}</dd></div>
            ${s.location || s.sublocation ? `<div><dt>Location (2010 list)</dt><dd>${esc([s.sublocation, s.location, s.division].filter(Boolean).join(", "))}</dd></div>` : ""}
            ${s.town ? `<div><dt>Town</dt><dd>${esc(s.town)}</dd></div>` : ""}
          </dl>
          ${s.lat != null ? `<div class="d-map" id="d-map"></div>
            <p style="margin:8px 0 0;font-size:12.5px"><a target="_blank" rel="noopener" href="https://www.google.com/maps/search/?api=1&query=${s.lat},${s.lon}">Open in Google Maps</a> ·
            <a target="_blank" rel="noopener" href="https://www.openstreetmap.org/?mlat=${s.lat}&mlon=${s.lon}#map=16/${s.lat}/${s.lon}">OpenStreetMap</a></p>` : ""}
        </section>
        ${s.nearby.length ? `<section class="d-sec nearby"><h3>Nearby schools</h3>${s.nearby.map((x) => `<a href="#" data-open="${x.id}"><span>${esc(x.name)} <span class="muted">· ${esc(x.level_labels.join(", "))}</span></span><span>${x.km} km</span></a>`).join("")}</section>` : ""}
        <section class="d-sec"><h3>Sources</h3>
          <p class="muted" style="margin:0;font-size:12.5px">${esc(s.sources.map((x) => ({ moe2010: "Ministry of Education list (2010)", moe2017: "Ministry of Education list (2017)", osm: "OpenStreetMap", wikidata: "Wikidata", web: "school website", teacher: "Teacher.co.ke county list (2020/21)", eeg: "Enhanced Education Group directory", enh: "Education News Hub profile" })[x] || x).join(" · "))}
          ${s.osm_id ? ` · <a target="_blank" rel="noopener" href="https://www.openstreetmap.org/${esc(s.osm_id)}">map record</a>` : ""}
          ${s.enriched_at ? ` · website read ${ago(s.enriched_at)} (${esc(s.enrich_status)})` : ""}</p>
          ${x.moe_units && x.moe_units.length > 1 ? `<ul class="units">${x.moe_units.map((u) => `<li>${esc(u.name)} — ${esc((u.level || "").toLowerCase())}</li>`).join("")}</ul>` : ""}
        </section>
      </div>`;
    $("#d-close").onclick = closeDrawer;
    $("#d-quick-email")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const r = await api(`schools/${s.id}/contacts`, { method: "POST", body: { kind: "email", value: $("#qe").value } });
      if (r.error) return toast(r.error);
      renderDrawer(r); updateRow(r); toast("Email saved");
    });
    $("#d-star").onclick = () => patch(s.id, { starred: !s.starred });
    $$(".stages button", d).forEach((b) => (b.onclick = () => patch(s.id, { status: b.dataset.s }, `Moved to ${STAGE_LABEL[b.dataset.s]}`)));
    $$("#d-levels .pill", d).forEach((b) => (b.onclick = () => {
      const lv = b.dataset.lv;
      const keys = Object.keys(BIT).filter((k) => (k === lv ? !(s.levels & BIT[k]) : (s.levels & BIT[k])));
      patch(s.id, { levels: keys });
    }));
    $("#d-refresh").onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = "Reading the website…";
      const r = await api(`schools/${s.id}/refresh`, { method: "POST" });
      if (r.error) { toast(r.error); e.target.disabled = false; return; }
      renderDrawer(r); updateRow(r); toast("Website checked");
    };
    $$("[data-primary]", d).forEach((b) => (b.onclick = async () => { const r = await api(`contacts/${b.dataset.primary}`, { method: "PATCH", body: { primary: true } }); renderDrawer(r); updateRow(r); }));
    $$("[data-active]", d).forEach((b) => (b.onclick = async () => { const r = await api(`contacts/${b.dataset.active}`, { method: "PATCH", body: { active: b.dataset.to === "1" } }); renderDrawer(r); updateRow(r); }));
    $("#d-add").onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const r = await api(`schools/${s.id}/contacts`, { method: "POST", body: { kind: fd.get("kind"), value: fd.get("value") } });
      if (r.error) return toast(r.error);
      renderDrawer(r); updateRow(r); toast("Added");
    };
    let logKind = "note";
    $$("[data-kind]", d).forEach((b) => (b.onclick = () => { logKind = b.dataset.kind; $$("[data-kind]", d).forEach((x) => x.classList.toggle("on", x === b)); }));
    $("#d-log").onsubmit = async (e) => {
      e.preventDefault();
      const body = new FormData(e.target).get("body");
      const r = await api(`schools/${s.id}/activities`, { method: "POST", body: { kind: logKind, body } });
      if (r.error) return toast(r.error);
      if (s.status === "new" || s.status === "queued") {
        if (["call", "sms", "email", "meeting", "visit"].includes(logKind)) return patch(s.id, { status: "contacted" }, "Logged, and moved to Contacted");
      }
      renderDrawer(r); updateRow(r); toast("Logged");
    };
    $$("[data-tag]", d).forEach((b) => (b.onclick = () => patch(s.id, { tags: s.tags.filter((t) => t !== b.dataset.tag) })));
    $("#d-tag-in").onkeydown = (e) => { if (e.key === "Enter" && e.target.value.trim()) patch(s.id, { tags: [...s.tags, e.target.value.trim()] }, "Tagged"); };
    $$("[data-open]", d).forEach((a) => (a.onclick = (e) => { e.preventDefault(); openSchool(+a.dataset.open); }));
    if (dMap) { dMap.remove(); dMap = null; }
    if (s.lat != null && window.L) {
      dMap = L.map("d-map", { zoomControl: false, attributionControl: false, dragging: true, scrollWheelZoom: false }).setView([s.lat, s.lon], 14);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18 }).addTo(dMap);
      L.circleMarker([s.lat, s.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#1f4fa3", fillOpacity: 1 }).addTo(dMap);
    }
  }
  function quickActions(s) {
    const phone = s.phone, mobile = phone && /^\+254 [17]/.test(phone);
    const btn = (href, label, icon, sub, ext) => `<a class="quick-btn" href="${esc(href)}" ${ext ? 'target="_blank" rel="noopener"' : ""}>${ICON[icon]}<span><strong>${label}</strong><small>${esc(sub)}</small></span></a>`;
    const out = [];
    if (phone) out.push(btn(`tel:${phone.replace(/\s/g, "")}`, "Call", "phone", phone));
    if (mobile) out.push(btn(`https://wa.me/${phone.replace(/\D/g, "")}`, "WhatsApp", "phone", "Send a message", true));
    if (s.email) out.push(btn(`mailto:${s.email}`, "Email", "email", s.email));
    if (s.website) out.push(btn(s.website, "Website", "website", s.website.replace(/^https?:\/\/(www\.)?/, ""), true));
    if (!s.email) {
      const q = `${s.name} ${s.county || ""} Kenya`;
      out.push(btn(`https://www.facebook.com/search/pages/?q=${encodeURIComponent(q)}`, "Find on Facebook", "facebook", "Look for the school's page", true));
      out.push(btn(`https://www.google.com/search?q=${encodeURIComponent(`"${s.name}" ${s.county || ""} email`)}`, "Search Google for email", "email", "Opens a search in a new tab", true));
    }
    return out.join("") + (!s.email ? `<form class="quick-email" id="d-quick-email"><label for="qe">Found the email? Paste it here:</label>
      <div><input id="qe" type="email" placeholder="school@example.com" required><button class="btn primary" type="submit">Save email</button></div></form>` : "");
  }
  function miniLadderLarge(mask) {
    const cells = miniLadder(mask).replace('class="mini"', 'class="mini mini-lg"');
    return `${cells}<div class="mini mini-lg mini-labels">${GRADES.map((g) => `<span>${GRADE_SHORT[g] ?? g}</span>`).join("")}</div>`;
  }
  async function patch(id, body, msg) {
    const r = await api(`schools/${id}`, { method: "PATCH", body });
    renderDrawer(r); updateRow(r);
    if (msg) toast(msg);
    if (body.tags) state.facets = await api("facets");
  }
  function updateRow(s) {
    const i = state.rows.findIndex((r) => r.id === s.id);
    if (i < 0) return;
    const keep = state.rows[i];
    state.rows[i] = { ...keep, ...Object.fromEntries(Object.keys(keep).filter((k) => k in s).map((k) => [k, s[k]])) };
    const tr = $(`#rows tr[data-id="${s.id}"]`);
    if (tr) tr.outerHTML = rowHTML(state.rows[i], i);
  }

  // ------------------------------------------------------------ keyboard
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select")) { if (e.key === "Escape") e.target.blur(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === "/") { e.preventDefault(); if (state.view !== "schools") go("schools", state.f); setTimeout(() => $("#q").focus(), 30); return; }
    if (e.key === "Escape") { if (!$("#drawer").hidden) closeDrawer(); $("#filters").classList.remove("show"); return; }
    if (state.view !== "schools") return;
    const move = (d) => {
      if (!state.rows.length) return;
      state.cursor = Math.max(0, Math.min(state.rows.length - 1, state.cursor + d));
      $$("#rows tr").forEach((tr) => tr.classList.toggle("cursor", +tr.dataset.i === state.cursor));
      $(`#rows tr[data-i="${state.cursor}"]`)?.scrollIntoView({ block: "nearest" });
      if (!$("#drawer").hidden) openSchool(state.rows[state.cursor].id);
    };
    const cur = state.rows[state.cursor];
    if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Enter" && cur) openSchool(cur.id);
    else if (e.key === "x" && cur) { state.selected.has(cur.id) ? state.selected.delete(cur.id) : state.selected.add(cur.id); const c = $(`[data-sel="${cur.id}"]`); if (c) c.checked = state.selected.has(cur.id); renderBulk(); }
    else if (e.key === "s" && state.open) patch(state.open, { starred: !(state.rows.find((r) => r.id === state.open) || {}).starred });
    else if (/^[1-9]$/.test(e.key) && state.open) { const st = STAGES[+e.key - 1][0]; patch(state.open, { status: st }, `Moved to ${STAGE_LABEL[st]}`); }
  });

  // ------------------------------------------------------------ tooltip
  const tip = document.createElement("div");
  tip.className = "tooltip"; tip.hidden = true; document.body.appendChild(tip);
  const showTip = (e, html) => { tip.innerHTML = html; tip.hidden = false; tip.style.left = `${Math.min(e.clientX + 14, innerWidth - 270)}px`; tip.style.top = `${e.clientY + 14}px`; };
  const hideTip = () => (tip.hidden = true);

  // ------------------------------------------------------------ overview
  let geo = null, choroMetric = "per_child";
  async function renderOverview() {
    const el = $("#view-overview");
    if (!state.summary) el.innerHTML = `<div class="page"><p class="muted">Loading…</p></div>`;
    const [s, g] = await Promise.all([api("summary"), geo ? Promise.resolve(geo) : api("geo/counties")]);
    state.summary = s; geo = g;
    const T = s.schools || 1;
    const stageRows = [
      ["ecde", "Nursery (PP1–2)", s.l_ecde, "var(--stage-ecde)"], ["primary", "Primary (G1–6)", s.l_primary, "var(--stage-primary)"],
      ["junior", "Junior School (G7–9)", s.l_junior, "var(--stage-junior)"], ["senior", "Secondary (G10–12)", s.l_senior, "var(--stage-senior)"],
      ["tvet", "TVET / polytechnic", s.l_tvet, "var(--stage-post)"], ["ttc", "Teacher training", s.l_ttc, "var(--stage-post)"],
      ["university", "University", s.l_university, "var(--stage-post)"], ["nonformal", "Non-formal (APBET)", s.l_nonformal, "var(--rule-strong)"],
      ["adult", "Adult education", s.l_adult, "var(--rule-strong)"]];
    const maxStage = Math.max(...stageRows.map((r) => r[2]));
    const funnelMax = Math.max(1, ...STAGES.slice(0, 7).map(([k]) => s.by_status[k] || 0));
    const rampSteps = ["var(--seq-300)", "var(--seq-400)", "var(--seq-500)", "var(--seq-600)", "var(--seq-700)", "var(--good)"];
    el.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Every school in Kenya</h1>
        <p>${n(s.schools)} schools in all 47 counties, from nursery schools to universities. Click <strong>Find schools</strong> to search by grade, county and size.</p></div>
        <span style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn" href="#/schools?grades=10,11,12&missing=email&sort=size" title="Secondary schools with no email yet, biggest first. Open one and use Find on Facebook or Search Google.">Find missing emails</a>
        <a class="btn primary" href="#/schools">Find schools</a></span></div>
      <div class="hero">
        <div><div class="big">${n(s.schools)}</div><div class="lbl">schools and learning centres</div></div>
        <a class="hero-link" href="#/schools?has=email"><div class="mid">${n(s.with_email)}</div><div class="lbl">with an email (${pct(s.with_email, T)})</div></a>
        <a class="hero-link" href="#/schools?has=phone"><div class="mid">${n(s.with_phone)}</div><div class="lbl">with a phone number (${pct(s.with_phone, T)})</div></a>
        <div><div class="mid">${n(s.engaged)}</div><div class="lbl">in conversation with you</div></div>
        <div><div class="mid">${compact(s.school_age)}</div><div class="lbl">children aged 5–19 (2019 census)</div></div>
      </div>
      <div class="grid-2">
        <div class="card"><h2>Schools by grade level</h2><p class="sub">A school counts once for each level it teaches. Click a bar to list those schools.</p>
          <div class="stage-bars">${stageRows.map(([k, l, v, c]) => `<div class="sbar" data-level="${k}" role="button" tabindex="0">
            <span class="k"><i style="background:${c}"></i>${l}</span><span class="track"><span class="fill" style="display:block;width:${(100 * v) / maxStage}%;background:${c}"></span></span><span class="v">${n(v)}</span></div>`).join("")}</div>
          <p class="muted" style="font-size:12px;margin:10px 0 0">Junior School (Grades 7–9) is new since 2023 and mostly housed in primary schools, which the 2010 Ministry list can't show. Filter by Grades 7–9 to include them.</p>
        </div>
        <div class="card"><h2>Where the schools are</h2><p class="sub">Darker blue means more. Click a county to see its schools.</p>
          <div class="metric-switch" id="choro-metric">${[["per_child", "Schools per 10,000 children"], ["schools", "Schools"], ["reach", "Contact coverage"], ["engaged", "Engaged"]].map(([k, l]) => `<button data-m="${k}" class="${choroMetric === k ? "on" : ""}">${l}</button>`).join("")}</div>
          <div class="choro-wrap"><div class="choro" id="choro"></div><div class="choro-side" id="choro-side"></div></div>
        </div>
      </div>
      <div class="grid-3">
        <div class="card"><h2>Public and private</h2><p class="sub">Ownership recorded for ${pct(s.public + s.private, T)} of schools.</p>
          ${stack([[s.public, "var(--series-1)", "Public"], [s.private, "var(--series-2)", "Private"]])}
          <h2 style="margin-top:22px">Urban and rural</h2><p class="sub">By population density around each school.</p>
          ${stack([[s.urban, "var(--series-1)", "Urban"], [s.peri_urban, "var(--series-2)", "Peri-urban"], [s.rural, "var(--series-3)", "Rural"]])}
        </div>
        <div class="card"><h2>Contact coverage</h2><p class="sub">Share of all schools with each detail on file.</p>
          <div class="coverage">${[["Phone", s.with_phone], ["Email", s.with_email], ["Website", s.with_website], ["Named head", s.with_leader], ["P.O. Box", s.with_address], ["Size known", Math.max(s.with_students, s.with_classrooms)]].map(([l, v]) =>
            `<div class="cov"><span>${l}</span><span class="track"><span class="fill" style="display:block;width:${(100 * v) / T}%"></span></span><span class="v">${n(v)} · ${pct(v, T)}</span></div>`).join("")}</div>
          ${s.never_checked ? `<p class="muted" style="font-size:12.5px;margin:12px 0 0">${n(s.never_checked)} school websites haven't been read yet. Run <code>npm run crawl</code>.</p>` : ""}
        </div>
        <div class="card"><h2>Outreach</h2><p class="sub">Schools at each stage.</p>
          <div class="funnel">${STAGES.slice(0, 7).map(([k, l], i) => `<div class="frow"><a href="#/schools?status=${k}">${l}</a><span class="track"><span class="fill" style="display:block;width:${(100 * (s.by_status[k] || 0)) / funnelMax}%;background:${rampSteps[Math.max(0, i - 1)] || "var(--seq-200)"}"></span></span><span class="v">${n(s.by_status[k] || 0)}</span></div>`).join("")}</div>
        </div>
      </div>
      <div class="grid-2">
        <div class="card"><h2>Faith sponsors</h2><p class="sub">From school names and sponsor records. Many church-sponsored public schools carry no denomination in their name.</p>
          <div class="stage-bars">${s.faiths.slice(0, 10).map((f) => `<div class="sbar" data-faith="${esc(f.name)}" role="button" tabindex="0"><span class="k">${esc(f.name)}</span><span class="track"><span class="fill" style="display:block;width:${(100 * f.n) / s.faiths[0].n}%"></span></span><span class="v">${n(f.n)}</span></div>`).join("")}</div>
        </div>
        <div class="card"><h2>Recent activity</h2><p class="sub">Calls, notes and visits logged by your team.</p>
          <div class="recent">${s.recent.length ? s.recent.map((a) => `<a href="#/schools?open=${a.school_id}"><strong>${esc(a.school_name)}</strong><span class="when">${ago(a.created_at)}</span><span class="body">${esc(a.kind)}: ${esc(a.body)}</span></a>`).join("")
            : `<p class="muted" style="margin:0">Nothing logged yet. Open a school and log a call or note to start.</p>`}</div>
        </div>
      </div>
    </div>`;
    $$(".sbar[data-level]", el).forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.level, gs = { ecde: ["-1", "0"], primary: ["1", "2", "3", "4", "5", "6"], junior: ["7", "8", "9"], senior: ["10", "11", "12"] }[k];
      go("schools", gs ? { grades: gs, jss: k === "junior" ? "0" : "" } : { level: [k] });
    }));
    $$(".sbar[data-faith]", el).forEach((b) => b.addEventListener("click", () => go("schools", { faith: [b.dataset.faith] })));
    $$("#choro-metric button", el).forEach((b) => b.addEventListener("click", () => { choroMetric = b.dataset.m; $$("#choro-metric button").forEach((x) => x.classList.toggle("on", x === b)); drawChoro(); }));
    drawChoro();
  }
  function stack(parts) {
    const tot = parts.reduce((a, p) => a + p[0], 0) || 1;
    return `<div class="stack">${parts.map(([v, c, l]) => `<div style="width:${(100 * v) / tot}%;background:${c}" title="${l}: ${n(v)}"></div>`).join("")}</div>
      <div class="legend">${parts.map(([v, c, l]) => `<span><i style="background:${c}"></i>${l} <strong>${pct(v, tot)}</strong></span>`).join("")}</div>`;
  }
  function project(features) {
    let minX = 99, maxX = -99, minY = 99, maxY = -99;
    const each = (g, fn) => (g.type === "Polygon" ? [g.coordinates] : g.coordinates).forEach((p) => p.forEach((ring) => ring.forEach(fn)));
    features.forEach((f) => each(f.geometry, ([x, y]) => { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y); }));
    const k = Math.cos((((minY + maxY) / 2) * Math.PI) / 180), W = 400, s = W / ((maxX - minX) * k), H = (maxY - minY) * s;
    const path = (g) => (g.type === "Polygon" ? [g.coordinates] : g.coordinates).map((p) => p.map((ring) => "M" + ring.map(([x, y]) => `${((x - minX) * k * s).toFixed(1)},${((maxY - y) * s).toFixed(1)}`).join("L") + "Z").join("")).join("");
    return { W, H, path };
  }
  function drawChoro() {
    const s = state.summary, byCode = Object.fromEntries(s.counties.map((c) => [c.code, c]));
    const val = (c) => !c ? null : choroMetric === "per_child" ? (c.school_age ? (10000 * c.schools) / c.school_age : null)
      : choroMetric === "schools" ? c.schools : choroMetric === "reach" ? (c.schools ? c.reachable / c.schools : null) : c.engaged;
    const vals = s.counties.map(val).filter((v) => v != null).sort((a, b) => a - b);
    const steps = ["--seq-100", "--seq-200", "--seq-300", "--seq-400", "--seq-500", "--seq-600", "--seq-700"];
    const q = (v) => { if (v == null || !vals.length) return "var(--sheet-2)"; let i = 0; while (i < 6 && v > vals[Math.floor(((i + 1) * vals.length) / 7) - 1]) i++; return `var(${steps[i]})`; };
    const fmt = (v) => v == null ? "—" : choroMetric === "reach" ? `${Math.round(v * 100)}%` : choroMetric === "per_child" ? v.toFixed(1) : n(v);
    const P = project(geo.features);
    $("#choro").innerHTML = `<svg viewBox="0 0 ${P.W} ${P.H.toFixed(0)}" role="img" aria-label="Map of Kenya's counties">${geo.features.map((f) =>
      `<path d="${P.path(f.geometry)}" fill="${q(val(byCode[f.id]))}" data-code="${f.id}"><title>${esc(f.properties.name)}: ${fmt(val(byCode[f.id]))}</title></path>`).join("")}</svg>`;
    const side = (c) => {
      $("#choro-side").innerHTML = c ? `<div class="hover-name">${esc(c.name)}</div>
        <dl><div><dt>Schools</dt><dd>${n(c.schools)}</dd></div><div><dt>Population (2019)</dt><dd>${n(c.population)}</dd></div>
        <div><dt>Children 5–19</dt><dd>${n(c.school_age)}</dd></div><div><dt>Schools per 10,000 children</dt><dd>${c.school_age ? ((10000 * c.schools) / c.school_age).toFixed(1) : "—"}</dd></div>
        <div><dt>Primary · Secondary</dt><dd>${n(c.primary_n)} · ${n(c.senior_n)}</dd></div><div><dt>With phone or email</dt><dd>${pct(c.reachable, c.schools)}</dd></div></dl>`
        : `<div class="muted">Point at a county for its numbers.</div>`;
    };
    side(null);
    $$("#choro path").forEach((p) => {
      p.addEventListener("mouseenter", () => side(byCode[p.dataset.code]));
      p.addEventListener("click", () => go("schools", { county: [p.dataset.code] }));
    });
    const legend = document.createElement("div");
    legend.className = "seq-legend";
    legend.innerHTML = `<span>${fmt(vals[0])}</span><span class="ramp">${steps.map((s) => `<i style="background:var(${s})"></i>`).join("")}</span><span>${fmt(vals[vals.length - 1])}</span>`;
    $("#choro").appendChild(legend);
  }

  // ------------------------------------------------------------ map
  const PointsLayer = window.L ? L.Layer.extend({
    initialize(points) { this.points = points; },
    onAdd(map) {
      this._map = map;
      this.canvas = L.DomUtil.create("canvas", "leaflet-zoom-animated");
      map.getPanes().overlayPane.appendChild(this.canvas);
      map.on("moveend zoomend resize", this.redraw, this);
      map.on("click", this.onClick, this);
      map.on("mousemove", this.onMove, this);
      this.redraw();
    },
    onRemove(map) { this.canvas.remove(); map.off("moveend zoomend resize", this.redraw, this); map.off("click", this.onClick, this); map.off("mousemove", this.onMove, this); },
    setPoints(p) { this.points = p; this.redraw(); },
    redraw() {
      const map = this._map; if (!map) return;
      const size = map.getSize(), tl = map.containerPointToLayerPoint([0, 0]);
      L.DomUtil.setPosition(this.canvas, tl);
      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = size.x * dpr; this.canvas.height = size.y * dpr;
      this.canvas.style.width = `${size.x}px`; this.canvas.style.height = `${size.y}px`;
      const ctx = this.canvas.getContext("2d"); ctx.scale(dpr, dpr);
      const z = map.getZoom(), r = z < 8 ? 1.6 : z < 11 ? 3 : 5;
      const css = getComputedStyle(document.documentElement);
      const col = [css.getPropertyValue("--series-1"), css.getPropertyValue("--series-2"), css.getPropertyValue("--series-3")].map((c) => c.trim());
      const ring = css.getPropertyValue("--sheet").trim();
      const b = map.getBounds().pad(0.05);
      this.screen = [];
      for (const p of this.points) {
        if (!b.contains([p[1], p[2]])) continue;
        const pt = map.latLngToContainerPoint([p[1], p[2]]);
        const g = p[3] & (16 | 32 | 64 | 128) && !(p[3] & (1 | 2 | 4 | 8 | 256)) ? 2 : p[3] & 8 ? 1 : 0;
        this.screen.push([pt.x, pt.y, p[0]]);
        ctx.beginPath(); ctx.arc(pt.x, pt.y, r, 0, 6.2832);
        ctx.fillStyle = col[g]; ctx.fill();
        if (r >= 3) { ctx.lineWidth = 1.2; ctx.strokeStyle = ring; ctx.stroke(); }
      }
    },
    nearest(e) {
      let best = null, bd = 64;
      for (const [x, y, id] of this.screen || []) { const d = (x - e.containerPoint.x) ** 2 + (y - e.containerPoint.y) ** 2; if (d < bd) { bd = d; best = id; } }
      return best;
    },
    onClick(e) { const id = this.nearest(e); if (id) openSchool(id); },
    onMove(e) { this._map.getContainer().style.cursor = this.nearest(e) ? "pointer" : ""; },
  }) : null;
  let mapLayer = null, mapSeq = 0;
  function renderMap() {
    if (!window.L) { $("#map").innerHTML = `<div class="empty"><h3>The map library didn't load</h3>Check the internet connection, then reload.</div>`; return; }
    if (!state.map) {
      state.map = L.map("map", { preferCanvas: true }).fitBounds([[-4.75, 33.9], [5.05, 41.95]]);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(state.map);
      mapLayer = new PointsLayer([]); mapLayer.addTo(state.map);
      $("#map-legend").innerHTML = `<span><i style="background:var(--series-1)"></i>Nursery & primary</span><span><i style="background:var(--series-2)"></i>Secondary</span><span><i style="background:var(--series-3)"></i>Post-secondary</span>`;
      $("#map-to-list").addEventListener("click", (e) => { e.preventDefault(); const b = state.map.getBounds(); go("schools", { ...state.f, bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((x) => x.toFixed(4)).join(",") }); });
    }
    setTimeout(() => state.map.invalidateSize(), 50);
    loadMapPoints();
  }
  async function loadMapPoints() {
    const seq = ++mapSeq;
    const f = { ...state.f }; delete f.bbox;
    const saved = state.f; state.f = f;
    const p = paramsFromFilters(); state.f = saved;
    $("#map-summary").textContent = "Loading schools…";
    const d = await api(`points?${p}`);
    if (seq !== mapSeq) return;
    mapLayer.setPoints(d.points);
    const active = Object.values(f).some((v) => (Array.isArray(v) ? v.length : v));
    $("#map-summary").innerHTML = `<strong>${n(d.points.length)}</strong> schools${active ? ` match your filters (<a href="#/schools?${p}">change filters</a>)` : ". Set filters on the Schools page to narrow the map."} Click a dot to open the school.`;
  }

  // ------------------------------------------------------------ pipeline
  async function renderPipeline() {
    const el = $("#view-pipeline");
    el.innerHTML = `<div class="page" style="max-width:none;padding-bottom:12px"><div class="page-head"><div><h1>Pipeline</h1>
      <p>Drag a school between stages. ${Object.values(state.f).some((v) => (Array.isArray(v) ? v.length : v)) ? `Showing schools that match your <a href="#/schools?${paramsFromFilters()}">filters</a>.` : "Filters from the Schools page apply here too."}</p></div></div></div><div class="board" id="board"><p class="muted" style="padding:0 0 0 4px">Loading…</p></div>`;
    const d = await api(`pipeline?${paramsFromFilters()}`);
    $("#board").innerHTML = STAGES.map(([k, l]) => `<div class="col" data-s="${k}"><h3><span class="stage" data-s="${k}">${l}</span><span class="n">${n(d[k].total)}</span></h3>
      ${d[k].rows.map((r) => `<div class="pcard" draggable="true" data-id="${r.id}"><div class="s-name">${r.starred ? '<span class="star">★</span>' : ""}${esc(r.name)}</div>
        <div class="s-sub">${esc([r.county, r.level_labels.slice(-1)[0]].filter(Boolean).join(" · "))}</div>${r.leader ? `<div class="leader">${esc(r.leader)}</div>` : ""}</div>`).join("")}
      ${d[k].total > d[k].rows.length ? `<div class="more"><a href="#/schools?${paramsFromFilters({ status: k })}">and ${n(d[k].total - d[k].rows.length)} more</a></div>` : ""}</div>`).join("");
    $$(".pcard").forEach((c) => {
      c.addEventListener("dragstart", (e) => e.dataTransfer.setData("text/plain", c.dataset.id));
      c.addEventListener("click", () => openSchool(+c.dataset.id));
    });
    $$(".col").forEach((col) => {
      col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("drop"); });
      col.addEventListener("dragleave", () => col.classList.remove("drop"));
      col.addEventListener("drop", async (e) => {
        e.preventDefault(); col.classList.remove("drop");
        await api(`schools/${e.dataTransfer.getData("text/plain")}`, { method: "PATCH", body: { status: col.dataset.s } });
        toast(`Moved to ${STAGE_LABEL[col.dataset.s]}`); renderPipeline();
      });
    });
  }

  // ------------------------------------------------------------ counties
  let areaSort = ["population", -1], areaCounty = null;
  async function renderAreas() {
    const el = $("#view-areas");
    const d = await api(`areas?${areaCounty ? `kind=const&county=${areaCounty.code}` : ""}`);
    const rows = d.rows.map((r) => ({ ...r, per_child: r.school_age ? (10000 * r.schools) / r.school_age : null, reach: r.schools ? (r.emails + r.phones) / 2 / r.schools : 0 }));
    const [key, dir] = areaSort;
    rows.sort((a, b) => ((a[key] ?? -1) > (b[key] ?? -1) ? dir : (a[key] ?? -1) < (b[key] ?? -1) ? -dir : 0));
    const maxPer = Math.max(...rows.map((r) => r.per_child || 0));
    const cols = [["name", areaCounty ? "Constituency" : "County"], ["population", "Population"], ["school_age", "Aged 5–19"], ["schools", "Schools"],
      ["per_child", "Per 10k children"], ["primary_n", "Primary"], ["senior_n", "Secondary"], ["post_n", "Post-sec."], ["private_n", "Private"], ["phones", "Phones"], ["emails", "Emails"], ["engaged", "Engaged"]];
    el.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>${areaCounty ? esc(areaCounty.name) + " County" : "Counties"}</h1>
        <p>${areaCounty ? "Constituencies, with population estimated from WorldPop 2020 and the number of schools in each." : "Population from the 2019 census, and how many schools each county has for its children. Click a county to see its constituencies."}</p></div>
        ${areaCounty ? `<span><button class="btn ghost" id="area-back">All counties</button> <a class="btn primary" href="#/schools?county=${areaCounty.code}">List ${esc(areaCounty.name)} schools</a></span>` : ""}</div>
      <div class="card" style="padding:0;overflow:auto"><table class="plain"><thead><tr>${cols.map(([k, l]) => `<th data-k="${k}" class="${k === "name" ? "" : "num"}">${l}${key === k ? (dir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}<th></th></tr></thead>
        <tbody>${rows.map((r) => `<tr data-code="${r.code}" data-name="${esc(r.name)}">
          <td><strong>${esc(r.name)}</strong></td><td class="num">${n(r.population)}</td><td class="num">${n(r.school_age)}</td><td class="num">${n(r.schools)}</td>
          <td class="num">${r.per_child == null ? "—" : r.per_child.toFixed(1)}</td><td class="num">${n(r.primary_n)}</td><td class="num">${n(r.senior_n)}</td><td class="num">${n(r.post_n)}</td>
          <td class="num">${pct(r.private_n, r.schools)}</td><td class="num">${n(r.phones)}</td><td class="num">${n(r.emails)}</td><td class="num">${n(r.engaged)}</td>
          <td class="bar-cell"><div class="inline-bar" style="width:${maxPer ? (100 * (r.per_child || 0)) / maxPer : 0}%" title="Schools per 10,000 children"></div></td></tr>`).join("")}</tbody></table></div>
      ${areaCounty ? "" : `<p class="muted" style="font-size:12.5px">Constituency populations are WorldPop 2020 estimates, because the census publishes sub-county figures on different boundaries. Aged 5–19 per constituency applies the county's share.</p>`}
    </div>`;
    $$("th[data-k]", el).forEach((th) => th.addEventListener("click", () => { areaSort = [th.dataset.k, areaSort[0] === th.dataset.k ? -areaSort[1] : th.dataset.k === "name" ? 1 : -1]; renderAreas(); }));
    $$("tbody tr", el).forEach((tr) => tr.addEventListener("click", () => {
      if (areaCounty) go("schools", { county: [areaCounty.code], const: [tr.dataset.code] });
      else { areaCounty = { code: tr.dataset.code, name: tr.dataset.name }; renderAreas(); }
    }));
    $("#area-back")?.addEventListener("click", () => { areaCounty = null; renderAreas(); });
  }

  // ------------------------------------------------------------ data
  async function renderData() {
    const s = state.summary || (state.summary = await api("summary"));
    const el = $("#view-data");
    el.innerHTML = `<div class="page">
      <div class="page-head"><div><h1>Data</h1><p>Where each record comes from, how fresh it is, and how to refresh it.</p></div></div>
      <div class="grid-2">
        <div class="card"><h2>Sources</h2><p class="sub">Every contact detail keeps a link to where it was found.</p>
          <div class="src"><span class="name">Ministry of Education school list</span><span class="muted">${n(s.src_moe)} schools</span>
            <span class="what">Every registered school with its level, public/private status, sponsor, classrooms and location. 2010 edition via the Humanitarian Data Exchange. Save the 2017 World Bank edition to <code>data/cache/wb_schools.json</code> and run <code>python3 -m harvest moe</code> to fold it in.</span></div>
          <div class="src"><span class="name">OpenStreetMap</span><span class="muted">${n(s.src_osm)} schools</span>
            <span class="what">Schools mapped by volunteers and community surveys: phones, emails, head teachers, enrolment, fees, and schools opened since 2010. © OpenStreetMap contributors, ODbL.</span></div>
          <div class="src"><span class="name">Teacher.co.ke county lists (2020/21)</span><span class="muted">principals & phones</span>
            <span class="what">Every public county and sub-county secondary school: principal's name, school phone, day/boarding, enrolment. The site hides its email column from harvesters, so emails aren't taken from it.</span></div>
          <div class="src"><span class="name">Private-school directories</span><span class="muted">emails, phones, P.O. Box</span>
            <span class="what">Enhanced Education Group's lists of private primary and secondary, international, kindergarten, TVET and university contacts, and Education News Hub's school profiles, where they show an email or phone in plain text.</span></div>
          <div class="src"><span class="name">School websites</span><span class="muted">${n(s.with_website)} known</span>
            <span class="what">Found on the map, Wikidata, or by checking the .sc.ke / .ac.ke addresses a school's name suggests (a site is kept only when it names the school). Each site's home, contact and principal pages are read for emails, phones, P.O. Box and the head's name. robots.txt is honoured.</span></div>
          <div class="src"><span class="name">Population</span><span class="muted">47 counties · 290 constituencies</span>
            <span class="what">County totals and ages 5–19 from the 2019 Kenya Population and Housing Census (KNBS, via OCHA). Constituency totals and each school's local density from WorldPop 2020. Boundaries: OCHA / IEBC.</span></div>
          <div class="src"><span class="name">Optional, paid or keyed</span><span class="muted">${s.places_enabled ? "Google Places on" : "Google Places off"} · ${s.brave_enabled ? "Brave on" : "Brave off"}</span>
            <span class="what">Set <code>GOOGLE_PLACES_API_KEY</code> to add Google's phone numbers and websites (<code>python3 -m harvest places --limit 500</code>), or <code>BRAVE_API_KEY</code> to add web search to website discovery.</span></div>
        </div>
        <div class="card"><h2>Refresh</h2><p class="sub">Run these in a terminal in the project folder. Every step can be stopped and resumed.</p>
          <pre class="cmd">python3 -m harvest discover        # find more school websites</pre>
          <pre class="cmd">python3 -m harvest crawl           # read every new website</pre>
          <pre class="cmd">python3 -m harvest crawl --stale-days 60   # re-check older ones</pre>
          <pre class="cmd">python3 -m harvest osm             # pull the latest map data (weekly)</pre>
          <h2 style="margin-top:18px">Recent runs</h2>
          <table class="plain" style="margin-top:6px"><tbody>${s.runs.map((r) => `<tr><td><strong>${esc(r.step)}</strong></td><td>${esc(r.status)}</td><td class="muted">${ago(r.started_at)}</td>
            <td class="muted" style="font-size:12px">${esc(Object.entries(JSON.parse(r.stats || "{}")).filter(([k]) => k !== "seconds").slice(0, 4).map(([k, v]) => `${k.replace(/_/g, " ")} ${typeof v === "number" ? n(v) : v}`).join(" · "))}</td></tr>`).join("")}</tbody></table>
        </div>
      </div>
      <div class="card"><h2>Before you reach out</h2><div class="prose" style="margin-top:8px">
        <p>A listed email or phone is a lead, not a confirmed inbox. Many schools use a Gmail or Yahoo address that changes when the head teacher moves, so check a contact's "seen" date and prefer the school's own site.</p>
        <p>Kenya's Data Protection Act 2019 applies to personal details such as a head teacher's name and mobile number: contact schools about school matters, say who you are, and honour requests to stop by setting the school to <strong>Do not contact</strong>.</p>
        <p>The 2010 Ministry list predates the CBC reforms, some closures, and many new private schools. The map fills some gaps. Correct a school's levels or details from its record when you learn more.</p></div></div>
    </div>`;
  }

  boot();
})();
