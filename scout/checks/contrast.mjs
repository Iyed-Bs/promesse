// The desk's contrast and keyboard check (the look pass,). For every page, in daylight and under floodlights, it finds every
// visible piece of text, works out its colour and the paint behind it (walking up the page's backgrounds, opacity included) and prints
// the contrast ratio. Text must reach 4.5:1; large text (24 px, or 18.7 px bold) and graphic marks need 3:1.
// Then it tabs through each page and reports any focus stop with no visible focus ring.
//   node contrast.mjs [--out <file>] [--only route,route]     (from <local path> test desk on :8795 running)
// Exit code 1 when any pair is below its mark. Text laid on a gradient or picture is judged on its plain colour: if that passes it is marked ok*, if it fails it is listed SKIP for a look with the eyes, never guessed.
import { chromium } from "playwright-core";
import fs from "node:fs";

const BASE = "http://127.0.0.1:8795/";
// the pages checked (same routes as desk_check.mjs)
const ROUTES = ["", "discover", "boards", "compare", "lists", "combinations", "teams", "dives", "dive/barcelona", "club/barcelona", "method", "data", "player/926993"];
const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const only = arg("--only")?.split(","), outFile = arg("--out");

// runs in the page: every text-bearing element with its colour, its backdrop and its size
const scan = () => {
  const cv = document.createElement("canvas"); cv.width = cv.height = 1; const cx = cv.getContext("2d", { willReadFrequently: true });
  const rgba = (css) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = "#000"; cx.fillStyle = css; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (f, b) => [0, 1, 2].map((i) => f[i] * f[3] + b[i] * (1 - f[3])).concat([1]);
  const out = [], seen = new Set();
  const els = [...document.querySelectorAll("main *, .fascia *, .subnav *, .drawer *, .foot *")];
  for (const el of els) {
    const isSvgText = el instanceof SVGTextElement || el instanceof SVGTSpanElement;
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!own) continue;
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (cs.display === "none" || cs.visibility === "hidden" || r.width < 1 || r.height < 1) continue;
    let alpha = 1, stack = [], image = false, n = el, hidden = false, opaque = false;
    // SVG text sits on the shapes drawn under it (a pitch, a bar): take their fills first, topmost first
    if (isSvgText) {
      const mid = [r.left + r.width / 2, r.top + r.height / 2];
      // shapes drawn before the text whose box holds its middle point, topmost first (pointer-events: none shapes included)
      const under = [...el.ownerSVGElement.querySelectorAll("rect, path, circle, ellipse, polygon")].filter((u) => {
        if (!(el.compareDocumentPosition(u) & Node.DOCUMENT_POSITION_PRECEDING)) return false;
        const q = u.getBoundingClientRect(); return mid[0] >= q.left && mid[0] <= q.right && mid[1] >= q.top && mid[1] <= q.bottom; }).reverse();
      for (const u of under) {
        if (u === el || !(u instanceof SVGGeometryElement)) continue;
        if (getComputedStyle(u).fill === "none") continue;
        const f = rgba(getComputedStyle(u).fill); const o = parseFloat(getComputedStyle(u).fillOpacity);
        if (getComputedStyle(u).fill.startsWith("url(")) { image = true; break; }
        f[3] *= o; if (f[3] > 0) { stack.push(f); if (f[3] >= 1) { opaque = true; break; } }
      }
    }
    for (; n && n.nodeType === 1 && !opaque; n = n.parentElement) {
      const c = getComputedStyle(n);
      if (c.display === "none") { hidden = true; break; }
      alpha *= parseFloat(c.opacity);
      if (c.backgroundImage !== "none" && n !== document.body && n !== document.documentElement) image = true;
      // paint laid by a pseudo-element (a hero's gradient) cannot be sampled: skipped, never guessed
      for (const ps of ["::before", "::after"]) { const q = getComputedStyle(n, ps); if (q.content !== "none" && q.position === "absolute" && (q.backgroundImage !== "none" || rgba(q.backgroundColor)[3] > 0) && parseFloat(q.opacity) > 0) image = true; }
      const bg = rgba(c.backgroundColor); if (bg[3] > 0) { stack.push(bg); if (bg[3] >= 1) break; }
    }
    if (hidden || alpha === 0) continue;   // not drawn: a flip card's turned-away face
    let back = [255, 255, 255, 1];
    const bodyBg = rgba(getComputedStyle(document.body).backgroundColor); if (bodyBg[3] > 0) back = [bodyBg[0], bodyBg[1], bodyBg[2], 1];
    for (let i = stack.length - 1; i >= 0; i--) back = over(stack[i], back);
    const fgRaw = rgba(isSvgText ? cs.fill : cs.color); fgRaw[3] *= alpha;
    const fg = over(fgRaw, back);
    const lum = (c) => { const k = c.slice(0, 3).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * k[0] + 0.7152 * k[1] + 0.0722 * k[2]; };
    const [a, b] = [lum(fg), lum(back)], ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const px = parseFloat(cs.fontSize) * (isSvgText ? (el.ownerSVGElement.getBoundingClientRect().width / (el.ownerSVGElement.viewBox.baseVal.width || 1)) : 1);
    const large = px >= 24 || (px >= 18.66 && parseInt(cs.fontWeight) >= 700);
    const key = [fg.map(Math.round).join(","), back.map(Math.round).join(","), large, image].join("|");
    if (seen.has(key)) continue; seen.add(key);
    out.push({ ratio: +ratio.toFixed(2), large, image, fg: `rgb(${fg.slice(0, 3).map(Math.round)})`, bg: `rgb(${back.slice(0, 3).map(Math.round)})`,
      text: (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40), sel: el.tagName.toLowerCase() + (el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\s+/)[0] : "") });
  }
  return out;
};

