// Club boards (the Barça board first,): the system, then the pathway. Drawn in the Terrace: ink for every
// series (the seat ramp stays reserved for level, crimson for Promesse's own call); analysis files only.
const DIM_NAME = {
  possession: "Possession", combination: "Passing play", directness: "Going long", progression: "Passes into the final third",
  width: "Crossing from wide", dribbling: "1v1 dribbling", box_presence: "Play reaching the box",
  ball_winning: "Winning the ball back", aerial_play: "Aerial duels", back_three: "Back three", two_up_front: "Two up front",
};
const FAMILY_NAME = { GK: "Goalkeeper", CB: "Centre-backs", FB: "Full-backs", DM: "Holding midfield", CM: "Central midfield",
  AM: "Attacking midfield", W: "Wingers", ST: "Strikers" };
// the open page (window.PUBLIC_PAGE) publishes analysis without naming its sources; the private desk names them
const SRC = window.PUBLIC_PAGE
  ? { shapes: "match line-ups", detail: "The detailed match data used here starts in 2021/22" }
  : { shapes: "Transfermarkt line-ups", detail: "MatchData's detailed match stats only start in 2021/22" };
const SKILL_SHORT = { "Moves the ball into the final third": "Final-third passes", "Gets into scoring positions": "Scoring positions",
  "Quality of the chances he creates": "Chance quality", "Secure passer": "Secure passing", "Arrives in the box": "Box arrivals",
  "Wins the ball back": "Ball winning" };
const seasonShort = (s) => /^\d{4}-\d{4}$/.test(s) ? `${s.slice(2, 4)}/${s.slice(7, 9)}` : s;   // calendar-year leagues: "2025"
const signed = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;

// the game model, season by season: each cell is the value against LaLiga that season, its bar drawn from zero;
// Flick's seasons shaded. Numbers first, because the people reading this read numbers.
function seasonStrip(rows, dims, flickFrom = "2024-2025", label = "Barça's game model, season by season, against LaLiga", league = "LaLiga") {
  const fi = rows.findIndex((r) => r.season === flickFrom);
  const head = `<div class="zh"></div>${rows.map((r, i) => `<div class="zh${i >= fi && fi >= 0 ? " flick" : ""}">${seasonShort(r.season)}${r.matches < 20 ? "*" : ""}<small class="d-expert">${r.matches} matches</small></div>`).join("")}`;
  const body = dims.map((d) => `<div class="zl">${DIM_NAME[d] || d}</div>${rows.map((r, i) => {
    const v = r[d], w = Math.min(1, Math.abs(v) / 3.5) * 50;
    return `<div class="zc${i >= fi && fi >= 0 ? " flick" : ""}" title="${seasonShort(r.season)}: ${signed(v)} against ${league}"><i style="left:${v < 0 ? 50 - w : 50}%;width:${w}%"></i><b>${signed(v)}</b></div>`;
  }).join("")}`).join("");
  const eras = fi >= 0 ? `<div class="zl"></div><div class="ze" style="grid-column:span ${fi}">Xavi</div><div class="ze flick" style="grid-column:span ${rows.length - fi}">Flick</div>` : "";
  return `<div class="zgrid" style="--n:${rows.length}" role="table" aria-label="${esc(label)}">${head}${body}${eras}</div>`;
}

// what changed when Flick replaced Xavi: hollow = Xavi, filled = Flick, sorted by the size of the change
function dumbbells(byDim, label = "What changed when Flick replaced Xavi") {
  const rows = Object.entries(byDim).sort((a, b) => Math.abs(b[1].shift) - Math.abs(a[1].shift));
  const W = 760, rowH = 30, left = 190, right = 200, H = rows.length * rowH + 30;
  const lo = -3, hi = 3.5, X = (v) => left + ((v - lo) / (hi - lo)) * (W - left - right);
  const ticks = [-2, 0, 2].map((v) => `<line class="zero" x1="${X(v)}" x2="${X(v)}" y1="0" y2="${H - 22}"/><text class="sh" x="${X(v)}" y="${H - 6}" text-anchor="middle">${v > 0 ? "+" : ""}${v}</text>`).join("");
  const body = rows.map(([d, v], i) => {
    const yy = 12 + i * rowH;
    return `<g class="db${v.clear ? " clear" : ""}"><text class="dl" x="0" y="${yy + 4}">${DIM_NAME[d] || d}</text>
      <line class="dbl" x1="${X(v.before)}" x2="${X(v.after)}" y1="${yy}" y2="${yy}"/>
      <circle class="dbx" cx="${X(v.before)}" cy="${yy}" r="5"/><circle class="dbf" cx="${X(v.after)}" cy="${yy}" r="5.5"/>
      <text class="dv" x="${W - right + 14}" y="${yy + 4}">${signed(v.shift)}<tspan class="ci"> (${signed(v.ci95[0])} to ${signed(v.ci95[1])})</tspan></text></g>`;
  }).join("");
  return `<svg class="dumb" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${ticks}${body}</svg>`;
}

function shapes(f) {
  return Object.entries(f).map(([spell, v]) => `<div class="shape"><span>${esc(spell)} · ${num(v.matches)} matches</span>
    <div class="shapebar">${v.shapes.map((s, i) => `<i style="flex:${s.share}" class="${i ? "minor" : ""}" title="${esc(s.formation)}: ${pct(s.share)}"><b>${s.share >= 0.12 ? esc(s.formation) : ""}</b></i>`).join("")}</div>
    <small>${v.shapes.map((s) => `${esc(s.formation)} ${pct(s.share)}`).join(" · ")}</small></div>`).join("");
}

