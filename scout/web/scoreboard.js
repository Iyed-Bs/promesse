// The Scoreboard (#/method), rewritten: how Promesse is tested, where it stands, and how it
// grew. Answer first, proof below, every sentence in plain words with the depth in its specifics. Seven blocks:
//   1. where it stands: right picks out of 100 pairs of young players (the same unit as the Ground's screen);
//   2. how the vision broadened: the gap to market value over steps of understanding, never dates;
//   3. who ranks young players best: the ladder, then three plain questions answered from live figures;
//   4. two kinds of reading: the full reading and the projection (the two stands);
//   5. the tests: each module's question, how it was tested, what it found, its status;
//   6. how it grew: the pivotal milestones, a short devlog;
//   7. planned updates: what the next update adds, and the data still coming in.
// The engine's figures come live from /api/scoreboard (a rebuild shows by itself); the words are kept in
// scout/scoreboard.json. Generated wording follows the figures: no verdict here is written in advance.
// Uses app.js's helpers ($, $$, esc, num, icon, motion, api, sign, setNav, showTip, hideTip) and the desk's tokens.

(() => {   // a scope of its own: app.js and club.js already hold names like signed() at the top level
// ranking skill as right picks out of 100 pairs (an AUC times 100); differences in the same unit
const picks = (auc, dp = 1) => (auc == null ? "—" : (auc * 100).toFixed(dp));
const dpicks = (v, dp = 1) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(dp)}`);
const season = (y) => `${String(y).slice(2)}/${String(y + 1).slice(2)}`;
// the verdict follows the figures: the whole 95 % range above zero "ahead", the average above zero
// "edge" (just ahead), the range below zero "behind", otherwise "level". The engine's test counts as passed from "edge" up.
const verdict = (lo, hi, mean) => (lo > 0 ? "ahead" : hi < 0 ? "behind" : mean > 0 ? "edge" : "level");
// a score with one decimal when whole numbers would hide the difference (77.9 and 77.5 both round to 78)
const score2 = (a, b) => (Math.round(a * 100) === Math.round(b * 100) ? [picks(a), picks(b)] : [picks(a, 0), picks(b, 0)]);

// run fn once, the first time el comes into view (immediately when motion is off: nothing waits to be revealed)
function whenSeen(el, fn) {
  if (!el) return;
  if (!motion() || !("IntersectionObserver" in window)) return fn(false);
  const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { io.disconnect(); fn(true); } }, { threshold: 0.25 });
  io.observe(el);
}

// ── 1. where it stands ────────────────────────────────────────────────────────────────────────────────────────────
function now(d) {
  const eng = d.rungs.find((r) => r.kind === "engine"), mkt = d.rungs.find((r) => r.kind === "market");
  const g = d.gate || {}, [lo, hi] = g.ci95 || [null, null], v = verdict(lo, hi, g.mean);
  const [us, them] = score2(eng?.auc, mkt?.auc);
  const line = { ahead: "Ahead of market value, from match records alone", edge: "Just ahead of market value, from match records alone",
    level: "Level with market value, from match records alone",
    behind: `${dpicks(-g.mean)} right picks in 100 behind market value, from match records alone` }[v];
  // the closing sentence is the author's voice (proud and humble,); the figures in it are live
  const close = { ahead: "The whole range sits above zero: from public match records, Promesse reads young players better than the market's own valuation. Honestly, I'm proud of that, and the next seasons will keep testing it.",
    edge: `From public match records alone, Promesse already picks as well as the market's own valuation, and a little better on average. Honestly, I'm glad to have reached that point; the margin is thin, and widening it is the next job.`,
    level: "From public match records alone, Promesse picks as well as the market's own valuation. Getting ahead of it is the next job.",
    behind: "The market's own valuation still reads these players better; closing that gap is the next job." }[v];
  return `<section class="sb-now" aria-labelledby="sb-now-h">
    <div class="sb-panel">
      <h2 id="sb-now-h" class="sb-q">Who becomes a regular?<small>Right picks out of 100 pairs of young players</small></h2>
      <div class="sb-side us"><span class="sb-team">Promesse</span><span class="sb-score" data-to="${us}">${us}</span></div>
      <div class="sb-side flip"><span class="sb-team">A coin flip</span><span class="sb-score">50</span></div>
      <div class="sb-side them"><span class="sb-team">Market value</span><span class="sb-score" data-to="${them}">${them}</span></div>
      <p class="sb-verdict" data-state="${v}">${line}</p>
    </div>
    <p class="sb-caption">Tested on ${num(d.n_test)} under-21s from the ${esc(d.test || "2021-2022")} season, which the engine never learned from.
      Each pair is one player who became a regular in a first division within three seasons and one who didn't; the score is how
      often each side puts the right one first. Promesse ${picks(eng?.auc)}, market value ${picks(mkt?.auc)}. ${close}
      <span class="d-expert">On resampled players, the difference runs from ${dpicks(lo)} to ${dpicks(hi)} picks in 100 (95 % of resamples).</span></p>
  </section>`;
}

// ── 2. how the vision broadened: one step per deeper reading, the gap to market value after each ─────────────────
function vision(d) {
  const steps = d.gap_history || [], add = d.adds_to_market || {};
  const W = 880, H = 300, L = 64, R = 40, T = 30, B = 34, lo = -0.07, hi = 0.045, n = steps.length;
  const X = (i) => L + ((i + 0.5) / n) * (W - L - R);
  const Y = (v) => T + ((hi - v) / (hi - lo)) * (H - T - B);
  const grid = [-0.06, -0.04, -0.02, 0, 0.02, 0.04].map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/>
    <text class="ax" x="${L - 10}" y="${Y(v) + 4}" text-anchor="end">${v === 0 ? "0" : dpicks(v, 0)}</text>`).join("");
  const done = steps.filter((s) => !s.future);
  const path = done.map((s, i) => `${i ? "L" : "M"}${X(i)},${Y(s.gap)}`).join("");
  const ahead = steps.findIndex((s) => s.future);
  const dash = ahead > 0 ? `<path class="trend future" d="M${X(ahead - 1)},${Y(steps[ahead - 1].gap)} L${X(ahead)},${Y(0)}"/>` : "";
  const ref = add.mean != null ? `<line class="ref" x1="${L}" x2="${W - R}" y1="${Y(add.mean)}" y2="${Y(add.mean)}"/>
    <text class="reflab" x="${W - R}" y="${Y(add.mean) - 8}" text-anchor="end">with every rating added, market value included: ${dpicks(add.mean)}</text>` : "";
  const marks = steps.map((s, i) => s.future
    ? `<g class="pt future" data-i="${i}"><circle class="dot" cx="${X(i)}" cy="${Y(0)}" r="9"/><text class="q" x="${X(i)}" y="${Y(0) + 5}" text-anchor="middle">?</text>
        <text class="stepn" x="${X(i)}" y="${H - 8}" text-anchor="middle">${i + 1}</text></g>`
    : `<g class="pt" data-i="${i}" data-tip="${esc(`<b>${s.step}</b>${dpicks(s.gap)} right picks in 100 against market value (range ${dpicks(s.lo)} to ${dpicks(s.hi)})`)}">
        <rect class="hit" x="${X(i) - 40}" y="${T}" width="80" height="${H - T - B}"/>
        <line class="ci" x1="${X(i)}" x2="${X(i)}" y1="${Y(s.lo)}" y2="${Y(s.hi)}"/>
        <circle class="dot" cx="${X(i)}" cy="${Y(s.gap)}" r="7"/>
        <text class="val" x="${X(i) + 16}" y="${Y(s.gap) + 24}">${dpicks(s.gap)}</text>
        <text class="stepn" x="${X(i)}" y="${H - 8}" text-anchor="middle">${i + 1}</text></g>`).join("");
  // one idea per slide: the step, what it added, what it did to the gap; the chart's matching point lights up (the "step" event)
  const slides = steps.map((s, i) => ({ title: s.step, html: `<p class="step-kicker">Step ${i + 1}</p><h3>${esc(s.step)}</h3><p>${esc(s.idea)}</p>
      <p class="step-res">${s.future ? "Summer 2027" : `${dpicks(s.gap)} right picks in 100 against market value <span>(plausible range ${dpicks(s.lo)} to ${dpicks(s.hi)})</span>`}</p>` }));
  return `<figure class="sb-vision" data-active="0"><div class="fig-scroll">
      <svg data-fit viewBox="0 0 ${W} ${H}" role="img" aria-label="The gap to market value after each step: ${done.map((s) => `${s.step}, ${dpicks(s.gap)}`).join("; ")}; the next step is a season not yet played">
        ${grid}<line class="zero" x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}"/>
        <text class="zlab" x="${L + 6}" y="${Y(0) - 8}">level with market value</text>${ref}
        <path class="trend" d="${path}"/>${dash}${marks}</svg></div>
    </figure>
    ${UI.stepper({ label: "How the vision broadened, step by step", slides, cls: "step-vision" })}`;
}

