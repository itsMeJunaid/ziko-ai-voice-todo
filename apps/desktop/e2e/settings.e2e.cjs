// UI acceptance flow for Phase 6: first-run key onboarding, Settings, and "Ask Ziko" through real Gemini.
// Needs: a FRESH backend on 127.0.0.1:8765 (ZIKO_TOKEN=dev-token-change-me, empty credential store, e.g.
// PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring and a scratch ZIKO_DATA_DIR), `pnpm dev` on :1420,
// and GEMINI_API_KEY in the environment of this script. Run: GEMINI_API_KEY=… node e2e/settings.e2e.cjs [outdir]
const { chromium } = require("playwright-core");
const assert = require("node:assert/strict");
const OUT = process.argv[2] ?? require("node:os").tmpdir();
const CHROME = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";
const URL = process.env.ZIKO_UI_URL ?? "http://localhost:1420/#/panel";
const API = "http://127.0.0.1:8765";
const H = { Authorization: "Bearer dev-token-change-me", "Content-Type": "application/json" };
const KEY = process.env.GEMINI_API_KEY;

const api = async (path, init = {}) => (await fetch(API + path, { headers: H, ...init })).json();

(async () => {
  assert.ok(KEY, "set GEMINI_API_KEY");
  assert.equal((await api("/settings/api-key")).has_api_key, false, "backend must start without a key");
  await api("/settings", { method: "PATCH", body: JSON.stringify({ voice: { voice_replies_enabled: false } }) });

  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const page = await browser.newPage({ viewport: { width: 420, height: 640 }, deviceScaleFactor: 2, colorScheme: "dark" });
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
  await page.goto(URL);
  await page.evaluate(() => (document.body.style.background = "#1b1d2a"));
  const step = (s) => console.log("✓", s);
  const shot = (n) => page.screenshot({ path: `${OUT}/p6-${n}.png` });

  // ---- first run: the voice bar says voice is off and offers to add a key
  const bar = page.getByRole("region", { name: "Voice" });
  await bar.getByText("Voice is off").waitFor();
  await shot("1-no-key");
  step("first run: voice bar says 'Voice is off' with an Add key button");
  await bar.getByRole("button", { name: "Add key" }).click();
  const dlg = page.getByRole("dialog", { name: "Settings" });
  await dlg.getByText("No key yet").waitFor();
  const keyBox = dlg.getByLabel("Gemini API key");
  await keyBox.fill("AIzaSyThisIsNotARealKey0000000000000");
  await dlg.getByRole("button", { name: "Save & test" }).click();
  await dlg.getByText("Gemini rejected the API key").first().waitFor({ timeout: 20000 });
  assert.equal((await api("/settings/api-key")).has_api_key, false, "a bad key must not be stored");
  await shot("2-bad-key");
  step("a wrong key is rejected by the test and not saved");
  await keyBox.fill(KEY);
  await dlg.getByRole("button", { name: "Save & test" }).click();
  await dlg.getByText("Key saved").waitFor({ timeout: 30000 });
  assert.equal((await api("/settings/api-key")).has_api_key, true);
  const leaked = JSON.stringify(await api("/settings")) + JSON.stringify(await api("/settings/api-key"));
  assert.ok(!leaked.includes(KEY), "key must never be returned");
  await dlg.getByRole("button", { name: "Test connection" }).click();
  await dlg.getByText(/Connected · gemini/).waitFor({ timeout: 30000 });
  await shot("3-key-connected");
  step("the real key is tested, saved, never echoed; 'Test connection' reports Connected");

  // ---- settings save immediately
  await dlg.getByRole("switch", { name: "Wake word" }).click();
  await dlg.getByLabel("Turn the mic off after").selectOption("20");
  await dlg.getByLabel("Snooze for").selectOption("15");
  await dlg.getByRole("radiogroup", { name: "Pet size" }).getByRole("radio", { name: "L" }).click();
  await dlg.getByRole("radiogroup", { name: "Theme" }).getByRole("radio", { name: "Light" }).click();
  await page.waitForTimeout(400);
  const s = await api("/settings");
  assert.equal(s.voice.wake_word_enabled, false);
  assert.equal(s.ai.interaction_timeout_s, 20);
  assert.equal(s.tasks.snooze_minutes, 15);
  assert.equal(s.appearance.dot_size, 52);
  assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "light", "theme applies live");
  await shot("4-settings-light");
  step("settings save immediately to the backend; the theme switches live");
  await dlg.getByText("Privacy & data").scrollIntoViewIfNeeded();
  const del = dlg.getByRole("button", { name: "Delete", exact: true });
  assert.equal(await del.isDisabled(), true, "delete-all needs the typed confirmation");
  step("delete-all is locked until DELETE is typed");
  await dlg.getByRole("radiogroup", { name: "Theme" }).getByRole("radio", { name: "Dark" }).click();
  await dlg.getByRole("button", { name: "Close settings" }).click();
  await dlg.waitFor({ state: "detached" });
  await bar.getByText("Voice ready").waitFor();
  step("with a key the voice bar is ready");

  // ---- Ask Ziko through real Gemini (replies muted for the test)
  const quick = page.getByLabel("Add a task");
  await quick.fill("Add a task to renew my passport tomorrow at 11 AM");
  await page.getByRole("button", { name: "Ask Ziko" }).click();
  await page.getByText("Thinking…").waitFor({ timeout: 10000 });
  await shot("5-thinking");
  // The user's own words show in the conversation lines, so wait for the saved task itself.
  let tasks = [];
  for (let i = 0; i < 45 && !tasks.some(([t]) => /passport/i.test(t)); i++) {
    await page.waitForTimeout(1000);
    tasks = (await api("/tasks?view=upcoming")).items.map((t) => [t.title, t.due_at, t.source]);
  }
  console.log("   upcoming:", JSON.stringify(tasks));
  assert.ok(tasks.some(([title, , source]) => /passport/i.test(title) && source === "voice"));
  await page.getByText("Voice ready").waitFor({ timeout: 20000 });
  await shot("6-after-ask");
  await page.getByRole("tab", { name: /Upcoming/ }).click();
  await page.locator("#task-list").getByText(/passport/i).waitFor({ timeout: 5000 });
  await shot("7-upcoming");
  step("typed request → Gemini tool call → task saved and shown");

  assert.deepEqual(errors, [], "no console/page errors");
  step("no console errors");
  await browser.close();
})().catch((e) => {
  console.error("✗", e.message);
  process.exit(1);
});
