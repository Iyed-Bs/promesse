// The Scout Desk, built as the Terrace: every match a player has played is a seat in his terrace.
// Plain JS, one file. Rules from the spec: answer first and proof on demand; no number without its context; bands,
// not points; one seat ramp is the only colour data wears; crimson only for Promesse's own call; a model's panel only
// once it has passed its gate; what others think (EA, market value, MatchData) shown apart, as benchmarks.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const main = $("#main"), root = document.documentElement;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const motion = () => !reduced && window.gsap;
const api = async (path, opts) => { const r = await fetch(path, opts); if (!r.ok) throw new Error(`${r.status} on ${path}`); return r.json(); };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const eur = (v) => !v ? "—" : v >= 1e6 ? `€${(v / 1e6).toFixed(v >= 1e7 ? 0 : 1)} m` : v >= 1e3 ? `€${Math.round(v / 1e3)} k` : `€${v}`;
const num = (v) => v == null ? "—" : Math.round(v).toLocaleString("en");
const pct = (v) => v == null ? "—" : `${Math.round(v * 100)} %`;
const age = (a) => a == null ? "—" : `${Math.floor(a)} y ${Math.floor((a % 1) * 12)} m`;
const day = (d) => d ? new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—";
const season = (s) => `${String(s % 100).padStart(2, "0")}/${String((s + 1) % 100).padStart(2, "0")}`;
const ordinal = (n) => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th");
const yearsAt = (dob, y, m = 6, d = 1) => (new Date(y, m, d) - new Date(dob)) / 3.15576e10;
const store = { get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
                set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window: no memory */ } } };
// Two ways to see the desk's players as seats. Promesse: The Ground, a 3D model of the stadium (about 14 MB to download, more work for
// the graphics card). Promesse Light: the same stands drawn flat, nothing to download. The visitor's choice is kept in this browser;
// a phone-class device (touch screen, narrow window, little memory) opens in Light unless the visitor chose otherwise.
const DOOR = true;                       // ask at the first visit (false = open in DEFAULT_MODE without asking, the fascia still switches)
const DEFAULT_MODE = "promesse";
const phoneClass = () => matchMedia("(pointer: coarse)").matches || innerWidth <= 900 || (navigator.deviceMemory && navigator.deviceMemory < 4);
const deskMode = () => { const m = store.get("mode"); return m === "promesse" || m === "light" ? m : (phoneClass() ? "light" : DEFAULT_MODE); };
const SEASON_NOW = 2025;                 // the last complete season (25/26), as in precompute.py

// The one ramp. Step 0: youth football; 1-4: senior matches by level (Elo vs the big five's average that season).
const step = (level, kind) => kind === "youth" ? 0 : level == null ? 1 : level >= -50 ? 4 : level >= -150 ? 3 : level >= -250 ? 2 : 1;
const STEP_LABEL = ["youth football", "250+ Elo below the big five", "150 to 250 below", "within 150 of the big five", "big-five level or above"];
const KIND = { league: "league", cup: "domestic cup", europe: "Europe", youth: "youth" };
// a player's seat in the bowl and his row in a table wear the same ramp: the level he played at in 25/26
// (youth if he only played youth football; bare if we see no football from him that season)
const nowStep = (r) => r.min_now > 0 ? step(r.lvl, "league") : r.ym > 0 ? 0 : -1;
const STEP_SHORT = ["youth", "250+ below", "150 to 250 below", "within 150", "big five"];
const levelCell = (r) => { const s = nowStep(r); return s < 0 ? '<span class="dim">no minutes seen</span>' : `<i class="seatmark k${s}" style="vertical-align:-1px;margin-right:7px"></i>${STEP_SHORT[s]}`; };
// Transfermarkt names competitions by slug ("laliga", "premier-league"): print them as people write them
const LEAGUE_FIX = { laliga: "LaLiga", "laliga2": "LaLiga 2", "ligue-1": "Ligue 1", "ligue-2": "Ligue 2", "serie-a": "Serie A", "serie-b": "Serie B" };
const leagueName = (s) => !s ? "" : LEAGUE_FIX[s] || s.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const icon = (id) => `<svg class="ico" aria-hidden="true"><use href="#i-${id}"/></svg>`;
const ramp = (labels) => labels.map((l, i) => `<span><i class="seatmark k${i}"></i>${l}</span>`).join("");

// club names differ between sources ("FC Barcelona", "Barcelona"): same club when a distinctive word matches
const words = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().split(/[^a-z0-9]+/)
  .filter((w) => w.length > 2 && !["club", "the", "football", "futbol", "calcio", "sport", "sporting"].includes(w));
const sameClub = (a, b) => words(a).some((w) => words(b).includes(w));

/* ── small pieces of chrome ────────────────────────────────────────────────────────────────────────────────── */
const tip = $("#tip");
function showTip(html, x, y) {
  tip.innerHTML = html; tip.classList.add("on");
  const r = tip.getBoundingClientRect();
  let left = x + 14, top = y + 16;
  if (left + r.width > innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > innerHeight - 8) top = y - r.height - 12;
  tip.style.left = `${Math.max(8, left)}px`; tip.style.top = `${Math.max(8, top)}px`;
}
const hideTip = () => tip.classList.remove("on");
function toast(text) {
  const t = $("#toast"); t.textContent = text; t.classList.add("on");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 2600);
}
// two levels: Players and Clubs on top, each section's pages under it; Compare, Lists, Method in the drawer
// the desk's map: three groups, each page named for what it does, its purpose in one line
const SECTIONS = {
  scout: [["discover", "#/discover", "Find Players", "Describe the player you need in one sentence; the bowl lights the ones who fit"],
    ["boards", "#/boards", "Promesse's Picks", "Three lists the engine builds itself, each shown only once its test passes"],
    ["compare", "#/compare", "Compare Players", "Line players up at the same age, season by season"],
    ["lists", "#/lists", "Shortlists", "Your own working lists"]],
  game: [["combinations", "#/combinations", "Player Combinations", "In beta: which pairs do better together than apart, and where"],
    ["teams", "#/teams", "Clubs & Coaches", "How each team and each coach's teams play, and which players fit"],
    ["dives", "#/dives", "Deep Dives", "One club read through Promesse: FC Barcelona, then PSG"]],
  promesse: [["method", "#/method", "Scoreboard", "How Promesse is tested, where it stands, and how it grew"],
    ["data", "#/data", "Data & Vision", "The data Promesse holds, how it is used, and what a club's own data would add"]],
};
const SECTION_OF = { discover: "scout", boards: "scout", board: "scout", player: "scout", compare: "scout", lists: "scout",
  combinations: "game", teams: "game", coaches: "game", team: "game", coach: "game", club: "game", dives: "game", dive: "game",
  method: "promesse", data: "promesse", connect: "promesse" };