// ── 3. who ranks young players best: the ladder in right picks, then three plain questions ─────────────────────────
const RUNG = { floor: "A coin flip", market: "Market value", engine: "Promesse", "engine-alt": "Promesse before the extra seasons",
  ablation: "Promesse with every rating added (measured, never shipped)" };
const rungName = (r) => RUNG[r.kind] || (r.name === "Every rater together" ? "Every rating together" : r.name === "EA ratings" ? "EA's game ratings" : r.name);
function ladder(d) {
  const rows = d.rungs, W = 880, rowH = 48, L = 330, R = 70, T = 34, H = T + rows.length * rowH + 28, lo = 0.5, hi = 0.85;
  const X = (v) => L + ((v - lo) / (hi - lo)) * (W - L - R);
  const mkt = rows.find((r) => r.kind === "market");
  const ticks = [0.5, 0.6, 0.7, 0.8].map((v) => `<line class="grid" x1="${X(v)}" x2="${X(v)}" y1="${T - 6}" y2="${H - 24}"/>
    <text class="ax" x="${X(v)}" y="${H - 6}" text-anchor="middle">${picks(v, 0)}</text>`).join("");
  const marks = rows.map((r, i) => { const y = T + i * rowH + rowH / 2;
    return `<g class="rung k-${r.kind}" data-tip="${esc(`<b>${rungName(r)}</b>${picks(r.auc)} right picks in 100`)}">
      <rect class="hit" x="0" y="${y - rowH / 2}" width="${W}" height="${rowH}"/>
      <text class="name" data-wrap="${L - 36}" x="${L - 16}" y="${y + 5}" text-anchor="end">${esc(rungName(r))}</text>
      <line class="stem" x1="${X(lo)}" x2="${X(r.auc)}" y1="${y}" y2="${y}"/>
      <circle class="head" cx="${X(r.auc)}" cy="${y}" r="${r.kind === "engine" ? 8 : 6.5}"/>
      <text class="val" x="${X(r.auc) + 14}" y="${y + 5}">${picks(r.auc)}</text></g>`; }).join("");
  return `<figure class="sb-ladder"><div class="fig-scroll">
    <svg data-fit viewBox="0 0 ${W} ${H}" role="img" aria-label="Right picks out of 100 on the test season: ${rows.map((r) => `${rungName(r)} ${picks(r.auc)}`).join("; ")}">
      ${ticks}${mkt ? `<line class="bar" x1="${X(mkt.auc)}" x2="${X(mkt.auc)}" y1="${T - 16}" y2="${H - 24}"/>
      <text class="barlab" x="${X(mkt.auc)}" y="${T - 20}" text-anchor="middle">the market's own valuation</text>` : ""}${marks}</svg></div></figure>`;
}

