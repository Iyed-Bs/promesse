// The interaction check: on each page that carries them, press every flip card and step
// every slider with the keyboard, at desk and phone width, and report script errors. Headless Edge, never a window.
//   - flip card: click turns it (aria-pressed true, the back face has a box), Enter/Space turns it back; both faces' text is in the page
//   - stepper: with focus inside it, ArrowRight to the last slide, ArrowLeft back, End, Home; the dot, the count and the one
//     lit slide agree each time; the Next/Previous buttons are disabled at the ends; a "step" event fires per move
// A page with no flip card and no stepper is reported (it is not a failure for pages that were not rebuilt: pass --need to demand it).
//
//   node interact_check.mjs [--routes "#/method,#/data,#/combinations"] [--need]     (run from <local path>)
// Exit code 1 on any script error, a card that does not turn, a stepper that loses count, or (with --need) a page without any.
import { chromium } from "playwright-core";

const BASE = "http://127.0.0.1:8795/";
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const ROUTES = arg("--routes", "#/method,#/data,#/combinations").split(",");
const need = process.argv.includes("--need");
const VIEWS = [["desk", { width: 1400, height: 900 }, "light", false], ["phone", { width: 390, height: 844 }, "dark", false], ["desk-reduced", { width: 1400, height: 900 }, "light", true]];

const browser = await chromium.launch({ channel: "msedge" });
let bad = 0;
for (const route of ROUTES) {
  for (const [view, vp, scheme, reduced] of VIEWS) {
    const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme, reducedMotion: reduced ? "reduce" : "no-preference" });
    const page = await ctx.newPage();
    await page.addInitScript(() => { try { localStorage.setItem("mode", JSON.stringify("light")); } catch (e) {} });
    const errors = [], fails = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 120000 }).catch((e) => errors.push(String(e)));
    await page.waitForSelector("main .flip, main .stepper, main .page-head", { timeout: 60000 }).catch(() => errors.push("page did not draw"));
    await page.waitForTimeout(1200);

    // ── flip cards
    const nFlip = await page.locator("main .flip-btn").count();
    for (let i = 0; i < nFlip; i++) {
      const b = page.locator("main .flip-btn").nth(i);
      await b.scrollIntoViewIfNeeded();
      await b.click({ timeout: 5000 }).catch((e) => fails.push(`flip ${i}: click ${String(e).slice(0, 60)}`));
      const on = await b.getAttribute("aria-pressed");
      const backBox = await b.locator(".flip-back").boundingBox();
      const texts = await b.evaluate((el) => [el.querySelector(".flip-front").textContent.trim().length, el.querySelector(".flip-back").textContent.trim().length]);
      if (on !== "true") fails.push(`flip ${i}: not pressed after click`);
      if (!backBox || backBox.width < 10) fails.push(`flip ${i}: back face has no box`);
      if (texts[0] < 2 || texts[1] < 2) fails.push(`flip ${i}: a face is empty`);
      await b.focus(); await page.keyboard.press("Enter");                    // keyboard turns it back
      if ((await b.getAttribute("aria-pressed")) !== "false") fails.push(`flip ${i}: Enter did not turn it back`);
    }

    // ── steppers
    const nStep = await page.locator("main .stepper").count();
    for (let k = 0; k < nStep; k++) {
      const st = page.locator("main .stepper").nth(k), n = +(await st.getAttribute("data-n"));
      await st.scrollIntoViewIfNeeded();
      await st.evaluate((el) => { window.__steps = 0; el.addEventListener("step", () => window.__steps++); });
      const state = () => st.evaluate((el) => ({ i: +el.dataset.i, on: [...el.querySelectorAll(":scope > .step-track > .step-slide[data-on]")].map((s) => +s.dataset.s),
        cur: [...el.querySelectorAll(".step-dot")].findIndex((d) => d.hasAttribute("aria-current")), count: el.querySelector(".step-count b").textContent,
        prevOff: el.querySelector(".step-prev").getAttribute("aria-disabled") === "true", nextOff: el.querySelector(".step-next").getAttribute("aria-disabled") === "true" }));
      const expect = async (i, why) => { const s = await state();
        if (s.i !== i || s.on.length !== 1 || s.on[0] !== i || s.cur !== i || s.count !== String(i + 1) || s.prevOff !== (i === 0) || s.nextOff !== (i === n - 1)) fails.push(`step ${k} ${why}: wanted ${i}, got ${JSON.stringify(s)}`); };
      await st.locator(".step-next").focus();
      await expect(0, "start");
      for (let i = 1; i < n; i++) { await page.keyboard.press("ArrowRight"); await page.waitForTimeout(reduced ? 30 : 120); await expect(i, "right"); }
      await page.keyboard.press("ArrowRight"); await expect(n - 1, "right at the end");
      for (let i = n - 2; i >= 0; i--) { await page.keyboard.press("ArrowLeft"); await page.waitForTimeout(reduced ? 30 : 120); await expect(i, "left"); }
      await page.keyboard.press("End"); await page.waitForTimeout(150); await expect(n - 1, "End");
      await page.keyboard.press("Home"); await page.waitForTimeout(150); await expect(0, "Home");
      await st.locator(".step-next").click(); await page.waitForTimeout(150); await expect(1, "Next button");
      await st.locator(".step-dot").nth(n - 1).click(); await page.waitForTimeout(150); await expect(n - 1, "dot");
      await st.locator(".step-prev").click(); await page.waitForTimeout(150); await expect(n - 2, "Previous button");
      const ev = await page.evaluate(() => window.__steps);
      if (ev < 2 * (n - 1)) fails.push(`step ${k}: only ${ev} step events`);
    }

    const sideways = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    if (sideways > 0) fails.push(`sideways scroll ${sideways}px`);
    const missing = need && !nFlip && !nStep;
    const ok = !errors.length && !fails.length && !missing;
    if (!ok) bad++;
    console.log(`${ok ? "ok  " : "FAIL"} ${route} ${view}: ${nFlip} flip cards, ${nStep} steppers${errors.length ? `, errors: ${errors.slice(0, 3).join(" | ")}` : ""}${fails.length ? `, ${fails.slice(0, 4).join(" | ")}` : ""}${missing ? ", none on this page" : ""}`);
    await ctx.close();
  }
}
await browser.close();
console.log(bad ? `${bad} page views failed` : "all interactions passed");
process.exit(bad ? 1 : 0);