const browser = await chromium.launch({ channel: "msedge" });
const lines = [], fails = [];
let skipped = 0, checked = 0;
for (const [theme, scheme] of [["day", "light"], ["night", "dark"]]) {
  const pairs = new Map(), noRing = [];
  for (const route of ROUTES) {
    if (only && !only.includes(route)) continue;
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, colorScheme: scheme, reducedMotion: "reduce" });   // final layout: nothing waits to be revealed (the reveal animations)
    await page.addInitScript((t) => { localStorage.setItem("kickoff", JSON.stringify(t)); localStorage.setItem("depth", JSON.stringify("expert")); }, theme);
    await page.addInitScript(() => { try { localStorage.setItem("mode", JSON.stringify("light")); } catch (e) {} });
    await page.goto(BASE + "#/" + route, { waitUntil: "networkidle", timeout: 120000 }).catch(() => {});
    await page.waitForTimeout(2600);   // let the page's motion settle (digits flipping, lines drawing)
    for (const p of await page.evaluate(scan)) {
      const k = `${p.fg}|${p.bg}|${p.large}`;
      if (!pairs.has(k)) pairs.set(k, { ...p, pages: new Set() });
      pairs.get(k).pages.add(route || "home");
    }
    // keyboard: tab through the first 16 stops and report any with no visible ring
    for (let i = 0; i < 16; i++) {
      await page.keyboard.press("Tab");
      await page.waitForTimeout(400);   // a ring may fade in (stroke-width transitions): read it once it has settled
      const probe = () => page.evaluate(() => { const e = document.activeElement; if (!e || e === document.body) return null; const c = getComputedStyle(e);
        return { tag: e.tagName.toLowerCase() + (e.className && typeof e.className === "string" ? "." + e.className.trim().split(/\s+/)[0] : ""), ring: (c.outlineStyle !== "none" && parseFloat(c.outlineWidth) > 0) || c.boxShadow !== "none"
          // a focusable SVG group shows its ring as a heavier outline on its first shape
          || (e instanceof SVGElement && parseFloat(getComputedStyle(e.querySelector("rect, path, circle") || e).strokeWidth) >= 2.4) }; });
      let r = await probe();
      if (r && !r.ring) { await page.waitForTimeout(1500); r = await probe(); }   // a slow machine may still be mid-fade: look once more
      if (r && !r.ring) noRing.push(`#/${route} ${r.tag}`);
    }
    await page.close();
  }
  lines.push(`\n== ${theme} (${scheme}): ${pairs.size} text/background pairs ==`);
  for (const p of [...pairs.values()].sort((a, b) => a.ratio - b.ratio)) {
    const need = p.large ? 3 : 4.5, ok = p.ratio >= need;
    if (p.image && !ok) { skipped++; lines.push(`SKIP ${p.ratio.toFixed(2)} (on a gradient or picture) ${p.fg} on ${p.bg} "${p.text}" ${p.sel}`); continue; }
    checked++;
    const row = `${ok ? (p.image ? "ok* " : "ok  ") : "FAIL"} ${p.ratio.toFixed(2)} (needs ${need}) ${p.fg} on ${p.bg}${p.large ? " large" : ""} "${p.text}" ${p.sel} [${[...p.pages].slice(0, 3).join(", ")}]`;
    lines.push(row); if (!ok) fails.push(`${theme}: ${row}`);
  }
  const ring = [...new Set(noRing)];
  lines.push(`keyboard (${theme}): ${ring.length ? "no visible focus ring on " + ring.join("; ") : "every tab stop shows a focus ring"}`);
  if (ring.length) fails.push(`keyboard ${theme}: ${ring.join("; ")}`);
}
await browser.close();
if (outFile) fs.writeFileSync(outFile, lines.join("\n"));
console.log(`${checked} pairs checked, ${skipped} skipped (gradient or picture), ${fails.length} below their mark`);
for (const f of fails) console.log(f);
process.exit(fails.length ? 1 : 0);