const CURRENT_OF = { board: "boards", coaches: "teams", team: "teams", coach: "teams", club: "dives", dive: "dives", connect: "data" };
function setNav(name) {
  const sec = SECTION_OF[name] || null, cur = CURRENT_OF[name] || name;
  $$(".stands a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === sec));
  const sub = $("#subnav");
  sub.innerHTML = sec ? SECTIONS[sec].map(([k, href, label, why]) => `<a href="${href}" title="${why}"${k === cur ? ' aria-current="page"' : ""}>${label}</a>`).join("") : "";
  sub.hidden = !sec;
  $$(".drawer a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === cur));
}
// the drawer: the whole desk on one panel, the three groups with every page and what it is for. Opens from the
// fascia, closes on Escape, on a pick, or on the shade
const drawer = $("#drawer"), drawerBtn = $("#drawer-open");
const GROUP_NAME = { scout: ["A", "Scout"], game: ["B", "The game"], promesse: ["C", "Promesse"] };
$(".drawer-panel", drawer).innerHTML = Object.entries(SECTIONS).map(([g, pages]) => `<div class="drawer-group">
    <h2><b>${GROUP_NAME[g][0]}</b>${GROUP_NAME[g][1]}</h2>
    ${pages.map(([k, href, label, why]) => `<a href="${href}" data-nav="${k}"><span>${label}<small>${why}</small></span></a>`).join("")}</div>`).join("");
function openDrawer(open) {
  drawer.hidden = !open; drawerBtn.setAttribute("aria-expanded", String(open));
  if (open) { $(".drawer-panel a", drawer)?.focus(); if (motion()) gsap.from(".drawer-panel a", { x: 24, opacity: 0, duration: 0.32, ease: "expo.out", stagger: 0.04 }); }
}
drawerBtn.addEventListener("click", () => openDrawer(drawer.hidden));
drawer.addEventListener("click", (e) => { if (e.target === drawer || e.target.closest("a")) openDrawer(false); });
addEventListener("keydown", (e) => { if (e.key === "Escape" && !drawer.hidden) openDrawer(false); });
// a block's sign: a painted row marker and the block's name (the stands' letters A-D belong to the nav alone)
const sign = (_, title, meta = "", id = "") =>
  `<div class="sign"><span class="tile" aria-hidden="true"></span><h2${id ? ` id="${id}"` : ""}>${title}</h2>${meta ? `<span class="meta">${meta}</span>` : ""}</div>`;

/* ── 15:00 or 20:45: daylight or floodlights ───────────────────────────────────────────────────────────────── */
const kick = () => root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "night" : "day");
const paintKick = () => $$(".kickoff button[data-kick]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kick === kick())));
function setKick(t) {
  if (t === kick()) return;
  const apply = () => { root.dataset.theme = t; store.set("kickoff", t); paintKick(); dispatchEvent(new Event("themechange")); };
  if (!motion()) return apply();
  // the four corner floodlights flare, the light changes at the peak, then they settle
  gsap.timeline().to(".floodlights", { opacity: t === "night" ? 1 : 0.7, duration: 0.2, ease: "power2.out" })
    .call(apply).to(".floodlights", { opacity: 0, duration: 0.9, ease: "expo.out" });
}
$$(".kickoff button[data-kick]").forEach((b) => b.addEventListener("click", () => setKick(b.dataset.kick)));
// the view switch on the fascia: Promesse or Light, remembered; the Discover page is drawn again in the new view
const paintMode = () => $$(".kickoff button[data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === deskMode())));
function setMode(m) { store.set("mode", m); paintMode(); if (/^#\/discover|^#?$/.test(location.hash)) route(); }
$$(".kickoff button[data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
paintMode();
// the door: on the first visit, before anything loads, one choice (Esc or the backdrop: open in the default for this visit, ask again next time)
function openDoor() {
  return new Promise((done) => {
    const d = document.createElement("dialog");
    d.className = "door"; d.setAttribute("aria-labelledby", "door-h");
    d.innerHTML = `<h2 id="door-h">Two ways into the stadium</h2>
      <p class="door-lead">Every player is a seat. Pick how you want to see them; you can switch any time from the bar at the top.</p>
      <div class="door-ways">
        <button type="button" data-mode="promesse" class="door-way"><b>Promesse</b><span>The Ground: a 3D model of the stadium, built in Blender. Fly to a seat or to a part of the ground. It downloads about 14 MB and asks more of the graphics card, so it opens a little slower.</span></button>
        <button type="button" data-mode="light" class="door-way"><b>Promesse Light</b><span>The same stands, tiers and players drawn flat. Nothing to download, opens at once, easiest on the computer and the battery.</span></button>
      </div>`;
    document.body.appendChild(d);
    const finish = (m) => { if (m) store.set("mode", m); paintMode(); d.close(); d.remove(); done(); };
    d.addEventListener("click", (e) => { const b = e.target.closest("[data-mode]"); if (b) finish(b.dataset.mode); });
    d.addEventListener("cancel", (e) => { e.preventDefault(); finish(null); });
    d.showModal();
    d.querySelector(`[data-mode="${DEFAULT_MODE}"]`)?.focus();
  });
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { paintKick(); dispatchEvent(new Event("themechange")); });
paintKick();

/* ── Glance, Scout or Expert: how much the desk shows (style.css reads html[data-depth]; Scout when unset) ────────── */
const depth = () => root.dataset.depth || "scout";
const paintDepth = () => $$(".depth button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.depth === depth())));
function setDepth(v) {
  if (v === depth()) return;
  const apply = () => { root.dataset.depth = v; store.set("depth", v); paintDepth(); };
  if (document.startViewTransition && !reduced) document.startViewTransition(apply); else apply();
}
$$(".depth button").forEach((b) => b.addEventListener("click", () => setDepth(b.dataset.depth)));
paintDepth();

/* ── tables ────────────────────────────────────────────────────────────────────────────────────────────────── */
function table(cols, rows, onRow, caption = "") {
  const head = cols.map((c) => `<th class="${c.num ? "num" : ""}" scope="col">${c.label}</th>`).join("");
  const body = rows.map((r, i) => `<tr class="${onRow ? "row-link" : ""}" data-i="${i}"${onRow ? ' tabindex="0"' : ""}>` +
    cols.map((c) => `<td class="${c.num ? "num" : ""}" data-label="${c.label}">${c.fmt ? c.fmt(r[c.key], r) : esc(r[c.key])}</td>`).join("") + "</tr>").join("");
  const html = `<div class="scroll"><table class="rt">${caption ? `<caption class="visually-hidden">${caption}</caption>` : ""}<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  return { html, bind(el) { if (!onRow) return; $$("tbody tr", el).forEach((tr) => {
    const go = () => onRow(rows[+tr.dataset.i], tr);
    tr.addEventListener("click", go); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); }); }); } };
}
const seatrun = (p) => p == null ? "" : `<span class="seatrun" aria-hidden="true">${Array.from({ length: 10 }, (_, i) => `<i class="${i < Math.round(p * 10) ? "on" : ""}"></i>`).join("")}</span>`;
// the outlook column appears only when the engine has earned it (its gate passed and it gave numbers)
const playerCols = (rows) => [
  { key: "name", label: "Player", fmt: (v, r) => `<div class="who">${esc(v)}</div><div class="sub">${esc(r.club || "")}</div>` },
  { key: "age", label: "Age", num: true, fmt: (v) => v == null ? "—" : v.toFixed(1) },
  { key: "position", label: "Position", fmt: (v, r) => esc(r.sub || r.sub_position || v || "—") },
  { key: "lvl", label: "Level 25/26", fmt: (v, r) => levelCell(r) },
  { key: "min_now", label: "Minutes 25/26", num: true, fmt: num },
  ...(rows.some((r) => r.p_reg3 != null) ? [{ key: "p_reg3", label: "Regular within 3 seasons", num: true,
    fmt: (v) => v == null ? '<span class="dim">no call</span>' : `${pct(v)}${seatrun(v)}` }] : []),
  { key: "mv", label: "Market value", num: true, fmt: eur },
];
// open a player: his name flies to the page header (view transition), his terrace unfolds there
function openPlayer(r, tr) {
  const who = tr && $(".who", tr);
  if (who) who.style.viewTransitionName = "pname";
  location.hash = `#/player/${r.tm_id}`;
}

/* ── A. Discover: the sentence and the bowl ────────────────────────────────────────────────────────────────── */
let BOWL = null;
async function loadBowl() {
  if (BOWL) return BOWL;
  const d = await api("/api/bowl");
  const ix = Object.fromEntries(d.cols.map((c, i) => [c, i]));
  BOWL = d.rows.map((r) => Object.fromEntries(d.cols.map((c) => [c, r[ix[c]]])));
  layoutBowl(BOWL);
  return BOWL;
}
// Promesse Light's bowl (the flat one). Four stands by position, clockwise from the left: goalkeepers, midfield, attack,
// defence; each stand's share of the bowl is its share of the players. Every stand has the same two tiers as the 3D ground:
// the lower one, Projections, near the pitch, and the upper one, Deep analysis, set back behind a gangway (GAP rows wide).
// In a tier the youngest sit in the front rows and, among equals, the best outlook. Seats sit on concentric ellipses, one seat
// per unit of arc, and every seat is one player.
const STANDS = [["Goalkeeper", "Goalkeepers"], ["Midfield", "Midfield"], ["Attack", "Attack"], ["Defender", "Defence"]];
const STAND_NAME = Object.fromEntries(STANDS);
const TIER_NAME = { projection: "Projections", deep: "Deep analysis" };
const tierOf = (p) => (p.stand === "deep" || p.stand === "projection" ? p.stand : p.tier === "solid" ? "deep" : "projection");   // the same rule as the 3D ground
const A0 = 58, B0 = 30, GAP = 4;       // the pitch's half-axes in seat units; the gangway between the tiers, in rows
let BOWL_GEO = null;
function layoutBowl(players) {
  const groups = STANDS.map(([k]) => players.filter((p) => p.position === k)
    .sort((a, b) => (b.born - a.born) || ((b.p_reg3 ?? -1) - (a.p_reg3 ?? -1))));
  const total = groups.reduce((s, g) => s + g.length, 0);
  // arc length on a middle ring, from the left end clockwise, to place the stands' boundaries by their share
  const ref = [A0 + 26, B0 + 26], N = 4000, cum = [0];
  for (let i = 1; i <= N; i++) {
    const th = Math.PI + (2 * Math.PI * i) / N;
    cum.push(cum[i - 1] + Math.hypot(ref[0] * Math.sin(th), ref[1] * Math.cos(th)) * (2 * Math.PI / N));
  }
  const C = cum[N], aisle = C * 0.012;
  const thetaAt = (s) => { s = ((s % C) + C) % C; let lo = 0, hi = N; while (lo < hi) { const m = (lo + hi) >> 1; if (cum[m] < s) lo = m + 1; else hi = m; } return Math.PI + (2 * Math.PI * lo) / N; };
  let s = -(groups[0].length / total) * C / 2;
  const sectors = groups.map((g) => { const len = (g.length / total) * C; let a = thetaAt(s + aisle / 2), b = thetaAt(s + len - aisle / 2);
    if (b < a) a -= 2 * Math.PI; s += len; return [a, b]; });
  // per stand, per tier: rows k0..k1 (k1 exclusive) and how many seats
  let rings = 0;
  const tiers = groups.map((g, gi) => {
    const [t0, t1] = sectors[gi], out = {};
    let k = 0;
    for (const id of ["projection", "deep"]) {
      const q = g.filter((p) => tierOf(p) === id), k0 = k, n = q.length;
      for (; q.length && k < 400; k++) {
        const a = A0 + k, b = B0 + k;
        let th = t0;
        while (th < t1 && q.length) { const p = q.shift(); p.ux = a * Math.cos(th); p.uy = b * Math.sin(th); p.uk = k; p.ut = id;
          th += 1 / Math.hypot(a * Math.sin(th), b * Math.cos(th)); }
      }
      out[id] = { k0, k1: k, n };
      if (id === "projection") k += GAP;
    }
    rings = Math.max(rings, k);
    return out;
  });
  BOWL_GEO = { rings, sectors, tiers, counts: groups.map((g) => g.length) };
}
const FILTER_DEFAULT = { pos: "", born: "2005", min: "", mv: "", nation: "", sort: "level" };   // Promesse looks at the young
function matches(p, f) {
  if (f.pos && p.position !== f.pos && p.sub !== f.pos) return false;
  if (f.born && p.born < +f.born) return false;
  if (f.min && p.min_now < +f.min) return false;
  if (f.mv && (p.mv || 0) > +f.mv) return false;
  if (f.nation && p.nation.toLowerCase() !== f.nation.toLowerCase()) return false;
  return true;
}
const SORTS = { level: (a, b) => (nowStep(b) - nowStep(a)) || (b.min_now - a.min_now) || (b.ym - a.ym),
  outlook: (a, b) => (b.p_reg3 ?? -1) - (a.p_reg3 ?? -1), minutes: (a, b) => b.min_now - a.min_now,
  value: (a, b) => (b.mv || 0) - (a.mv || 0), young: (a, b) => a.age - b.age };

async function discover(seatOf) {
  const players = await loadBowl();
  return () => {
    setNav("discover");
    const f = { ...FILTER_DEFAULT, ...(store.get("filters") || {}) };
    const nations = [...new Set(players.map((p) => p.nation).filter(Boolean))].sort();
    const opt = (v, l, cur) => `<option value="${v}"${String(cur) === String(v) ? " selected" : ""}>${l}</option>`;
    const POS = ["", "Goalkeeper", "Defender", "Midfield", "Attack", "Centre-Back", "Left-Back", "Right-Back", "Defensive Midfield",
      "Central Midfield", "Attacking Midfield", "Left Winger", "Right Winger", "Centre-Forward"];
    const posLabel = { "": "any position", Goalkeeper: "goalkeepers", Defender: "defenders", Midfield: "midfielders", Attack: "attackers" };
    main.innerHTML = `
    <div class="discover">
      <section aria-labelledby="dh">
        <h1 id="dh" class="display">Find Players</h1>
        <form class="sentence" id="f" autocomplete="off">Show me
          <select class="f" name="pos" aria-label="Position">${POS.map((v) => opt(v, posLabel[v] || v.toLowerCase(), f.pos)).join("")}</select>
          born in <select class="f" name="born" aria-label="Born in or after">${opt("", "any year", f.born)}${[2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010].map((y) => opt(y, y, f.born)).join("")}</select>
          or later, with at least <input class="f" name="min" inputmode="numeric" pattern="[0-9]*" placeholder="0" value="${esc(f.min)}" aria-label="Minimum first-division minutes in 25/26">
          first&#8209;division minutes in 25/26, valued at most <select class="f" name="mv" aria-label="Market value at most">${opt("", "anything", f.mv)}${[[5e5, "€500 k"], [1e6, "€1 m"], [2e6, "€2 m"], [5e6, "€5 m"], [1e7, "€10 m"], [2.5e7, "€25 m"]].map(([v, l]) => opt(v, l, f.mv)).join("")}</select>,
          from <input class="f wide" name="nation" list="nations" placeholder="anywhere" value="${esc(f.nation)}" aria-label="Nationality">,
          sorted by <select class="f" name="sort" aria-label="Sort by">${[["level", "level"], ["minutes", "minutes"], ["young", "youngest"], ["value", "market value"],
            ...(players.some((p) => p.p_reg3 != null) ? [["outlook", "outlook"]] : [])].map(([v, l]) => opt(v, l, f.sort)).join("")}</select>.
        </form>
        <datalist id="nations">${nations.map((n) => `<option value="${esc(n)}">`).join("")}</datalist>
        <div class="tally" aria-live="polite"><b id="tally">—</b><span>players match</span></div>
        <button class="link reset" id="reset" type="button">Clear the sentence</button>
      </section>
      <section aria-label="The bowl: every player a seat">
        <div class="bowl" id="bowl"><canvas id="bowl-base" role="img" aria-label="22,522 players as seats in a stadium bowl, four stands by position"></canvas><canvas id="bowl-top" aria-hidden="true"></canvas></div>
        <div class="bowl-key">${ramp(STEP_LABEL)}<span><i class="seatmark" style="background:var(--seat-key, var(--seat-bare))"></i>no minutes seen in 25/26</span><span>seat colour: the level he played at in 25/26 · <span class="k2d">front rows youngest</span><span class="k3d">a block per birth year, oldest left, youngest right, the best outlook in front</span></span></div>
        <p class="bowl-note"><b>Two stands.</b> The upper one, <b>Deep analysis</b>, holds the players we have analysed best: 1,800 or more minutes with match stats. They are our reference standard. The lower one, <b>Projections</b>, holds everyone else, projected from that standard; open a seat to see what data would make his projection more accurate. Until the deep-analysis group is fixed by hand, the evidence tier decides who sits where. The big end is Attack and the quiet low end Goalkeepers by design, not by head count.</p>
      </section>
    </div>
    <section class="block" aria-labelledby="rh">${sign("A", "The players", "", "rh")}<div class="results-head"><span class="dim" id="rmeta"></span></div><div id="res"></div>
      <button class="btn more" id="more" type="button" hidden>Show 100 more</button></section>`;
    const form = $("#f");
    let shown = 100, list = [];
    const read = () => Object.fromEntries(new FormData(form));
    const run = (animate) => {
      const cur = read(); store.set("filters", cur);
      list = players.filter((p) => matches(p, cur)).sort(SORTS[cur.sort] || SORTS.outlook);
      const ids = new Set(list.map((p) => p.tm_id));
      players.forEach((p) => { p.on = ids.has(p.tm_id); });
      $("#tally").textContent = list.length.toLocaleString("en");
      bowl.draw(animate);
      shown = 100; paintRows();
    };
    const paintRows = () => {
      const t = table(playerCols(list), list.slice(0, shown), openPlayer, "Players matching the sentence");
      $("#res").innerHTML = list.length ? t.html : `<div class="empty"><h2>No seat matches</h2><p>Loosen one part of the sentence: an earlier birth year, fewer minutes or a higher value.</p></div>`;
      t.bind($("#res"));
      $("#rmeta").textContent = list.length ? `Showing ${Math.min(shown, list.length).toLocaleString("en")} of ${list.length.toLocaleString("en")}` : "";
      $("#more").hidden = shown >= list.length;
    };
    $("#more").addEventListener("click", () => { shown += 100; paintRows(); });
    form.addEventListener("input", () => { clearTimeout(form._t); form._t = setTimeout(() => run(true), 120); });
    form.addEventListener("submit", (e) => e.preventDefault());
    $("#reset").addEventListener("click", () => { store.set("filters", FILTER_DEFAULT); route(); });
    // a part of The Ground opens what it names: a stand lights its position's players (the sentence), the screen opens the Scoreboard
    const bowl = bowlView(players, (p) => openPlayer(p), (t) => {
      const kind = t.show?.kind;
      if (kind === "stand") { form.elements.pos.value = t.show.position; form.dispatchEvent(new Event("input")); }
      else if (kind === "scoreboard") location.hash = "#/method";
    });
    run(false);
    // arriving from a player's ticket ("find his seat"): his seat lights crimson in the bowl
    const mine = seatOf && players.find((p) => String(p.tm_id) === String(seatOf));
    return () => { bowl.enter(); if (mine) bowl.mark(mine); };
  };
}

// a seat's card, the same in the flat bowl and the stadium
function seatTip(p) {
  const s = nowStep(p);
  return `<b>${esc(p.name)}</b>${esc(p.club)} · ${p.age.toFixed(1)} · ${esc(p.sub || p.position)}<br>25/26: ${s < 0 ? "no minutes seen" : s === 0 ? `${num(p.ym)} youth minutes` : `${num(p.min_now)} first-division minutes, ${STEP_LABEL[s]}`}${p.p_reg3 != null ? ` · regular within three seasons: ${pct(p.p_reg3)}` : ""}${tierLine(p)}`;
}
// which stand he sits in (gold/stands.py, the rule ): the full reading, or the projection and what data
// would move him up. The bowl carries `stand`, `fs` (full seasons: 900+ minutes with match stats, 2021/22-2025/26) and
// `why` (a short code); the player page carries the same as `stand` (stand, full_seasons, reason).
const WHY_LINE = {
  one: "one season of 900+ minutes with match stats so far; a second gives him the full reading",
  id: "his match record isn't yet tied to his Transfermarkt profile by an exact birth date; that link gives him the full reading",
  held: "two records claim the same player, so his identity is being checked first",
};
const REASON_CODE = { "fewer than two full seasons with stats": "one", "no identity link with an exact birth date": "id",
  "held back: identity conflict under review": "held" };
function standText(stand, fs, why) {
  if (stand === "deep") return `Full reading: ${fs} seasons of 900+ minutes with match stats since 2021/22, identity confirmed.`;
  return `Projection: ${WHY_LINE[why] || "no season of 900+ minutes with match stats yet; one would start a sharper reading"}.`;
}
function tierLine(p) { return `<br><span class="tier-line">${standText(p.stand, p.fs, p.why)}</span>`; }
function standLine(s) { return standText(s.stand, s.full_seasons, REASON_CODE[s.reason]); }
// the engine's test in one sentence, from /api/meta's live figures (proud and humble; passed from "just ahead")
function engineLine(t) {
  if (!t || t.engine == null) return "";
  const lead = { ahead: "Ahead of market value", edge: "Just ahead of market value", level: "Level with market value", behind: "Behind market value" }[t.verdict];
  return ` <b>${lead}:</b> on under-21s from 2021-22, a season it never learned from, it picks the right player in ${t.engine} of 100 pairs (one who became a regular, one who didn't); market value picks ${t.market}, a coin flip 50 (<a href="#/method">the Scoreboard</a> has the test).`;
}

// the bowl, drawn on canvas: 22,522 seats; matching seats in focus, the rest drop to faint concrete
function bowlView(players, onPick, onTarget) {
  const wrap = $("#bowl"), base = $("#bowl-base"), top = $("#bowl-top");
  let geo = null, hover = null, mix = 1, reveal = 1;
  const grid = new Map();
  const tok = (n) => getComputedStyle(root).getPropertyValue(n).trim();
  function size() {
    const r = wrap.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
    for (const c of [base, top]) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0); }
    const R = BOWL_GEO.rings + 6, room = r.width > 600 ? 200 : 40;     // room for the stands' painted names
    const sc = Math.min((r.width - room) / (2 * (A0 + R)), (r.height - 40) / (2 * (B0 + R)));
    geo = { w: r.width, h: r.height, cx: r.width / 2, cy: r.height / 2, sc };
    grid.clear();
    for (const p of players) if (p.ux != null) { const key = `${Math.round(p.ux)},${Math.round(p.uy)}`; (grid.get(key) || grid.set(key, []).get(key)).push(p); }
  }
  function pitch(ctx) {
    const { cx, cy, sc } = geo;
    const h = 2 * B0 * 0.66 * sc, w = Math.min(2 * A0 * 0.74 * sc, h * 1.55), x = cx - w / 2, y = cy - h / 2;
    ctx.fillStyle = tok("--field"); ctx.fillRect(x, y, w, h);          // a pitch painted on the concrete
    ctx.fillStyle = tok("--grass"); ctx.globalAlpha = 0.07;            // the mowing: stripes along the pitch
    for (let i = 0; i < 8; i += 2) ctx.fillRect(x + (w / 8) * i, y, w / 8, h);
    ctx.globalAlpha = 0.7;
    ctx.strokeStyle = tok("--field-line"); ctx.lineWidth = 1.2;
    ctx.strokeRect(x, y, w, h);
    ctx.beginPath(); ctx.moveTo(cx, y); ctx.lineTo(cx, y + h); ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, h * 0.13, 0, 2 * Math.PI); ctx.stroke();
    const bw = w * 0.16, bh = h * 0.58, gw = w * 0.055, gh = h * 0.27;
    ctx.strokeRect(x, cy - bh / 2, bw, bh); ctx.strokeRect(x + w - bw, cy - bh / 2, bw, bh);
    ctx.strokeRect(x, cy - gh / 2, gw, gh); ctx.strokeRect(x + w - gw, cy - gh / 2, gw, gh);       // the six-yard boxes
    ctx.fillStyle = tok("--field-line"); ctx.beginPath(); ctx.arc(cx, cy, 2, 0, 2 * Math.PI); ctx.fill();
    ctx.globalAlpha = 1;
    return { x, y, w, h };
  }
  // one tier of one stand as a ring sector: its concrete, between rows k0 and k1 and the stand's two ends
  function tierPath(ctx, [t0, t1], k0, k1) {
    const { cx, cy, sc } = geo, steps = Math.max(8, Math.ceil((t1 - t0) / 0.02)), at = (k, th) => [cx + (A0 + k) * sc * Math.cos(th), cy + (B0 + k) * sc * Math.sin(th)];
    ctx.beginPath();
    for (let i = 0; i <= steps; i++) { const [x, y] = at(k1 - 0.5, t0 + ((t1 - t0) * i) / steps); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
    for (let i = steps; i >= 0; i--) { const [x, y] = at(k0 - 0.5, t0 + ((t1 - t0) * i) / steps); ctx.lineTo(x, y); }
    ctx.closePath();
  }
  // the bowl; `reveal` (0 to 1) is how far the stands have filled, front rows first (the entrance, when motion is allowed)
  function draw(animate) {
    if (!geo) size();
    if (animate && motion()) { const o = { m: 0.35 }; gsap.to(o, { m: 1, duration: 0.28, ease: "power2.out", onUpdate: () => { mix = o.m; paint(); } }); }
    else { mix = 1; paint(); }
  }
  function paint() {
    const ctx = base.getContext("2d"), { w, h, cx, cy, sc } = geo;
    ctx.clearRect(0, 0, w, h);
    // the concrete of each tier: the lower (Projections) light, the upper (Deep analysis) in the stand's navy, as on the ground
    BOWL_GEO.sectors.forEach((sec, gi) => {
      for (const id of ["projection", "deep"]) {
        const t = BOWL_GEO.tiers[gi][id]; if (t.k1 <= t.k0) continue;
        tierPath(ctx, sec, t.k0, t.k1);
        ctx.fillStyle = id === "deep" ? tok("--roof") : tok("--terrace"); ctx.globalAlpha = id === "deep" ? 0.2 : 0.55; ctx.fill();
        ctx.globalAlpha = 0.5; ctx.strokeStyle = id === "deep" ? tok("--roof") : tok("--ink-3"); ctx.lineWidth = id === "deep" ? 1.6 : 1; ctx.stroke();
      }
    });
    ctx.globalAlpha = 1;
    pitch(ctx);
    const seat = Math.max(1.2, sc * 0.76), half = seat / 2, lim = reveal * (BOWL_GEO.rings + 1);
    const cols = [0, 1, 2, 3, 4].map((i) => tok(`--s${i}`)), bare = tok("--seat-bare");
    // batch by colour and focus: a dozen fill styles for 22,522 rectangles
    const buckets = new Map();
    for (const p of players) { if (p.ux == null || p.uk > lim) continue; const k = `${nowStep(p)}|${p.on ? 1 : 0}`; (buckets.get(k) || buckets.set(k, []).get(k)).push(p); }
    for (const [k, ps] of buckets) {
      const [st, on] = k.split("|").map(Number);
      ctx.fillStyle = st < 0 ? bare : cols[st];
      ctx.globalAlpha = on ? mix + 0.14 * (1 - mix) : 0.14;
      for (const p of ps) ctx.fillRect(cx + p.ux * sc - half, cy + p.uy * sc - half, seat, seat);
    }
    ctx.globalAlpha = 1;
    if (reveal < 1) return;
    // the tiers' names and head counts on the gangway between them; each stand's name and head count outside
    ctx.textBaseline = "middle";
    BOWL_GEO.sectors.forEach(([a, b], gi) => {
      const th = (a + b) / 2, T = BOWL_GEO.tiers[gi], kg = T.projection.k1 + (GAP - 1) / 2;
      if (!T.deep.n || sc < 2.3) return;
      const fs = Math.min(12, Math.max(8, Math.round(sc * GAP * 0.8))), r = [(A0 + kg) * sc, (B0 + kg) * sc];
      const x = cx + r[0] * Math.cos(th), y = cy + r[1] * Math.sin(th);
      let ang = Math.atan2(r[1] * Math.cos(th), -r[0] * Math.sin(th)); if (Math.cos(ang) < 0) ang += Math.PI;      // along the gangway, never upside down
      const arc = (b - a) * Math.hypot(r[0] * Math.sin(th), r[1] * Math.cos(th));
      ctx.save(); ctx.translate(x, y); ctx.rotate(ang);
      ctx.font = `700 ${fs}px "Barlow Condensed"`; ctx.textAlign = "center"; ctx.fillStyle = tok("--ink-2"); ctx.letterSpacing = "1px";
      const full = `${TIER_NAME.projection.toUpperCase()} ${T.projection.n.toLocaleString("en")}  ·  ${TIER_NAME.deep.toUpperCase()} ${T.deep.n.toLocaleString("en")}`;
      const short = `${T.projection.n.toLocaleString("en")}  ·  DEEP ${T.deep.n.toLocaleString("en")}`;
      const text = ctx.measureText(full).width < arc * 0.9 ? full : ctx.measureText(short).width < arc * 0.9 ? short : "";
      if (text) ctx.fillText(text, 0, 0);
      ctx.restore();
    });
    ctx.letterSpacing = "0px"; ctx.fillStyle = tok("--ink-2"); ctx.font = `700 ${Math.max(11, Math.round(sc * 4.2))}px "Barlow Condensed"`;
    BOWL_GEO.sectors.forEach(([a, b], i) => {
      const th = (a + b) / 2, R = BOWL_GEO.rings + 4.5;
      const x = cx + (A0 + R) * sc * Math.cos(th), y = cy + (B0 + R) * sc * Math.sin(th);
      const text = `${STANDS[i][1].toUpperCase()} · ${BOWL_GEO.counts[i].toLocaleString("en")}`, tw = ctx.measureText(text).width;
      const align = Math.cos(th) < -0.5 ? "right" : Math.cos(th) > 0.5 ? "left" : "center";
      const lo = align === "right" ? tw + 4 : align === "center" ? tw / 2 + 4 : 4, hi = align === "left" ? w - tw - 4 : align === "center" ? w - tw / 2 - 4 : w - 4;
      ctx.textAlign = align; ctx.fillText(text, Math.min(hi, Math.max(lo, x)), Math.min(h - 8, Math.max(10, y)));
    });
  }
  function ring(p, colour) {
    const ctx = top.getContext("2d"); ctx.clearRect(0, 0, geo.w, geo.h);
    if (!p) return;
    const { cx, cy, sc } = geo, s = Math.max(5, sc * 2.2), x = cx + p.ux * sc, y = cy + p.uy * sc;
    ctx.strokeStyle = colour || tok("--ink"); ctx.lineWidth = 2; ctx.strokeRect(x - s / 2, y - s / 2, s, s);
    if (colour) { ctx.fillStyle = colour; ctx.fillRect(x - s / 4, y - s / 4, s / 2, s / 2); }
  }
  function nearest(ev) {
    const r = base.getBoundingClientRect(), ux = (ev.clientX - r.left - geo.cx) / geo.sc, uy = (ev.clientY - r.top - geo.cy) / geo.sc;
    let best = null, bd = 1.1;
    for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) for (const p of grid.get(`${Math.round(ux) + i},${Math.round(uy) + j}`) || []) {
      const d = Math.hypot(p.ux - ux, p.uy - uy); if (p.on && d < bd) { bd = d; best = p; } }
    return best;
  }
  base.addEventListener("pointermove", (ev) => {
    const p = nearest(ev);
    if (p !== hover) { hover = p; ring(p); base.classList.toggle("hit", !!p); }
    if (p) showTip(seatTip(p), ev.clientX, ev.clientY);
    else hideTip();
  });
  base.addEventListener("pointerleave", () => { hover = null; ring(null); hideTip(); });
  base.addEventListener("click", (ev) => {
    const p = nearest(ev); if (!p) return;
    hideTip(); ring(p, tok("--crimson"));                 // find your seat: it lights crimson, then the page opens
    setTimeout(() => onPick(p), motion() ? 160 : 0);
  });
  const onResize = () => { if (!document.body.contains(base)) return removeEventListener("resize", onResize); geo = null; size(); paint(); };
  addEventListener("resize", onResize);
  addEventListener("themechange", () => { if (document.body.contains(base)) paint(); });
  const flat = { draw, mark(p) { ring(p, tok("--crimson")); }, enter() {
    if (!motion()) return;
    const o = { r: 0 };
    reveal = 0; paint();
    gsap.to(o, { r: 1, duration: 1.4, ease: "power2.out", onUpdate: () => { reveal = o.r; paint(); }, onComplete: () => { reveal = 1; paint(); } });
  } };
  // Promesse: the stadium in 3D (stadium3d.js, The Ground's model) when the visitor's choice is Promesse and the browser has WebGL2.
  // It loads over the flat bowl ("Loading the Ground" meanwhile); if the module or the model fails, Light takes its place.
  let stadium = null, entered = false, marked = null;
  const want3d = deskMode() === "promesse" && !!document.createElement("canvas").getContext("webgl2");
  const wide = () => { if (innerWidth > 900) { wrap.classList.add("wide"); wrap.closest(".discover")?.classList.add("wide"); } };   // Light, too, takes the first viewport on a desktop
  let use3d = want3d;                                    // false once Light has taken over
  const toLight = (why) => {
    console.warn("stadium: opening Promesse Light", why);
    use3d = false; stadium?.dispose?.(); stadium = null;
    wrap.querySelectorAll(".stadium, .ground-parts, .ground-loading").forEach((n) => n.remove());
    wrap.classList.remove("is3d"); wrap.closest(".discover")?.classList.remove("is3d");
    wrap.dataset.view = "light"; wide();
    geo = null; size(); paint(); if (entered) flat.enter(); if (marked) flat.mark(marked);
  };
  if (want3d) {
    wrap.classList.add("is3d"); wrap.closest(".discover")?.classList.add("is3d"); wrap.dataset.view = "promesse";
    wrap.insertAdjacentHTML("beforeend", '<div class="ground-loading" role="status"><b>Loading the Ground</b><span>the stadium model, about 14 MB</span><i></i></div>');
    import("/static/stadium3d.js").then(({ createStadium }) => {
      if (!document.body.contains(wrap)) return;
      stadium = createStadium(wrap, players, { tok, stepOf: nowStep, isNight: () => kick() === "night", reduced,
        onHover: (p, x, y) => (p ? showTip(seatTip(p), x, y) : hideTip()), onPick: (p) => onPick(p), onTarget, onFail: toLight });
      if (entered) stadium.enter();
      if (marked) stadium.mark(marked);
    }).catch((e) => { if (document.body.contains(wrap)) toLight(e); });
  } else { wrap.dataset.view = "light"; wide(); }
  return {
    draw(a) { if (!use3d) flat.draw(a); stadium?.draw(a); },
    mark(p) { marked = p; if (use3d) stadium?.mark(p); else flat.mark(p); },
    enter() { entered = true; if (use3d) stadium?.enter(); else flat.enter(); },
  };
}

/* ── B. Boards: stand signage ──────────────────────────────────────────────────────────────────────────────── */
const BOARD_NOTE = { above_age: "Playing first-division football above his age", debut_watch: "Ready in youth football, not yet in the first team",
  under_radar: "A strong outlook the market hasn't priced" };
async function boards(name) {
  if (!name) {
    const list = await api("/api/boards");
    return () => {
      setNav("boards");
      main.innerHTML = `<div class="page-head"><div><h1>Promesse's Picks</h1><p class="lead">Three lists the engine builds itself, rebuilt with the data every week. Each shows only once its test passes; your own lists are the Shortlists.</p></div></div>
        <a class="clubsign" href="#/club/barcelona"><span class="tag">Club board</span><h2>FC Barcelona</h2><p>The system first (Flick's game model against Xavi's, his shape, the roles he asks for), then La Masia's pathway against Europe's academies.</p>${icon("right")}</a>
        <div class="boardsigns">${list.map((b) => { const [title, ...rest] = b.label.split(":");
          const idle = !b.n && b.id === "under_radar";       // it reads the outlook, which waits for its gate
          return `<a class="boardsign${idle ? " idle" : ""}" href="#/board/${b.id}"><span class="count">${idle ? "waits for its test to pass" : b.n}</span><div><h2>${esc(title)}</h2><p>${esc(rest.join(":").trim())}</p></div>${icon("right")}</a>`; }).join("")}</div>`;
      return () => motion() && gsap.from(".boardsign", { y: 14, opacity: 0, duration: 0.45, ease: "expo.out", stagger: 0.06 });
    };
  }
  const b = await api(`/api/board/${name}`);
  return () => {
    setNav("boards");
    const [title, ...rest] = b.label.split(":");
    const t = table(playerCols(b.rows), b.rows, openPlayer, title);
    main.innerHTML = `<a class="back" href="#/boards">${icon("left")}Boards</a>
      <div class="boardhead"><div><h1>${esc(title)}</h1><p>${esc(rest.join(":").trim())}</p></div><span class="count">${b.rows.length}</span></div>
      ${b.rows.length ? t.html : `<div class="empty"><h2>Nobody on this board</h2><p>${esc(BOARD_NOTE[name] || "")}: no player meets it in this build.</p></div>`}`;
    t.bind(main);
  };
}

/* ── the player page ───────────────────────────────────────────────────────────────────────────────────────── */
function terraceSVG(seats, dob, width, compact = false) {
  const bySeason = new Map();
  seats.forEach((s, i) => { (bySeason.get(s.season) || bySeason.set(s.season, []).get(s.season)).push({ ...s, i }); });
  const seasons = [...bySeason.keys()].sort((a, b) => a - b);          // oldest first in the DOM: the stand fills upward
  const left = compact ? 0 : 66, right = compact || width < 640 ? 0 : 158, inner = width - left - right;
  const most = Math.max(36, ...[...bySeason.values()].map((r) => r.length));
  const p = Math.max(3.4, Math.min(15, inner / most)), sw = p * 0.78, sh = Math.min(p * 1.1, 16), rowH = compact ? sh + 6 : Math.max(sh + 22, 42);
  const H = seasons.length * rowH + 4;
  const rows = seasons.map((s, ri) => {
    const y = H - (ri + 1) * rowH;                                    // latest season on top
    const list = bySeason.get(s), base = y + rowH - (compact ? 3 : 14);
    const mins = list.reduce((t, x) => t + (x.minutes || 0), 0);
    const seatsSvg = list.map((x, j) => {
      const sx = left + j * p, sy = base - sh, f = Math.min(1, (x.minutes || 0) / 90), r = sw * 0.3;
      const shape = `M${sx},${base}V${sy + r}Q${sx},${sy} ${sx + r},${sy}H${sx + sw - r}Q${sx + sw},${sy} ${sx + sw},${sy + r}V${base}Z`;
      const fill = f >= 0.85 ? `<path class="k${step(x.level, x.kind)}" d="${shape}"/>`
        : `<rect class="k${step(x.level, x.kind)}" x="${sx}" y="${base - sh * f}" width="${sw}" height="${sh * f}"/>`;
      return `<g class="seat" data-i="${x.i}"><path class="back" d="${shape}"/>${fill}</g>`;
    }).join("");
    const a = Math.floor(yearsAt(dob, s));
    return `<g class="row">${compact ? "" : `<text class="age" x="0" y="${base - 2}">${a}</text><text class="season" x="0" y="${base + 11}">${season(s)}</text>`}
      ${seatsSvg}<line class="riser" x1="${left}" x2="${left + inner}" y1="${base + 2.5}" y2="${base + 2.5}"/>
      ${right ? `<text class="sum" x="${width}" y="${base - 2}" text-anchor="end"><tspan class="hi">${num(mins)}</tspan> min · ${list.length} ${list.length === 1 ? "match" : "matches"}</text>` : ""}</g>`;
  }).join("");
  return `<svg class="terrace" viewBox="0 0 ${width} ${H}" width="${width}" height="${H}" role="img" aria-label="His terrace: ${seats.length} matches over ${seasons.length} seasons, one row per season by age">${rows}</svg>`;
}
function bindTerrace(el, seats) {
  el.addEventListener("pointerover", (ev) => {
    const g = ev.target.closest(".seat"); if (!g) return;
    const s = seats[+g.dataset.i];
    showTip(`<b>${day(s.date)}</b>${KIND[s.kind] || s.kind} · ${num(s.minutes)} min<br>${s.kind === "youth" ? "youth football" : s.level == null ? "level unknown" : `match level ${s.level > 0 ? "+" : ""}${s.level} Elo vs the big five`}`, ev.clientX, ev.clientY);
  });
  el.addEventListener("pointermove", (ev) => { if (tip.classList.contains("on") && ev.target.closest(".seat")) showTip(tip.innerHTML, ev.clientX, ev.clientY); });
  el.addEventListener("pointerout", (ev) => { if (!ev.relatedTarget || !ev.relatedTarget.closest?.(".seat")) hideTip(); });
}
function bandSVG(o) {
  const W = 520, H = 70, pad = 6, mx = Math.max(9000, Math.ceil((o.qmin3_p90 * 1.06) / 1000) * 1000);
  const X = (v) => pad + (v / mx) * (W - 2 * pad);
  const ticks = []; for (let v = 0; v <= mx; v += 500) ticks.push(`<rect class="tick" x="${X(v) - 2.5}" y="${v % 1000 ? 31 : 28}" width="5" height="${v % 1000 ? 7 : 10}" rx="1.5"/>`);
  const labels = []; for (let v = 0; v <= mx; v += mx > 16000 ? 4000 : 2000) labels.push(`<text x="${X(v)}" y="64" text-anchor="middle">${num(v)}</text>`);
  return `<svg class="scale" viewBox="0 0 ${W} ${H}" role="img" aria-label="80 % band: ${num(o.qmin3_p10)} to ${num(o.qmin3_p90)} quality minutes, ${num(o.qmin3_p50)} most likely">
    ${ticks.join("")}<rect class="band" x="${X(o.qmin3_p10)}" y="22" width="${Math.max(2, X(o.qmin3_p90) - X(o.qmin3_p10))}" height="22" rx="2" opacity=".9"/>
    <rect class="mid" x="${X(o.qmin3_p50) - 1.5}" y="14" width="3" height="38"/>
    <text class="lab" x="${X(o.qmin3_p50)}" y="10" text-anchor="middle">${num(o.qmin3_p50)}</text>${labels.join("")}</svg>`;
}
function pitchSVG(spots) {
  const W = 340, H = 220;
  // MatchData's lineup grid: y runs from his own goal (0) to the opponents' (1), x across the pitch from his right (0).
  // Drawn attacking left to right, so his right flank sits at the bottom. One mark per spot, sized by how often.
  const at = new Map();
  spots.forEach((s) => { const k = `${s.x.toFixed(2)},${s.y.toFixed(2)}`; at.set(k, (at.get(k) || 0) + 1); });
  const dots = [...at].map(([k, n]) => { const [x, y] = k.split(",").map(Number);
    return `<circle class="spot" cx="${(6 + y * (W - 12)).toFixed(1)}" cy="${(6 + (1 - x) * (H - 12)).toFixed(1)}" r="${(3.5 + Math.sqrt(n) * 1.4).toFixed(1)}"><title>${n} ${n === 1 ? "lineup" : "lineups"}</title></circle>`; }).join("");
  return `<svg class="pitch" viewBox="0 0 ${W} ${H}" role="img" aria-label="Where he lined up in ${spots.length} matches"><rect class="ground" width="${W}" height="${H}" rx="3"/>
    <g class="chalk"><rect x="6" y="6" width="${W - 12}" height="${H - 12}"/><line x1="${W / 2}" x2="${W / 2}" y1="6" y2="${H - 6}"/><circle cx="${W / 2}" cy="${H / 2}" r="26"/>
    <rect x="6" y="${H / 2 - 52}" width="46" height="104"/><rect x="${W - 52}" y="${H / 2 - 52}" width="46" height="104"/>
    <rect x="6" y="${H / 2 - 22}" width="16" height="44"/><rect x="${W - 22}" y="${H / 2 - 22}" width="16" height="44"/></g>${dots}</svg>`;
}

async function playerPage(id) {
  const [p, metaDoc] = await Promise.all([api(`/api/player/${id}`), META || api("/api/meta").then((m) => (META = m))]);
  return () => {
    setNav("player");
    const h = p.head, o = p.outlook, r = p.rarity, as = metaDoc.as_of || {};
    const recent = (store.get("recent") || []).filter((x) => x.tm_id !== h.tm_id);
    store.set("recent", [{ tm_id: h.tm_id, name: h.name, club: h.club }, ...recent].slice(0, 8));
    // where he stands now: a regular last season? (half his club's league minutes, as the targets define it)
    const last = p.career.filter((c) => c.season === SEASON_NOW).sort((a, b) => (b.share || 0) - (a.share || 0))[0];
    const regular = last && last.share >= 0.5;
    const moved = h.club_src === "MatchData" && h.club_tm && !sameClub(h.club, h.club_tm);
    const clubNote = h.club_src === "MatchData" ? `MatchData, last match ${day(h.club_date)}` : `Transfermarkt, ${day(h.club_date)}`;
    const ticket = [
      ["Age", age(h.age), `born ${day(h.dob)}`], ["Position", h.sub_position || h.position || "—", ""], ["Foot", h.foot || "—", ""],
      ["Height", h.height ? `${(h.height / 100).toFixed(2)} m` : "—", ""], ["Nation", h.nation || "—", ""],
      ["Club", h.club || "—", moved ? `moved from ${h.club_tm} · ${clubNote}` : clubNote],
      ["Contract", moved ? "—" : h.contract ? new Date(h.contract).getFullYear() : "—", moved ? "new contract not in Transfermarkt yet" : "Transfermarkt"],
      ["Minutes 25/26", num(h.min_now), "first division, 31 leagues"], ["Matches tracked", num(p.terrace.length), "senior since 12/13, youth since 21/22"],
      ["Seat", p.seat ? `${STAND_NAME[p.seat.stand] || p.seat.stand} ${num(p.seat.seat)}` : "—", p.seat ? `row ${p.seat.row}` : ""],
    ].map(([k, v, s]) => `<div><span>${k}</span><b title="${esc(v)}">${esc(v)}</b>${s ? `<small title="${esc(s)}">${esc(s)}</small>` : ""}${k === "Seat" && p.seat ? `<small><a class="link" href="#/discover?seat=${h.tm_id}">find it in the bowl</a></small>` : ""}</div>`).join("");
    // the call: what Promesse says, in the one crimson
    const rarityLine = r ? `By the end of 25/26, a season he began at ${r.age}: ${num(r.q)} quality minutes, ${r.rank === 1 ? "the most" : `${ordinal(r.rank)}`} of ${num(r.n)} players with senior minutes by that age since 2012/13${r.rank === 1 && r.second_name ? `. Next: ${esc(r.second_name)}, ${num(r.second_q)}` : ""}.` : "";
    const rarityFig = r ? (r.rank === 1 ? "1st" : r.rank <= 3 ? ordinal(r.rank) : `top ${Math.max(1, Math.ceil((r.rank / r.n) * 100))} %`) : null;
    let call;
    if (regular && r) {
      call = `<span class="status">${icon("check")}Already a regular</span>
        <div class="call-figure" data-fig="${r.rank <= 3 ? "rank" : "top"}" data-to="${r.rank <= 3 ? r.rank : Math.max(1, Math.ceil((r.rank / r.n) * 100))}" data-from="${r.rank <= 3 ? r.n : 100}">${rarityFig}</div>
        <p class="call-text">${rarityLine}</p>
        <p class="call-meta">${pct(last.share)} of ${esc(last.club)}'s league minutes in 25/26, at ${STEP_LABEL[step(last.level, "league")]}. Whether he becomes a regular is settled; what's open is how high, and that model hasn't passed its test yet.</p>`;
    } else if (o && o.p_reg3 != null) {
      call = `<div class="call-figure" data-fig="pct" data-to="${Math.round(o.p_reg3 * 100)}" data-from="0">${Math.round(o.p_reg3 * 100)}<small>%</small></div>
        <p class="call-text">chance he becomes a regular in one of the 31 leagues within three seasons</p>
        <p class="call-meta">From the start of the 2026/27 season. The engine, ProEngine, reads what happened only (minutes, match level, age, position, per-90 match stats) and was tested on seasons it never saw.${engineLine(metaDoc.engine_test)}${rarityLine ? " " + rarityLine : ""}</p>`;
    } else {
      // no outlook: say why. Under 21 with no number means the engine hasn't earned its gate yet.
      const gated = h.age < 22 && metaDoc.models?.outlook?.gates?.phase4 === false;
      const why = gated ? "No outlook yet: there isn't enough evidence on him for the engine to say anything honest."
        : "No outlook: he was 21 or older at the start of the 2026/27 season.";
      call = r ? `<div class="call-figure" data-fig="${r.rank <= 3 ? "rank" : "top"}" data-to="${r.rank <= 3 ? r.rank : Math.max(1, Math.ceil((r.rank / r.n) * 100))}" data-from="${r.rank <= 3 ? r.n : 100}">${rarityFig}</div><p class="call-text">${rarityLine}</p><p class="call-meta">${why}</p>`
        : `<p class="call-text">${gated ? why : "No call yet. He was 21 or older at the start of the 2026/27 season, or there isn't enough evidence to say anything honest."}</p>`;
    }
    const band = o && o.qmin3_p50 != null ? `<div class="call-sub"><h3>Next three seasons</h3>${bandSVG(o)}
      <p class="call-meta">Quality minutes: ${num(o.qmin3_p10)} to ${num(o.qmin3_p90)} (80 % band), ${num(o.qmin3_p50)} most likely.${metaDoc.projection_held?.low ? ` Bands like this held ${metaDoc.projection_held.low} to ${metaDoc.projection_held.high} % of real outcomes on seasons that have played out.` : ""}</p>
      <details class="how"><summary>How is this computed?</summary><p>Quality minutes are minutes weighted by the level of each match against the big five's average that season. The band comes from quantile models with a conformal layer calibrated on years they never trained on, so "80 %" means 80 %.</p></details></div>` : "";
    const seasonsCols = [
      { key: "season", label: "Season", fmt: season },
      { key: "club", label: "Club", fmt: (v, c) => `${esc(v)}<div class="sub">${esc(leagueName(c.league) || "cups and Europe")}</div>` },
      { key: "level", label: "Club level", num: true, fmt: (v) => v == null ? "—" : `<i class="seatmark k${step(v, "league")}" style="vertical-align:-1px;margin-right:6px"></i>${v > 0 ? "+" : ""}${v}` },
      { key: "minutes", label: "Minutes", num: true, fmt: num },
      { key: "share", label: "Share", num: true, fmt: pct },
      { key: "qmin", label: "Quality min", num: true, fmt: num },
    ];
    const matchCols = [
      { key: "date", label: "Date", fmt: (v) => `<span class="num">${day(v)}</span>` }, { key: "league", label: "Competition" },
      { key: "home_team", label: "Match", fmt: (v, m) => `${esc(v)} – ${esc(m.away_team)}` },
      { key: "minutes", label: "Min", num: true, fmt: num }, { key: "goals", label: "G", num: true, fmt: (v) => v || "" },
      { key: "assists", label: "A", num: true, fmt: (v) => v || "" },
      { key: "rating", label: "matchdata rating", num: true, fmt: (v) => v == null ? "—" : v.toFixed(1) },
    ];
    const ts = table(seasonsCols, [...p.career].reverse(), null, "Season by season"), tm = table(matchCols, p.matches.slice(0, 15), null, "Match log");
    const staleTM = as["Transfermarkt appearances"] && (new Date() - new Date(as["Transfermarkt appearances"])) / 864e5 > 45;
    const prov = p.provenance;
    main.innerHTML = `
    <article class="player">
      <section class="id" aria-label="Who he is">
        <h1 class="pname${h.name.length > 18 ? " long" : ""}">${esc(h.name)}</h1>
        <div class="ticket-wrap"><div class="ticket">${ticket}</div></div>
        <div class="actions">
          <button class="btn solid" id="keep-open" type="button" aria-expanded="false" aria-controls="keep">${icon("plus")}Add to a list</button>
          <a class="btn" href="#/compare?ids=${h.tm_id}">${icon("compare")}Compare</a>
        </div>
        <p class="stand-line" data-stand="${esc(p.stand.stand)}">${standLine(p.stand)}</p>
        <form class="keep" id="keep"><label class="field">List<input name="list" list="lists-dl" required value="${esc(store.get("lastList") || "Shortlist")}"></label>
          <label class="field">Note<input name="note" placeholder="what you saw"></label><button class="btn solid" type="submit">${icon("ticket")}Keep him</button>
          <datalist id="lists-dl"></datalist></form>
      </section>
      <section class="call" aria-label="Promesse's call">${call}${band}</section>
      <section class="block terrace-block" aria-labelledby="t-h">${sign("A", "His terrace", "a row per season, by his age · a seat per match, filled by minutes", "t-h")}
        <div id="terrace">${p.terrace.length ? "" : '<p class="none">No matches recorded yet in the 31 leagues or the youth competitions MatchData covers.</p>'}</div>
        <div class="ramp">${ramp(STEP_LABEL.map((l, i) => i ? `senior, ${l}` : l))}<span><i class="seatmark half"></i>half full: 45 minutes</span></div></section>
      <section class="block seasons" aria-labelledby="s-h">${sign("B", "Season by season", "31 first divisions, cups and Europe", "s-h")}${p.career.length ? ts.html : '<p class="none">No first-division seasons in the 31 leagues.</p>'}</section>
      <section class="block where" aria-labelledby="w-h">${sign("C", "Where he plays", "", "w-h")}${p.spots.length ? pitchSVG(p.spots) + `<p class="caption">${p.spots.length} lineups, MatchData positions, attacking left to right.</p>` : '<p class="none">No lineup positions recorded (MatchData, 2021 on).</p>'}</section>
      ${p.why && o && o.p_reg3 != null && !regular ? `<section class="block whyb" aria-labelledby="y-h">${sign("", "What the call is made of", "from a player at every input's average, each group of inputs in turn · points of chance", "y-h")}${whyCall(p.why)}
        <p class="note">The engine written out term by term: a logistic regression on standardised inputs, so these pushes add up exactly to the maintainer's choice. Expert depth lists each input inside a group.</p></section>
      <section class="block simb" aria-labelledby="b-h">${sign("", "With a club's data", "a simulation: move what only the club measures and watch the call", "b-h")}${simPanel(p.why)}</section>` : ""}
      <section class="block how" aria-labelledby="h-h">${sign("D", "How he plays", "his role, his skills beyond the system, the attributes that repeat", "h-h")}${howPlays(p.style)}</section>
      <section class="block raters" aria-labelledby="r-h">${sign("E", "What others think", "benchmarks, never inputs", "r-h")}
        <div class="raters-grid">
          <div><span>EA Sports FC</span><b>${h.ea_overall ?? "—"}${h.ea_potential ? `<small style="font-size:.5em;color:var(--ink-3)"> / ${Math.round(h.ea_potential)}</small>` : ""}</b><small>${h.ea_overall ? `overall / potential, ${day(h.ea_date)}` : "not rated"}</small></div>
          <div><span>Market value</span><b>${eur(h.mv)}</b><small>${h.mv ? `Transfermarkt, ${day(h.mv_date)}` : "no value set"}</small></div>
          <div><span>MatchData rating</span><b>${h.fm_rating ?? "—"}</b><small>${h.fm_rating ? `average of ${h.fm_rating_n} senior matches, last 365 days` : "no rated senior match"}</small></div>
        </div>
        <p class="note">Promesse's engines never read these. They read what happened: minutes, the level of each match, age, position. These opinions are scored against the engines on seasons neither saw, so the desk can say where the industry and Promesse agree, and who read the player better.</p></section>
      <section class="block matches" aria-labelledby="m-h">${sign("F", "Match log", `MatchData, the last ${Math.min(80, p.matches.length)}`, "m-h")}<div id="mlog">${p.matches.length ? tm.html : '<p class="none">No MatchData matches linked to him.</p>'}</div>
        ${p.matches.length > 15 ? `<button class="btn more" id="mlog-all" type="button">Show all ${p.matches.length}</button>` : ""}</section>
      <section class="block sources" aria-labelledby="p-h">${sign("G", "Where every number comes from", `${num(h.n_sources)} sources linked to him · built ${day(prov.built)}`, "p-h")}
        <dl class="ledger">
          ${Object.entries(as).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${typeof v === "number" ? `${num(v)} players` : `up to ${day(v)}`}${k === "Transfermarkt appearances" && staleTM ? ' <span class="stale">· before the summer window: clubs come from MatchData where it is newer</span>' : ""}</dd>`).join("")}
          ${Object.entries(prov.sources).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}
          ${Object.entries(prov.models).filter(([, v]) => typeof v === "string").map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}
        </dl></section>
    </article>`;
    // the terrace is drawn to the width it has
    const tEl = $("#terrace");
    const drawTerrace = () => { if (p.terrace.length) { tEl.innerHTML = terraceSVG(p.terrace, h.dob, Math.max(300, tEl.clientWidth)); } };
    drawTerrace(); bindTerrace(tEl, p.terrace);
    const onResize = () => { if (!document.body.contains(tEl)) return removeEventListener("resize", onResize); clearTimeout(tEl._r); tEl._r = setTimeout(drawTerrace, 120); };
    addEventListener("resize", onResize);
    $("#mlog-all")?.addEventListener("click", (e) => { $("#mlog").innerHTML = table(matchCols, p.matches, null, "Match log").html; e.currentTarget.remove(); });
    // keep him: a list and a note, inline
    const keep = $("#keep"), opener = $("#keep-open");
    opener.addEventListener("click", async () => {
      const open = keep.classList.toggle("open"); opener.setAttribute("aria-expanded", String(open));
      if (open) { $("input[name=note]", keep).focus(); api("/api/lists").then((d) => { $("#lists-dl").innerHTML = Object.keys(d).map((n) => `<option value="${esc(n)}">`).join(""); }).catch(() => {}); }
    });
    keep.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = Object.fromEntries(new FormData(keep));
      try {
        await api("/api/lists", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ list: fd.list, tm_id: h.tm_id, note: fd.note || "" }) });
        store.set("lastList", fd.list); keep.classList.remove("open"); opener.setAttribute("aria-expanded", "false");
        opener.innerHTML = `${icon("check")}In ${esc(fd.list)}`; toast(`${h.name} is on ${fd.list}.`);
      } catch (err) { toast(`Couldn't save to the list (${err.message}). Is the desk's server running?`); }
    });
    return () => { wireSim(p.why); enterPlayer(); };
  };
}
// what the engine's call is made of (models/explain.py): from the average player's chance, each group of inputs pushes
// it up or down (log-odds, added in turn); Expert depth lists every input with its value. The model term by term.
const sig = (x) => 1 / (1 + Math.exp(-x));
function whyCall(w) {
  if (!w) return "";
  let run = w.intercept;
  const steps = w.groups.map((g) => { const from = sig(run); run += g.logit; return { ...g, from, to: sig(run) }; });
  const X = (p) => `${(p * 100).toFixed(1)}%`;
  const rows = steps.map((s) => {
    const lo = Math.min(s.from, s.to), hi = Math.max(s.from, s.to);
    const ins = w.inputs.filter((i) => i.group === s.group && Math.abs(i.logit) >= 0.01).slice(0, 6)
      .map((i) => `${esc(i.label)}${i.value == null ? " (not known)" : ""} ${i.logit > 0 ? "+" : "−"}${Math.abs(i.logit).toFixed(2)}`).join(" · ");
    return `<div class="wr"><span class="wl">${esc(s.group)}</span><span class="wt"><i class="${s.logit >= 0 ? "up" : "down"}" style="left:${X(lo)};width:${X(hi - lo)}"></i></span>
      <b>${s.logit >= 0 ? "+" : "−"}${Math.abs(s.to - s.from) < 0.001 ? "0" : (Math.abs(s.to - s.from) * 100).toFixed(1)}</b>
      <small class="d-expert">${ins}</small></div>`;
  }).join("");
  return `<div class="why"><div class="wr base"><span class="wl">At every input's average, nothing missing</span><span class="wt"><i class="mark" style="left:${X(sig(w.intercept))}"></i></span><b>${(sig(w.intercept) * 100).toFixed(0)} %</b></div>
    ${rows}<div class="wr total"><span class="wl">His call</span><span class="wt"><i class="mark" style="left:${X(sig(run))}"></i></span><b>${(sig(run) * 100).toFixed(0)} %</b></div></div>`;
}

// version B, with a club's data (a simulation): the inputs a club knows better use the engine's own coefficients
// (the player's current term swapped for the new one); the club-only measures add ln(odds ratio) per standard deviation
// against his age group, from the studies in models/club_variables.json, every one editable. All sliders at the
// average: the public call, exactly.
const SD_LABEL = { "-2": "well below", "-1": "below", "0": "his age group's average", "1": "above", "2": "well above" };
function simPanel(w) {
  if (!w?.club) return "";
  const c = w.club;
  const eng = c.engine_inputs.map((e, i) => `<div class="sv"><label for="se${i}">${esc(e.label)}${e.value == null ? ` <em>not known in public data</em>` : ""}</label>
    <input type="range" id="se${i}" data-eng="${i}" min="${e.min}" max="${e.max}" step="${e.step}" value="${e.value ?? e.median}">
    <output></output><small>${esc(e.why)}</small></div>`).join("");
  const club = c.club_measures.map((m, i) => `<div class="sv"><label for="sc${i}">${esc(m.label)}</label>
    <input type="range" id="sc${i}" data-club="${i}" min="-2" max="2" step="0.5" value="0">
    <output>${SD_LABEL["0"]}</output>
    <span class="or">odds ratio per SD <input type="number" step="0.05" min="0.2" max="5" data-or="${i}" value="${m.or_per_sd}"></span>
    <small><b>${esc(m.status)}</b> · ${esc(m.source)}</small></div>`).join("");
  return `<div class="sim"><div class="simhead"><div><span>Version A · public data</span><b id="simA"></b></div>
      <div><span>Version B · with these values</span><b id="simB"></b></div><button type="button" class="btn" id="simReset">Reset</button></div>
    <div class="simtrack"><i id="simMa"></i><i id="simMb"></i></div>
    <h3>Inputs the engine already weighs, that a club knows better</h3>${eng}
    <h3>Measured only by the club</h3>${club}
    <ul class="unread">${c.caveats.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`;
}
function gridAt(g, x) {
  if (x <= g[0][0]) return g[0][1];
  for (let i = 1; i < g.length; i++) if (x <= g[i][0]) return g[i - 1][1] + (g[i][1] - g[i - 1][1]) * (x - g[i - 1][0]) / (g[i][0] - g[i - 1][0]);
  return g[g.length - 1][1];
}
function wireSim(w) {
  if (!w?.club || !$(".sim")) return;
  const c = w.club, base = w.intercept + w.groups.reduce((s, g) => s + g.logit, 0), pA = sig(base);
  const fmt = (p) => `${(p * 100).toFixed(0)} %`;
  const calc = () => {
    let l = base;
    c.engine_inputs.forEach((e, i) => {
      const el = $(`[data-eng="${i}"]`), x = +el.value;
      $(`[data-eng="${i}"] + output`).textContent = `${e.step < 1 ? x.toFixed(2) : num(x)} ${e.unit}`;
      // only once moved: his term swapped for the one at the new value (the missing flag goes to 0: the value is known)
      // (ProEngine is a tree: the call re-scored at 15 values across the slider is in e.grid, read between points)
      if (el.dataset.touched && e.grid?.length) l += gridAt(e.grid, x) - base;
    });
    c.club_measures.forEach((m, i) => {
      const z = +$(`[data-club="${i}"]`).value, or = Math.max(0.05, +$(`[data-or="${i}"]`).value || 1);
      $(`[data-club="${i}"] + output`).textContent = SD_LABEL[String(Math.round(z))] + (Math.abs(z % 1) ? " (half a step)" : "");
      l += Math.log(or) * z;
    });
    const pB = sig(l);
    $("#simA").textContent = fmt(pA); $("#simB").textContent = fmt(pB);
    $("#simMa").style.left = `${pA * 100}%`; $("#simMb").style.left = `${pB * 100}%`;
  };
  $$(".sim input").forEach((el) => el.addEventListener("input", () => { el.dataset.touched = "1"; calc(); }));
  $("#simReset").addEventListener("click", () => {
    c.engine_inputs.forEach((e, i) => { const el = $(`[data-eng="${i}"]`); el.value = e.value ?? e.median; delete el.dataset.touched; });
    c.club_measures.forEach((m, i) => { $(`[data-club="${i}"]`).value = 0; $(`[data-or="${i}"]`).value = m.or_per_sd; });
    calc();
  });
  calc();
}

// how he plays: his role in his team, the skills his system doesn't explain, the
// attributes that repeat from match to match; then what these data can't read, named. Percentiles among his position
// that season; a dot on a track, the median marked, bold from the 90th percentile.
const FAM_PLURAL = { GK: "goalkeepers", CB: "centre-backs", FB: "full-backs", DM: "holding midfielders", CM: "central midfielders",
  AM: "attacking midfielders", W: "wingers", ST: "strikers" };
const pctRow = (label, v, { strong = false, note = "", cls = "", extra = "" } = {}) =>
  `<div class="pr${strong ? " sig" : ""}${cls ? ` ${cls}` : ""}"><span class="pr-l">${esc(label)}${note ? `<small>${esc(note)}</small>` : ""}${extra}</span>` +
  `<span class="pr-t"><i class="pr-m"></i><i class="pr-d" style="left:${(v * 100).toFixed(1)}%"></i></span><b>${ordinal(Math.min(99, Math.max(1, Math.round(v * 100))))}</b></div>`;
// Expert depth: how far to trust a bar. Both numbers describe the measure across every player-season of 1,800+
// minutes, not this player ("what do they even mean?"): how well a season's odd matches predict its
// even ones (the gate shows a measure from 0.50), and, for the attributes, how much of the gap between two players is
// real rather than which matches they happened to play (discrimination, Franks et al. 2016)
const expertNum = (r, dsc) => r == null ? "" : `<small class="d-expert">How far to trust this bar (the same on every player's page): a season's odd and even matches agree at ${r.toFixed(2)}, shown from 0.50${dsc != null ? ` · ${Math.round(dsc * 100)} % of the gaps between players are real, the rest is which matches they played` : ""}</small>`;
function howPlays(st) {
  if (!st) return '<p class="none">Read from the detailed match stats (2021/22 on) once he has a league season of 900+ minutes.</p>';
  const ssn = /^\d{4}-\d{4}$/.test(st.season) ? `${st.season.slice(2, 4)}/${st.season.slice(7, 9)}` : st.season;
  const roles = Object.entries(st.roles).sort((a, b) => b[1] - a[1]);
  const unread = [...st.hidden.map((h) => `<li><b>${esc(h.label)}</b> doesn't repeat from one half-season to the next (${h.split_half.toFixed(2)})</li>`),
    ...Object.entries(st.not_readable).map(([k, v]) => `<li><b>${esc(k[0].toUpperCase() + k.slice(1))}</b>: ${esc(v)}</li>`)].join("");
  return `<p class="caption">${ssn} · <a href="#/team/${st.team_id}">${esc(st.team)}</a> · ${num(st.minutes)} league minutes · percentiles among the ${FAM_PLURAL[st.family] || st.family} of his league that season</p>
    <div class="howplays">
      <div><h3>His role</h3>${roles.map(([k, v]) => pctRow(k, v, { strong: k === st.top_role })).join("")}
        <p class="note">How strongly his game reads as each role of his position. Bold: the role he plays most like.</p></div>
      <div><h3>Beyond his system</h3>${st.skills.map((s, i) => pctRow(s.label, s.pct, { strong: s.pct >= 0.9, cls: i < 3 ? "top" : "", extra: expertNum(s.split_half) })).join("") || '<p class="none">Not enough minutes to read.</p>'}
        <p class="note">What he does more of than his team's game model and his league predict. Bold: his signature, 90th percentile and up.</p></div>
      <div><h3>Attributes</h3>${st.attributes.map((a) => pctRow(a.label, a.pct, { note: a.reads, extra: expertNum(a.split_half, a.discrimination) })).join("") || '<p class="none">Read for outfield players.</p>'}
        <h4>Not read here</h4><ul class="unread">${unread}</ul></div>
    </div>`;
}
function enterPlayer() {
  if (!motion()) return;
  const seats = $$(".terrace .seat");
  if (seats.length) gsap.from(seats, { scaleY: 0, transformOrigin: "50% 100%", duration: 0.34, ease: "power3.out",
    stagger: { each: Math.min(0.0022, 0.8 / seats.length) } });               // the stand fills, oldest row first
  // the call counts once: a rank climbs through the field to his place, a share rises to its value
  const fig = $(".call-figure[data-fig]");
  if (fig) {
    const { fig: kind, from, to } = fig.dataset, o = { v: +from }, rest = kind === "pct" ? fig.innerHTML.replace(/^\d+/, "") : "";
    const show = (v) => { const n = Math.round(v);
      fig.innerHTML = kind === "rank" ? ordinal(n) : kind === "top" ? `top ${n} %` : `${n}${rest}`; };
    show(+from);
    gsap.to(o, { v: +to, duration: kind === "rank" ? 1.1 : 0.8, ease: "expo.out", onUpdate: () => show(o.v) });
  }
  const band = $(".scale .band");
  if (band) gsap.from(band, { scaleX: 0, transformOrigin: "50% 50%", duration: 0.6, ease: "expo.out", delay: 0.15 });
  gsap.from(".ticket > div", { y: 6, opacity: 0, duration: 0.4, ease: "expo.out", stagger: 0.025 });
  // how he plays: every dot waits on the median and moves to his percentile when the block comes into view
  // (onView lives in club.js, loaded with the desk)
  const dots = $$(".howplays .pr-d");
  if (dots.length) {
    dots.forEach((d) => { d.dataset.to = d.style.left; gsap.set(d, { left: "50%" }); });
    onView(".howplays", () => gsap.to(dots, { left: (i, el) => el.dataset.to, duration: 0.7, ease: "expo.out", stagger: 0.015 }));
  }
}

/* ── C. Compare: lined up by age ───────────────────────────────────────────────────────────────────────────── */
// players are told apart by ink and dash only: the seat ramp means level, nothing else
const CMP = [["var(--ink)", ""], ["var(--ink)", "8 5"], ["var(--ink-3)", ""], ["var(--ink-3)", "2 4"]];
async function compare(ids) {
  const players = ids ? await api(`/api/compare?ids=${ids}`) : [];
  return () => {
    setNav("compare");
    let chart = "", grid = "";
    if (players.length) {
      // quality minutes summed by age at each season's end: lined up by age, never by calendar date
      const W = 900, H = 260, padL = 44, padR = 150;
      const lines = players.map((p) => { let cum = 0; return p.seasons.map((s) => { cum += s.qmin || 0; return [yearsAt(p.dob, s.season + 1, 5, 30), cum]; }); });
      const xs = lines.flat().map((v) => v[0]), ys = lines.flat().map((v) => v[1]);
      const x0 = Math.floor(Math.min(16, ...xs)), x1 = Math.ceil(Math.max(21, ...xs)), y1 = Math.max(1000, ...ys) * 1.05;
      const X = (a) => padL + ((a - x0) / (x1 - x0)) * (W - padL - padR), Y = (v) => H - 26 - (v / y1) * (H - 46);
      const gl = []; for (let a = x0; a <= x1; a++) gl.push(`<line class="grid" x1="${X(a)}" x2="${X(a)}" y1="10" y2="${H - 26}"/><text x="${X(a)}" y="${H - 8}" text-anchor="middle">${a}</text>`);
      const paths = lines.map((l, i) => {
        const [c, dash] = CMP[i]; if (!l.length) return "";
        const [ea, ev] = l.at(-1);
        return `<polyline fill="none" stroke="${c}" stroke-width="2.5" ${dash ? `stroke-dasharray="${dash}"` : ""} points="${l.map(([a, v]) => `${X(a)},${Y(v)}`).join(" ")}"/>` +
          l.map(([a, v]) => `<circle cx="${X(a)}" cy="${Y(v)}" r="3.2" fill="${c}"/>`).join("") +
          `<text class="end" x="${X(ea) + 8}" y="${Y(ev) + 4}" style="fill:${c}">${esc(players[i].name.split(" ").at(-1))} · ${num(ev)}</text>`;
      }).join("");
      chart = `<svg class="cmp-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Quality minutes summed by age">${gl.join("")}<line class="axis" x1="${padL}" x2="${W - padR}" y1="${H - 26}" y2="${H - 26}"/>${paths}</svg>
        <p class="caption">Quality minutes summed by age at each season's end. Quality minutes weigh every minute by the level of the match.</p>`;
      // age by age: each player's terrace row at that age, side by side
      const ages = new Set(); const at = players.map((p) => { const m = new Map(); p.terrace.forEach((s) => { const a = Math.floor(yearsAt(p.dob, s.season)); ages.add(a); (m.get(a) || m.set(a, []).get(a)).push(s); }); return m; });
      const sorted = [...ages].sort((a, b) => a - b);
      const cols = `grid-template-columns: 64px repeat(${players.length}, minmax(0, 1fr))`;
      grid = `<div class="cmp-grid" style="${cols}"><div class="h"></div>${players.map((p, i) => `<div class="h"><b><svg width="26" height="8" aria-hidden="true" style="margin-right:8px"><line x1="0" x2="26" y1="4" y2="4" stroke="${CMP[i][0]}" stroke-width="3" ${CMP[i][1] ? `stroke-dasharray="${CMP[i][1]}"` : ""}/></svg>${esc(p.name)}</b><small>${esc(p.club || "")} · born ${day(p.dob)} · <a class="link" href="#/compare?ids=${players.filter((_, j) => j !== i).map((x) => x.tm_id).join(",")}">remove</a></small></div>`).join("")}
        ${sorted.map((a) => `<div class="age">${a}</div>${at.map((m) => { const s = m.get(a) || []; const mins = s.reduce((t, x) => t + (x.minutes || 0), 0);
          return `<div class="cell">${s.length ? miniRow(s) : ""}<small>${s.length ? `${num(mins)} min · ${s.length} ${s.length === 1 ? "match" : "matches"}` : "—"}</small></div>`; }).join("")}`).join("")}</div>`;
    }
    main.innerHTML = `<div class="page-head"><div><h1>Compare Players</h1><p class="lead">Up to four players, lined up by age: at 18, who had played more, and at what level.</p></div>
      <form class="add-player" id="cmp-form" autocomplete="off"><label class="field">Add a player<input id="cmp-add" type="search" placeholder="a name" ${players.length >= 4 ? "disabled" : ""}></label><ul id="cmp-res" role="listbox"></ul></form></div>
      ${players.length ? `<section class="block" aria-labelledby="c1">${sign("A", "Quality minutes by age", "", "c1")}${chart}</section>
        <section class="block" aria-labelledby="c2">${sign("B", "Age by age", "each row: his matches in the season he began at that age", "c2")}${grid}
        <div class="ramp">${ramp(STEP_LABEL.map((l, i) => i ? `senior, ${l}` : l))}</div></section>`
      : `<div class="empty"><h2>Two stands, facing</h2><p>Add a player by name above, or press "Compare" on a player's page. Their careers line up by age, not by date.</p></div>`}`;
    const inp = $("#cmp-add");
    inp.addEventListener("input", async () => {
      const rows = inp.value.length < 2 ? [] : await api(`/api/search?q=${encodeURIComponent(inp.value)}&limit=6`);
      $("#cmp-res").innerHTML = rows.map((r) => `<li><a href="#/compare?ids=${[...players.map((p) => p.tm_id), r.tm_id].join(",")}"><span class="who" style="font:700 1rem/1.2 var(--sign);text-transform:uppercase">${esc(r.name)}</span> <span class="dim">${esc(r.club || "")} · ${r.age ?? ""}</span></a></li>`).join("");
    });
    return () => motion() && gsap.from(".cmp-chart polyline", { strokeDasharray: "2000", strokeDashoffset: 2000, duration: 1, ease: "expo.out", stagger: 0.08, clearProps: "strokeDasharray,strokeDashoffset" });
  };
}
function miniRow(seats) {
  const W = 300, p = Math.min(9, W / Math.max(30, seats.length)), sw = p * 0.78, sh = 12;
  return `<svg viewBox="0 0 ${W} 16" preserveAspectRatio="xMinYMid meet" aria-hidden="true" class="terrace">${seats.map((s, j) =>
    `<rect class="back" x="${j * p}" y="2" width="${sw}" height="${sh}" rx="2"/><rect class="k${step(s.level, s.kind)}" x="${j * p}" y="${2 + sh * (1 - Math.min(1, (s.minutes || 0) / 90))}" width="${sw}" height="${sh * Math.min(1, (s.minutes || 0) / 90)}"/>`).join("")}</svg>`;
}

/* ── D. Lists: season-ticket books ─────────────────────────────────────────────────────────────────────────── */
async function lists() {
  const [data, players] = await Promise.all([api("/api/lists"), loadBowl().catch(() => [])]);
  const byId = new Map(players.map((p) => [p.tm_id, p]));
  return () => {
    setNav("lists");
    const names = Object.keys(data).filter((n) => data[n].length);
    if (!names.length) {
      main.innerHTML = `<div class="page-head"><div><h1>Shortlists</h1></div></div><div class="empty"><h2>No shortlist yet</h2><p>On a player's page, "Add to a list" keeps him here with your note.</p></div>`;
      return;
    }
    // the page's lead and the compare hint are the only fixed words here; the rest is written from the figures
    main.innerHTML = `<div class="page-head"><div><h1>Shortlists</h1><p class="lead">Your own working lists: the players you keep, with what you saw, and what has moved since the day you kept each one.</p></div></div>` + names.map((n, li) =>
      `<section class="block" aria-labelledby="l${li}">${sign(String.fromCharCode(65 + (li % 26)), esc(n), `${data[n].length} ${data[n].length === 1 ? "player" : "players"}`, `l${li}`)}
      ${data[n].length > 1 ? `<div class="list-tools"><a class="btn" data-cmp-go="${li}" href="#/compare">${icon("compare")}Compare the ticked</a><span class="dim">tick up to four players; the first four are ticked to start</span></div>` : ""}
      ${data[n].map((e, ei) => { const p = byId.get(e.tm_id) || {}, who = esc(p.name || `#${e.tm_id}`); return `<div class="stub">
        ${data[n].length > 1 ? `<input type="checkbox" class="cmp-tick" data-cmp="${li}" value="${e.tm_id}"${ei < 4 ? " checked" : ""} aria-label="Compare ${who}">` : "<span></span>"}
        <a href="#/player/${e.tm_id}"><div class="who">${who}</div><div class="sub dim">${esc(p.club || "")}${p.age ? ` · ${p.age.toFixed(1)}` : ""}</div></a>
        <div class="note-cell">${e.note ? esc(e.note) : '<span class="dim">no note</span>'}</div><span class="dim num">kept ${day(e.added)}</span>
        <button class="btn" type="button" data-rm="${esc(n)}|${e.tm_id}" aria-label="Remove ${who} from ${esc(n)}">${icon("x")}</button>
        ${sinceKept(e)}</div>`; }).join("")}</section>`).join("");
    $$("[data-rm]").forEach((b) => b.addEventListener("click", async () => {
      const [n, id] = b.dataset.rm.split("|");
      await api(`/api/lists/${encodeURIComponent(n)}/${id}`, { method: "DELETE" }); toast("Removed."); route();
    }));
    // compare this list: the ticked players (four at most, the Compare page's limit) go into the link
    names.forEach((n, li) => {
      const go = $(`[data-cmp-go="${li}"]`); if (!go) return;
      const ticks = $$(`[data-cmp="${li}"]`);
      const sync = () => {
        const on = ticks.filter((t) => t.checked);
        ticks.forEach((t) => { t.disabled = !t.checked && on.length >= 4; });
        go.href = `#/compare?ids=${on.map((t) => t.value).join(",")}`;
        go.classList.toggle("off", on.length < 2); go.setAttribute("aria-disabled", String(on.length < 2));
      };
      ticks.forEach((t) => t.addEventListener("change", sync)); sync();
      go.addEventListener("click", (ev) => { if (go.classList.contains("off")) { ev.preventDefault(); toast("Tick at least two players to compare."); } });
    });
  };
}
// Since you kept him: the desk on the day he was kept (`kept`, stored by the server) against the desk today (`now`).
// The call moves with each weekly rebuild; the 25/26 level and minutes belong to the last complete season, so they move
// only when the data for it is revised or 26/27 closes; the matches since are counted after the last match the desk held
// that day, so they are the ones you hadn't seen.
const levelWord = (r) => r.min_now > 0 ? STEP_SHORT[step(r.lvl, "league")] : r.ym > 0 ? "youth only" : "no football seen";
function sinceKept(e) {
  const k = e.kept, n = e.now, s = e.since;
  if (!n) return "";
  const bits = [];
  if (k) {
    if (k.p_reg3 != null && n.p_reg3 != null) {
      const d = Math.round((n.p_reg3 - k.p_reg3) * 100);
      bits.push(d ? `<li class="mv-call">Promesse's call ${pct(k.p_reg3)} → <b>${pct(n.p_reg3)}</b> <span class="num">(${d > 0 ? "+" : "−"}${Math.abs(d)} points)</span></li>`
                  : `<li>Promesse's call ${pct(n.p_reg3)}, unchanged</li>`);
    } else if (n.p_reg3 != null) bits.push(`<li class="mv-call">Promesse's call now <b>${pct(n.p_reg3)}</b> (none when you kept him)</li>`);
    else if (k.p_reg3 != null) bits.push(`<li>No call now (${pct(k.p_reg3)} when you kept him): he is past the under-21 cohort the engine scores</li>`);
    if (k.club !== n.club) bits.push(`<li>Club: ${esc(k.club || "none")} → <b>${esc(n.club || "none")}</b></li>`);
    if (levelWord(k) !== levelWord(n)) bits.push(`<li>Level in 25/26: ${levelWord(k)} → <b>${levelWord(n)}</b></li>`);
    if (k.min_now !== n.min_now) bits.push(`<li>First-division minutes in 25/26: ${num(k.min_now)} → <b>${num(n.min_now)}</b></li>`);
    if (k.engine && n.engine && k.engine !== n.engine) bits.push(`<li class="dim">The engine was updated since: part of the call's move is the engine's, not his.</li>`);
  }
  bits.push(s.n ? `<li>Since ${day(s.from)}: <b>${s.n} ${s.n === 1 ? "match" : "matches"}</b>, ${num(s.senior)} senior minutes${s.youth ? `, ${num(s.youth)} youth` : ""} (the latest ${day(s.last)})</li>`
                : `<li class="dim">No match after ${day(s.from)} yet${k && k.built === n.built ? ", the last one the desk held when you kept him; it rebuilds with the data every week" : ""}</li>`);
  return `<ul class="since" aria-label="Since you kept him">${bits.join("")}</ul>`;
}

/* ── Ctrl+K: any player, any board ─────────────────────────────────────────────────────────────────────────── */
const pal = $("#palette"), pin = $("#palette-input"), pres = $("#palette-results");
let sel = 0, found = [];
const BOARD_ITEMS = [["above_age", "Above his age level"], ["debut_watch", "Debut watch"], ["under_radar", "Under the radar"]];
function openPal() { pal.showModal(); pin.value = ""; found = (store.get("recent") || []).map((r) => ({ ...r, kind: "recent" })); sel = 0; drawPal(); pin.focus(); }
$("#palette-open").addEventListener("click", openPal);
addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); pal.open ? pal.close() : openPal(); } });
pin.addEventListener("input", async () => {
  const q = pin.value.trim().toLowerCase();
  const bds = q.length < 2 ? [] : BOARD_ITEMS.filter(([, l]) => l.toLowerCase().includes(q)).map(([id, l]) => ({ board: id, name: l, kind: "board" }));
  const ppl = q.length < 2 ? [] : await api(`/api/search?q=${encodeURIComponent(pin.value)}`).catch(() => []);
  found = q.length < 2 ? (store.get("recent") || []).map((r) => ({ ...r, kind: "recent" })) : [...bds, ...ppl.map((r) => ({ ...r, kind: "player" }))];
  sel = 0; drawPal();
});
function drawPal() {
  pres.innerHTML = found.length ? found.map((r, i) => `<li role="option" id="po${i}" aria-selected="${i === sel}" data-i="${i}"><span class="who">${esc(r.name)}</span>
    <span class="kind">${r.kind === "board" ? "board" : r.kind === "recent" ? "recent" : esc(r.position || "")}</span>
    <span class="sub">${r.kind === "board" ? "ready-made list" : `${esc(r.club || "")}${r.age ? ` · ${r.age}` : ""}`}</span></li>`).join("")
    : `<li aria-disabled="true"><span class="sub">${pin.value.length < 2 ? "Type two letters of a name." : "Nobody by that name in the 22,522."}</span></li>`;
  pin.setAttribute("aria-activedescendant", found.length ? `po${sel}` : "");
  $$("li[data-i]", pres).forEach((li) => li.addEventListener("click", () => go(found[+li.dataset.i])));
}
function go(r) { pal.close(); if (!r) return; location.hash = r.kind === "board" ? `#/board/${r.board}` : `#/player/${r.tm_id}`; }
pin.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { sel = Math.min(sel + 1, found.length - 1); drawPal(); e.preventDefault(); }
  if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); drawPal(); e.preventDefault(); }
  if (e.key === "Enter") { e.preventDefault(); go(found[sel]); }
});