function questions(d) {
  const eng = d.rungs.find((r) => r.kind === "engine"), mkt = d.rungs.find((r) => r.kind === "market");
  const alt = d.rungs.find((r) => r.kind === "engine-alt"), add = d.adds_to_market || {}, [alo, ahi] = add.ci95 || [];
  const e = eng?.ece, m = mkt?.ece;
  const calib = e == null ? "" : e < 0.01 ? "Yes, to within a point." : e < 0.03 ? "Mostly." : "Not yet.";
  const algo = alt && d.engine_v1 != null ? (alt.auc - d.engine_v1) : null, info = alt ? (eng.auc - alt.auc) : null;
  const which = algo == null ? "" : info > algo ? "The information." : "The algorithm.";
  const sees = alo > 0 ? "Yes." : "Not clearly.";
  return `<div class="sb-qs">
    <article><h3>When Promesse says 20 %, does it happen about 20 % of the time?</h3>
      <p><b>${calib}</b> Its percentages are off by ${(e * 100).toFixed(1)} points on average. Market value, turned into percentages the same way, is off by ${(m * 100).toFixed(1)}.</p></article>
    <article><h3>Does Promesse see something the market misses?</h3>
      <p><b>${sees}</b> Put Promesse's evidence together with every rating, market value included, and it ranks ${dpicks(add.mean)} picks in 100 better than market value alone (plausible range ${dpicks(alo)} to ${dpicks(ahi)}). Public match records hold something the price leaves out.</p></article>
    <article><h3>Was the progress the algorithm or the information?</h3>
      <p><b>${which}</b> Same information, a different algorithm: ${picks(d.engine_v1)} to ${picks(alt?.auc)}. Same algorithm, eight more seasons of match stats: ${picks(alt?.auc)} to ${picks(eng?.auc)}.</p></article>
  </div>`;
}

