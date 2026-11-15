// What Promesse (the Ground's model) costs a desktop, measured headless (never a window)..
//   - opening -> the model on screen (data-ground="model" on the bowl), unthrottled, in a fresh profile (nothing cached)
//   - frame time while the camera orbits for 5 s: median and 95th percentile
//   - the longest main-thread task after first paint (Long Tasks API: only tasks over 50 ms are reported)
//   - the JS heap, and the graphics card the browser really used
// "Too heavy" if any of: model on screen after more than 4 s, median frame over 20 ms (under 50 frames a second), a task over 500 ms.
// Needs the test desk (scout/checks/test_desk.py, :8795). Run from <local path>
//   node ../_research/football/scout/checks/load_profile.mjs [--soft] [--out file.json]      (--soft: software GL, like the other checks)
import { chromium } from "playwright-core";
import fs from "node:fs";

const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const soft = process.argv.includes("--soft"), outFile = arg("--out");
const BASE = "http://127.0.0.1:8795/";
const SOFT = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
const HARD = ["--ignore-gpu-blocklist", "--enable-gpu-rasterization", "--enable-precise-memory-info", "--use-angle=d3d11"];

const browser = await chromium.launch({ channel: "msedge", args: soft ? [...SOFT, "--enable-precise-memory-info"] : HARD });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, colorScheme: "light" });   // a new context = a fresh profile: no cache, no storage
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.addInitScript(() => {
  localStorage.setItem("mode", JSON.stringify("promesse"));        // skip the door: measure the model itself
  window.__long = []; window.__paint = {};
  new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push([Math.round(e.startTime), Math.round(e.duration)]))).observe({ type: "longtask", buffered: true });
  new PerformanceObserver((l) => l.getEntries().forEach((e) => { window.__paint[e.name] = Math.round(e.startTime); })).observe({ type: "paint", buffered: true });
});
const cdp = await ctx.newCDPSession(page);
await cdp.send("Performance.enable");
let modelBytes = 0;
page.on("response", async (r) => { if (/the_ground\.glb/.test(r.url())) { try { modelBytes = (await r.body()).length; } catch { /* streamed */ } } });

const t0 = Date.now();
await page.goto(BASE + "#/discover", { waitUntil: "commit" });
await page.waitForFunction(() => document.querySelector("#bowl")?.__stadium, null, { timeout: 120000, polling: 50 });
const tStadium = Date.now() - t0;
await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.ground === "model" || document.querySelector("#bowl")?.dataset.view === "light", null, { timeout: 120000, polling: 50 });
const tModel = Date.now() - t0;
const view = await page.evaluate(() => document.querySelector("#bowl").dataset.ground || document.querySelector("#bowl").dataset.view);
await page.waitForTimeout(1500);                                   // let the seats and the first frames settle

// the orbit: 5 s of rAF frame times while the camera swings round
const frames = await page.evaluate(() => new Promise((done) => {
  const s = document.querySelector("#bowl").__stadium, dts = [];
  let last = performance.now(); const start = last, az0 = -0.62;
  const tick = (now) => {
    dts.push(now - last); last = now;
    s.setView({ az: az0 + ((now - start) / 5000) * Math.PI });
    if (now - start < 5000) requestAnimationFrame(tick); else done(dts);
  };
  requestAnimationFrame(tick);
}));
const sorted = [...frames].sort((a, b) => a - b), q = (p) => +sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))].toFixed(1);
const info = await page.evaluate(() => {
  const gl = document.createElement("canvas").getContext("webgl2"), ext = gl?.getExtension("WEBGL_debug_renderer_info");
  return { long: window.__long, paint: window.__paint, renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null, heapMB: +(performance.memory.usedJSHeapSize / 1048576).toFixed(1) };
});
const m = Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map((x) => [x.name, x.value]));
const fcp = info.paint["first-contentful-paint"] ?? 0;
const after = info.long.filter(([start]) => start >= fcp), longest = after.reduce((a, [, d]) => Math.max(a, d), 0);
const report = {
  mode: soft ? "software GL (swiftshader)" : "hardware GL (d3d11)", renderer: info.renderer, view,
  firstContentfulPaintMs: fcp, desktopReadyMs: tStadium, modelOnScreenMs: tModel, modelMB: +(modelBytes / 1048576).toFixed(1),
  frames: frames.length, frameMedianMs: q(0.5), frameP95Ms: q(0.95), framesPerSecond: +(1000 / q(0.5)).toFixed(0),
  longestTaskAfterFirstPaintMs: longest, longTasksOver50ms: after.length, jsHeapMB: info.heapMB, cdpHeapUsedMB: +(m.JSHeapUsedSize / 1048576).toFixed(1), errors,
};
report.tooHeavy = { modelOver4s: tModel > 4000, medianOver20ms: report.frameMedianMs > 20, taskOver500ms: longest > 500 };
report.verdict = Object.values(report.tooHeavy).some(Boolean) ? "TOO HEAVY" : "not too heavy";
console.log(JSON.stringify(report, null, 1));
if (outFile) fs.writeFileSync(outFile, JSON.stringify(report, null, 1));
await browser.close();
