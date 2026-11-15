// The layout check ("a sentence overlaps the one next to it, gets hidden behind something, gets split at
// the end"). For every page and view it measures the text as the browser lays it out and reports:
//   overlap  - two pieces of text drawn over each other (HTML or SVG labels), more than a sliver;
//   covered  - text with something visible drawn on top of it (a box, a chart mark, a sticky panel);
//   clipped  - text cut by a box that hides overflow (overflow hidden/clip, an SVG's edge, an ellipsis, a line clamp);
//   split    - a word broken across two lines (letters on both sides of the break);
//   widow    - a heading or label whose last line holds a single short word (soft: reported, not failing).
// Final layout only: reduced motion, so nothing is caught mid-animation. Headless Edge, never a window.
//
//   node layout_check.mjs [--base http://127.0.0.1:8795/] [--routes "#/,#/method"] [--out report.json]
// (run from <local path> for playwright-core). Exit 1 when any overlap, covered, clipped or split.
// For a static page: --base http://127.0.0.1:8793/ --routes index.html
// From Git Bash, prefix MSYS_NO_PATHCONV=1 when passing --routes, or "#/" is rewritten into a Windows path.
// Baseline before the fixes: scout/checks/out/layout-desk-before.json (18 page views with faults).
import { chromium } from "playwright-core";
import { writeFileSync } from "node:fs";

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg("--base", "http://127.0.0.1:8795/");
// the desk's pages (keep in step with desk_check.mjs)
const ROUTES = arg("--routes", "#/,#/discover,#/boards,#/compare,#/lists,#/combinations,#/teams,#/dives,#/dive/barcelona,#/club/barcelona,#/method,#/data,#/player/926993").split(",");
const OUT = arg("--out", null);
const VIEWS = [  // name, viewport, colour scheme, the desk's depth (Glance / Scout / Expert)
  ["desk", { width: 1440, height: 900 }, "light", "scout"],
  ["laptop-expert", { width: 1280, height: 760 }, "light", "expert"],
  ["phone-night", { width: 390, height: 844 }, "dark", "scout"],
];

