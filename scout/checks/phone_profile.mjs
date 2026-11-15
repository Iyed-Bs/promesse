// Page weight and first paint of the stadium page (#/discover) on a phone-class profile, headless and throttled, and, for
// comparison, the same page on a desktop that takes the model. Numbers go to stdout and (with --out) to a JSON file.
//   phone:    390x844 at 3x, touch, CPU 4x slower, network "fast 4G" (1.6 Mbit/s down, 150 ms round trip)
//   laptop:   1400x900, CPU 4x slower, the same network: what a modest laptop does with the 13.7 MB model
//   desktop:  1400x900, no throttle (the reference)
// Needs the test desk (:8795). Run from <local path>
//   node ../../_research/football/scout/checks/phone_profile.mjs [--out file.json] [--only phone,laptop,desktop]
import { chromium } from "playwright-core";
import fs from "node:fs";

const BASE = "http://127.0.0.1:8795/";
const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const out = arg("--out"), only = arg("--only")?.split(",");
const GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
const NET = { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (0.75 * 1024 * 1024) / 8 };
const PROFILES = {
  phone: { ctx: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true }, cpu: 4, net: NET, waitModel: false },
  laptop: { ctx: { viewport: { width: 1400, height: 900 } }, cpu: 4, net: NET, waitModel: true },
  desktop: { ctx: { viewport: { width: 1400, height: 900 } }, cpu: 1, net: null, waitModel: true },
};

const browser = await chromium.launch({ channel: "msedge", args: GL });
const results = {};
for (const [name, P] of Object.entries(PROFILES)) {
  if (only && !only.includes(name)) continue;
  const context = await browser.newContext(P.ctx);
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: P.cpu });
  if (P.net) await cdp.send("Network.emulateNetworkConditions", P.net);
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  let bytes = 0, requests = 0, groundBytes = 0, groundRequests = 0;
  const urls = new Map();
  cdp.on("Network.requestWillBeSent", (e) => { urls.set(e.requestId, e.request.url); requests++; if (/\/ground\//.test(e.request.url)) groundRequests++; });
  cdp.on("Network.loadingFinished", (e) => { bytes += e.encodedDataLength; if (/\/ground\//.test(urls.get(e.requestId) || "")) groundBytes += e.encodedDataLength; });
  await page.addInitScript(() => {
    window.__paint = {};
    new PerformanceObserver((l) => l.getEntries().forEach((e) => { window.__paint[e.name] = e.startTime; })).observe({ type: "paint", buffered: true });
    new PerformanceObserver((l) => l.getEntries().forEach((e) => { window.__paint.lcp = e.startTime; })).observe({ type: "largest-contentful-paint", buffered: true });
  });
  const t0 = Date.now();
  await page.goto(BASE + "#/discover", { waitUntil: "load", timeout: 240000 });
  await page.waitForSelector(".discover", { timeout: 240000 });
  const drawn = Date.now() - t0;
  let modelMs = null, mode = null;
  if (P.waitModel) {
    await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.ground, null, { timeout: 420000 }).catch(() => {});
    modelMs = Date.now() - t0;
  } else await page.waitForTimeout(6000);                    // long enough for a model request to show up if one were going to be made
  mode = await page.evaluate(() => ({ ground: document.querySelector("#bowl")?.dataset.ground ?? null, is3d: !!document.querySelector("#bowl.is3d"), coarse: matchMedia("(pointer: coarse)").matches }));
  const paint = await page.evaluate(() => window.__paint);
  results[name] = {
    profile: { viewport: P.ctx.viewport, cpuSlowdown: P.cpu, network: P.net ? "1.6 Mbit/s down, 150 ms round trip" : "none" },
    firstPaintMs: Math.round(paint["first-paint"] ?? -1), firstContentfulPaintMs: Math.round(paint["first-contentful-paint"] ?? -1), largestContentfulPaintMs: Math.round(paint.lcp ?? -1),
    discoverDrawnMs: drawn, modelReadyMs: modelMs, stadium: mode,
    transferredMB: +(bytes / 1048576).toFixed(2), requests, modelMB: +(groundBytes / 1048576).toFixed(2), modelRequests: groundRequests,
  };
  console.log(name, JSON.stringify(results[name]));
  await context.close();
}
await browser.close();
if (out) fs.writeFileSync(out, JSON.stringify(results, null, 1));
