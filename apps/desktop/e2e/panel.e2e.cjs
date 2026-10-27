// UI acceptance flow for the panel (Phase 2). Needs: backend on 127.0.0.1:8765 with ZIKO_TOKEN=dev-token-change-me,
// seeded with "Submit AI Security assignment" and "Call the bank about card renewal"; `pnpm dev` on :1420.
// Run: pnpm e2e   (set CHROME_PATH on Windows, e.g. "C:/Program Files/Google/Chrome/Application/chrome.exe")
// Drives the real panel (Vite dev server + live backend) through the Phase 2 acceptance flows.
const { chromium } = require("playwright-core");
const assert = require("node:assert/strict");
const OUT = process.argv[2] ?? require("node:os").tmpdir();
const CHROME = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";
const URL = process.env.ZIKO_UI_URL ?? "http://localhost:1420/#/panel";

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const page = await browser.newPage({ viewport: { width: 420, height: 640 }, deviceScaleFactor: 2, colorScheme: "dark" });
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => m.type() === "error" && errors.push("console: " + m.text()));
  await page.addStyleTag({ content: "" }).catch(() => {});
  await page.goto(URL);
  await page.evaluate(() => (document.body.style.background = "#1b1d2a"));
  const step = (s) => console.log("✓", s);

  await page.getByText("Submit AI Security assignment").waitFor();
  step("loads tasks from the live backend");

  // Quick add
  const quick = page.getByLabel("Add a task");
  await quick.fill("Buy groceries");
  await quick.press("Enter");
  await page.getByText("Buy groceries").waitFor();
  await page.getByText("Task saved").waitFor();
  assert.equal(await quick.inputValue(), "", "quick add clears after success");
  step("quick add creates a task, confirms, clears input");

  // Editor: validation
  await page.getByRole("button", { name: "Details" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  await page.getByLabel("Task", { exact: true }).fill("Book dentist appointment");
  await page.getByLabel("Reminder", { exact: true }).selectOption("custom");
  await page.getByRole("button", { name: "Add task" }).click();
  await page.getByText("Pick a reminder time").waitFor();
  step("editor validates before submitting");

  // Editor: full create with due + relative reminder + priority
  const tomorrow = new Date(Date.now() + 86400000);
  const pad = (n) => String(n).padStart(2, "0");
  const due = `${tomorrow.getFullYear()}-${pad(tomorrow.getMonth() + 1)}-${pad(tomorrow.getDate())}T08:00`;
  await page.getByLabel("Due", { exact: true }).fill(due);
  await page.getByLabel("Reminder", { exact: true }).selectOption("15");
  await page.getByText("high", { exact: true }).click();
  await page.screenshot({ path: `${OUT}/panel_editor.png` });
  await page.getByRole("button", { name: "Add task" }).click();
  await dialog.waitFor({ state: "detached" });
  await page.getByRole("tab", { name: /Upcoming/ }).click();
  const card = page.locator("li", { hasText: "Book dentist appointment" });
  await card.waitFor();
  const meta = await card.textContent(); // includes screen-reader text
  assert.match(meta, /High priority/);
  assert.match(meta, /Tomorrow 8:00/);
  assert.match(meta, /7:45/);
  step("editor creates task with due, 15-min reminder, high priority → Upcoming");

  // Edit: only changed field
  await card.getByRole("button", { name: /^Edit/ }).click();
  await page.getByLabel("Task", { exact: true }).fill("Book dentist appointment (Dr. Khan)");
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.getByText("Book dentist appointment (Dr. Khan)").waitFor();
  assert.match(await page.locator("li", { hasText: "Dr. Khan" }).innerText(), /7:45/, "reminder untouched");
  step("edit updates title and leaves reminder intact");

  // Keyboard tab navigation
  await page.getByRole("tab", { name: /Upcoming/ }).focus();
  await page.keyboard.press("ArrowLeft");
  assert.equal(await page.getByRole("tab", { name: /Today/ }).getAttribute("aria-selected"), "true");
  step("arrow keys move between tabs");

  // Complete → Done tab
  await page.getByRole("checkbox", { name: /Call the bank/ }).click();
  await page.locator("li", { hasText: "Call the bank" }).waitFor({ state: "detached" });
  await page.getByRole("tab", { name: "Done" }).click();
  await page.getByText("Call the bank about card renewal").waitFor();
  step("completing moves a task to Done");

  // Archive → Archived → Restore
  await page.getByRole("tab", { name: /Today/ }).click();
  await page.getByRole("button", { name: /Archive “Buy groceries”/ }).click();
  await page.getByText(/Task archived/).waitFor();
  await page.getByRole("tab", { name: "Archived" }).click();
  await page.getByRole("button", { name: /Restore “Buy groceries”/ }).click();
  await page.getByText("Task restored").waitFor();
  await page.getByRole("tab", { name: /Today/ }).click();
  await page.getByText("Buy groceries").waitFor();
  step("archive is recoverable via restore");

  // Backend rejection is shown inside the editor, input preserved
  await page.getByRole("button", { name: "Details" }).click();
  await dialog.waitFor();
  await page.getByLabel("Task", { exact: true }).fill("Past reminder test");
  await page.getByLabel("Reminder", { exact: true }).selectOption("custom");
  await page.getByLabel("Reminder time").fill("2020-01-01T09:00");
  await page.getByRole("button", { name: "Add task" }).click();
  await dialog.getByText("Reminder time is in the past").waitFor();
  assert.equal(await page.getByLabel("Task", { exact: true }).inputValue(), "Past reminder test");
  await page.screenshot({ path: `${OUT}/panel_editor_error.png` });
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached" });
  step("backend rejection shown inline in the editor; input kept");

  // Esc closes editor first
  await page.getByRole("button", { name: "Details" }).click();
  await dialog.waitFor();
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached" });
  step("Esc closes the editor");

  await page.waitForTimeout(3000); // let notices fade for a clean shot
  await page.screenshot({ path: `${OUT}/panel_after.png` });
  // 422 responses are expected above; the browser logs failed requests as console errors.
  const unexpected = errors.filter((e) => !/status of 422/.test(e));
  assert.deepEqual(unexpected, [], "no unexpected console/page errors");
  step("no console or page errors");
  await browser.close();
})().catch((e) => {
  console.error("✗", e.message.split("\n")[0]);
  process.exit(1);
});
