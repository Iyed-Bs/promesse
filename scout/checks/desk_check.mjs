// The desk's headless check: every page, at desk and phone width, in day and night,
// on the test desk (:8795, scout/checks/test_desk.py). Reports per page: script errors, sideways scroll in pixels, and
// whether the page drew its main content. Optional screenshots, one per page and view, for a few pages. Never opens a window (headless Edge through playwright-core).
//
//   node desk_check.mjs [--shots <dir>] [--only route1,route2]       (run from <local path>)
// Exit code 1 when any page has a script error, a sideways scroll, or drew nothing.
import { chromium } from "playwright-core";

const BASE = "http://127.0.0.1:8795/";
// the desk's pages and the selector that proves each one drew (add a page here when the map grows)
const PAGES = {
  "": "main *", discover: "main *", boards: ".page-head", compare: ".page-head", lists: ".page-head",
  combinations: ".duo", teams: ".clubhead", dives: ".page-head", "dive/barcelona": "main *", "club/barcelona": "main *",
  method: ".sb-now", data: ".page-head", "player/926993": ".stand-line",
};
const VIEWS = [["desk-day", { width: 1400, height: 900 }, "light"], ["desk-night", { width: 1400, height: 900 }, "dark"], ["phone-day", { width: 390, height: 844 }, "light"], ["phone-night", { width: 390, height: 844 }, "dark"]];   // both widths, both lights
const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const shots = arg("--shots"), only = arg("--only")?.split(",");

const browser = await chromium.launch({ channel: "msedge" });
let bad = 0;
for (const [route, sel] of Object.entries(PAGES)) {
  if (only && !only.includes(route)) continue;
  for (const [view, vp, scheme] of VIEWS) {
    const page = await browser.newPage({ viewport: vp, colorScheme: scheme });
    await page.addInitScript(() => { try { localStorage.setItem("mode", JSON.stringify(window.__MODE || "light")); } catch (e) {} });   // no door in a check; Light unless a check asks for the model
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await page.goto(BASE + "#/" + route, { waitUntil: "networkidle", timeout: 120000 }).catch((e) => errors.push(String(e)));
    const drew = await page.waitForSelector(sel, { timeout: 60000 }).then(() => true).catch(() => false);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth).catch(() => -1);
    if (shots) await page.screenshot({ path: `${shots}/${(route || "home").replace(/\W+/g, "_")}_${view}.png` });
    const ok = !errors.length && overflow <= 0 && drew;
    if (!ok) bad++;
    console.log(`${ok ? "ok  " : "FAIL"} #/${route} ${view}: drew ${drew}, overflow ${overflow}px${errors.length ? `, errors: ${errors.slice(0, 3).join(" | ")}` : ""}`);
    await page.close();
  }
}
await browser.close();
console.log(bad ? `${bad} page views failed` : "all page views passed");
process.exit(bad ? 1 : 0);