// ── 4. two kinds of reading: a side section of a two-tier stand, the full reading above the projections ─────────────
function standsSVG(s) {
  // side section, pitch on the right. The lower tier: 9 shallow rows (run 28, rise 13) from the pitch back to the rear
  // wall. The upper tier: 6 steeper rows (run 30, rise 18) that overhang the lower one, under a cantilever roof hung
  // from a mast on the rear wall. One seat per row in section: filled upstairs (read in full), dashed downstairs
  // (projected). A faint sightline from the top row shows the overhang doesn't hide the touchline.
  const G = 322;
  const tier = (fx, fy, rows, run, rise) => {
    let p = `M${fx},${fy}`, seats = [];
    for (let r = 0; r < rows; r++) {
      const x = fx - run * r, y = fy - rise * r;
      p += ` L${x - run},${y} L${x - run},${y - rise}`;
      seats.push([x - run / 2, y]);
    }
    return { p, seats, back: [fx - run * rows, fy - rise * rows] };
  };
  const lo = tier(528, 300, 9, 28, 13), up = tier(448, 168, 6, 30, 18);
  const seat = (cls, [cx, y], r) => `<rect class="seat ${cls}" data-row="${r}" x="${(cx - 6).toFixed(1)}" y="${(y - 9).toFixed(1)}" width="12" height="9" rx="2"/>`;
  return `<svg class="stands-svg" viewBox="0 0 700 340" role="img" aria-label="A two-tier stand: the upper tier, the full reading, holds ${num(s.deep)} players; the lower tier, the projection, holds everyone else">
    <line class="sight" x1="${up.seats[5][0]}" y1="${up.seats[5][1] - 12}" x2="560" y2="${G - 4}"/>
    <path class="concrete" d="M528,${G} L528,300 ${lo.p.slice(lo.p.indexOf("L"))} L${lo.back[0]},${G} Z"/>
    <path class="concrete upper" d="M448,186 L448,168 ${up.p.slice(up.p.indexOf("L"))} L${up.back[0] - 14},${up.back[1]} L${up.back[0] - 14},204 Z"/>
    <rect class="wall" x="${up.back[0] - 30}" y="${up.back[1] - 22}" width="18" height="${G - up.back[1] + 22}"/>
    <path class="roof" d="M${up.back[0] - 34},${up.back[1] - 20} L506,20 L508,28 L${up.back[0] - 32},${up.back[1] - 10} Z"/>
    <line class="mast" x1="${up.back[0] - 21}" y1="6" x2="${up.back[0] - 21}" y2="${up.back[1] - 18}"/><line class="stay" x1="${up.back[0] - 21}" y1="6" x2="500" y2="22"/>
    <rect class="pitch" x="532" y="${G - 4}" width="168" height="8" rx="1"/><line class="touch" x1="548" x2="548" y1="${G - 4}" y2="${G + 4}"/>
    <line class="groundline" x1="0" x2="700" y1="${G + 4}" y2="${G + 4}"/>
    ${lo.seats.map((p, r) => seat("proj", p, r)).join("")}${up.seats.map((p, r) => seat("deep", p, r)).join("")}
  </svg>`;
}