// runs inside the page: measures every text node's line boxes, then tests them
function audit() {
  const out = { overlap: [], covered: [], clipped: [], split: [], widow: [] };
  const path = (el) => { const a = []; for (let e = el; e && e !== document.body && a.length < 4; e = e.parentElement)
    a.unshift(e.tagName.toLowerCase() + (e.classList.length ? "." + [...e.classList].slice(0, 2).join(".") : "")); return a.join(" > "); };
  const hid = new Map();
  const isHidden = (el) => { if (hid.has(el)) return hid.get(el); let h = false;
    for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e); if (s.visibility === "hidden" || s.opacity === "0" || s.display === "none") { h = true; break; } }
    hid.set(el, h); return h; };
  const fixedOf = (el) => { for (let e = el; e && e !== document.documentElement; e = e.parentElement) { const p = getComputedStyle(e).position; if (p === "fixed" || p === "sticky") return e; } return null; };
  // a box that hides nothing: transparent HTML with no text of its own, or an SVG shape with no fill and no stroke
  const seeThrough = (e) => { const s = getComputedStyle(e);
    if (s.opacity === "0" || s.visibility === "hidden") return true;
    if (e instanceof SVGElement) return e.tagName === "svg" || e.tagName === "g" || ((s.fill === "none" || s.fill === "transparent" || s.fill === "rgba(0, 0, 0, 0)" || +s.fillOpacity === 0) && (s.stroke === "none" || +s.strokeOpacity === 0));
    return (s.backgroundColor === "rgba(0, 0, 0, 0)" || s.backgroundColor === "transparent") && s.backgroundImage === "none" && !e.tagName.match(/^(IMG|CANVAS|VIDEO|INPUT|SELECT|TEXTAREA)$/); };
  // screen-reader-only text (a 1 px clipped box) is invisible by design: not part of the layout
  const srOnly = (el) => { for (let e = el, k = 0; e && k < 4; e = e.parentElement, k++) { const s = getComputedStyle(e);
    if (e.matches(".visually-hidden, .sr-only") || (s.position === "absolute" && (/rect\(0/.test(s.clip) || /inset\(50%/.test(s.clipPath) || (parseFloat(s.width) <= 1 && parseFloat(s.height) <= 1)))) return true; } return false; };
  const snip = (it) => ({ text: it.n.nodeValue.trim().replace(/\s+/g, " ").slice(0, 70), where: path(it.el) });

  // text inside a closed <details> (other than its summary) is not drawn: the browser still reports a box for it, so skip it
  const closedDetails = (el) => { const d = el.closest("details:not([open])"); return !!d && !el.closest("summary"); };
  // painting is what matters here, not clicking: an SVG label with pointer-events:none must still count as the thing on top
  const st = document.createElement("style"); st.textContent = "svg text, svg tspan { pointer-events: visiblePainted !important; }"; document.head.appendChild(st);
  const items = [], sx = scrollX, sy = scrollY;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: (n) => (n.nodeValue.trim().length > 1 ? 1 : 2) });
  for (let n; (n = walker.nextNode()); ) {
    const el = n.parentElement;
    if (!el || /^(SCRIPT|STYLE|NOSCRIPT|TITLE|OPTION|TEMPLATE)$/.test(el.tagName) || el.closest("dialog:not([open]), [hidden]") || closedDetails(el) || isHidden(el) || srOnly(el)) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const rects = [...r.getClientRects()].filter((q) => q.width > 1 && q.height > 1).map((q) => ({ x: q.left + sx, y: q.top + sy, w: q.width, h: q.height }));
    if (rects.length) items.push({ n, el, rects, fixed: !!fixedOf(el) });
  }

  // overlap: line boxes of two different text nodes sharing more than 30 % of the smaller one
  const flat = [];
  items.forEach((it, i) => { if (!it.fixed) it.rects.forEach((q) => flat.push({ i, ...q })); });
  flat.sort((a, b) => a.y - b.y);
  const pairs = new Set();
  for (let a = 0; a < flat.length; a++) {
    const A = flat[a];
    for (let b = a + 1; b < flat.length && flat[b].y < A.y + A.h; b++) {
      const B = flat[b]; if (A.i === B.i) continue;
      const ix = Math.min(A.x + A.w, B.x + B.w) - Math.max(A.x, B.x), iy = Math.min(A.y + A.h, B.y + B.h) - Math.max(A.y, B.y);
      if (ix <= 2 || iy <= 2 || ix * iy < 0.3 * Math.min(A.w * A.h, B.w * B.h)) continue;
      const key = Math.min(A.i, B.i) + "|" + Math.max(A.i, B.i); if (pairs.has(key)) continue; pairs.add(key);
      out.overlap.push({ a: snip(items[A.i]), b: snip(items[B.i]), at: [Math.round(A.x), Math.round(A.y)] });
    }
  }

  // covered: at each line's centre, the topmost visible thing must be the text itself (or its own box)
  const H = innerHeight, total = document.documentElement.scrollHeight, done = new Set();
  for (let top = 0; top < total; top += Math.max(200, H - 120)) {
    scrollTo(0, top);
    items.forEach((it, i) => {
      if (it.fixed || done.has(i)) return;
      for (const q of it.rects) {
        const cx = q.x + q.w / 2 - scrollX, cy = q.y + q.h / 2 - scrollY;
        if (cy < 0 || cy > H || cx < 0 || cx > innerWidth) continue;
        for (const e of document.elementsFromPoint(cx, cy)) {
          if (it.el.contains(e) || e.contains(it.el)) break;                     // reached the text: visible
          if (fixedOf(e)) break;                                                 // under the sticky chrome: scrolled past, fine
          if (seeThrough(e)) continue;
          done.add(i); out.covered.push({ ...snip(it), by: path(e) }); return;
        }
      }
    });
  }
  scrollTo(sx, sy);

  // clipped: a line box running past an ancestor that hides overflow, or an ellipsis that cut the text
  items.forEach((it) => {
    if (it.fixed) return;
    const cs = getComputedStyle(it.el);
    if (cs.textOverflow === "ellipsis" && it.el.scrollWidth > it.el.clientWidth + 1) { out.clipped.push({ ...snip(it), why: "ellipsis" }); return; }
    for (let e = it.el.parentElement; e && e !== document.body; e = e.parentElement) {
      const s = getComputedStyle(e), clip = /hidden|clip/.test(s.overflowX + s.overflowY) || e.tagName === "svg";
      if (!clip || /auto|scroll/.test(s.overflowX + s.overflowY)) continue;
      const b = e.getBoundingClientRect(), bx = b.left + sx, by = b.top + sy;
      const cut = it.rects.some((q) => q.x < bx - 2 || q.y < by - 2 || q.x + q.w > bx + b.width + 2 || q.y + q.h > by + b.height + 2);
      if (cut) { out.clipped.push({ ...snip(it), why: "cut by " + path(e) }); return; }
    }
  });

  // split: a line break with a letter or digit on both sides
  items.forEach((it) => {
    if (it.rects.length < 2 || it.n.nodeValue.length > 800) return;
    const t = it.n.nodeValue, r = document.createRange(); let prev = null;
    for (let k = 0; k < t.length; k++) {
      r.setStart(it.n, k); r.setEnd(it.n, k + 1); const q = r.getClientRects()[0]; if (!q) continue;
      if (prev !== null && q.top > prev + 2 && k > 0 && /[\p{L}\p{N}]/u.test(t[k]) && /[\p{L}\p{N}]/u.test(t[k - 1])) {
        const w = t.slice(Math.max(0, t.lastIndexOf(" ", k) + 1), (t.indexOf(" ", k) + 1 || t.length + 1) - 1);
        out.split.push({ ...snip(it), word: w }); return; }
      prev = q.top;
    }
  });

  // widow (soft): a heading or label ending on a lone short word
  document.querySelectorAll("h1, h2, h3, figcaption > b, .sign h2, .lead").forEach((h) => {
    if (isHidden(h)) return;
    const r = document.createRange(); r.selectNodeContents(h);
    const lines = [...r.getClientRects()].reduce((m, q) => { const k = Math.round(q.top); m[k] = (m[k] || 0) + q.width; return m; }, {});
    const ws = Object.values(lines); if (ws.length < 2) return;
    if (ws[ws.length - 1] < 0.18 * Math.max(...ws)) out.widow.push({ text: h.textContent.trim().slice(0, 70), where: path(h) });
  });
  return out;
}