/* ── routing: fetch first, then change the page in one view transition ────────────────────────────────────── */
let META = null, routeN = 0, painted = false;
// Method (drawer): every module, the question it answers, the test it had to pass on data it never saw, what it said.
// A module that didn't pass stays off the desk; the page says so instead of hiding it
async function methodPage() {
  const d = await api("/api/method");
  return () => {
    setNav("method");
    main.innerHTML = `<div class="page-head"><div><h1>Method</h1>
      <p class="lead">Every number on this desk comes from a module that had to pass a test first, on matches or seasons it never saw. ${d.rows.filter((r) => r.passed).length} of ${d.rows.length} passed; the others stay off the pages until they do.</p></div></div>
      <ol class="method">${d.rows.map((r, i) => `<li class="${r.passed ? "ok" : "held"}" data-reveal>
        <b class="m-k">${String.fromCharCode(65 + i)}</b>
        <div class="m-q"><h2>${esc(r.module)}</h2><p>${esc(r.asks)}</p></div>
        <div class="m-t"><span class="kicker">The test</span><p>${esc(r.test)}</p></div>
        <div class="m-r"><span class="kicker">What it said</span><p class="num">${esc(r.result)}</p></div>
        <span class="m-s">${r.passed ? "Passed" : "Held back"}</span></li>`).join("")}</ol>
      <p class="note">What a club's own data would add to each of these is on <a href="#/club/barcelona">FC Barcelona</a>, under "What Barça's own data would add". On every player page, Expert depth shows the test behind each figure.</p>`;
    if (motion()) gsap.from(".method li", { y: 18, opacity: 0, duration: 0.5, ease: "expo.out", stagger: 0.05 });
  };
}