// ── 5. the tests: each module's question, how it was tested, what it found, in plain words from the live figures ────
const nums = (t) => (String(t || "").match(/-?\d[\d,.]*/g) || []).map((x) => x.replace(/,/g, ""));
function plainTests(d) {
  const g = d.gate || {}, [lo, hi] = g.ci95 || [], eng = d.rungs.find((r) => r.kind === "engine"), mkt = d.rungs.find((r) => r.kind === "market");
  const pv = Object.values(d.projection || {}).filter((v) => v != null);
  const pvOk = pv.length && pv.every((v) => v >= 0.77 && v <= 0.83);
  const P = {
    "Team strength": (r) => { const [a, b] = nums(r.result); return ["How strong was each team on the day of each match?",
      "Forecasting results it never saw, against plain Elo ratings", `Its forecasts miss less than plain Elo's: an error of ${(+a).toFixed(3)} against ${(+b).toFixed(3)}, lower is better`]; },
    "Game models": (r) => { const [a, b] = nums(r.result); return ["How does each team play, season by season?",
      "A team's odd and even matches must describe the same team", `${a} of ${b} ways of playing are measured reliably`]; },
    "Coach fingerprints": (r) => { const [a, b, c] = nums(r.result); return ["Does a coach take his way of playing from club to club?",
      `His new club must move toward his last one, on ${c} real moves`, `${a} of ${b} aspects of his style travel with him`]; },
    "Roles": (r) => { const [a, b] = nums(r.result); return ["What does he do inside his team?",
      "A player's role must hold from one half of a season to the other", `${a} of ${b} roles hold`]; },
    "Skills beyond the system": (r) => { const [a, b] = nums(r.result); return ["What does he do more of than his system asks for?",
      "With the system taken out, his first half of a season must predict his second", `${a} of ${b} skills show through`]; },
    "System fit": (r) => { const [a] = nums(r.result); return ["If he joins a team that plays like this, what will he do there?",
      "It must beat both “the same as before” and “like that team's player in his position” on moves it never saw", `It does, on ${num(+a)} unseen moves`]; },
    "Development by system (ProT6)": () => ["Which styles and coaches grow young players fastest?",
      "Knowing the club's style or its coach must sharpen next season's forecast", "No gain from either, in two attempts (the second on 2.3 times the players), so it stays off the desk"],
    "Attributes": (r) => ["What kind of footballer: vision, composure, discipline?",
      "Each must repeat from one half-season to the next, and come from the player more than from the match",
      "Vision, composure and discipline hold; concentration, consistency and big-game form don't, and stay hidden"],
    "The engine": () => ["Who becomes a regular in a first division within three seasons?",
      "Ranked against market value on a season it never learned from",
      `${{ ahead: "Ahead of", edge: "Just ahead of", level: "Level with", behind: "Behind" }[verdict(lo, hi, g.mean)]} market value: ${picks(eng?.auc)} against ${picks(mkt?.auc)} right picks in 100. Next: widen the margin`],
    "The projection": () => ["How many minutes will he play over the next three seasons, and how sure is that?",
      "Its 80 % ranges must hold the real outcome 77 to 83 % of the time, on seasons that have played out",
      pv.length ? `They held ${Math.min(...pv).toLocaleString("en", { style: "percent", minimumFractionDigits: 1 })} to ${Math.max(...pv).toLocaleString("en", { style: "percent", minimumFractionDigits: 1 })} across the four kinds of evidence. A sharper version narrowed the ranges but let one kind of evidence slip just under 77 %, so it was cut. A club's own data (training loads, injuries, the coach's plans) could narrow them; that is named here, not yet measured` : "Waiting for its report"],
  };
  // status: passed or not passed; the engine passes from "just ahead" up, the projection on settled seasons
  const rows = d.modules.map((r) => {
    const [q, how, found] = (P[r.module.replace(/ \(T[1-5]\)$/, "").replace(/ \(T6\)$/, " (ProT6)")] || (() => [r.asks, r.test, r.result]))(r);   // also reads the old "(T1)" names until the desk restarts
    const state = r.module === "The projection" ? (pvOk ? "ok" : "held") : r.module === "The engine" ? (["ahead", "edge"].includes(verdict(lo, hi, g.mean)) ? "ok" : "held") : r.passed ? "ok" : "held";
    return { module: r.module, q, how, found, state };
  });
  // Player Combinations, in beta: its test passed on open data from past seasons; today's players come later
  const c = d.combinations || {};
  if (c.testable) rows.splice(rows.length - 2, 0, { module: "Player combinations", state: "beta", q: "Which pairs do better together than apart?",
    how: "Duos football remembers, named before the run, must sit in the top third of pairs like them",
    found: `${c.top_third} of the ${c.testable} duos that could be tested do. In beta: it reads StatsBomb's free past seasons, so today's young players come in a later version` });
  return rows;
}

