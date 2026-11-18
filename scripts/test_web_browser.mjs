/** File purpose: Verify a standalone Skill's managed Web startup and real feedback saves. */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const requireWeb = createRequire(path.join(root, "web", "package.json"));
const { chromium, expect } = requireWeb("@playwright/test");
const python = process.env.COACH_WEB_PYTHON || path.join(root, ".venv-web", "bin", "python");
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "coach-web-browser-"));
const data = path.join(temporary, "private");
const bundle = path.join(temporary, "algorithm-coach");
const entry = path.join(bundle, "scripts", "coach.py");
const trainingDate = "2026-01-02";
const managedDirectories = new Set();
let webPython = null;
const artifacts = process.env.COACH_WEB_ARTIFACTS_DIR || path.join(root, "web", "test-results");
fs.mkdirSync(artifacts, { recursive: true });

/**
 * Inputs: Python arguments for a fixture or public Skill command.
 * Outputs: Parsed JSON from the successful child process.
 * Logic: Use argument arrays and isolated synthetic data without a shell.
 * Dependencies: The chosen Web Python and spawnSync.
 */
function runPython(arguments_) {
  const result = spawnSync(python, arguments_, {
    cwd: temporary, encoding: "utf8", timeout: 30_000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  return JSON.parse(result.stdout);
}

/**
 * Inputs: Public Skill arguments and an optional synthetic data directory.
 * Outputs: A successful CLI data object.
 * Logic: Read the same authority through the dependency-free Skill entry.
 * Dependencies: runPython and a freshly built standalone Skill runner.
 */
function skill(arguments_, directory = data) {
  const result = runPython(["-S", entry, "--data-dir", directory, ...arguments_]);
  assert.equal(result.ok, true);
  return result.data;
}

/**
 * Inputs: A synthetic authority and an optional preferred local port.
 * Outputs: A ready session created through the public standalone Skill.
 * Logic: Let the runtime bind a port, then validate its date and store-bound link.
 * Dependencies: skill, the optional Web interpreter, and the session contract.
 */
function startSession(directory = data, port = 0) {
  managedDirectories.add(directory);
  const saved = skill(["start-session", "--date", trainingDate, "--web-python", webPython, "--web-port", String(port)], directory);
  assert.equal(saved.web.status, "ready", `Managed startup failed: ${saved.web.reason ?? "unknown"}`);
  const url = new URL(saved.web.url);
  assert.equal(url.hostname, "127.0.0.1");
  assert.equal(url.searchParams.get("date"), trainingDate);
  assert.equal(url.searchParams.get("store"), saved.web.store_id);
  assert.equal(saved.plan.training_date, trainingDate);
  return saved;
}

/**
 * Inputs: A known synthetic managed workspace.
 * Outputs: A confirmed stopped service without any PID signaling.
 * Logic: Use private managed control and verify its public status before cleanup.
 * Dependencies: The standalone web stop and web status commands.
 */
function stopServer(directory = data) {
  const stopped = skill(["web", "stop"], directory);
  assert.equal(stopped.status, "stopped", `Managed stop failed: ${stopped.reason ?? "unknown"}`);
  const status = skill(["web", "status"], directory);
  assert.equal(status.status, "stopped", `Managed service remains active: ${status.reason ?? "unknown"}`);
}

/**
 * Inputs: A page and a known saved plan item.
 * Outputs: Its visible record editor locator.
 * Logic: Locate the stable attempt rather than guessing from list order.
 * Dependencies: Playwright accessible roles and the attempt metadata attribute.
 */
async function openCard(page, item) {
  const card = page.locator(`[data-attempt-id="${item.attempt_id}"]`);
  await card.getByRole("button", { name: /^(Record result for|Update record for) / }).click();
  return card;
}

/**
 * Inputs: A page, local server origin, and expected store identity.
 * Outputs: Parsed current topic scores.
 * Logic: Read the public API without substituting mock score data.
 * Dependencies: Playwright API requests and the actual HTTP adapter.
 */
async function scores(page, origin, storeId) {
  const response = await page.request.get(`${origin}/v1/scores?language=Java`, { headers: { "X-Coach-Store-Id": storeId } });
  assert.equal(response.status(), 200);
  return (await response.json()).data;
}

/**
 * Inputs: None. Use temporary authorities and a fresh standalone Web Skill bundle.
 * Outputs: Verified automatic startup, record persistence, guarded links, and screenshots.
 * Logic: Reuse, save, recover, restart, and reject a real copied store at a reused port.
 * Dependencies: Chromium, public Skill commands, the managed runtime, and assertions.
 */
async function main() {
  assert.ok(fs.existsSync(path.join(root, "web", "dist", "index.html")), "Build the Web UI first.");
  let browser = null;
  let page = null;
  const pageErrors = [];
  try {
    webPython = runPython(["-c", "import json,sys; print(json.dumps(sys.executable))"]);
    const built = runPython(["-S", path.join(root, "scripts", "build_skill.py"), "--output", bundle, "--with-web"]);
    assert.equal(built.ok, true);
    assert.equal(built.data.web_assets, true);
    assert.ok(fs.existsSync(path.join(bundle, "assets", "web", "coach-ui-manifest.json")));
    skill(["init", "--timezone", "UTC", "--language", "Java"]);
    let session = startSession();
    assert.equal(session.web.action, "started");
    const seeded = session.plan;
    const first = seeded.items[0];
    const second = seeded.items[1];
    const third = seeded.items[2];
    const fourth = seeded.items[3];
    const fifth = seeded.items[4];
    const origin = new URL(session.web.url).origin;
    const port = Number(new URL(session.web.url).port);
    const repeated = startSession();
    assert.equal(repeated.web.action, "reused");
    assert.equal(repeated.web.instance_id, session.web.instance_id);
    assert.equal(repeated.plan.id, seeded.id);
    const status = skill(["web", "status"]);
    assert.equal(status.status, "ready");
    assert.equal(status.instance_id, session.web.instance_id);
    browser = await chromium.launch();
    page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
    /**
     * Inputs: An uncaught browser error.
     * Outputs: A bounded list of runtime failures.
     * Logic: Fail the browser check when rendering throws after a successful build.
     * Dependencies: The Playwright page error event.
     */
    function capturePageError(error) { pageErrors.push(error.message); }
    page.on("pageerror", capturePageError);
    await page.goto(session.web.url);
    await expect(page.getByRole("heading", { name: "Training record" })).toBeVisible();
    await expect(page.getByLabel("Training date", { exact: true })).toHaveValue(trainingDate);
    await expect(page.locator(".problem-card")).toHaveCount(5);
    await page.screenshot({ path: path.join(artifacts, "plan-desktop.png"), fullPage: true });

    let card = await openCard(page, first);
    await card.getByText("Code and complexity review", { exact: true }).click();
    await expect(card.getByText("No code submitted", { exact: true })).toBeVisible();
    const syntheticCode = "int identity(int n) { return n; }";
    await card.locator('[name="code"]').fill(syntheticCode);
    await card.locator('[name="input_definition"]').fill("n is one integer");
    await card.getByRole("button", { name: `Close ${first.problem.title}`, exact: true }).click();
    card = await openCard(page, first);
    await card.getByText("Code and complexity review", { exact: true }).click();
    await expect(card.locator('[name="code"]')).toHaveValue(syntheticCode);
    /**
     * Inputs: The next code evidence response.
     * Outputs: One durable write with an intentionally lost response.
     * Logic: Verify that browser retries recover the same code operation.
     * Dependencies: Playwright routing and the real solution endpoint.
     */
    async function loseCodeResponse(route) {
      await route.fetch();
      await route.abort("failed");
    }
    await page.route("**/v1/attempts/*/solution", loseCodeResponse, { times: 1 });
    await card.getByRole("button", { name: "Save code for review", exact: true }).click();
    await expect(card.getByRole("button", { name: "Retry code save", exact: true })).toBeVisible();
    await expect(card.getByRole("radio", { name: /Independent AC/ })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Topic scores", exact: true })).toBeDisabled();
    await card.getByRole("button", { name: "Retry code save", exact: true }).click();
    await expect(card.getByText("Code saved · awaiting review", { exact: true })).toBeVisible();
    const codeStatus = skill(["review", "status", "--attempt", first.attempt_id]);
    assert.equal(codeStatus.items[0].evidence.body.code, syntheticCode);
    assert.equal(codeStatus.items[0].feedback_revision, 0);
    assert.equal(skill(["history", "--attempt", first.attempt_id]).revisions.length, 0);
    await page.screenshot({ path: path.join(artifacts, "code-review-desktop.png"), fullPage: true });
    await card.getByText("Code and complexity review", { exact: true }).click();
    await expect(card.getByRole("radio", { checked: true })).toHaveCount(0);
    await card.getByRole("radio", { name: /Independent AC/ }).check();
    await page.keyboard.press("ArrowRight");
    await expect(card.getByRole("radio", { name: /AC with hints/ })).toBeChecked();
    await page.keyboard.press("ArrowLeft");
    await expect(card.getByRole("radio", { name: /Independent AC/ })).toBeChecked();
    await expect(card.getByRole("radio", { checked: true })).toHaveCount(1);
    await card.locator('[name="elapsed_minutes"]').fill("25");
    await card.getByText("More details", { exact: false }).click();
    await card.locator('[name="boundary_tests"]').selectOption("false");
    await card.getByRole("button", { name: `Close ${first.problem.title}`, exact: true }).click();
    card = await openCard(page, first);
    await expect(card.getByRole("radio", { name: /Independent AC/ })).toBeChecked();
    await expect(card.locator('[name="elapsed_minutes"]')).toHaveValue("25");
    await card.getByText("More details", { exact: false }).click();
    await expect(card.locator('[name="boundary_tests"]')).toHaveValue("false");
    const otherDraft = await openCard(page, second);
    await expect(otherDraft.getByRole("radio", { checked: true })).toHaveCount(0);
    await expect(otherDraft.locator('[name="elapsed_minutes"]')).toHaveValue("");
    card = await openCard(page, first);
    await page.getByRole("button", { name: "Topic scores", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Topic scores", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Plan & records", exact: true }).click();
    card = page.locator(`[data-attempt-id="${first.attempt_id}"]`);
    if (!(await card.locator("form").count())) card = await openCard(page, first);
    await expect(card.getByRole("radio", { name: /Independent AC/ })).toBeChecked();
    await expect(card.locator('[name="elapsed_minutes"]')).toHaveValue("25");
    await page.getByLabel("Training date", { exact: true }).fill("2099-01-01");
    await expect(page.getByRole("heading", { name: "No saved plan for this date" })).toBeVisible();
    await page.getByLabel("Training date", { exact: true }).fill(trainingDate);
    await expect(page.locator(".problem-card")).toHaveCount(5);
    card = await openCard(page, first);
    await expect(card.getByRole("radio", { name: /Independent AC/ })).toBeChecked();
    await expect(card.locator('[name="elapsed_minutes"]')).toHaveValue("25");
    await card.getByText("More details", { exact: false }).click();
    await expect(card.locator('[name="boundary_tests"]')).toHaveValue("false");
    await page.screenshot({ path: path.join(artifacts, "form-desktop.png"), fullPage: true });
    await card.getByRole("button", { name: /Save feedback/ }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved to your record" })).toBeVisible();
    const initialHistory = skill(["history", "--attempt", first.attempt_id]);
    assert.equal(initialHistory.attempt.feedback.result, "A");
    assert.equal(initialHistory.attempt.feedback.elapsed_minutes, 25);
    assert.equal(initialHistory.attempt.feedback.boundary_tests, false);
    assert.equal(initialHistory.revisions.length, 1);
    assert.equal(skill(["review", "status", "--attempt", first.attempt_id]).items[0].status, "stale");
    const initialScores = await scores(page, origin, session.web.store_id);
    for (const row of initialScores.topics) {
      if (first.problem.tags.includes(row.tag)) {
        assert.equal(row.score, 100);
        assert.equal(row.problem_count, 1);
        assert.equal(row.stable_count, 0);
      }
    }

    await page.getByRole("button", { name: "Topic scores", exact: true }).click();
    await expect(page.getByRole("heading", { name: /Topic/ })).toBeVisible();
    await page.screenshot({ path: path.join(artifacts, "scores-desktop.png"), fullPage: true });
    await page.getByRole("button", { name: "Plan & records", exact: true }).click();
    card = page.locator(`[data-attempt-id="${first.attempt_id}"]`);
    if (!(await card.locator("form").count())) card = await openCard(page, first);
    await card.getByLabel("How are you updating this record?").selectOption("correction");
    await card.getByRole("radio", { name: /AC with hints/ }).check();
    await card.locator('[name="elapsed_minutes"]').fill("30");
    await card.getByRole("button", { name: /Save feedback/ }).click();
    await expect(page.getByRole("status").filter({ hasText: "revision 2" })).toBeVisible();
    const corrected = skill(["history", "--attempt", first.attempt_id]);
    assert.deepEqual(corrected.revisions.map(resultOfRevision), ["A", "B"]);
    assert.equal(corrected.attempt.feedback.boundary_tests, false);
    await expect(card.getByRole("radio", { name: /AC with hints/ })).toBeChecked();
    await expect(card.locator('[name="elapsed_minutes"]')).toHaveValue("30");

    card = await openCard(page, second);
    await card.getByRole("radio", { name: /Not yet AC/ }).check();
    await card.locator('[name="elapsed_minutes"]').fill("20");
    /**
     * Inputs: The next browser feedback request.
     * Outputs: A committed server write with a deliberately lost browser response.
     * Logic: Exercise receipt recovery without mocking the database operation.
     * Dependencies: Playwright routing and the actual HTTP feedback endpoint.
     */
    async function loseResponse(route) {
      await route.fetch();
      await route.abort("failed");
    }
    await page.route("**/v1/attempts/*/feedback", loseResponse, { times: 1 });
    await card.getByRole("button", { name: /Save feedback/ }).click();
    await expect(card.getByRole("button", { name: "Retry this save", exact: true })).toBeVisible();
    await expect(card.locator('[name="elapsed_minutes"]')).toHaveValue("20");
    await expect(card.getByRole("radio", { name: /Not yet AC/ })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Topic scores", exact: true })).toBeDisabled();
    await card.getByRole("button", { name: "Retry this save", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "revision 1" })).toBeVisible();
    const recovered = skill(["history", "--attempt", second.attempt_id]);
    assert.equal(recovered.revisions.length, 1);
    assert.equal(recovered.attempt.feedback.result, "D");

    card = await openCard(page, third);
    await expect(card.locator('[name="defer_until"]')).toBeHidden();
    await expect(card.locator('[name="skip_until"]')).toBeHidden();
    await card.getByRole("radio", { name: /Do it later/ }).check();
    await expect(card.locator('[name="defer_until"]')).toBeVisible();
    await expect(card.locator('[name="skip_until"]')).toBeHidden();
    await card.getByRole("radio", { name: /End this attempt/ }).check();
    await expect(card.locator('[name="skip_until"]')).toBeVisible();
    await expect(card.locator('[name="defer_until"]')).toBeHidden();
    await card.getByRole("radio", { name: /Do it later/ }).check();
    await card.locator('[name="defer_until"]').fill("2026-01-05");
    await card.locator('[name="elapsed_minutes"]').fill("0");
    let stalledRoute = null;
    /**
     * Inputs: The next browser feedback request.
     * Outputs: A committed write with its response held indefinitely.
     * Logic: Prove a hung response releases the UI through a bounded timeout.
     * Dependencies: Playwright routing and the real feedback endpoint.
     */
    async function stallResponse(route) {
      await route.fetch();
      stalledRoute = route;
    }
    await page.route("**/v1/attempts/*/feedback", stallResponse, { times: 1 });
    await card.getByRole("button", { name: /Save feedback/ }).click();
    await expect(card.getByRole("button", { name: "Retry this save", exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(card.locator('[name="elapsed_minutes"]')).toHaveValue("0");
    await card.getByRole("button", { name: "Retry this save", exact: true }).click();
    await expect(card.getByRole("button", { name: "Retry this save", exact: true })).toHaveCount(0);
    if (stalledRoute) await stalledRoute.abort().catch(ignoreRouteFailure);
    const timedOut = skill(["history", "--attempt", third.attempt_id]);
    assert.equal(timedOut.revisions.length, 1);
    assert.equal(timedOut.attempt.feedback.result, "E");
    assert.equal(timedOut.attempt.feedback.elapsed_minutes, 0);
    assert.equal(timedOut.attempt.feedback.defer_until, "2026-01-05");

    const oldInstance = session.web.instance_id;
    stopServer();
    session = startSession(data, port);
    assert.equal(new URL(session.web.url).origin, origin);
    assert.notEqual(session.web.instance_id, oldInstance);
    await page.reload();
    await expect(page.locator(`[data-attempt-id="${first.attempt_id}"]`)).toContainText("B · AC with hints");
    await expect(page.locator(`[data-attempt-id="${second.attempt_id}"]`)).toContainText("D · Not yet AC");
    const savedPlan = skill(["show", "--date", seeded.training_date]);
    assert.equal(savedPlan.items.length, 5);
    const missing = "2099-01-01";
    await page.getByLabel("Training date", { exact: true }).fill(missing);
    await expect(page.getByRole("heading", { name: "No saved plan for this date" })).toBeVisible();
    const unchanged = skill(["show", "--date", seeded.training_date]);
    assert.equal(unchanged.id, savedPlan.id);
    const missingRead = await page.request.get(`${origin}/v1/plans/${missing}`);
    assert.equal(missingRead.status(), 404);

    await page.getByLabel("Training date", { exact: true }).fill(seeded.training_date);
    await expect(page.locator(".problem-card")).toHaveCount(5);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(artifacts, "plan-mobile.png"), fullPage: true });
    /**
     * Inputs: The browser document.
     * Outputs: Whether the mobile page fits its viewport horizontally.
     * Logic: Compare layout width without relying on a screenshot filename.
     * Dependencies: Browser document geometry.
     */
    function fitsViewport() { return document.documentElement.scrollWidth <= window.innerWidth; }
    assert.equal(await page.evaluate(fitsViewport), true, "The mobile layout must not overflow.");
    card = await openCard(page, first);
    await page.screenshot({ path: path.join(artifacts, "form-mobile.png"), fullPage: true });
    assert.equal(await page.evaluate(fitsViewport), true, "The mobile form must not overflow.");
    const choiceSizes = await card.locator(".result-choice").evaluateAll(measureChoices);
    assert.equal(choiceSizes.length, 6);
    for (const size of choiceSizes) {
      assert.ok(size.height >= 44, `Result targets must be at least 44px tall, got ${size.height}.`);
      assert.ok(size.label >= 12 && size.detail >= 12, "Mobile result labels and details must be at least 12px.");
    }
    const actionHeights = await page.locator(".record-button, .primary-button, .date-control input").evaluateAll(measureHeights);
    for (const height of actionHeights) assert.ok(height >= 44, `Mobile actions must be at least 44px tall, got ${height}.`);
    await page.getByRole("button", { name: "Topic scores", exact: true }).click();
    await page.screenshot({ path: path.join(artifacts, "scores-mobile.png"), fullPage: true });
    assert.equal(await page.evaluate(fitsViewport), true, "Mobile scores must not overflow.");
    for (const width of [320, 768, 1440]) {
      await page.setViewportSize({ width, height: 844 });
      await page.getByRole("button", { name: "Plan & records", exact: true }).click();
      card = page.locator(`[data-attempt-id="${first.attempt_id}"]`);
      if (await card.locator("form").count()) {
        await card.getByRole("button", { name: `Close ${first.problem.title}`, exact: true }).click();
      }
      assert.equal(await page.evaluate(fitsViewport), true, `The plan must not overflow at ${width}px.`);
      card = await openCard(page, first);
      assert.equal(await page.evaluate(fitsViewport), true, `The feedback form must not overflow at ${width}px.`);
      await page.getByRole("button", { name: "Topic scores", exact: true }).click();
      assert.equal(await page.evaluate(fitsViewport), true, `Topic scores must not overflow at ${width}px.`);
    }
    await page.setViewportSize({ width: 390, height: 844 });

    const guardPage = await browser.newPage();
    guardPage.on("pageerror", capturePageError);
    const invalidQueries = [
      `date=2026-02-30&store=${session.web.store_id}`,
      "date=2026-01-02&store=invalid",
      `date=2026-01-02&date=2026-01-03&store=${session.web.store_id}`,
    ];
    for (const query of invalidQueries) {
      await guardPage.goto(`${origin}/?${query}`);
      await expect(guardPage.getByRole("heading", { name: "This training link is invalid", exact: true })).toBeVisible();
      await expect(guardPage.locator("form")).toHaveCount(0);
      await expect(guardPage.locator(".problem-card")).toHaveCount(0);
    }

    await page.getByRole("button", { name: "Plan & records", exact: true }).click();
    card = await openCard(page, fourth);
    await card.getByRole("radio", { name: /Not yet AC/ }).check();
    await card.locator('[name="elapsed_minutes"]').fill("15");
    await guardPage.goto(session.web.url);
    await expect(guardPage.locator(".problem-card")).toHaveCount(5);
    const refreshCard = await openCard(guardPage, fourth);
    await refreshCard.getByRole("radio", { name: /Not yet AC/ }).check();
    await refreshCard.locator('[name="elapsed_minutes"]').fill("17");
    const copied = path.join(temporary, "copied-private");
    fs.mkdirSync(copied);
    skill(["backup", "--output", path.join(copied, "coach.sqlite3")]);
    skill(["feedback", "--attempt", fifth.attempt_id, "--submission", "synthetic-clone-only", "--expected-revision", "0", "--changes", JSON.stringify({ result: "D", elapsed_minutes: 9 })], copied);
    const originalContext = await (await page.request.get(`${origin}/v1/context`)).json();
    stopServer();
    const copiedSession = startSession(copied, port);
    assert.equal(new URL(copiedSession.web.url).origin, origin);
    assert.notEqual(copiedSession.web.store_id, session.web.store_id);
    const copiedContext = await page.request.get(`${origin}/v1/context`);
    assert.equal((await copiedContext.json()).data.workspace_id, originalContext.data.workspace_id);
    await guardPage.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(guardPage.getByRole("alert").filter({ hasText: "This is a different training workspace." }).first()).toBeVisible();
    await expect(refreshCard.locator('[name="elapsed_minutes"]')).toHaveValue("17");
    await expect(refreshCard.getByRole("button", { name: /Save feedback/ })).toBeDisabled();
    await expect(guardPage.locator(`[data-attempt-id="${fifth.attempt_id}"]`)).toContainText("No result recorded");
    await card.getByRole("button", { name: /Save feedback/ }).click();
    await expect(page.getByRole("alert").filter({ hasText: "This is a different training workspace." }).first()).toBeVisible();
    await expect(card.locator('[name="elapsed_minutes"]')).toHaveValue("15");
    await expect(card.getByRole("button", { name: /Save feedback/ })).toBeDisabled();
    assert.equal(skill(["history", "--attempt", fourth.attempt_id]).revisions.length, 0);
    assert.equal(skill(["history", "--attempt", fourth.attempt_id], copied).revisions.length, 0);
    await guardPage.goto(session.web.url);
    await expect(guardPage.getByRole("heading", { name: "This is a different training workspace", exact: true })).toBeVisible();
    await expect(guardPage.locator("form")).toHaveCount(0);
    await expect(guardPage.locator(".problem-card")).toHaveCount(0);
    await guardPage.goto(copiedSession.web.url);
    await expect(guardPage.getByRole("heading", { name: "Training record" })).toBeVisible();
    await expect(guardPage.getByLabel("Training date", { exact: true })).toHaveValue(trainingDate);
    await expect(guardPage.locator(".problem-card")).toHaveCount(5);
    await expect(guardPage.locator(`[data-attempt-id="${fifth.attempt_id}"]`)).toContainText("D · Not yet AC");
    await guardPage.close();
    assert.deepEqual(pageErrors, [], "The browser must have no uncaught runtime errors.");
    process.stdout.write(`Standalone Skill startup, reuse, managed restart, browser saves, draft retention, conditional dates, recovery, scores, and store guards passed.\nScreenshots: ${artifacts}\n`);
  } catch (failure) {
    if (page) await page.screenshot({ path: path.join(artifacts, "failure.png"), fullPage: true }).catch(ignoreScreenshotFailure);
    if (pageErrors.length) process.stderr.write(`Browser runtime errors: ${pageErrors.join("; ")}\n`);
    throw failure;
  } finally {
    if (browser) await browser.close();
    const cleanupFailures = [];
    for (const directory of managedDirectories) {
      try { stopServer(directory); }
      catch (failure) { cleanupFailures.push(failure); }
    }
    if (cleanupFailures.length) throw new AggregateError(cleanupFailures, "Managed test cleanup failed; temporary files were retained.");
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

/**
 * Inputs: The rendered result-choice labels from the browser document.
 * Outputs: Their target heights and visible label and detail font sizes.
 * Logic: Measure computed typography and touch targets at the mobile viewport.
 * Dependencies: Browser layout geometry and getComputedStyle.
 */
function measureChoices(choices) {
  const sizes = [];
  for (const choice of choices) {
    sizes.push({
      height: choice.getBoundingClientRect().height,
      label: Number.parseFloat(getComputedStyle(choice.querySelector("strong") || choice).fontSize),
      detail: Number.parseFloat(getComputedStyle(choice.querySelector("small") || choice).fontSize),
    });
  }
  return sizes;
}

/**
 * Inputs: The rendered action controls from the browser document.
 * Outputs: Each action's visible target height.
 * Logic: Measure hit areas independently of a screenshot's appearance.
 * Dependencies: Browser layout geometry.
 */
function measureHeights(controls) {
  const heights = [];
  for (const control of controls) heights.push(control.getBoundingClientRect().height);
  return heights;
}

/**
 * Inputs: A screenshot error during failure cleanup.
 * Outputs: None.
 * Logic: Preserve the original failed assertion if the browser already closed.
 * Dependencies: The failure cleanup path.
 */
function ignoreScreenshotFailure() {}

/**
 * Inputs: An already-cancelled route error during test cleanup.
 * Outputs: None.
 * Logic: Leave the verified save intact when the browser already aborted.
 * Dependencies: The deliberate hung-response fixture.
 */
function ignoreRouteFailure() {}

/**
 * Inputs: An immutable feedback revision.
 * Outputs: Its reported outcome.
 * Logic: Read historical results without using the effective latest snapshot.
 * Dependencies: The feedback history contract.
 */
function resultOfRevision(revision) { return revision.snapshot.result; }

/**
 * Inputs: An uncaught browser verification failure.
 * Outputs: A nonzero process exit code and actionable error text.
 * Logic: Preserve failed-run evidence without reporting a successful check.
 * Dependencies: stderr and the Error object.
 */
function failed(error) {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
}

await main().catch(failed);
