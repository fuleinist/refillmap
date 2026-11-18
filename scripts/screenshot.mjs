// Capture real screenshots of the running refillmap app.
// Usage: node scripts/screenshot.mjs <baseUrl> <outDir>
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const base = process.argv[2] || "http://127.0.0.1:8199";
const outDir = process.argv[3] || "docs/screenshots";
mkdirSync(outDir, { recursive: true });

const shots = [
  {
    name: "parramatta-afternoon.png",
    url: `${base}/?area=parramatta&at=2026-11-19T15:00&shade=1.5`,
    wait: 2500,
  },
  {
    name: "newtown-morning.png",
    url: `${base}/?area=newtown&at=2026-11-19T09:00&shade=1.5`,
    wait: 2500,
  },
];

const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });

for (const shot of shots) {
  await page.goto(shot.url, { waitUntil: "networkidle", timeout: 120000 });
  await page.waitForFunction(() => {
    const status = document.getElementById("status");
    return status && /Plan ready/.test(status.textContent || "");
  }, { timeout: 120000 });
  await page.waitForTimeout(shot.wait);
  await page.screenshot({ path: `${outDir}/${shot.name}`, fullPage: true });
  console.log(`SAVED ${outDir}/${shot.name}`);
}

await browser.close();