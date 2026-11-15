// Names what each long task (over 50 ms) of the Ground's arrival is doing: a CPU sampling profile of the whole load,
// cut into the windows of the long tasks, each window summed by function (self time)..
//   node ../_research/football/scout/checks/load_trace.mjs [--soft] [--out file.json]     (from <local path>)
// Needs the test desk on :8795 (scout/checks/test_desk.py). Headless only.
import { chromium } from "playwright-core";
import fs from "node:fs";

const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const soft = process.argv.includes("--soft"), outFile = arg("--out");
const BASE = "http://127.0.0.1:8795/";
const SOFT = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
const HARD = ["--ignore-gpu-blocklist", "--enable-gpu-rasterization", "--use-angle=d3d11"];
const browser = await chromium.launch({ channel: "msedge", args: soft ? SOFT : HARD });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, colorScheme: "light" });
const page = await ctx.newPage();
await page.addInitScript(() => {
  localStorage.setItem("mode", JSON.stringify("promesse"));
  window.__long = [];
  new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push([e.startTime, e.duration]))).observe({ type: "longtask", buffered: true });
});
const cdp = await ctx.newCDPSession(page);
await cdp.send("Profiler.enable");
await cdp.send("Profiler.setSamplingInterval", { interval: 200 });   // microseconds
await cdp.send("Profiler.start");
await page.goto(BASE + "#/discover", { waitUntil: "commit" });
await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.ground === "model", null, { timeout: 120000, polling: 50 });
await page.waitForTimeout(2500);
const { profile } = await cdp.send("Profiler.stop");
const long = await page.evaluate(() => window.__long);
const nodes = new Map(profile.nodes.map((n) => [n.id, n]));
// sample times (profile.startTime is in microseconds on the monotonic clock; performance.now() origin differs, so align by the long tasks' count of samples)
let t = profile.startTime; const samples = profile.samples.map((id, i) => { t += profile.timeDeltas[i]; return { id, t: t / 1000 }; });
const origin = await page.evaluate(() => performance.timeOrigin);   // not comparable with the profiler clock; use the first sample as 0 instead
const t0 = samples[0].t;
const parent = new Map(); profile.nodes.forEach((n) => (n.children || []).forEach((c) => parent.set(c, n.id)));
const chain = (id) => { const o = []; for (let i = 0; id && i < 8; i++) { const n = nodes.get(id); o.push(`${n.callFrame.functionName || "(anon)"}@${n.callFrame.url.split("/").pop()}:${n.callFrame.lineNumber + 1}:${n.callFrame.columnNumber}`); id = parent.get(id); } return o.join(" < "); };
const label = (n) => `${n.callFrame.functionName || "(anon)"} ${n.callFrame.url.split("/").pop()}:${n.callFrame.lineNumber + 1}`;
// the navigation starts a little after the profiler: align by the end of the last sample against the page's now
const nowEnd = await page.evaluate(() => performance.now());
const shift = samples.at(-1).t - nowEnd;       // profiler ms minus page ms
const out = [];
for (const [start, dur] of long) {
  if (dur < 50) continue;
  const a = start + shift, b = start + dur + shift, self = new Map(), heavy = new Map();
  samples.forEach((s, i) => { if (s.t >= a && s.t <= b) { const n = nodes.get(s.id); const k = label(n); self.set(k, (self.get(k) || 0) + (profile.timeDeltas[i] / 1000)); heavy.set(s.id, (heavy.get(s.id) || 0) + profile.timeDeltas[i] / 1000); } });
  const hid = [...heavy].sort((x, y) => y[1] - x[1])[0]?.[0];
  out.push({ startMs: Math.round(start), durMs: Math.round(dur), heaviestChain: hid ? chain(hid) : null, top: [...self].sort((x, y) => y[1] - x[1]).slice(0, 6).map(([k, v]) => `${v.toFixed(0)} ms  ${k}`) });
}
console.log(JSON.stringify(out, null, 1));
if (outFile) fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
await browser.close();