// the team sheet: his regulars by line, each with the role he plays most like, as a matchday programme lists them
function teamSheet(roles, season, league = "LaLiga") {
  const fams = ["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"];
  return `<div class="sheet">${fams.map((f) => {
    const ps = roles.filter((r) => r.season === season && r.family === f && r.top_role);
    if (!ps.length) return "";
    return `<div class="line"><span class="fam">${FAMILY_NAME[f]}</span>${ps.map((p) => {
      const top = p.role_percentiles[p.top_role];
      const name = !window.PUBLIC_PAGE && p.tm_id ? `<a href="#/player/${p.tm_id}">${esc(p.name)}</a>` : esc(p.name);
      return `<div class="pl"><b>${name}</b><span class="role">${esc(p.top_role)}</span><small>${num(p.minutes)} min · ${ordinal(Math.min(99, Math.round(top * 100)))} percentile in ${esc(league)}</small></div>`;
    }).join("")}</div>`;
  }).join("")}</div>`;
}

// academies by how many of their U19 players had a first-division season by 21, with 95 % intervals
function academies(funnel) {
  const W = 760, rowH = 26, left = 170, right = 120, H = funnel.length * rowH + 30;
  const X = (v) => left + v * (W - left - right) / 0.7;
  const grid = [0, 0.2, 0.4, 0.6].map((v) => `<line class="zero" x1="${X(v)}" x2="${X(v)}" y1="0" y2="${H - 22}"/><text class="sh" x="${X(v)}" y="${H - 6}" text-anchor="middle">${Math.round(v * 100)} %</text>`).join("");
  const body = funnel.map((r, i) => {
    const yy = 12 + i * rowH, me = r.academy === "Barcelona";
    return `<g class="ac${me ? " me" : ""}"><text class="dl" x="0" y="${yy + 4}">${esc(r.academy)}</text>
      <line class="ci-l" x1="${X(r.first_division_by_21_ci95[0])}" x2="${X(r.first_division_by_21_ci95[1])}" y1="${yy}" y2="${yy}"/>
      <circle class="pt" cx="${X(r.first_division_by_21)}" cy="${yy}" r="${me ? 6 : 4.5}"/>
      <text class="dv" x="${W - right + 12}" y="${yy + 4}">${pct(r.first_division_by_21)}<tspan class="ci"> of ${r.u19_players}</tspan></text></g>`;
  }).join("");
  return `<svg class="dumb acad" viewBox="0 0 ${W} ${H}" role="img" aria-label="Academies: share of U19 players with a first-division season by 21">${grid}${body}</svg>`;
}

// who fits Flick's Barça, one role at a time: the young players whose profile, moved by T5 into Barça's game model,
// sits closest to what Flick's regulars do. Each skill is a track: bar = the regulars, ring = the player at his club
// now, dot = the model's read of him at Barça. Ink only; the league he played it in is written beside his name.
const FIT_LO = -2, FIT_HI = 3.5;
const fitX = (v) => `${((Math.min(FIT_HI, Math.max(FIT_LO, v)) - FIT_LO) / (FIT_HI - FIT_LO) * 100).toFixed(1)}%`;
function fitBoard(v, bigFiveOnly) {
  const asks = v.what_the_role_asks;
  const rows = v.candidates.filter((c) => !bigFiveOnly || c.big_five).slice(0, 8);
  if (!rows.length) return `<p class="note">Nobody close to this role played in a big-five league in 25/26.</p>`;
  const head = `<div class="fh">Player</div>${asks.map((a) => `<div class="fh sk" title="${esc(a.skill)}">${esc(SKILL_SHORT[a.skill] || a.skill)}<b>${signed(a.template)}</b></div>`).join("")}<div class="fh fp">Closer than</div>`;
  const body = rows.map((c) => {
    const name = window.PUBLIC_PAGE || !c.tm_id ? `<b>${esc(c.name)}</b>` : `<a href="#/player/${c.tm_id}"><b>${esc(c.name)}</b></a>`;
    const where = `${esc(c.club)} · ${esc(c.league)}${c.club_now ? ` · now ${esc(c.club_now)}` : ""}${c.first_team_min ? ` · ${num(c.first_team_min)} min for Flick in 26/27` : ""}`;
    const tracks = asks.map((a) => {
      const now = c.now?.[a.skill], at = c.at_barca[a.skill];
      const title = `${a.skill}: ${now == null ? "" : `now ${signed(now)}, `}at Barça ${signed(at)}, Flick's regulars ${signed(a.template)}`;
      return `<div class="ft" title="${esc(title)}"><span class="trk"><span class="zero" style="left:${fitX(0)}"></span><span class="tpl" style="left:${fitX(a.template)}"></span>${now == null ? "" : `<i class="nw" style="left:${fitX(now)}"></i>`}<i class="at" data-from="${fitX(now ?? 0)}" data-to="${fitX(at)}" style="left:${fitX(at)}"></i></span></div>`;
    }).join("");
    return `<div class="fn">${name}<small>${c.age == null ? "" : `${c.age.toFixed(1)} · `}${where}</small>${attrLine(c.attributes)}</div>${tracks}<div class="fp"><b>${Math.min(99, Math.floor(c.fit_pct * 100))}</b><small>%</small></div>`;
  }).join("");
  return `<p class="note regs">Flick's regulars here: ${v.regulars.map(esc).join(", ")} · ${num(v.pool)} players in the pool</p><div class="fitgrid">${head}${body}</div>`;
}
// his attributes under his name: percentiles among his position, bold from the 90th
const attrLine = (at) => {
  const parts = Object.entries(at || {}).filter(([, v]) => v != null)
    .map(([k, v]) => { const n = Math.min(99, Math.max(1, Math.round(v * 100))); return v >= 0.9 ? `<b>${esc(k)} ${ordinal(n)}</b>` : `${esc(k)} ${ordinal(n)}`; });
  return parts.length ? `<small class="attrs">${parts.join(" · ")}</small>` : "";
};
// the filled dot travels from where he plays now to where the model reads him at Barça
function slideFit() {
  if (!motion()) return;
  $$("#fit .ft .at").forEach((el, i) => {
    gsap.fromTo(el, { left: el.dataset.from }, { left: el.dataset.to, duration: 0.75, ease: "expo.out", delay: 0.15 + Math.floor(i / 4) * 0.045 });
  });
}
// run once, the first time a part is a quarter in view (parts already in view at load run straight away)
function onView(sel, run) {
  const el = typeof sel === "string" ? $(sel) : sel;          // a selector or the element itself
  if (!el) return;
  const io = new IntersectionObserver((es) => {
    if (es.some((e) => e.isIntersecting)) { io.disconnect(); run(); }
  }, { threshold: 0.25 });
  io.observe(el);
}