function stations(rows) {
  const W = 1120, H = 150, L = 46, R = 46, y = 52, n = rows.length;
  const X = (i) => L + (i / (n - 1)) * (W - L - R);
  const short = (m) => m.replace(/\s*\(T\d\)/, "").replace("Skills beyond the system", "Skills").replace("Development by system", "Development");
  const words = (t) => { const w = t.split(" "), a = []; let cur = "";
    w.forEach((x) => { if ((cur + " " + x).trim().length > 12 && cur) { a.push(cur); cur = x; } else cur = (cur + " " + x).trim(); }); a.push(cur); return a; };
  const MK = { ok: (x) => `<path class="mk" d="M${x - 6},${y} l4,4.5 l8,-9"/>`, held: (x) => `<path class="mk" d="M${x - 5},${y - 5} l10,10 M${x + 5},${y - 5} l-10,10"/>`,
    waits: (x) => `<path class="mk" d="M${x},${y - 7} V${y} l5,4"/>`,
    beta: (x) => `<text class="mk-b" x="${x}" y="${y + 4}" text-anchor="middle">β</text>` };
  const st = rows.map((m, i) => `<g class="station ${m.state}" data-tip="${esc(`<b>${m.q}</b>${m.found}`)}">
      <rect class="hit" x="${X(i) - 50}" y="0" width="100" height="${H}"/>
      <circle cx="${X(i)}" cy="${y}" r="15"/>${MK[m.state](X(i))}
      <text x="${X(i)}" y="${y + 38}" text-anchor="middle">${words(short(m.module)).map((w, k) => `<tspan x="${X(i)}" dy="${k ? 15 : 0}">${esc(w)}</tspan>`).join("")}</text></g>`).join("");
  return `<div class="st-scroll"><svg data-fit class="stations" viewBox="0 0 ${W} ${H}" role="img" aria-label="${rows.filter((m) => m.state === "ok").length} of ${n} modules passed: ${rows.map((m) => `${m.module} ${STATE_WORD[m.state].toLowerCase()}`).join(", ")}">
    <text class="end" x="${L - 30}" y="${y - 26}">the data</text><text class="end" x="${W - R + 30}" y="${y - 26}" text-anchor="end">the call</text>
    <line class="track" x1="${L}" x2="${W - R}" y1="${y}" y2="${y}"/>${st}</svg></div>`;
}

const STATE_WORD = { ok: "Passed", held: "Not passed", waits: "Waits", beta: "Beta" };
function testList(rows) {
  return `<div class="flip-grid wide">${rows.map((m) => UI.flip({ state: m.state, frontHint: "How it was tested", backHint: "The question",
    front: `<span class="fc-chips"><b class="fc-state">${STATE_WORD[m.state]}</b></span><span class="fc-q">${esc(m.q)}</span>`,
    back: `<span class="fc-l">Tested by</span><span class="fc-t">${esc(m.how)}</span><span class="fc-l">Found</span><span class="fc-t">${esc(m.found)}</span>` })).join("")}</div>`;
}

// ── 6. how it grew: pivotal milestones in full, the smaller ones as ticks between them ─────────────────────────────
function grew(list) {
  return UI.stepper({ label: "How Promesse grew, milestone by milestone", cls: "step-grew",
    slides: list.map((m) => ({ title: m.title, small: !m.pivotal,
      html: `<p class="step-kicker">${m.pivotal ? "Milestone" : "A smaller step"}</p><h3>${esc(m.title)}</h3><p>${esc(m.text)}</p>` })) });
}

// ── 7. planned updates, and the data still coming in, season by season ─────────────────────────────────────────────
function coverage(d) {
  const [y0, y1] = d.seasons, n = y1 - y0 + 1;
  const at = (y) => ((y - y0) / n) * 100;
  const head = Array.from({ length: n }, (_, i) => `<span>${season(y0 + i)}</span>`).join("");
  const rows = d.timeline.map((r) => `<div class="tl-row"><div class="tl-name"><b>${esc(r.source)}</b><small>${esc(r.via)}</small></div>
    <div class="tl-track">${r.spans.map(([a, b, st]) => `<i class="tl-bar st-${st}" style="left:${at(a)}%;width:${at(b + 1) - at(a)}%"
      data-tip="${esc(`<b>${r.source}</b>${season(a)}${b > a ? ` to ${season(b)}` : ""}: ${d.states[st]}<br>${r.via}`)}"></i>`).join("")}</div></div>`).join("");
  const legend = Object.entries(d.states).map(([k, v]) => `<span class="lg"><i class="tl-bar st-${k}"></i>${esc(v)}</span>`).join("");
  const table = `<details class="sb-table"><summary>As a table</summary><table><thead><tr><th>Source</th><th>Via</th><th>Seasons</th></tr></thead><tbody>
    ${d.timeline.map((r) => `<tr><td>${esc(r.source)}</td><td>${esc(r.via)}</td><td>${r.spans.map(([a, b, st]) => `${season(a)}${b > a ? `–${season(b)}` : ""} (${d.states[st]})`).join("; ")}</td></tr>`).join("")}
    </tbody></table></details>`;
  return `<div class="tl-legend">${legend}</div>
    <div class="tl-scroll"><div class="tl" style="--n:${n}">
      <div class="tl-row tl-head"><div class="tl-name"></div><div class="tl-track tl-seasons">${head}</div></div>
      <div class="tl-body">${rows}</div>
    </div></div>${table}`;
}