async function route() {
  const n = ++routeN;
  const [path, query] = location.hash.slice(2).split("?");
  const [view, arg] = (path || "discover").split("/");
  const params = new URLSearchParams(query || "");
  hideTip();
  if (view === "club" && arg === "barcelona") return location.replace("#/dive/barcelona");   // Barça lives in Deep Dives now
  const slow = setTimeout(() => root.classList.add("loading"), 150);
  let paint;
  try {
    paint = view === "player" ? await playerPage(arg)
      : view === "boards" || view === "board" ? await boards(arg)
      : view === "compare" ? await compare(params.get("ids") || "")
      : view === "lists" ? await lists()
      : view === "club" && window.clubPage ? await clubPage(arg)
      : view === "team" && window.teamPage ? await teamPage(arg)
      : view === "teams" && window.teamsIndex ? await teamsIndex()
      : view === "coaches" && window.coachesIndex ? await coachesIndex()
      : view === "method" ? await (window.scoreboardPage ? scoreboardPage() : methodPage())
      : (view === "data" || view === "connect") && window.connectPage ? await connectPage()
      : view === "combinations" && window.combinationsPage ? await combinationsPage()
      : view === "dives" && window.divesIndex ? await divesIndex()
      : view === "dive" && window.divePage ? await divePage(arg)
      : view === "coach" && window.coachPage ? await coachPage(arg)
      : await discover(params.get("seat"));
  } catch (err) {
    paint = () => { main.innerHTML = `<div class="empty"><h2>The desk couldn't load this page</h2><p>${esc(err.message)}. If the server stopped, start it again: <code>python scout/serve.py</code> (the watchdog also restarts it within the hour).</p></div>`; };
  }
  clearTimeout(slow); root.classList.remove("loading");
  if (n !== routeN) return;
  let enter = null;
  const swap = () => { delete main.dataset.dive; enter = paint(); main.focus({ preventScroll: true }); scrollTo(0, 0); };   // a dive repaints its own tokens
  if (painted && document.startViewTransition && !reduced) await document.startViewTransition(swap).updateCallbackDone;
  else swap();
  painted = true;
  if (typeof enter === "function") enter();
}
addEventListener("hashchange", route);
(async () => {
  await document.fonts.ready;            // the bowl paints its labels in Barlow Condensed
  if (DOOR && !store.get("mode") && !phoneClass()) await openDoor();
  route();
  api("/api/meta").then((m) => { META = m; const a = m.as_of || {}; $("#asof").textContent = `Built ${day(m.built)} · MatchData to ${day(a["MatchData matches"])} · Transfermarkt to ${day(a["Transfermarkt appearances"])}`; }).catch(() => {});
})();
