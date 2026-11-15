// Headless screenshot of one player page on the live desk with the data-source names masked (D15,).
// Run from <local path>  node <this file> <tm_id> <out dir>
// Never opens a window. The masking is done in the page's text only; nothing on the desk changes.
import { chromium } from "playwright-core";
const [id, out] = [process.argv[2] || "979064", process.argv[3] || "."];
const MASK = [[/Transfermarkt/g, "the source"], [/MatchData/g, "the source"]];   // words to hide
const browser = await chromium.launch({ channel: "msedge" });
for (const [name, vp, scheme] of [["desk-day", { width: 1400, height: 900 }, "light"], ["desk-night", { width: 1400, height: 900 }, "dark"]]) {
  const page = await browser.newPage({ viewport: vp, colorScheme: scheme });
  await page.addInitScript(() => localStorage.setItem("mode", JSON.stringify("light")));   // flat view: no mode dialog, no 3D download
  await page.goto(`http://127.0.0.1:8792/#/player/${id}`, { waitUntil: "networkidle", timeout: 120000 });
  await page.waitForSelector(".stand-line", { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const left = await page.evaluate((pairs) => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) for (const [re, to] of pairs) n.nodeValue = n.nodeValue.replace(new RegExp(re[0], "g"), to);
    return /MatchData|Transfermarkt/.test(document.body.innerText);
  }, MASK.map(([re, to]) => [[re.source], to]));
  await page.screenshot({ path: `${out}/player_${id}_${name}.png`, fullPage: true });
  console.log(name, left ? "STILL SHOWS A SOURCE NAME" : "masked");
  await page.close();
}
await browser.close();