function planned(list) {
  return `<ul class="sb-plan">${list.map((p) => `<li><h3>${esc(p.title)}</h3><p>${esc(p.text)}</p></li>`).join("")}</ul>`;
}

// ── the page ──────────────────────────────────────────────────────────────────────────────────────────────────
async function scoreboardPage() {
  const d = await api("/api/scoreboard");
  return () => {
    setNav("method");
    const tests = plainTests(d), passed = tests.filter((m) => m.state === "ok").length;
    const steps = (d.gap_history || []).filter((s) => !s.future).length;
    main.innerHTML = `<div class="sb">
      <div class="page-head"><div><h1>Scoreboard</h1><p class="lead">${esc(d.goal)}</p></div></div>
      ${now(d)}
      <section class="block" aria-labelledby="sb-v">${sign("", "How the vision broadened", `${steps} steps so far, each a deeper reading of the game`, "sb-v")}
        ${vision(d)}</section>
      <section class="block" aria-labelledby="sb-l">${sign("", "Who ranks young players best", `${num(d.n_test)} players, a season none of them learned from`, "sb-l")}
        ${ladder(d)}${questions(d)}</section>
      <section class="block sb-stands" aria-labelledby="sb-s">${sign("", "Two kinds of reading", "the rule was fixed before looking at any player", "sb-s")}
        <div class="sb-standsrow">${standsSVG(d.stands)}<div class="sb-standstext">
          <ul class="sb-key"><li class="deep"><i aria-hidden="true"></i><div><b>The full reading</b><span><em>${num(d.stands.deep)}</em> players, ${num(d.stands.deep_young)} of them 21 or under</span></div></li>
            <li class="proj"><i aria-hidden="true"></i><div><b>The projection</b><span>everyone else, read with a range around each call</span></div></li></ul>
          <p><b>The full reading.</b> Players with two or more seasons of 900+ minutes with per-player match stats, from 2021/22 to 2025/26, and a Transfermarkt identity confirmed by an exact birth date: ${num(d.stands.deep)} of them, ${num(d.stands.deep_young)} aged 21 or under when the period started for them. For them the desk reads everything: the lines he plays in, his roles, what he does beyond his system.</p>
          <p><b>The projection.</b> Everyone else, mostly younger players with thinner records. Each gets the same call, plus a range for the minutes he is likely to play, and his page says what data would move him up.</p>
          <p class="note">Next for this table: reading 100 of these players against what analysts wrote about them, to list what the numbers miss.</p></div></div></section>
      <section class="block" aria-labelledby="sb-m">${sign("", "The tests", `${passed} of ${tests.length} passed · a part of Promesse shows on the desk only once it passes`, "sb-m")}
        ${stations(tests)}${testList(tests)}</section>
      <section class="block" aria-labelledby="sb-g">${sign("", "How it grew", "the milestones", "sb-g")}${grew(d.grew || [])}</section>
      <section class="block" aria-labelledby="sb-n">${sign("", "Planned updates", "what the next update adds", "sb-n")}
        ${planned(d.planned || [])}
        <h3 class="sb-sub-h">What the data covers, season by season</h3>${coverage(d)}
        <p class="note">What a club's own data would add is a different question, answered on <a href="#/data">Data &amp; Vision</a>.</p></section>
    </div>`;
    // hover: one delegated listener for every mark that carries a tip
    const sb = $(".sb", main);
    sb.addEventListener("pointermove", (e) => { const t = e.target.closest("[data-tip]"); if (t) showTip(t.dataset.tip, e.clientX, e.clientY); else hideTip(); });
    sb.addEventListener("pointerleave", hideTip);
    sb.addEventListener("step", (ev) => {   // the slide's point on the chart lights up
      if (!ev.target.closest(".step-vision")) return;
      const fig = $(".sb-vision", sb); fig.dataset.active = ev.detail.i;
      $$(".pt", fig).forEach((g) => g.classList.toggle("on", +g.dataset.i === ev.detail.i));
    });
    animate();
  };
}

