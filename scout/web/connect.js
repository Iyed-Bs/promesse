// Data & Vision (#/data), rewritten: three questions only, each answered first.
//   1. what Promesse holds (sources, seasons, sizes, open or private; the two stands' counts),
//   2. how each source is used (the plug board: from the feed to the call),
//   3. what a club could plug in (its sockets, who is who, the adapters' proof, and club_data_table.json drawn as a table:
//      measured where we hold the data, named where we don't).
// Player Combinations (#/combinations) lives in the second half of this file. Data: /api/connect, /api/meta, /api/scoreboard.
(() => {
  const KIND_TABLES = { matches: ["matches", "appearances"], careers: ["appearances"], events: ["events"], tracking: ["tracking"],
    physical: ["physical"], availability: ["availability"], benchmark: [], identity: ["identity_links"], reports: ["reports"] };
  // the contract's tables -> what reads them (when an engine starts reading a table)
  const FEEDS = { matches: ["The call", "Full reading", "Roles", "System fit"], appearances: ["The call", "Full reading", "Roles", "Player Combinations"],
    events: ["Roles", "Player Combinations", "Signature skills"], tracking: ["Player Combinations", "Signature skills", "System fit"], physical: ["Projections"],
    availability: ["Projections", "The call"], reports: ["The call"], identity_links: [] };
  const MODULES = ["The call", "Full reading", "Roles", "System fit", "Player Combinations", "Signature skills", "Projections"];
  const TABLE_NOTE = { matches: "one row a match", appearances: "who played, where, how long", events: "every action, with its place",
    tracking: "every player, every frame", physical: "what a body ran", availability: "status, never a diagnosis",
    reports: "what a scout saw", identity_links: "who is who, across providers" };
  const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);

  // ── the plug board ────────────────────────────────────────────────────────────────────────────────────────────
  function board(inv) {
    const left = inv.have.map((h) => ({ name: h.source, kind: h.kind, state: h.state, size: h.size, licence: h.licence, club: false })), tables = Object.keys(FEEDS);
    const W = 1100, rowL = 25, rowT = 44, rowM = 50, top = 34;
    const H = Math.max(left.length * rowL, tables.length * rowT, MODULES.length * rowM) + top + 20;
    const yL = (i) => top + i * rowL + 10, yT = (i) => top + (H - top - tables.length * rowT) / 2 + i * rowT + 18, yM = (i) => top + (H - top - MODULES.length * rowM) / 2 + i * rowM + 20;
    const xL = 300, xT0 = 470, xT1 = 680, xM = 860;
    const curve = (x0, y0, x1, y1) => `M${x0},${y0} C${(x0 + x1) / 2},${y0} ${(x0 + x1) / 2},${y1} ${x1},${y1}`;
    let paths = "", nodes = "";
    left.forEach((s, i) => {
      const y = yL(i), cls = s.club ? "socket" : s.state;
      nodes += `<g class="cn-src ${cls}" data-src="${i}" tabindex="0" role="button" aria-label="${esc(s.name)}: ${esc(s.size)}">
        <rect x="8" y="${y - 10}" width="${xL - 18}" height="20" rx="3"/><text x="18" y="${y + 4}">${esc(s.name)}</text>
        <circle class="jack" cx="${xL - 4}" cy="${y}" r="4.5"/></g>`;
      for (const t of KIND_TABLES[s.kind] || []) {
        const j = tables.indexOf(t);
        paths += `<path class="cn-flow ${cls}" data-src="${i}" data-t="${t}" d="${curve(xL, y, xT0, yT(j))}"/>`;
      }
    });
    tables.forEach((t, j) => {
      const y = yT(j);
      nodes += `<g class="cn-table" data-t="${t}"><rect x="${xT0}" y="${y - 17}" width="${xT1 - xT0}" height="34" rx="2"/>
        <text class="tn" x="${xT0 + 12}" y="${y - 1}">${t.replace("_", " ")}</text><text class="tm" x="${xT0 + 12}" y="${y + 12}">${TABLE_NOTE[t]}</text></g>`;
      for (const m of FEEDS[t]) paths += `<path class="cn-flow out" data-t="${t}" data-m="${esc(m)}" d="${curve(xT1, y, xM, yM(MODULES.indexOf(m)))}"/>`;
    });
    MODULES.forEach((m, k) => {
      const y = yM(k);
      nodes += `<g class="cn-mod" data-m="${esc(m)}"><rect x="${xM}" y="${y - 16}" width="${W - xM - 8}" height="32" rx="16"/><text x="${xM + 18}" y="${y + 5}">${esc(m)}</text></g>`;
    });
    const heads = `<text class="cn-h" x="8" y="16">The data we hold</text><text class="cn-h" x="${xT0}" y="16">One set of tables</text><text class="cn-h" x="${xM}" y="16">What reads them</text>`;
    const idbar = `<g class="cn-id"><rect x="${xT0 - 2}" y="${top - 6}" width="${xT1 - xT0 + 4}" height="${H - top - 8}" rx="4"/></g>`;
    const bh = H - top - 8;   // the stage bands: the stepper lights one column at a time (a wash behind it, so no text is ever dimmed)
    const bands = `<rect class="cn-stage feed" x="0" y="${top - 6}" width="${xL + 10}" height="${bh}" rx="4"/><rect class="cn-stage tables" x="${xT0 - 6}" y="${top - 6}" width="${xT1 - xT0 + 12}" height="${bh}" rx="4"/><rect class="cn-stage modules" x="${xM - 8}" y="${top - 6}" width="${W - xM}" height="${bh}" rx="4"/>`;
    return { svg: `<div class="cn-scroll"><svg class="cn-board" viewBox="0 0 ${W} ${H}" role="img" aria-label="Every source we hold, the common tables it lands in, and the parts of Promesse that read them, ending in the call">${heads}${bands}${idbar}${paths}${nodes}</svg></div>`, left };
  }

  // a ring gauge: share linked, the checked part darker
  const ring = (share, label, sub) => {
    const r = 34, c = 2 * Math.PI * r;
    return `<figure class="cn-ring"><svg viewBox="0 0 84 84" aria-hidden="true"><circle cx="42" cy="42" r="${r}" class="bg"/>
      <circle cx="42" cy="42" r="${r}" class="fg" style="--dash:${(c * share).toFixed(1)} ${c.toFixed(1)}" stroke-dasharray="0 ${c.toFixed(1)}"/></svg>
      <figcaption><b>${Math.round(share * 100)}%</b><span>${label}</span><small>${sub}</small></figcaption></figure>`;
  };

  function runs(rep) {
    const NAME = { impect: ["Impect", "events · Bundesliga 2023/24"], dfl: ["DFL / Sportec", "events · positions"], metrica: ["Metrica", "events + tracking"], skillcorner: ["SkillCorner", "broadcast tracking"] };
    return Object.entries(rep.runs || {}).map(([k, r]) => {
      const [nm, what] = NAME[k] || [k, ""];
      if (!r.ok) return `<article class="cn-run bad"><h3>${esc(nm)}</h3><p class="dim">${esc(r.error || "failed")}</p></article>`;
      const t = r.tables || {}, rows = Object.entries(t).filter(([n]) => ["events", "tracking"].includes(n));
      const filled = Math.min(...Object.values(t).flatMap((x) => Object.values(x.required_filled || {})));
      const inPitch = Object.values(t).flatMap((x) => Object.entries(x).filter(([c]) => c.endsWith("_in_pitch")).map(([, v]) => v));
      const id = r.identity;
      return `<article class="cn-run"><header><h3>${esc(nm)}</h3><span class="kicker">${esc(what)}</span></header>
        <div class="cn-run-n"><b>${num(r.matches)}</b><span>matches</span>${rows.map(([n, x]) => `<b>${num(x.rows)}</b><span>${n} rows</span>`).join("")}</div>
        <ul class="cn-checks"><li class="ok">required columns filled: ${Math.round(filled * 100)}%</li>${inPitch.length ? `<li class="ok">positions on the pitch: ${(Math.min(...inPitch) * 100).toFixed(1)}% or more</li>` : ""}<li class="ok">${r.seconds}s for the lot</li></ul>
        ${id ? ring(id.linked_share, "of its players found", `${id.checked_agree} of ${id.linked} agree with our own record (birth date and name)`) : `<p class="cn-noid">No player ids to link: ${k === "metrica" ? "the sample is anonymised" : "DFL ids are not in the register yet"}.</p>`}</article>`;
    }).join("");
  }

  function coverage(cov) {
    const ORDER = [["in_reep", "In the register"], ["impect", "Impect id"], ["skillcorner", "SkillCorner id"], ["sofascore", "Sofascore id"], ["wyscout", "Wyscout id"],
      ["opta", "Opta id"], ["fbref", "FBref id"], ["matchdata", "MatchData id (ours are linked already)"], ["gamerating_a", "gamerating_a (EA) id"]];
    return `<div class="cn-bars" role="table" aria-label="Of the desk's players, how many carry each provider's id in the register">${ORDER.map(([k, l]) => cov[k] != null ? `
      <div class="cn-bar" role="row"><span role="cell">${l}</span><i role="cell" style="--w:${pct(cov[k], cov.players)}%"><b></b></i><em role="cell">${pct(cov[k], cov.players)}% <small>${num(cov[k])}</small></em></div>` : "").join("")}</div>`;
  }

  // question 1: every source as a row. Open = the licence lets anyone read it (credit given); private = scraped or licensed for our
  // research only, so it stays on this PC and a run on it never hands out the rows
  const isPrivate = (lic) => /scraped|all rights|no licence/i.test(lic || "");
  function holdTable(inv) {
    const STATE = { in: "in", collecting: "still coming in", found: "found, not loaded" };
    // the parts of Promesse a source reaches: its kind -> the common tables -> what reads them (the plug board's roads)
    const reach = (kind) => [...new Set((KIND_TABLES[kind] || []).flatMap((t) => FEEDS[t] || []))];
    const use = (h) => { const r = reach(h.kind);
      if (r.length) return `<span class="fc-t">It feeds:</span><span class="cn-reach">${r.map((m) => `<i>${esc(m)}</i>`).join("")}</span>`;
      if (h.kind === "benchmark") return `<span class="fc-t">A benchmark: what Promesse is measured against, never what it learns from.</span>`;
      if (h.kind === "identity") return `<span class="fc-t">It joins the others: who is who, across providers.</span>`;
      return `<span class="fc-t">Held; no part of Promesse reads it yet.</span>`; };
    return `<div class="flip-grid cn-hold-cards">${inv.have.map((h) => { const priv = isPrivate(h.licence);
      return UI.flip({ state: h.state, frontHint: "How Promesse uses it", backHint: "What it is",
        front: `<span class="fc-name">${esc(h.source)}</span><span class="fc-sub">${esc(h.what)}</span><span class="fc-chips"><span class="chip ${priv ? "priv" : "open"}">${priv ? "private" : "open"}</span><span class="chip ${h.state}">${STATE[h.state] || h.state}</span></span>`,
        back: `<span class="fc-name">${esc(h.source)}</span><span class="fc-l">How Promesse uses it</span>${use(h)}<span class="fc-l">Seasons</span><span class="fc-t">${esc(h.seasons)}</span><span class="fc-l">Size</span><span class="fc-t">${esc(h.size)}</span><span class="fc-l">Licence</span><span class="fc-t">${esc(h.licence)}</span>` }); }).join("")}</div>`;
  }

  // question 3: club_data_table.json as the table it is. {placeholders} in the cells come from the desk's live figures
  // (/api/meta: engine_test, projection_held), so the wording follows the figures. the three status labels
  const KIND = { measured: ["Measured on public data", "measured"], both: ["Measured in part", "both"], named: ["Named, not run", "named"] };
  function fillLive(t, m) {
    const e = m.engine_test || {}, p = m.projection_held || {}, sg = (v) => `${v > 0 ? "+" : ""}${v}`;
    const word = e.verdict === "ahead" ? `ahead by ${sg(e.diff)}` : e.verdict === "edge" ? `just ahead, ${sg(e.diff)}` : e.verdict === "behind" ? `behind, ${sg(e.diff)}` : `level, ${sg(e.diff)}`;
    return String(t).replace("{engine}", e.engine != null ? `${e.engine} right picks in 100` : "its score").replace("{market}", e.market ?? "–")
      .replace("{diff_word}", e.diff != null ? word : "see the Scoreboard").replace("{lo}", e.lo != null ? sg(e.lo) : "–").replace("{hi}", e.hi != null ? sg(e.hi) : "–")
      .replace("{plow}", p.low ?? "–").replace("{phigh}", p.high ?? "–");
  }
  function clubTable(ct, meta) {
    if (!ct || !ct.rows) return "";
    return `<div class="flip-grid wide cn-club-cards">${ct.rows.map((r) => { const [lab, cls] = KIND[r.kind] || KIND.named;
      return UI.flip({ state: cls, frontHint: "How it would be tested", backHint: "What it would add",
        front: `<span class="fc-name">${esc(r.part)}</span><span class="fc-chips"><span class="chip st-${cls}">${lab}</span></span><span class="fc-l">What it would add</span><span class="fc-t">${esc(fillLive(r.adds, meta))}</span>`,
        back: `<span class="fc-name">${esc(r.part)}</span><span class="fc-l">A club's data</span><span class="fc-t">${esc(r.club_data)}</span><span class="fc-l">How it would be tested</span><span class="fc-t">${esc(fillLive(r.test, meta))}</span><span class="fc-l">What we hold today</span><span class="fc-t">${esc(r.held)}</span><span class="fc-l">Where it stands</span><span class="fc-t">${esc(r.status)}</span>` }); }).join("")}</div>`;
  }

  function sockets(inv) {
    return `<div class="cn-sockets">${inv.club_only.map((c) => `<article class="cn-socket"><div class="plug" aria-hidden="true"><i></i><i></i></div>
      <h3>${esc(c.source)}</h3><p class="cn-who">${esc(c.who)}</p><p>${esc(c.adds)}</p>
      <div class="cn-feeds">${c.sharpens.map((f) => `<span>${esc(f)}</span>`).join("")}</div><p class="cn-adapter">${esc(c.adapter)}</p></article>`).join("")}</div>`;
  }

  // a partner reading against its pass mark: how well the two halves of the matches agree (odd against even; 1 = the same, 0 = nothing
  // in common) per measure, the 0.5 line, an interval where the report has one (sb_interval); measures in `base` are the baseline
  // rung (match totals) and drawn hatched
  function gateSvg(rel, LBL, aria, base = []) {
    const rows = Object.entries(rel).sort((a, b) => (b[1].spearman_brown ?? -1) - (a[1].spearman_brown ?? -1));
    const W = 560, x0 = 190;
    const scale = (v) => x0 + ((Math.max(-0.3, Math.min(1, v)) + 0.3) / 1.3) * (W - x0 - 20);
    const zero = scale(0), gate = scale(0.5), h = rows.length * 22 + 40;
    const bars = rows.map(([k, r], i) => { const v = r.spearman_brown ?? 0, y = 30 + i * 22, a = Math.min(zero, scale(v)), b = Math.max(zero, scale(v));
      const ci = r.sb_interval && r.sb_interval[0] != null ? `<line class="ci" x1="${scale(r.sb_interval[0])}" x2="${scale(r.sb_interval[1])}" y1="${y + 8.5}" y2="${y + 8.5}"/>` : "";
      return `<text class="lbl" x="${x0 - 10}" y="${y + 12}" text-anchor="end">${LBL[k] || k}</text><rect class="${v >= 0.5 ? "pass" : "fail"}${base.includes(k) ? " base" : ""}" x="${a}" y="${y + 2}" width="${Math.max(2, b - a)}" height="13" rx="2" data-w="${Math.max(2, b - a)}"/>
        ${ci}<text class="val" x="${Math.max(b, r.sb_interval && r.sb_interval[1] != null ? scale(r.sb_interval[1]) : b) + 6}" y="${y + 12}">${v.toFixed(2)}</text>`; }).join("");
    return `<div class="fig-scroll cn-gate-wrap"><svg data-fit viewBox="0 0 ${W} ${h}" class="cn-gate" role="img" aria-label="${esc(aria)}">
        <line class="zero" x1="${zero}" x2="${zero}" y1="22" y2="${h - 8}"/><line class="gate" x1="${gate}" x2="${gate}" y1="14" y2="${h - 8}"/>
        <text class="gate-l" data-flip x="${gate + 5}" y="18">pass mark 0.5: the halves agree</text>${bars}</svg></div>`;
  }

  // a verdict block: kicker, the answer in one line (from the figures), the full account behind a button
  const verdictBlock = (kicker, short, body) => `<div class="cn-verdict"><p class="kicker">${kicker}</p>${UI.more(short, body, "How it was tested, and what it says")}</div>`;

  // the first test (match totals), against its gate; honest about the fail
  function partners(p) {
    if (!p || !p.G1_pair_reliability) return "";
    const LBL = { touches: "Touches", passes: "Accurate passes", final_third: "Passes into the final third", chances: "Chances created", xa: "xA", xg: "xG",
      shots: "Shots", box: "Touches in the box", dribbles: "Dribbles", def_actions: "Defensive actions", recoveries: "Recoveries", long_balls: "Long balls", crosses: "Crosses" };
    const rows = Object.entries(p.G1_pair_reliability).sort((a, b) => (b[1].spearman_brown ?? -1) - (a[1].spearman_brown ?? -1));
    const g2 = p.G2_patterns || {}, g3 = p.G3_balance || {};
    return `<div class="cn-partners">${gateSvg(p.G1_pair_reliability, LBL, "How well a pair's effect on one half of the matches agrees with the other half, per rate, against the pass mark of 0.5: none reaches it")}
      ${verdictBlock("Tested, not on the desk", `It does not come back: the best rate, ${esc((LBL[rows[0][0]] || rows[0][0]).toLowerCase())}, scores ${(rows[0][1].spearman_brown).toFixed(2)} against the 0.5 asked.`, `
        <p>The question: does who plays beside a player change his match totals, and does the change repeat? We took <b>${num(p.pairs)}</b> player-and-partner pairs from <b>${num(p.starts)}</b> starts, measured each pair's effect on his odd-numbered matches and again on his even ones, and compared the two. A score of 1 means the halves agree perfectly, 0 that they have nothing in common; we asked for at least 0.5. It does not come back: the best rate, ${esc((LBL[rows[0][0]] || rows[0][0]).toLowerCase())}, scores ${(rows[0][1].spearman_brown).toFixed(2)}.</p>
        <p>Patterns by role (a mezzala beside an anchor, then beside a deep playmaker) fail the same way: ${g2.patterns_testable} could be tested, and the two halves agree at ${(g2.corr_halves ?? 0).toFixed(2)} against the 0.5 asked.</p>
        <p>What it says: from match totals, who stands beside a player moves his numbers by less than one match differs from the next. Partners change where and when he gets the ball, which totals blur. The next section reads places (where each reception happens, on Impect's Bundesliga matches); tracking (the space between two partners) comes after. Balance: with him and without, the home share differs by ${g3.mean_abs_home_diff} on average and opponent strength by ${g3.mean_abs_opp_strength_diff} (a match-to-match spread of ${g3.opp_strength_sd_between_matches}); both are adjusted for before any comparison.</p>`)}</div>`;
  }

  // design 1 (gold/partners_places.py): the same comparison read from places, its gate chart with the totals rung, the
  // slot check, and the passing measures' largest pairs (shrunk, in metres, with interval and counts). Every sentence is
  // built from the report's figures.
  function places(p) {
    if (!p || !p.G1_pair_reliability) return "";
    const LBL = { rec_x: "Depth of receptions", rec_width: "Width of receptions", btl: "Between the lines", half_space: "In the half-spaces",
      box: "In the box", def_x: "Depth of defending", def_width: "Width of defending", receptions: "Receptions (total)",
      box_receptions: "Box receptions (total)", def_actions: "Defensive actions (total)" };
    const rel = p.G1_pair_reliability, base = Object.keys(rel).filter((k) => !String(rel[k].kind).startsWith("place"));
    const placesK = Object.keys(rel).filter((k) => !base.includes(k)), pass = p.G1_places_passing || [];
    const bestBase = base.map((k) => rel[k].spearman_brown ?? -1).reduce((a, b) => Math.max(a, b), -1);
    const sb = (k) => (rel[k].spearman_brown ?? 0).toFixed(2), name = (k) => (LBL[k] || k).toLowerCase();
    const slot = p.same_slot || {}, g2 = p.G2_patterns || {}, g3 = p.G3_balance || {};
    const slotLine = pass.map((k) => { const s = slot[k] || {};
      return s.spearman_brown == null ? `${name(k)} cannot be read (${num(s.pairs || 0)} pairs)` : s.pass ? `${name(k)} holds at ${s.spearman_brown.toFixed(2)}` : `${name(k)} falls to ${s.spearman_brown.toFixed(2)}, under the pass mark`; }).join("; ");
    const DIR = { rec_x: ["higher up", "deeper"], rec_width: ["wider", "more central"] };
    const ex = Object.entries(p.examples || {}).map(([k, rows]) => `<div><h3>${esc(LBL[k] || k)}</h3><ol>${rows.slice(0, 4).map((r) => {
      const [up, down] = DIR[k] || ["more", "less"];
      return `<li><b>${esc(r.player)}</b> beside ${esc(r.partner)} <span class="cn-ex-team">${esc(r.team)}, ${esc(r.line)}</span><br>receives ${Math.abs(r.in_unit).toFixed(1)} m ${r.in_unit >= 0 ? up : down}
        <span class="cn-ex-ci">(${r.lo.toFixed(1)} to ${r.hi.toFixed(1)} m${r.lo <= 0 && r.hi >= 0 ? ", crosses zero" : ""}) · ${r.n_with} with, ${r.n_without} without</span></li>`; }).join("")}</ol></div>`).join("");
    return `<div class="cn-partners">${gateSvg(rel, LBL, `How well a pair's effect on where he receives, measured on one half of the matches, agrees with the other half, against the pass mark of 0.5: ${pass.length} of ${placesK.length} places reach it`, base)}
      ${verdictBlock(`Tested ${esc((p.built || "").slice(0, 10))} · ${esc(p.data || "")}`, `<b>${pass.length} of ${placesK.length}</b> places reach the pass mark of 0.5${pass.length ? `: ${pass.map((k) => `${name(k)} (${sb(k)})`).join(" and ")}` : ""}.`, `
        <p>The question: does a partner change <i>where</i> a player receives the ball, and does the change repeat? Each pair's effect is measured on the odd-numbered matches and again on the even ones; 1 means the halves agree perfectly, 0 that they have nothing in common, and we asked for at least 0.5. <b>${pass.length} of ${placesK.length}</b> places reach it${pass.length ? `: ${pass.map((k) => `${name(k)} (${sb(k)})`).join(" and ")}` : ""}. Reading the same ${num(p.starts)} starts from match totals instead of places, ${bestBase >= 0.5 ? "the halves agree too" : `they do not agree (best ${bestBase.toFixed(2)})`}: ${pass.length && bestBase < 0.5 ? "the gain comes from reading places, not from having more data" : "places add nothing over totals here"}.</p>
        ${pass.length ? `<p>A further check, run after the pass mark was set: keep only the starts where he plays his usual slot (${Math.round((slot.starts_kept || 0) * 100)} % of starts kept). ${slotLine.charAt(0).toUpperCase() + slotLine.slice(1)}. Where it falls, part of the effect was the partner moving him to another slot.</p>` : ""}
        <p>Thin: ${num(rel[placesK[0]].pairs)} pairs reach ten starts on each side, the intervals are wide, and one season of ${num(p.matches)} matches is all the clean event data we hold. Patterns by role: only ${num(g2.patterns_testable || 0)} could be tested, so none was. Fairness check: the matches with him beside a partner and without differ in home share by ${g3.mean_abs_home_diff} on average and in opponent strength by ${g3.mean_abs_opp_strength_diff}; both are adjusted for.</p>`)}</div>
      ${ex ? `<div class="cn-examples">${ex}</div><p class="note">The largest effects after shrinkage, in metres, with their 95 % interval and their counts. Impect open data, research only.</p>` : ""}`;
  }

  // The named duos on a painted pitch, one card each. Each player stands at his
  // usual position group and side in their matches together (/api/connect, from gold/partner_interplay.parquet),
  // attacking left to right, so a left-sider is at the top. The chalk link's weight is the pair's chemistry percentile:
  // what the two do together beyond what each does with anyone, against pairs of the same type in the same league.
  // A full link is a duo in the top third of its type (the test's call); a dashed one couldn't be tested (too few
  // pairs of its type). Spots are the group's usual place, not tracked positions, and the caption says so.
  const DEPTH = { CB: 0.13, FB: 0.25, DM: 0.36, CM: 0.48, AM: 0.62, W: 0.72, ST: 0.84 };
  const WIDE = new Set(["FB", "W"]);
  const GROUP = { CB: "centre-back", FB: "full-back", DM: "holding midfielder", CM: "central midfielder", AM: "attacking midfielder", W: "winger", ST: "striker" };
  const SIDE = { L: "on the left", R: "on the right", C: "in the centre" };
  function duoPitch(d) {
    const W = 220, H = 142, m = 5, iw = W - 2 * m, ih = H - 2 * m;
    const at = (s) => [m + (DEPTH[s.group] ?? 0.5) * iw,
      m + (s.side === "C" ? 0.5 : WIDE.has(s.group) ? (s.side === "L" ? 0.17 : 0.83) : (s.side === "L" ? 0.31 : 0.69)) * ih];
    let [a, b] = d.spots.map(at);
    if (Math.hypot(a[0] - b[0], a[1] - b[1]) < 16) { a = [a[0], a[1] - 15]; b = [b[0], b[1] + 15]; }   // the same spot: side by side
    const chem = d.chemistry_pct ?? 0, cls = d.testable ? (d.top_third ? "top" : "below") : "nt";
    const label = (p, s, below) => { const x = Math.min(W - 34, Math.max(34, p[0])), y = below ? p[1] + 17 : p[1] - 10;
      return `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle">${esc(s.name)}</text>`; };
    const [sa, sb] = d.spots, aBelow = a[1] > b[1] || (a[1] === b[1] && a[1] > H / 2);
    return `<svg class="pitch duo-pitch" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(sa.name)}, ${GROUP[sa.group] || sa.group} ${SIDE[sa.side]}, and ${esc(sb.name)}, ${GROUP[sb.group] || sb.group} ${SIDE[sb.side]}: chemistry ${Math.round(chem * 100)} out of 100 among pairs of their type">
      <rect class="ground" width="${W}" height="${H}" rx="3"/>
      <g class="chalk"><rect x="${m}" y="${m}" width="${iw}" height="${ih}"/><line x1="${W / 2}" x2="${W / 2}" y1="${m}" y2="${H - m}"/><circle cx="${W / 2}" cy="${H / 2}" r="${(ih * 0.13).toFixed(1)}"/>
        <rect x="${m}" y="${H / 2 - ih * 0.25}" width="${iw * 0.14}" height="${ih * 0.5}"/><rect x="${W - m - iw * 0.14}" y="${H / 2 - ih * 0.25}" width="${iw * 0.14}" height="${ih * 0.5}"/></g>
      <line class="duo-link ${cls}" x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}" stroke-width="${(1.5 + chem * 7).toFixed(1)}"/>
      <circle class="duo-man" cx="${a[0].toFixed(1)}" cy="${a[1].toFixed(1)}" r="6.5"/><circle class="duo-man" cx="${b[0].toFixed(1)}" cy="${b[1].toFixed(1)}" r="6.5"/>
      <g class="duo-names">${label(a, sa, aBelow)}${label(b, sb, !aBelow)}</g></svg>`;
  }
  function duoPitches(duos) {
    const drawn = duos.filter((d) => d.spots && d.spots.length === 2);
    if (!drawn.length) return "";
    const p100 = (v) => v == null ? null : Math.round(v * 100);
    const words = (v) => v == null ? "not available" : `${v} out of 100: the pair matches or beats ${v} of every 100 pairs of its type`;
    const call = (d) => d.testable ? (d.top_third ? "top third of its type" : "below the top third") : `not testable: ${d.pool_pairs} pairs of its type`;
    // the legend is the only fixed text; each card is written from its figures. Short first: one line, the full legend behind it
    return `<div class="duo-legend">${UI.more("Each card shows two players where they usually stood in their matches together; turn it over for the figures in words.",
      `<p>Each card: the two players where they usually stood in their matches together, attacking left to right. The thicker the chalk link, the more the two do together beyond what each does with anyone. The figures place the pair among pairs of the same positions and flanks in the same league, out of 100: chemistry 62 means the pair matches or beats 62 of every 100 such pairs, and 100 means the highest of its type. A full link is in the top third, the test's call; a dashed one had too few pairs of its type to test.</p>`, "What the card shows")}</div>
      <div class="flip-grid duo-cards-flip">${drawn.map((d) => UI.flip({ cls: "duo", state: d.testable ? (d.top_third ? "top" : "below") : "nt", frontHint: "The figures in words", backHint: "The pitch",
        front: `<span class="fc-pitch">${duoPitch(d)}</span><span class="fc-name">${esc(d.duo)}</span><span class="fc-sub">${esc(call(d))}</span>`,
        back: `<span class="fc-name">${esc(d.duo)}</span><span class="fc-sub">${esc(d.team)} · ${esc(d.pool)} · ${num(d.matches)} matches together</span>
          <span class="fc-l">Chemistry</span><span class="fc-t">${words(p100(d.chemistry_pct))}</span><span class="fc-l">Wall passes</span><span class="fc-t">${words(p100(d.one_twos_pct))}</span>
          <span class="fc-l">Third man</span><span class="fc-t">${words(p100(d.third_man_pct))}</span><span class="fc-l">The test's call</span><span class="fc-t">${esc(call(d))}</span>` })).join("")}</div>
      <p class="note">Spots are each position group's usual place on its side, not tracked positions. StatsBomb open data, credit StatsBomb.</p>`;
  }

  // design 5 (gold/partners_interplay.py): what two players do together, across lines, from their passes. The pair's
  // own signal (G2) against its gate, the chronological check, and the duos named before the run (G3) by percentile
  // within their type. Every sentence is built from the report's figures.
  function interplay(p) {
    if (!p || !p.G1_signature) return "";
    const LBL = { links: "Passes between them", chemistry: "Chemistry, beyond volume", one_twos: "Wall passes", third_man: "Third man",
      b_wider: "Who holds the width", b_higher: "Who goes higher" };
    const g1 = p.G1_signature, g2 = p.G2_pair_own || {}, g3 = p.G3_known_duos || {}, ch = p.chrono || {};
    const f = (x) => (x == null ? "–" : x.toFixed(2)), sbs = (o) => Object.values(o).map((x) => x.spearman_brown ?? -1);
    const g1min = Math.min(...sbs(g1)), own = Object.entries(g2).map(([k, x]) => `${LBL[k].toLowerCase()} ${f(x.spearman_brown)}`).join(", ");
    const f3 = (x) => (x == null ? "–" : x.toFixed(x >= 0.495 && x < 0.5 ? 3 : 2));   // 0.497 must not read as "falls to 0.50"
    const chrono0 = Object.entries(ch.G2 || {}).map(([k, x]) => `${LBL[k].toLowerCase()} ${x.pass ? "holds at" : "falls to"} ${f3(x.spearman_brown)}`).join("; "), chrono = chrono0.charAt(0).toUpperCase() + chrono0.slice(1);
    const apart = ch.G2_different_seasons || {}, apartAll = Object.values(apart).every((x) => x.pass);
    const duos = (p.duos || []).filter((d) => d.found).sort((a, b) => (b.testable - a.testable) || ((b.chemistry_pct ?? 0) - (a.chemistry_pct ?? 0)));
    const misses = duos.filter((d) => d.testable && !d.top_third);
    const bar = (v) => `<span class="ip-bar"><i style="width:${Math.round((v ?? 0) * 100)}%"></i></span><span class="ip-pct">${v == null ? "–" : Math.round(v * 100)}</span>`;
    const rows = duos.map((d) => `<tr class="${d.testable ? (d.top_third ? "top" : "below") : "nt"}"><th scope="row">${esc(d.duo)}<span>${esc(d.team)} · ${esc(d.type)} · ${d.matches} matches</span></th>
        <td>${bar(d.chemistry_pct)}</td><td>${bar(d.one_twos_pct)}</td><td>${bar(d.third_man_pct)}</td>
        <td class="ip-call">${d.testable ? (d.top_third ? "top third" : "below") : `not testable (${d.pool_pairs} of its type)`}</td></tr>`).join("");
    return `<div class="cn-partners">${gateSvg(g2, LBL, `How well what stays with the pair, each player's own habits taken out, on one half of the matches agrees with the other half, against the pass mark of 0.5: ${Object.values(g2).filter((x) => x.pass).length} of ${Object.keys(g2).length} reach it`)}
      ${verdictBlock(`Tested ${esc((p.built || "").slice(0, 10))} · ${esc(p.data || "")}`, `What stays with the pair, each player's own habits taken out, ${Object.values(g2).every((x) => x.pass) ? "still comes back" : "does not always come back"} from one half of the matches to the other; <b>${g3.top_third} of ${g3.testable}</b> of the duos football remembers sit in the top third of their type on chemistry.`, `
        <p>The question: when two players pass to each other, is the way they link up a property of the pair, or noise? We took <b>${num(p.pairs)}</b> pairs from <b>${num(p.matches)}</b> league matches, every line with every line, measured how each pair links up on its odd-numbered matches and again on its even ones, and compared. 1 means the halves agree perfectly, 0 that they have nothing in common; we asked for at least 0.5. ${g1min >= 0.5 ? "Every measure clears it" : "Not every measure clears it"} (the weakest scores ${f(g1min)}). Then each player's own habits, what he does with anyone, are taken out, and what stays with the pair ${Object.values(g2).every((x) => x.pass) ? "still comes back" : "does not always come back"}: ${own}.</p>
        <p>A further check, run after the pass mark was set: earlier matches against later ones. ${chrono}. On the ${num(ch.pairs_different_seasons || 0)} pairs whose halves fall in different seasons, ${apartAll ? "all three still agree" : "not all three still agree"} (${Object.entries(apart).map(([k, x]) => `${LBL[k].toLowerCase()} ${f(x.spearman_brown)}`).join(", ")}).</p>
        <p>The duos football remembers, named before the run: <b>${g3.top_third} of ${g3.testable}</b> sit in the top third of their type on chemistry; by chance, a third would.${misses.length ? ` Below: ${misses.map((d) => `${esc(d.duo)} (chemistry ${Math.round(d.chemistry_pct * 100)}, wall passes ${Math.round(d.one_twos_pct * 100)}, third man ${Math.round(d.third_man_pct * 100)})`).join("; ")}.` : ""}</p>
        <p>What it can't separate: a coach who builds a link (one side made to overload) from two players who find each other. Tracking would add the runs that the passes only hint at.</p>`)}</div>
      ${duoPitches(duos)}
      <div class="ip-wrap d-expert"><table class="ip-duos"><thead><tr><th scope="col">Duo</th><th scope="col">Chemistry</th><th scope="col">Wall passes</th><th scope="col">Third man</th><th scope="col">Call</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="note">Percentiles among pairs of the same type (positions and flanks) in the same competition, 10+ matches together. StatsBomb open data, credit StatsBomb.</p>`;
  }

  const RULES = [
    ["Point in time", "every row says when it could first be known; a projection only reads what was known then"],
    ["Where it came from", "source and licence on every row; licensed and scraped data never leave the club"],
    ["Minors' data", "an academy's players are mostly under 18: enhanced protection under GDPR, the least data that does the job, and a club's own records stay its own"],
    ["Status, not diagnosis", "availability comes in as available, injured, ill, suspended or away; a diagnosis is refused at the door"],
    ["Tests before the desk", "a part appears on the desk once its test passes; until then it is named here, with its result"],
    ["Benchmarks are not inputs", "market value and game ratings are what the engine is measured against, never what it learns from"],
  ];
  async function connectPage() {
    const [d, meta, sb] = await Promise.all([api("/api/connect"), api("/api/meta"), api("/api/scoreboard")]);
    const inv = d.inventory || { have: [], club_only: [] }, rep = d.connect || {}, cov = rep.desk_coverage || {}, st = sb.stands || {};
    const b = board(inv), nOpen = inv.have.filter((h) => !isPrivate(h.licence)).length, nPriv = inv.have.length - nOpen;
    return () => {
      setNav("data");
      // the page's words. Each question opens with its answer in one plain sentence; the figures come from the files.
      main.innerHTML = `<div class="page-head"><div><h1>Data &amp; Vision</h1>
          <p class="lead">Promesse reads ${inv.have.length} sources: ${nPriv} scraped or licensed for our own research (they stay on this PC) and ${nOpen} open ones we credit. A club's own data would plug in through adapters and sharpen specific parts of it; the table below says which parts, and which of those we have measured.</p></div></div>
        <section class="block" aria-labelledby="cn-a">${sign("", "1. What Promesse holds", "sources, seasons, sizes, open or private", "cn-a")}
          <p class="cn-ans">The match records are the backbone: MatchData's, for ${esc((inv.have.find((h) => /MatchData match/.test(h.source)) || {}).size || "")} from 2021/22 on, and Transfermarkt's careers back to 2012/13. The rest are ratings to test against, and open samples of events and tracking that prove the method.</p>
          ${st.deep ? `<p class="cn-ans">What that data allows: the <b>full reading</b> (two or more seasons of 900+ minutes with match stats, 2021/22 to 2025/26, and a confirmed identity) covers <b>${num(st.deep)}</b> players, <b>${num(st.deep_young)}</b> of them aged 21 or under; everyone else gets the projection.</p>` : ""}
          ${holdTable(inv)}</section>
        <section class="block cn-board-wrap" aria-labelledby="cn-b">${sign("", "2. How each source is used", "from the feed to the call · hover or tab to a source to follow it", "cn-b")}
          <div class="cn-path">${UI.stepper({ label: "From a feed to the call", cls: "step-path", slides: [
            { title: "A feed", html: `<h3>A feed</h3><p>Every source arrives in its own format. Follow one across the board below to see which parts of Promesse it reaches.</p>` },
            { title: "The same few tables", html: `<h3>The same few tables</h3><p>Every source is turned into the same few tables (a match, a person, an action).</p>` },
            { title: "The parts that read them", html: `<h3>The parts that read them</h3><p>Each part of Promesse reads those tables, never a provider's own format.</p>` },
            { title: "The call", html: `<h3>The call</h3><p>Every road ends at the call.</p>` }] })}</div>${b.svg}
          <p class="note">Solid: data in and used. Striped: still coming in. Dashed outline: found, not loaded yet.</p></section>
        <section class="block" aria-labelledby="cn-c">${sign("", "3. What a club could plug in", "its own feeds, through adapters, onto our players", "cn-c")}
          <p class="cn-ans">A club measures far more than any public source. Each feed below has an adapter written and, where a public sample exists, proven on real files. Plugging one in would sharpen the parts named in the table; none of it is claimed until it is measured on that club's data.</p>
          ${sockets(inv)}
          <h3 class="cn-sub">Who is who</h3><p class="cn-ans">A club's player ids meet ours through an open register, so its export lands on our players without guessing. Of the desk's ${num(cov.players || 0)} players, here is how many each provider's id would find on day one.</p>
          <div class="cn-id-grid">${coverage(cov)}<div class="cn-id-note"><p>The bridge is the <b>Reep register</b>: one id per person, with that person's id at 30+ providers, public domain. A club's Wyscout, SkillCorner or Impect export lands on our players by id; the rest go through our own name and birth-date match.</p>
          <p>Some of the register's links are its own name and birth-date matches, each with a confidence; we check every link against our record before an engine uses it. On the samples below, every link checked agrees.</p></div></div>
          <h3 class="cn-sub">Proven on real files</h3><p class="cn-ans">${Object.keys(rep.runs || {}).length} providers' formats went through the same tables (${esc((rep.built || "").slice(0, 10))}): matches read, rows counted, required columns filled, players found.</p>
          <div class="cn-runs">${runs(rep)}</div>
          <h3 class="cn-sub">What each feed would add, and what we measured</h3><p class="cn-ans">One row per part of Promesse. "Measured" means we ran the test on the public data we hold; "named, not run" means the test is written and waits for a club's data. Right picks in 100 is the desk's one unit for ranking skill: out of 100 pairs of young players (one who made it, one who didn't), how many the engine orders correctly; a coin flip gets 50.</p>
          ${clubTable(d.club_table, meta)}
          <h3 class="cn-sub">The rules at the door</h3>
          <div class="cn-rules">${RULES.map(([r, w]) => `<div><h3>${r}</h3><p>${w}</p></div>`).join("")}</div></section>`;
      wire(b.left);
      const STAGE = ["feed", "tables", "modules", "call"];
      $(".cn-board-wrap", main).addEventListener("step", (ev) => { if (ev.target.closest(".step-path")) $(".cn-board", main).dataset.stage = STAGE[ev.detail.i]; });
      return animate;
    };
  }

  function wire(left) {
    const svg = main.querySelector(".cn-board");
    const focus = (i) => {
      svg.classList.toggle("focus", i != null);
      const tables = new Set();
      svg.querySelectorAll(".cn-flow[data-src]").forEach((p) => { const on = p.dataset.src === String(i); p.classList.toggle("hi", on); if (on) tables.add(p.dataset.t); });
      const mods = new Set();
      svg.querySelectorAll(".cn-flow.out").forEach((p) => { const on = tables.has(p.dataset.t); p.classList.toggle("hi", on); if (on) mods.add(p.dataset.m); });
      svg.querySelectorAll(".cn-table").forEach((g) => g.classList.toggle("hi", tables.has(g.dataset.t)));
      svg.querySelectorAll(".cn-mod").forEach((g) => g.classList.toggle("hi", mods.has(g.dataset.m)));
      svg.querySelectorAll(".cn-src").forEach((g) => g.classList.toggle("hi", g.dataset.src === String(i)));
    };
    svg.querySelectorAll(".cn-src").forEach((g) => {
      const i = +g.dataset.src, s = left[i];
      g.addEventListener("pointerenter", (e) => { focus(i); showTip(`<b>${esc(s.name)}</b><br>${esc(s.size)}<br><span class="dim">${esc(s.licence)}</span>`, e.clientX, e.clientY); });
      g.addEventListener("pointermove", (e) => showTip(`<b>${esc(s.name)}</b><br>${esc(s.size)}<br><span class="dim">${esc(s.licence)}</span>`, e.clientX, e.clientY));
      g.addEventListener("pointerleave", () => { focus(null); hideTip(); });
      g.addEventListener("focus", () => focus(i)); g.addEventListener("blur", () => focus(null));
    });
  }

  function animate() {
    if (!window.gsap || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      main.querySelectorAll(".cn-ring .fg").forEach((c) => c.setAttribute("stroke-dasharray", c.style.getPropertyValue("--dash")));
      return;
    }
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (!e.isIntersecting) return; io.unobserve(e.target); const el = e.target;
      if (el.matches(".cn-board")) gsap.from(el.querySelectorAll(".cn-src, .cn-table, .cn-mod"), { opacity: 0, x: -8, duration: 0.5, stagger: 0.02, ease: "power2.out" });
      if (el.matches(".cn-ring")) { const c = el.querySelector(".fg"); gsap.to(c, { attr: { "stroke-dasharray": c.style.getPropertyValue("--dash") }, duration: 1.4, ease: "power2.out" }); }
      if (el.matches(".cn-bars")) gsap.from(el.querySelectorAll(".cn-bar i b"), { scaleX: 0, transformOrigin: "0 50%", duration: 1.1, stagger: 0.06, ease: "power3.out" });
      if (el.matches(".cn-gate")) gsap.from(el.querySelectorAll("rect"), { attr: { width: 0 }, duration: 0.9, stagger: 0.04, ease: "power2.out" });
      if (el.matches(".cn-held, .cn-sockets, .cn-roles")) gsap.from(el.children, { opacity: 0, y: 14, duration: 0.5, stagger: 0.04, ease: "power2.out" });
    }), { threshold: 0.2 });
    main.querySelectorAll(".cn-board, .cn-ring, .cn-bars, .cn-gate, .cn-held, .cn-sockets, .cn-roles").forEach((el) => io.observe(el));
  }

  // Player Combinations (#/combinations): the partners analysis on a page of its own. The answer first:
  // what two players do together (passed every gate), then where he receives beside a partner (part passed), then the
  // first test from match totals, which failed and stays on the record. Same data as Data & Vision (/api/connect).
  async function combinationsPage() {
    const d = await api("/api/connect");
    return () => {
      setNav("combinations");
      // the beta line (a beta feature, still in progress, for this version)
      main.innerHTML = `<div class="page-head"><div><h1>Player Combinations<span class="beta-tag">Beta</span></h1>
          <p class="lead">Which pairs do better together than apart, where on the pitch, and how they combine. A pair's reading shows only when it holds from one half of a season to the other, once each player's own habits are taken out.</p>
          <p class="lead beta-note">Still in progress: it reads StatsBomb's free past seasons, so it shows how the method reads duos football already knows. Today's young players come in a later version, from minutes played together.</p></div></div>
        <section class="block" aria-labelledby="pc-a">${sign("", "What two players do together", "across lines, from their passes", "pc-a")}${interplay(d.interplay)}</section>
        <section class="block" aria-labelledby="pc-b">${sign("", "Where he receives, beside a partner", "with him and without him", "pc-b")}${places(d.places)}</section>
        <section class="block" aria-labelledby="pc-c">${sign("", "The first test: who plays beside him", "from lineups and match totals; it failed, and stays on the record", "pc-c")}${partners(d.partners)}</section>`;
      return animate;
    };
  }

  window.connectPage = connectPage;
  window.combinationsPage = combinationsPage;
})();
