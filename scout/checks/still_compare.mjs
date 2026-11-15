// Three stills of the Ground (the bowl, a marked seat, the seated view) into a folder, headless, for a before/after pixel compare
// (still_diff.py).. Run from <local path> test desk on :8795:
//   node <local path> <out dir> [--soft]
import { chromium } from "playwright-core";
import fs from "node:fs";

const dir = process.argv[2]; fs.mkdirSync(dir, { recursive: true });
const soft = process.argv.includes("--soft");
const SOFT = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
const browser = await chromium.launch({ channel: "msedge", args: soft ? SOFT : ["--ignore-gpu-blocklist", "--use-angle=d3d11"] });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, colorScheme: "light", reducedMotion: "no-preference" });
const page = await ctx.newPage();
const errors = []; page.on("pageerror", (e) => errors.push(e.message));
await page.addInitScript(() => {
  localStorage.setItem("mode", JSON.stringify("promesse"));
  sessionStorage.setItem("promesse.walkout", "1");               // the short walk-in, not the long first-visit one
  Math.random = () => 0.5;                                       // anything random (sparks, drift) is the same each run
});
await page.goto("http://127.0.0.1:8795/#/discover");
await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.ground === "model", null, { timeout: 120000, polling: 50 });
await page.waitForTimeout(5000);
const bowl = page.locator("#bowl");
await page.evaluate(() => { const s = document.querySelector("#bowl").__stadium; s.setView({ az: -0.62, el: 0.4, dist: 205 }); });
await page.waitForTimeout(800);
await bowl.screenshot({ path: `${dir}/1_bowl.png` });
// a marked seat: the marker's rise and the flight, then the camera comes to rest at the seat
await page.evaluate(() => { const s = document.querySelector("#bowl").__stadium; window.__p = s.seatFor((x) => !x.gone && x.p.on !== false).p; s.mark(window.__p); });
await page.waitForTimeout(15000);
await bowl.screenshot({ path: `${dir}/2_flight_end.png` });
// the seated view by the test hook (a jump to the seat's eye point, no flight)
await page.evaluate(() => { const s = document.querySelector("#bowl").__stadium; s.park(window.__p); });
await page.waitForTimeout(1500);
await bowl.screenshot({ path: `${dir}/3_seated.png` });
console.log(JSON.stringify({ shots: fs.readdirSync(dir), errors }));
await browser.close();