// a split-flap number: every digit turns over (squashes on X, swaps its face, opens again) a few times, the last one on its target
function flipDigits(el, to) {
  const txt = String(+to % 1 ? (+to).toFixed(1) : Math.round(+to));
  el.setAttribute("aria-label", txt);
  el.innerHTML = [...txt].map((c) => /\d/.test(c) ? `<span class="fd" aria-hidden="true">${c === "0" ? "0" : "5"}</span>` : `<span aria-hidden="true">${c}</span>`).join("");
  const targets = [...txt].filter((c) => /\d/.test(c));
  $$(".fd", el).forEach((d, i) => {
    const target = targets[i] ?? "0", n = 5 + i * 3, tl = gsap.timeline({ delay: 0.15 + i * 0.14 });
    for (let k = 1; k <= n; k++) {
      tl.to(d, { rotateX: -90, duration: 0.05, ease: "power1.in" })
        .call(() => { d.textContent = k === n ? target : String((+d.textContent + 1 + (k % 3)) % 10); })
        .fromTo(d, { rotateX: 90 }, { rotateX: 0, duration: 0.05, ease: "power1.out" });
    }
  });
}

function animate() {
  if (!motion()) return;
  // the two scores flip into place like the Ground's screen: each digit is a flap that turns over a few times and lands on its value.
  // The number keeps its decimal when it has one (77.9 against 77.5: whole numbers would show 78 and 78) and reads as one number to
  // a screen reader (aria-label on the figure; the flaps are hidden from it).
  $$(".sb-score[data-to]").forEach((el) => { flipDigits(el, el.dataset.to); });
  gsap.from(".sb-verdict", { y: 10, opacity: 0, duration: 0.6, ease: "expo.out", delay: 0.6 });
  whenSeen($(".sb-vision"), () => {   // the line draws step by step, each point arriving as the line reaches it
    const p = $(".sb-vision .trend:not(.future)"); const len = p.getTotalLength();
    const tl = gsap.timeline();
    tl.fromTo(p, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 1.4, ease: "power2.inOut" });
    tl.from(".sb-vision .pt:not(.future)", { opacity: 0, scale: 0.4, transformOrigin: "center", duration: 0.45, ease: "back.out(2)", stagger: 0.45 }, 0);
    tl.from(".sb-vision .future, .sb-vision .ref, .sb-vision .reflab", { opacity: 0, duration: 0.6 }, 1.3);
  });
  whenSeen($(".sb-ladder"), () => {
    gsap.from(".sb-ladder .stem", { attr: { x2: (i, el) => el.getAttribute("x1") }, duration: 0.9, ease: "expo.out", stagger: 0.07 });
    gsap.from(".sb-ladder .head", { attr: { cx: () => $(".sb-ladder .stem").getAttribute("x1") }, duration: 0.9, ease: "expo.out", stagger: 0.07 });
    gsap.from(".sb-ladder .bar, .sb-ladder .barlab", { opacity: 0, duration: 0.6, delay: 0.6 });
  });
  whenSeen($(".stands-svg"), () => {
    gsap.from(".stands-svg .seat.proj", { opacity: 0, y: 6, duration: 0.35, ease: "power2.out", stagger: 0.05 });
    gsap.from(".stands-svg .seat.deep", { opacity: 0, y: 6, duration: 0.35, ease: "power2.out", stagger: 0.07, delay: 0.5 });
  });
  whenSeen($(".stations"), () => {
    const t = $(".stations .track"); const len = t.getTotalLength();
    gsap.fromTo(t, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 1.2, ease: "power2.inOut" });
    gsap.from(".stations .station", { opacity: 0, scale: 0.5, transformOrigin: "center 52px", duration: 0.45, ease: "back.out(2)", stagger: 0.09, delay: 0.2 });
  });
  whenSeen($(".tl"), () => gsap.from(".tl-body .tl-bar", { scaleX: 0, transformOrigin: "left center", duration: 0.8, ease: "expo.out", stagger: 0.035 }));
}

window.scoreboardPage = scoreboardPage;
})();
