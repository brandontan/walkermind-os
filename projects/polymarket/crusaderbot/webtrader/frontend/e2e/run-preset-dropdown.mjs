// E2E driver for the /admin preset dropdown — Playwright-as-a-library (avoids the
// test-runner's ESM module-registry split in this "type":"module" project).
//
// Boots the Vite dev server, drives real Chromium against the harness
// (preset-demo.html → real FieldSelect + PRESET_OPTIONS), asserts the option
// contract, and writes the before/after screenshot CMD requested.
//
// Run: npm run test:e2e   (exits non-zero on any failed assertion)
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import { chromium } from "playwright";

const BASE = "http://localhost:5173/dashboard";
const URL = `${BASE}/preset-demo.html`;
const EXPECTED = [
  "candle_auto",
  "close_sweep",
  "safe_close",
  "flip_hunter",
  "weather_monitor",
  "playbook",
];

let failures = 0;
function check(cond, msg) {
  if (cond) {
    console.log(`  ✓ ${msg}`);
  } else {
    failures += 1;
    console.error(`  ✗ ${msg}`);
  }
}

async function waitForServer(url, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch {
      /* server not up yet */
    }
    await sleep(500);
  }
  throw new Error(`vite dev server did not become ready at ${url}`);
}

const vite = spawn("npm", ["run", "dev", "--", "--port", "5173", "--strictPort"], {
  stdio: "ignore",
});

let browser;
try {
  await waitForServer(URL);
  browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1000, height: 600 } });
  await page.goto(URL, { waitUntil: "networkidle" });

  const select = page.getByTestId("field").locator("select");
  const optionCount = await select.locator("option").count();
  check(optionCount === EXPECTED.length + 1, `dropdown has ${EXPECTED.length} presets + placeholder (got ${optionCount})`);

  for (const key of EXPECTED) {
    const n = await select.locator(`option[value="${key}"]`).count();
    check(n === 1, `dropdown offers preset "${key}"`);
  }
  const smartStrike = await select.locator('option[value="candle_auto"]').textContent();
  check(/Smart Strike/.test(smartStrike ?? ""), `candle_auto labelled "Smart Strike" (got "${smartStrike?.trim()}")`);
  const playbook = await select.locator('option[value="playbook"]').textContent();
  check(/Playbook/.test(playbook ?? ""), `playbook labelled "Playbook" (got "${playbook?.trim()}")`);

  await page
    .getByTestId("before-after")
    .screenshot({ path: "playwright/__screenshots__/preset-dropdown-before-after.png" });
  console.log("  ✓ wrote playwright/__screenshots__/preset-dropdown-before-after.png");
} finally {
  if (browser) await browser.close();
  vite.kill("SIGTERM");
}

if (failures > 0) {
  console.error(`\nE2E FAILED: ${failures} assertion(s) failed`);
  process.exit(1);
}
console.log("\nE2E PASSED");
