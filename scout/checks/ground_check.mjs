// The Ground inside the stadium page: the integration checks, headless (never a window).
//   1. the model loads and the desk's seats stand on its treads (every seat, a ray down lands on the concrete within 6 cm)
//   2. the camera audit (72 seat flights + seat-to-seat flights) against the model: 0 crossings, 0.45 m clearance
//   3. every clickable part (targets.json, 21) is clicked with the real mouse from its own pose; the camera flies to it, Esc flies back
//   4. the fallback: pointed at a wrong path, the page opens Promesse Light (the flat bowl), drawn, without an error
// Needs the test desk (scout/checks/test_desk.py, :8795). Run from <local path>
//   node ../_research/football/scout/checks/ground_check.mjs [--shots <dir>] [--only audit,seats,parts,fallback]
// Exit code 1 if any check fails.
import { chromium } from "playwright-core";
import fs from "node:fs";

const BASE = "http://127.0.0.1:8795/";
const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const shots = arg("--shots"), only = arg("--only")?.split(",");
const want = (k) => !only || only.includes(k);
const GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
const report = { checks: {}, errors: [] };
let failed = 0;
const record = (name, ok, detail) => { report.checks[name] = { ok, ...detail }; if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${name} ${JSON.stringify(detail)}`); };

async function open(browser, { groundBase, scheme = "light" } = {}) {
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 }, colorScheme: scheme });
  page.on("pageerror", (e) => report.errors.push(`${groundBase ?? "model"}: ${e.message}`));
  page.on("console", (m) => { if (/^stadium/.test(m.text())) console.log("  page:", m.text().slice(0, 300)); });
  page.on("console", (m) => { if (m.type() === "error" && !(groundBase && /404|Failed to load/.test(m.text()))) report.errors.push(`${groundBase ?? "model"}: ${m.text()}`); });
  if (groundBase) await page.addInitScript((b) => { window.__GROUND_BASE = b; }, groundBase);
  await page.addInitScript(() => { try { localStorage.setItem("mode", JSON.stringify("promesse")); } catch (e) {} });          // Promesse mode: the model (no door in a check)
  await page.goto(BASE + "#/discover", { waitUntil: "load", timeout: 120000 });
  await page.waitForSelector("#bowl.is3d", { timeout: 120000 });
  return page;
}
const stadium = (page, fn, arg) => page.evaluate(`(async () => { const s = document.querySelector("#bowl").__stadium; return await (${fn})(s, ${JSON.stringify(arg ?? null)}); })()`);

const browser = await chromium.launch({ channel: "msedge", args: GL });
try {
  if (want("audit") || want("seats") || want("parts") || want("overlay")) {
    const t0 = Date.now();
    const page = await open(browser);
    await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.ground, null, { timeout: 120000 });
    const mode = await stadium(page, "(s) => s.mode()");
    record("model loaded", mode === "model", { mode, seconds: +((Date.now() - t0) / 1000).toFixed(1) });
    if (mode === "model") {
      await page.evaluate(() => { window.gsap.globalTimeline.timeScale(12); return 1; });          // the flights are real, only faster
      if (want("seats")) {
        const r = await stadium(page, "(s) => s.seatsOnTreads()");
        record("seats stand on the model's treads", r.off === 0, r);
        const st = await stadium(page, "(s) => s.stands()");
        report.stands = st;
      }
      if (want("audit")) {
        const a = await stadium(page, "(s) => s.audit()");
        record("seat audit (model)", a.control > 0 && a.crossings === 0 && a.minClear >= 0.45 - 1e-6 && a.tooClose === 0, { seats: a.seats, across: a.across, crossings: a.crossings, minClear: +a.minClear.toFixed(3), tooClose: a.tooClose, control: a.control, bad: a.bad.slice(0, 3) });
        const e = await stadium(page, "(s) => s.auditEnter()");
        record("walk-out audit (model)", e.crossings === 0, { crossings: e.crossings, minClear: +e.minClear.toFixed(3), minY: +e.minY.toFixed(2) });
      }
      if (want("parts")) {
        const names = await stadium(page, "(s) => s.ground().targets.map((t) => t.name)");
        const results = [];
        for (const name of names) {
          const r = { name, point: false, selected: false, back: false, flightAudit: null };
          await stadium(page, "(s, n) => s.selectPart(n, { instant: true })", name);        // stand at its pose (the camera of targets.json)
          const pt = await stadium(page, "(s, n) => s.partPoint(n)", name);
          if (pt) {
            r.point = true;
            await page.mouse.move(pt.x, pt.y);
            await page.mouse.down(); await page.mouse.up();
            await page.waitForFunction((n) => { const s = document.querySelector("#bowl").__stadium; return s.currentPart() === n && !s.busy(); }, name, { timeout: 60000 }).then(() => { r.selected = true; }).catch(() => {});
          }
          r.card = await page.evaluate(() => { const c = document.querySelector(".ground-card"); return c && !c.hidden ? c.querySelector(".gc-title").textContent : null; });
          if (shots && name === "DRESS_screen") await page.screenshot({ path: `${shots}/ground_screen.png` });
          await page.keyboard.press("Escape");
          await page.waitForFunction(() => { const s = document.querySelector("#bowl").__stadium; return s.currentPart() === null && !s.busy(); }, null, { timeout: 60000 }).then(() => { r.back = true; }).catch(() => {});
          r.flightAudit = await stadium(page, "(s, n) => s.auditPart(n)", name);
          results.push(r);
        }
        const bad = results.filter((r) => !r.point || !r.selected || !r.back || !r.card);
        record("every part clicked", results.length === 21 && bad.length === 0, { parts: results.length, clicked: results.filter((r) => r.selected).length, flewBack: results.filter((r) => r.back).length, bad: bad.map((r) => r.name) });
        const crossing = results.filter((r) => r.flightAudit && (r.flightAudit.crossings > 0 || r.flightAudit.minClear < 0.1));
        record("flights to the parts clear the structure (no crossing, 0.1 m at the kit's own poses)", crossing.length === 0, { checked: results.length, bad: crossing.map((r) => ({ n: r.name, ...r.flightAudit })) });
        report.parts = results;
      }
      if (want("overlay")) {                                 // the panels over the picture: Back to the ground, Parts of the ground (open), the card: no overlap, all inside the picture
        await stadium(page, "(s) => { s.selectPart('STAND_W_Defence', { instant: true }); return 1; }");
        await page.evaluate(() => { document.querySelector(".ground-parts").open = true; });
        const rects = await page.evaluate(() => {
          const r = (sel) => { const e = document.querySelector(sel); if (!e || e.hidden) return null; const b = e.getBoundingClientRect(); return { x: b.left, y: b.top, w: b.width, h: b.height }; };
          return { bowl: r("#bowl"), leave: r(".stadium-leave"), parts: r(".ground-parts"), card: r(".ground-card") };
        });
        const names = ["leave", "parts", "card"], bad = [];
        const hit = (a, b) => a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1;
        for (const n of names) { if (!rects[n]) bad.push(n + " missing"); else if (rects[n].x < rects.bowl.x - 1 || rects[n].y < rects.bowl.y - 1 || rects[n].x + rects[n].w > rects.bowl.x + rects.bowl.w + 1 || rects[n].y + rects[n].h > rects.bowl.y + rects.bowl.h + 1) bad.push(n + " outside the picture"); }
        for (let i = 0; i < names.length; i++) for (let j = i + 1; j < names.length; j++) if (rects[names[i]] && rects[names[j]] && hit(rects[names[i]], rects[names[j]])) bad.push(names[i] + " overlaps " + names[j]);
        record("panels over the picture do not overlap", bad.length === 0, { bad, rects });
        await page.evaluate(() => { document.querySelector(".ground-parts").open = false; });
        await page.keyboard.press("Escape");
        await page.waitForFunction(() => { const s = document.querySelector("#bowl").__stadium; return s.currentPart() === null && !s.busy(); }, null, { timeout: 60000 }).catch(() => {});
      }
      if (shots) {                                           // the two screenshots: the wide view by day, and by night
        await stadium(page, "(s) => { s.setView({ az: -0.62, el: 0.4, dist: 205 }); return 1; }");
        await page.waitForTimeout(1500);
        await page.screenshot({ path: `${shots}/ground_day.png` });
        await page.emulateMedia({ colorScheme: "dark" });
        await page.waitForTimeout(2500);
        await page.screenshot({ path: `${shots}/ground_night.png` });
      }
    }
    await page.close();
  }
  if (want("fallback")) {
    // pointed at a wrong path the model cannot load: Promesse Light (the flat bowl) takes its place, drawn, and no script error is raised
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
    await page.addInitScript(() => { try { localStorage.setItem("mode", JSON.stringify("promesse")); } catch (e) {} window.__GROUND_BASE = "/ground-missing"; });
    await page.goto(BASE + "#/discover", { waitUntil: "load", timeout: 120000 });
    await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.view === "light", null, { timeout: 60000 });
    const r = await page.evaluate(() => {
      const w = document.querySelector("#bowl"), c = w.querySelector("#bowl-base"), g = c.getContext("2d");
      const px = g.getImageData(0, 0, c.width, c.height).data; let ink = 0; for (let i = 3; i < px.length; i += 4 * 97) if (px[i] > 0) ink++;
      return { stadiumCanvas: !!w.querySelector("canvas.stadium"), loadingShown: !!w.querySelector(".ground-loading"), is3d: w.classList.contains("is3d"), drawnPixels: ink, alarming: /error|failed|sorry|unable/i.test(w.innerText) };
    });
    record("fallback: a model that cannot load opens Promesse Light", !r.stadiumCanvas && !r.loadingShown && !r.is3d && r.drawnPixels > 500 && !r.alarming, r);
    await page.close();
  }
} finally {
  await browser.close();
}
record("no script errors", report.errors.length === 0, { errors: report.errors.slice(0, 5) });
if (shots) fs.writeFileSync(`${shots}/ground_check.json`, JSON.stringify(report, null, 1));
console.log(failed ? `${failed} checks failed` : "all ground checks passed");
process.exit(failed ? 1 : 0);