const browser = await chromium.launch({ channel: "msedge" });
const report = [];
let failing = 0;
for (const route of ROUTES) {
  for (const [view, vp, scheme, depth] of VIEWS) {
    const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme, reducedMotion: "reduce" });
    await ctx.addInitScript(([d, t]) => { try { localStorage.setItem("depth", JSON.stringify(d)); localStorage.setItem("kickoff", JSON.stringify(t)); } catch {} },
      [depth, scheme === "dark" ? "night" : "day"]);
    const page = await ctx.newPage();
    await page.addInitScript(() => { try { localStorage.setItem("mode", JSON.stringify("light")); } catch (e) {} });
    await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 120000 }).catch(() => {});
    await page.waitForTimeout(2500);
    const r = await page.evaluate(audit).catch((e) => ({ error: String(e) }));
    const n = r.error ? -1 : r.overlap.length + r.covered.length + r.clipped.length + r.split.length;
    if (n) failing++;
    report.push({ route, view, ...r });
    console.log(`${n ? "FAIL" : "ok  "} ${route} ${view}: ${r.error ? r.error : `overlap ${r.overlap.length}, covered ${r.covered.length}, clipped ${r.clipped.length}, split ${r.split.length}, widow ${r.widow.length}`}`);
    await ctx.close();
  }
}
await browser.close();
if (OUT) writeFileSync(OUT, JSON.stringify(report, null, 1));
console.log(failing ? `${failing} page views with layout faults` : "no layout faults");
process.exit(failing ? 1 : 0);