// Academy graduates in the first team: each club's share of league minutes played by its own academy's players, a line across
// six seasons (the last one under way), clubs ranked by the last full season; Barça in ink, the others in the second ink
function academyShare(doc) {
  const seasons = ["2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026", "2026-2027"];
  const full = "2025-2026";
  const rows = Object.entries(doc.by_club).filter(([, v]) => v[full]).sort((a, b) => b[1][full].share - a[1][full].share);
  const W = 120, H = 26, top = 0.6;
  const X = (i) => 4 + i * (W - 8) / (seasons.length - 1), Y = (v) => H - 3 - (Math.min(v, top) / top) * (H - 6);
  return `<ol class="share">${rows.map(([club, v]) => {
    const pts = seasons.map((s, i) => v[s] ? [X(i), Y(v[s].share)] : null).filter(Boolean);
    const me = club === "Barcelona";
    const now = v["2026-2027"];
    return `<li class="${me ? "me" : ""}"><span class="sc">${esc(club)}</span>
      <svg viewBox="0 0 ${W} ${H}" class="spark" aria-hidden="true"><polyline points="${pts.map((p) => p.join(",")).join(" ")}"/>${pts.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="${i === pts.length - 1 ? 2.6 : 1.6}"/>`).join("")}</svg>
      <b>${pct(v[full].share)}</b><small>${now ? `${pct(now.share)} so far` : ""}</small></li>`;
  }).join("")}</ol>`;
}

// the squad and who's next: per position, each player a bar from today to the end of his contract (years 2026 to
// 2031), weighted by his minutes this season; a summer signing's contract isn't in the data yet: an open bar, said so;
// next in line on the right, La Masia first, then the market's closest reads
function succession(doc) {
  const Y0 = 2026 + 9.8 / 12, Y1 = 2031.5, X = (y) => `${((Math.min(y, Y1) - Y0) / (Y1 - Y0) * 100).toFixed(1)}%`;
  const maxMin = Math.max(...doc.families.flatMap((f) => f.players.map((p) => p.min_26_27)), 1);
  const axis = [2027, 2028, 2029, 2030, 2031].map((y) => `<span style="left:${X(y + 0.5)}">${y}</span>`).join("");
  return `<div class="succ"><div class="sx"><span></span><div class="axis">${axis}</div><span class="nx">Next in line</span></div>
    ${doc.families.map((f) => `<div class="sr"><span class="sf">${esc(f.role)}</span><div class="lanes">${f.players.map((p) => {
      const w = 0.35 + 0.65 * p.min_26_27 / maxMin;
      const end = p.contract_end ? p.contract_end + 0.5 : null;
      const name = !window.PUBLIC_PAGE && p.tm_id ? `<a href="#/player/${p.tm_id}">${esc(p.name)}</a>` : esc(p.name);
      return `<div class="lane"><i class="${end ? "bar" : "bar open"}" style="width:${end ? X(end) : "28%"};--w:${w.toFixed(2)}"></i>
        <span class="pn">${name} <small>${p.age.toFixed(0)} · ${num(p.min_26_27)} min${end ? ` · to ${p.contract_end}` : " · signed this summer"}</small></span></div>`;
    }).join("")}</div>
      <div class="nl">${f.in_line?.length ? `<span><b>On the bench</b> ${f.in_line.map((p) => `${esc(p.name)} (${p.matchday_squads} squads, ${p.minutes} min)`).join(", ")}</span>` : ""}${f.next_la_masia.length ? `<span><b>La Masia</b> ${f.next_la_masia.map(esc).join(", ")}</span>` : ""}${f.next_market.length ? `<span><b>Market</b> ${f.next_market.map((m) => `${esc(m.name)} (${esc(m.club)})`).join(", ")}</span>` : ""}</div></div>`).join("")}</div>`;
}

function funnelSteps(r) {
  const steps = [["U19", 1], ["B team", r.b_team], ["First-team debut", r.debut], ["10+ first-team matches", r.ten_apps], ["A first-division season by 21", r.first_division_by_21]];
  return `<div class="funnel">${steps.map(([l, v]) => `<div class="step"><span class="bar" style="--w:${Math.max(0.02, v || 0)}"></span><b>${pct(v || 0)}</b><span>${l}</span></div>`).join("")}</div>`;
}

// the next wave's call: already a regular, or the engine's chance of becoming one within three seasons
const nextCall = (w) => w.regular ? `<em class="call-tag">already a regular</em>`
  : w.p_reg3 == null ? "" : `<em class="call-tag"><b>${Math.round(w.p_reg3 * 100)} %</b> to be a regular within three seasons</em>`;
// the season buttons: Xavi's last season and the season under way say so
const seasonLabel = (v, roles) => v === "2023-2024" ? `${seasonShort(v)} · Xavi` : roles.some((r) => r.season === v && r.under_way) ? `${seasonShort(v)}*` : seasonShort(v);
// one line on what's clear this season: the dimensions whose interval excludes zero, biggest first
function nowLine(byDim) {
  const clear = Object.entries(byDim).filter(([, v]) => v.clear && Math.abs(v.shift) >= 0.1).sort((a, b) => Math.abs(b[1].shift) - Math.abs(a[1].shift));
  return clear.length ? `Clear so far: ${clear.map(([k, v]) => `${(DIM_NAME[k] || k).toLowerCase()} ${signed(v.shift)}`).join(", ")}.` : "Nothing clear yet.";
}

async function clubPage(slug) {
  const d = await api(`/api/club/${slug}`);
  return () => {
    setNav("club");
    const s = d.system, p = d.pathway, fit = d.fit, x2f = s.xavi_to_flick;
    const hasCall = p.next_up.some((w) => w.p_reg3 != null && !w.regular);   // calls off the board until the engine earns them
    // two pools, one lens: Europe's young regulars (moved into Barça's game model) and La Masia's U19s (Youth League)
    const pools = { europe: fit, masia: d.prospects };
    const famsOf = (pool) => ["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"].filter((f) => pools[pool]?.by_family[f]);
    const thin = fit ? new Set(fit.thin_spots.map((t) => t.code)) : new Set();
    const fitState = { pool: "europe", fam: fit ? [...fit.thin_spots].sort((a, b) => b.oldest - a.oldest)[0]?.code || famsOf("europe")[0] : null, big: false };
    const roleButtons = () => famsOf(fitState.pool).map((f) => `<button type="button" data-fam="${f}" aria-pressed="${f === fitState.fam}">${FAMILY_NAME[f]}${thin.has(f) ? '<i class="thin" title="thin spot"></i>' : ""}</button>`).join("");
    const pa = d.prospects?.academy;
    const FIT_NOTE = {
      europe: fit ? `Players 23 or younger with 1,200+ league minutes in 25/26. Bar: what Flick's regulars do in the role. Ring: the player at his club now. Dot: the model's read of him in Barça's game model; it learned from ${num(fit.moves_learned)} real moves between teams how a player's game shifts with his new team's, and beat "he stays the same" and "he plays like his new teammates" on moves it never saw. "Closer than": the share of the role's pool whose read sits further from the regulars. A fit, not a forecast of quality: the league beside each name says how strong the football was.` : "",
      masia: pa ? `La Masia's U19s with 360+ Youth League minutes, keepers aside. Dot: his Youth League profile against every player in his role there, pulled toward the average by how few minutes he has (it slides out from that average). Only the ${d.prospects.skills_used.length} skills that repeat from one match to the next in youth football are read; chance quality and scoring positions aren't recorded in youth matches. As a group they sit closer to Flick's roles than ${pct(pa.median_closer_than)} of the pool (95 % ${pct(pa.ci95[0])} to ${pct(pa.ci95[1])}), against ${pct(pa.pool_median)} for random players: a lean, not yet clear with ${pa.players} players. Their U19 team plays the first team's model, so this reads the academy's teaching as much as the players.` : "",
    };
    // thin spots from the squad Flick uses this season: who's in each family, and the oldest
    const thinText = fit ? fit.thin_spots.map((t) => `${FAMILY_NAME[t.code].toLowerCase()} (${t.players?.length ? t.players.join(", ") : `${t.regulars}`}; the oldest ${t.oldest})`).join("; ") : "";
    const seasons = [...new Set(s.roles.map((r) => r.season))].sort();
    const barca = p.funnel.find((r) => r.academy === "Barcelona");
    const clear = Object.entries(x2f.by_dimension).filter(([, v]) => v.clear).map(([k, v]) => `${(DIM_NAME[k] || k).toLowerCase()} ${signed(v.shift)}`);
    main.innerHTML = `
    <a class="back" href="#/boards">${icon("left")}Boards</a>
    <header class="clubhead"><h1 class="display">FC Barcelona</h1>
      <p class="lead">The system first, then who fits it, then the pathway that feeds it. Every figure is standardised within LaLiga or against Europe's academies, and every comparison carries its interval.</p></header>
    <section class="block" aria-labelledby="c-sys">${sign("", "The game model, season by season", "against LaLiga's teams that season · * season under way", "c-sys")}
      ${seasonStrip(s.by_season, s.dimensions)}
      <p class="note">Positional possession every season: Barça keep the ball, pass short and win it back far more than LaLiga's other teams.</p></section>
    <section class="block" aria-labelledby="c-flick">${sign("", "What Flick changed", `${x2f.xavi_matches} matches under Xavi, ${x2f.flick_matches} under Flick · bold = the 95 % interval excludes zero`, "c-flick")}
      <div class="scrollx">${dumbbells(x2f.by_dimension)}</div>
      <p class="note">Clear changes: ${clear.join(", ")}. Hollow: Xavi; filled: Flick, this season's matches included; in units of the spread between LaLiga's teams.</p></section>
    ${s.this_season ? `<section class="block" aria-labelledby="c-now">${sign("", "This season so far", `${s.this_season.this_matches} LaLiga matches to ${s.this_season.through.slice(8, 10)}/${s.this_season.through.slice(5, 7)} against the ${s.this_season.last_matches} of 25/26 · bold = the 95 % interval excludes zero`, "c-now")}
      <div class="scrollx">${dumbbells(s.this_season.by_dimension, "Barça's game model this season against last")}</div>
      <p class="note">${nowLine(s.this_season.by_dimension)} Hollow: 25/26; filled: 26/27 so far. ${s.this_season.this_matches} matches make wide intervals: a first reading, redrawn after every match.</p></section>` : ""}
    <div class="twin">
      <section class="block" aria-labelledby="c-shape">${sign("", "His shape", SRC.shapes, "c-shape")}${shapes(s.flick_formations)}
        <p class="note">The same 4-2-3-1 at Bayern and at Barça. ${SRC.detail}, so his Bayern style can't be measured on the dimensions above: only his shapes.</p></section>
      <section class="block" aria-labelledby="c-like">${sign("", "Who plays like Flick's Barça", "closest game models, 2024/25-2025/26", "c-like")}
        <ol class="likes">${s.plays_like_flick_barca.map((t) => `<li><b>${esc(t.team)}</b> <span class="dim">${seasonShort(t.season)} · ${esc(t.league)}</span><i style="--w:${Math.max(0.08, 1 - t.distance / 3)}"></i></li>`).join("")}</ol></section>
    </div>
    <section class="block" aria-labelledby="c-roles">${sign("", "The roles he asks for", "each regular's closest role, against his line in LaLiga", "c-roles")}
      <div class="kickoff seasonpick" role="group" aria-label="Season">${seasons.map((v) => `<button type="button" data-season="${v}" aria-pressed="${v === seasons.at(-1)}">${seasonLabel(v, s.roles)}</button>`).join("")}</div>
      <div id="sheet">${teamSheet(s.roles, seasons.at(-1))}</div>
      ${s.roles.some((r) => r.under_way) ? `<p class="note">${seasonShort(seasons.at(-1))}: the season under way, read at 450+ minutes instead of 900, so its roles rest on fewer matches.</p>` : ""}
      ${(s.role_changes || []).some((c) => c.changed) ? `<h3 class="sub">Same player, new role: Xavi's last season against Flick's first</h3>
        <ol class="changes">${s.role_changes.filter((c) => c.changed).map((c) => `<li><b>${esc(c.name)}</b><span class="from">${esc(c.xavi)}</span><span class="arrow">→</span><span class="to">${esc(c.flick)}</span></li>`).join("")}</ol>` : ""}
      <p class="note">Roles are read from what each player does and his share of his team's actions. In a side that keeps the ball this much, some carry the system's imprint (full-backs cross less, so they read as "inverted"): the next layer separates the player from the system.</p></section>
    ${d.succession ? `<section class="block" aria-labelledby="c-succ">${sign("", "The squad, and who's next", "each player: today to the end of his contract, weighted by his minutes this season", "c-succ")}
      ${succession(d.succession)}
      <p class="note">Contract ends from the June 2026 snapshot; this summer's signings are open bars until their new contracts are in the data. Next in line: La Masia's U19s closest to Flick's version of the role, then the closest reads among Europe's young players in the big five (both below, in "Who fits").</p></section>` : ""}
    ${fit ? `<section class="block" aria-labelledby="c-fit">${sign("", "Who fits Flick's Barça", "the young players closest to what his regulars do, role by role", "c-fit")}
      <p class="note">Where the squad is thin, from the players Flick has used this season (270+ minutes in LaLiga and the Champions League): ${esc(thinText)}. The role templates below are what his 25/26 regulars did, the last full season.</p>
      <div class="fitbar">${pools.masia ? `<div class="kickoff poolpick" role="group" aria-label="Players"><button type="button" data-pool="europe" aria-pressed="true">Europe's U23s</button><button type="button" data-pool="masia" aria-pressed="false">La Masia's U19s</button></div>` : ""}
        <div class="kickoff rolepick" role="group" aria-label="Role">${roleButtons()}</div>
        <div class="kickoff levelpick" role="group" aria-label="Level"><button type="button" data-big="0" aria-pressed="true">Every level</button><button type="button" data-big="1" aria-pressed="false">Big-five leagues</button></div></div>
      <div id="fit">${fitBoard(fit.by_family[fitState.fam], false)}</div>
      <p class="note" id="fitnote">${FIT_NOTE.europe}</p></section>` : ""}
    ${d.academy_share ? `<section class="block" aria-labelledby="c-share">${sign("", "Academy graduates in the first team", "share of league minutes played by each club's own academy graduates · 25/26, then 26/27 so far", "c-share")}
      ${academyShare(d.academy_share)}
      <p class="note">This season, La Masia's players in Flick's league minutes: ${d.academy_share.barca_academy_26_27.filter((x) => x.minutes > 0).map((x) => `${esc(x.name)} ${num(x.minutes)}`).join(", ")}. An academy player here: a youth-team stint begun before 19 or a B-team stint begun before 18, and no senior football at another club before he arrived (a teenager bought from a first team doesn't count). The lines run 21/22 to 26/27, the last point the season under way.</p></section>` : ""}
    <section class="block" aria-labelledby="c-path">${sign("", "La Masia's pathway", `${esc(p.cohort)} · ${barca.u19_players} at Barça`, "c-path")}
      ${funnelSteps(barca)}
      <div class="scrollx">${academies(p.funnel)}</div>
      <p class="note">Each academy's U19 players, followed to 2025/26. A first-division season by 21: 900+ minutes in one of 31 first divisions. U19 coverage varies between academies, hence the intervals.</p></section>
    <div class="twin">
      <section class="block" aria-labelledby="c-peaks">${sign("", "The peaks", "most quality minutes by 23", "c-peaks")}
        <ol class="peaks">${p.la_masia_graduates.slice(0, 8).map((g) => `<li><b>${esc(g.name)}</b><span class="num">${num(g.quality_minutes_by_23)}</span><small>${g.born}${g.rank_at_age ? ` · ${esc(g.rank_at_age)}` : ""}${g.debut_at_barca ? "" : " · career made elsewhere"}</small></li>`).join("")}</ol></section>
      <section class="block" aria-labelledby="c-next">${sign("", "The next wave", `born 2006 on · first-team matches, this season's minutes${hasCall ? ", the engine's call" : ""}`, "c-next")}
        <ol class="peaks">${p.next_up.slice(0, 10).map((w) => `<li><b>${esc(w.name)}</b><span class="num">${w.first_team_apps}</span><small>${w.born} · first-team matches · Barça Atlètic ${w.atletic_apps}${w.minutes_26_27 ? ` · ${num(w.minutes_26_27)} min for Flick in 26/27` : ""}${w.club_now && w.club_now !== "Barcelona" ? ` · now ${esc(w.club_now)}` : ""}${w.rank_at_age ? ` · ${esc(w.rank_at_age)}` : ""}</small>${nextCall(w)}</li>`).join("")}</ol>
        ${hasCall ? `<p class="note">The call: his chance of being a regular (half his club's league minutes) in one of 31 first divisions within three seasons, from what he has played so far. It reads public match data only, so it knows nothing of training, growth or medical records; the last section shows how it compares with market value on seasons it never saw.</p>`
          : `<p class="note">No forecast here: from public match data alone, the model doesn't beat market value, so the board leaves it out. The last section gives the figures and what would close the gap.</p>`}</section>
    </div>
    ${d.dial ? `<section class="block" aria-labelledby="c-dial">${sign("", "What Barça's own data would add", "what public data reads today, the gap that's measured, what closes it", "c-dial")}
      <div class="dial"><div class="dh">The question</div><div class="dh">Public data, today</div><div class="dh">With Barça's data</div>
        ${d.dial.rows.map((r) => `<div class="dq">${esc(r.what)}</div><div class="dn">${esc(r.now)}<small>${esc(r.gap)}</small></div><div class="dc">${esc(r.club)}</div>`).join("")}</div>
      <p class="note">The figures are the tests' own results (seasons the models never saw, or a season's two halves); the right-hand column is what a club's own data would let the same tests check.</p></section>` : ""}
    <p class="note">${esc(s.data_note[0].toUpperCase() + s.data_note.slice(1))}.</p>`;
    const paintFit = () => { $("#fit").innerHTML = fitBoard(pools[fitState.pool].by_family[fitState.fam], fitState.pool === "europe" && fitState.big); slideFit(); };
    // role buttons are redrawn when the pool changes (La Masia has no reading for some roles), so one listener on the row
    $(".rolepick")?.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      $$(".rolepick button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      fitState.fam = b.dataset.fam; paintFit();
    });
    $$(".poolpick button").forEach((b) => b.addEventListener("click", () => {
      $$(".poolpick button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      fitState.pool = b.dataset.pool;
      if (!pools[fitState.pool].by_family[fitState.fam]) fitState.fam = famsOf(fitState.pool)[0];
      $(".rolepick").innerHTML = roleButtons();
      $(".levelpick").style.display = fitState.pool === "europe" ? "" : "none";
      $("#fitnote").textContent = FIT_NOTE[fitState.pool];
      paintFit();
    }));
    $$(".levelpick button").forEach((b) => b.addEventListener("click", () => {
      $$(".levelpick button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      fitState.big = b.dataset.big === "1"; paintFit();
    }));
    $$(".seasonpick button").forEach((b) => b.addEventListener("click", () => {
      $$(".seasonpick button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      $("#sheet").innerHTML = teamSheet(s.roles, b.dataset.season);
      if (motion()) gsap.from("#sheet .pl", { y: 8, opacity: 0, duration: 0.35, ease: "expo.out", stagger: 0.025 });
    }));
    return () => {
      if (!motion()) return;
      // every part waits in its start state and moves when it first comes into view: the strip draws itself season by
      // season, the shifts slide from Xavi to Flick, the closest teams line up, the dots travel to their read at Barça,
      // the funnel fills step by step
      const bars = $$(".zgrid .zc i");
      gsap.set(bars, { scaleX: 0, transformOrigin: "50% 50%" });
      onView(".zgrid", () => gsap.to(bars, { scaleX: 1, duration: 0.6, ease: "expo.out", stagger: { each: 0.004, from: "start" } }));
      // each before/after chart (Xavi to Flick, last season to this one) slides when it comes into view
      $$("svg.dumb:not(.acad)").forEach((svg) => {
        const shifts = $$(".db", svg).map((g) => ({ f: $(".dbf", g), line: $(".dbl", g), x0: +$(".dbx", g).getAttribute("cx"), x1: +$(".dbf", g).getAttribute("cx") }));
        shifts.forEach(({ f, line, x0 }) => { gsap.set(f, { attr: { cx: x0 } }); gsap.set(line, { attr: { x2: x0 } }); });
        onView(svg, () => shifts.forEach(({ f, line, x1 }, i) => {
          gsap.to(f, { attr: { cx: x1 }, duration: 0.8, ease: "expo.out", delay: 0.1 + i * 0.05 });
          gsap.to(line, { attr: { x2: x1 }, duration: 0.8, ease: "expo.out", delay: 0.1 + i * 0.05 });
        }));
      });
      gsap.set(".likes i", { scaleX: 0, transformOrigin: "0 50%" });
      onView(".likes", () => gsap.to(".likes i", { scaleX: 1, duration: 0.7, ease: "expo.out", stagger: 0.06 }));
      $$("#fit .ft .at").forEach((el) => gsap.set(el, { left: el.dataset.from }));
      onView("#fit", slideFit);
      gsap.set(".funnel .bar", { scaleX: 0, transformOrigin: "0 50%" });
      onView(".funnel", () => gsap.to(".funnel .bar", { scaleX: 1, duration: 0.7, ease: "expo.out", stagger: 0.08 }));
    };
  };
}

// The team page (#/team/<id>): any club whose game model is measured, read the way the Barça board reads Barça.
// The season strip and the team sheet are the board's own; the five game models are labels, the vector is the reading.
async function teamPage(id) {
  const d = await api(`/api/team/${id}`);
  return () => {
    setNav("team");
    const last = d.seasons.at(-1), seasons = [...new Set(d.roles.map((r) => r.season))].sort();
    const runs = [];                                     // the game models in runs: "Positional possession, 21/22-25/26"
    d.seasons.forEach((s) => { const r = runs.at(-1); if (r && r.a === s.archetype) r.to = s.season; else runs.push({ a: s.archetype, from: s.season, to: s.season }); });
    main.innerHTML = `
    <a class="back" href="javascript:history.back()">${icon("left")}Back</a>
    <header class="clubhead"><h1 class="display">${esc(d.team)}</h1>
      <p class="lead">${esc(d.league)} · its game model season by season against its league, the teams that play most like it, its coaches and the roles of its regulars.</p></header>
    <section class="block" aria-labelledby="t-sys">${sign("A", "The game model, season by season", "against its league that season · * fewer than 20 matches", "t-sys")}
      <div class="scrollx">${seasonStrip(d.seasons, d.dimensions, null, `${d.team}'s game model, season by season`, "its league")}</div>
      <p class="note">Closest of the five game models: ${runs.map((r) => `${esc(r.a)} (${seasonShort(r.from)}${r.to !== r.from ? `-${seasonShort(r.to)}` : ""})`).join(", ")}. The label is a shorthand; the numbers are the reading.</p></section>
    <div class="twin">
      <section class="block" aria-labelledby="t-like">${sign("B", "Who plays like them", `first divisions, full seasons, the closest game models to its last full one`, "t-like")}
        <ol class="likes">${d.plays_like.map((t) => `<li><b><a href="#/team/${t.team_id}">${esc(t.team)}</a></b> <span class="dim">${seasonShort(t.season)} · ${esc(t.league)}</span><i style="--w:${Math.max(0.08, 1 - t.distance / 3)}"></i></li>`).join("")}</ol></section>
      <section class="block" aria-labelledby="t-coach">${sign("C", "Its coaches", "the matches we hold, 2021/22 on", "t-coach")}
        ${d.coaches.length ? `<ol class="peaks">${d.coaches.map((c) => `<li><b><a href="#/coach/${encodeURIComponent(c.manager)}">${esc(c.manager)}</a></b><span class="num">${c.matches}</span><small>${c.first} to ${c.last} · matches</small></li>`).join("")}</ol>` : '<p class="none">No coach linked for these seasons.</p>'}</section>
    </div>
    ${seasons.length ? `<section class="block" aria-labelledby="t-roles">${sign("D", "The roles of its regulars", "each player's closest role, 900+ league minutes", "t-roles")}
      <div class="kickoff seasonpick" role="group" aria-label="Season">${seasons.map((v, i) => `<button type="button" data-season="${v}" aria-pressed="${i === seasons.length - 1}">${seasonShort(v)}</button>`).join("")}</div>
      <div id="sheet">${teamSheet(d.roles, seasons.at(-1), d.league)}</div></section>` : ""}`;
    $$(".seasonpick button").forEach((b) => b.addEventListener("click", () => {
      $$(".seasonpick button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      $("#sheet").innerHTML = teamSheet(d.roles, b.dataset.season, d.league);
      if (motion()) gsap.from("#sheet .pl", { y: 8, opacity: 0, duration: 0.35, ease: "expo.out", stagger: 0.025 });
    }));
    return () => {
      if (!motion()) return;
      gsap.from(".zgrid .zc i", { scaleX: 0, transformOrigin: "50% 50%", duration: 0.6, ease: "expo.out", stagger: { each: 0.004, from: "start" } });
      gsap.set(".likes i", { scaleX: 0, transformOrigin: "0 50%" });
      onView(".likes", () => gsap.to(".likes i", { scaleX: 1, duration: 0.7, ease: "expo.out", stagger: 0.06 }));
    };
  };
}

// The coach page (#/coach/<name>): T2's reading of one coach. The style each of his teams played under him (league-
// relative), his fingerprint on the eight dimensions coaches carry from club to club (width, dribbling and box presence
// come with the players), and each move: where the new club was before him, where it went under him, against where his
// previous club was. Tracks as on the fit board: bar = his previous club, ring = the new club before him, dot = under him.
const CTR_LO = -2.5, CTR_HI = 2.5;
const ctrX = (v) => `${((Math.min(CTR_HI, Math.max(CTR_LO, v)) - CTR_LO) / (CTR_HI - CTR_LO) * 100).toFixed(1)}%`;
async function coachPage(name) {
  const d = await api(`/api/coach/${encodeURIComponent(decodeURIComponent(name))}`);
  return () => {
    setNav("coach");
    const carried = new Set(d.carried);
    const total = d.spells.reduce((n, s) => n + s.matches, 0);
    const strip = `<div class="zgrid" style="--n:${d.spells.length}" role="table" aria-label="${esc(d.manager)}'s teams' game models, spell by spell">
      <div class="zh"></div>${d.spells.map((s) => `<div class="zh" title="${s.first} to ${s.last}">${s.team_id ? `<a href="#/team/${s.team_id}">${esc(s.team)}</a>` : esc(s.team)}<small>${s.first.slice(2, 4)}-${s.last.slice(2, 4)} · ${s.matches}</small></div>`).join("")}
      ${d.dimensions.map((dim) => `<div class="zl${carried.has(dim) ? "" : " loose"}">${DIM_NAME[dim] || dim}</div>${d.spells.map((s) => {
        const v = s[dim] ?? 0, w = Math.min(1, Math.abs(v) / 3.5) * 50;
        return `<div class="zc"><i style="left:${v < 0 ? 50 - w : 50}%;width:${w}%"></i><b>${signed(v)}</b></div>`;
      }).join("")}`).join("")}</div>`;
    const moves = d.moves.map((m) => `<div class="move"><h3>${esc(m.from)} → ${esc(m.to)} <small>${m.arrived} · ${m.matches_after} matches after</small></h3>
      ${Object.entries(m.dims).map(([dim, v]) => {
        const toward = (v.under_him - v.before) * Math.sign(v.previous - v.before);
        return `<div class="pr"><span class="pr-l">${DIM_NAME[dim] || dim}</span><span class="pr-t"><span class="tpl" style="left:${ctrX(v.previous)}"></span><i class="nw" style="left:${ctrX(v.before)}"></i><i class="pr-d" style="left:${ctrX(v.under_him)}"></i></span><b class="${toward > 0.15 ? "tw" : ""}">${toward > 0.15 ? "toward" : toward < -0.15 ? "away" : "held"}</b></div>`;
      }).join("")}</div>`).join("");
    main.innerHTML = `
    <a class="back" href="javascript:history.back()">${icon("left")}Back</a>
    <header class="clubhead"><h1 class="display">${esc(d.manager)}</h1>
      <p class="lead">${d.spells.length} spell${d.spells.length > 1 ? "s" : ""} and ${num(total)} matches in the data we hold (2021/22 on). Coaches carry eight of the eleven dimensions from club to club; width, dribbling and box presence come with the players, so they're greyed here.</p></header>
    <section class="block" aria-labelledby="k-sp">${sign("A", "His teams, spell by spell", "each team's game model under him, against its league", "k-sp")}
      <div class="scrollx">${strip}</div></section>
    <section class="block" aria-labelledby="k-fp">${sign("B", "His fingerprint", "the dimensions coaches carry, weighted by matches", "k-fp")}
      ${d.fingerprint ? `<div class="howplays one">${Object.entries(d.fingerprint).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1])).map(([dim, v]) => `<div class="pr"><span class="pr-l">${DIM_NAME[dim] || dim}${d.carry_effects[dim] != null ? `<small class="d-expert">a new club moves ${d.carry_effects[dim].toFixed(2)} of the way toward the coach's last (T2, 220 moves)</small>` : ""}</span><span class="pr-t"><i class="pr-m"></i><i class="pr-d" style="left:${ctrX(v)}"></i></span><b>${signed(v)}</b></div>`).join("")}</div>
        <p class="note">Across his spells, in units of the spread between a league's teams. On 220 coach moves, a new club's style moved toward the coach's previous club on each of these eight.</p>`
        : '<p class="none">One spell in the data we hold: that is his team\'s style, not yet what he carries. A second club will tell.</p>'}</section>
    ${d.moves.length ? `<section class="block" aria-labelledby="k-mv">${sign("C", "What his arrival changed", "bar: his previous club · ring: the new club before him · dot: under him", "k-mv")}
      <div class="moves">${moves}</div>
      <p class="note">"Toward": under him the new club moved toward where his previous club was by more than 0.15 of the spread between a league's teams. Each dimension is measured against the club's own league, so a move between clubs of very different strength (a side fighting relegation, then a champion) mostly shows that gap: a dominant side keeps the ball whoever coaches it. The eight-of-eleven finding holds across 220 moves, not in every single one.</p></section>` : ""}`;
    return () => {
      if (!motion()) return;
      gsap.from(".zgrid .zc i", { scaleX: 0, transformOrigin: "50% 50%", duration: 0.6, ease: "expo.out", stagger: { each: 0.004 } });
      $$(".move .pr-d").forEach((el) => { const to = el.style.left, from = el.parentElement.querySelector(".nw")?.style.left; if (from) gsap.fromTo(el, { left: from }, { left: to, duration: 0.8, ease: "expo.out", delay: 0.2 }); });
    };
  };
}

// Teams (Clubs, second page): every club whose game model is measured, by league, with its latest game model; a search
async function teamsIndex() {
  const d = await api("/api/teams");
  return () => {
    setNav("teams");
    const by = {};
    d.teams.forEach((t) => (by[t.league_id] ||= []).push(t));          // by id: Germany's and Austria's Bundesliga share a name
    // first divisions first, then the rest (second tiers, reserve and youth leagues), each by size
    const leagues = Object.keys(by).sort((a, b) => (by[b][0].first - by[a][0].first) || (by[b].length - by[a].length));
    main.innerHTML = `<header class="clubhead"><h1 class="display">Clubs &amp; Coaches</h1>
      <p class="lead">${num(d.teams.length)} clubs whose game model is measured, each read against its own league, season by season. Pick one for its game model, its coaches and the roles of its regulars.</p></header>
      <input class="search" id="tq" type="search" placeholder="Find a club" aria-label="Find a club" autocomplete="off">
      <div class="idx" id="tl">${leagues.map((lg) => `<section class="idx-g"><h2>${esc(by[lg][0].league)}<small>${esc(by[lg][0].country)}</small></h2><ul>${by[lg].map((t) => `<li data-q="${esc((t.team + " " + t.league + " " + t.country).toLowerCase())}"><a href="#/team/${t.team_id}">${esc(t.team)}</a><small>${esc(t.archetype || "")} · ${seasonShort(t.season)}</small></li>`).join("")}</ul></section>`).join("")}</div>`;
    const q = $("#tq");
    q.addEventListener("input", () => {
      const v = q.value.trim().toLowerCase();
      $$("#tl li").forEach((li) => { li.hidden = v && !li.dataset.q.includes(v); });
      $$("#tl .idx-g").forEach((g) => { g.hidden = !$$("li", g).some((li) => !li.hidden); });
    });
    q.focus({ preventScroll: true });
  };
}

// Coaches (Clubs, third page): every coach the desk links to its matches, his clubs and how many matches it rests on
async function coachesIndex() {
  const d = await api("/api/coaches");
  return () => {
    setNav("coaches");
    main.innerHTML = `<header class="clubhead"><h1 class="display">Coaches</h1>
      <p class="lead">${num(d.coaches.length)} coaches, linked to the matches we hold (2021/22 on). A fingerprint appears from a second club on: that's when what he carries can be told from what the club already was.</p></header>
      <input class="search" id="cq" type="search" placeholder="Find a coach or a club" aria-label="Find a coach or a club" autocomplete="off">
      <ul class="idx-flat" id="cl">${d.coaches.map((c) => `<li data-q="${esc((c.manager + " " + c.teams.join(" ")).toLowerCase())}"><a href="#/coach/${encodeURIComponent(c.manager)}">${esc(c.manager)}</a><small>${c.teams.map(esc).join(" → ")} · ${num(c.matches)} matches${c.spells > 1 ? ` · ${c.spells} clubs` : ""}</small></li>`).join("")}</ul>`;
    const q = $("#cq");
    q.addEventListener("input", () => { const v = q.value.trim().toLowerCase(); $$("#cl li").forEach((li) => { li.hidden = v && !li.dataset.q.includes(v); }); });
    q.focus({ preventScroll: true });
  };
}
