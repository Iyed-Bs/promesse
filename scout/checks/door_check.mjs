// The door: Promesse or Promesse Light, headless (never a window). Needs the test desk (:8795). From <local path>
//   node ../../_research/football/scout/checks/door_check.mjs [--shots <dir>]
//   1. a fresh profile sees the door before anything loads; the model is not requested
//   2. Promesse Light: no download of the model, the flat bowl drawn, the choice remembered across a reload (no door the second time)
//   3. the fascia switch: Promesse brings the model, Light takes it away again
//   4. Esc on the door: the default for this visit, nothing remembered, the door asks again next time
//   5. a phone-class device opens in Light with no door and no model download
//   6. every seat is one player and clickable in Light: a click on a seat opens that player
import { chromium } from "playwright-core";

const BASE = "http://127.0.0.1:8795/";
const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const shots = arg("--shots");
const GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"];
let failed = 0;
const record = (name, ok, detail) => { if (!ok) failed++; console.log(`${ok ? "ok  " : "FAIL"} ${name} ${JSON.stringify(detail)}`); };
const browser = await chromium.launch({ channel: "msedge", args: GL });

async function fresh(opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, ...opts });
  const page = await ctx.newPage(), glb = [], errors = [];
  page.on("request", (r) => { if (/the_ground\.glb/.test(r.url())) glb.push(r.url()); });
  page.on("pageerror", (e) => errors.push(e.message));
  return { ctx, page, glb, errors };
}
const view = (page) => page.evaluate(() => { const b = document.querySelector("#bowl"); return b ? { view: b.dataset.view, ground: b.dataset.ground || null, stadium: !!b.querySelector("canvas.stadium"), is3d: b.classList.contains("is3d") } : null; });
const drawn = (page) => page.evaluate(() => { const c = document.querySelector("#bowl-base"), px = c.getContext("2d").getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < px.length; i += 4 * 97) if (px[i] > 0) n++; return n; });

try {
  {
    const { ctx, page, glb, errors } = await fresh();
    await page.goto(BASE + "#/discover", { waitUntil: "load" });
    await page.waitForSelector("dialog.door[open]", { timeout: 30000 });
    await page.waitForTimeout(800);
    const ways = await page.$$eval(".door-way b", (n) => n.map((x) => x.textContent));
    record("the door opens first, with both ways, and nothing is downloaded yet", ways.length === 2 && glb.length === 0 && (await view(page)) === null, { ways, glbRequests: glb.length });
    if (shots) await page.screenshot({ path: `${shots}/door.png` });
    await page.click('.door-way[data-mode="light"]');
    await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.view === "light", null, { timeout: 30000 });
    await page.waitForTimeout(2200);          // the entrance
    const v = await view(page), px = await drawn(page);
    record("Promesse Light: the flat bowl is drawn, no model downloaded", v.view === "light" && !v.stadium && !v.is3d && px > 500 && glb.length === 0, { ...v, drawnPixels: px, glbRequests: glb.length });
    if (shots) await page.screenshot({ path: `${shots}/light.png` });
    // 6: a seat is a player
    // find a seat by moving the pointer over the bowl in steps of 5 px until the canvas says it is over one (class "hit"), then really click there
    const spot = await page.evaluate(() => {
      const c = document.querySelector("#bowl-base"), r = c.getBoundingClientRect();
      for (let y = r.top + 10; y < r.bottom - 10; y += 5) for (let x = r.left + 10; x < r.right - 10; x += 5) {
        c.dispatchEvent(new PointerEvent("pointermove", { clientX: x, clientY: y, bubbles: true }));
        if (c.classList.contains("hit")) return { x, y };
      }
      return null;
    });
    let opened = false;
    if (spot) { await page.mouse.click(spot.x, spot.y); opened = await page.waitForFunction(() => /^#\/player\//.test(location.hash), null, { timeout: 5000 }).then(() => true).catch(() => false); }
    record("Light: a click on a seat opens that player", opened, { spot, hash: await page.evaluate(() => location.hash) });
    await page.goto(BASE + "#/discover"); await page.reload({ waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("#bowl"), null, { timeout: 30000 });
    const door2 = await page.$("dialog.door[open]"), mode = await page.evaluate(() => JSON.parse(localStorage.getItem("mode")));
    record("the choice is remembered: no door after a reload", !door2 && mode === "light", { mode });
    // 3: the fascia switch
    await page.click('.fascia button[data-mode="promesse"]');
    await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.ground === "model", null, { timeout: 120000 });
    const vp = await view(page);
    if (shots) { await page.waitForTimeout(1500); await page.screenshot({ path: `${shots}/promesse.png` }); }
    record("fascia: Promesse brings the model", vp.ground === "model" && vp.stadium && glb.length >= 1, { ...vp, glbRequests: glb.length });
    await page.click('.fascia button[data-mode="light"]');
    await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.view === "light", null, { timeout: 30000 });
    const vl = await view(page);
    record("fascia: Light takes the model away", vl.view === "light" && !vl.stadium && (await page.evaluate(() => JSON.parse(localStorage.getItem("mode")))) === "light", vl);
    record("no script errors (door, Light, switch)", errors.length === 0, { errors: errors.slice(0, 4) });
    await ctx.close();
  }
  // 4: Esc
  {
    const { ctx, page } = await fresh();
    await page.goto(BASE + "#/discover", { waitUntil: "load" });
    await page.waitForSelector("dialog.door[open]", { timeout: 30000 });
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelector("#bowl"), null, { timeout: 30000 });
    const stored = await page.evaluate(() => localStorage.getItem("mode")), open = !!(await page.$("dialog.door[open]"));
    record("Esc: opens in the default for this visit, remembers nothing", stored === null && !open, { stored, doorOpen: open });
    await ctx.close();
  }
  // 5: a phone-class device
  {
    const { ctx, page, glb, errors } = await fresh({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
    await page.goto(BASE + "#/discover", { waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("#bowl")?.dataset.view, null, { timeout: 30000 });
    await page.waitForTimeout(1500);
    const v = await view(page), door = !!(await page.$("dialog.door"));
    record("phone-class: opens in Light, no door, no model download", v.view === "light" && !door && glb.length === 0 && errors.length === 0, { ...v, door, glbRequests: glb.length, errors });
    await ctx.close();
  }
} finally {
  await browser.close();
}
console.log(failed ? `${failed} door checks failed` : "all door checks passed");
process.exit(failed ? 1 : 0);
