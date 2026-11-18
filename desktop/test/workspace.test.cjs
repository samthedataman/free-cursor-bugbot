const { test } = require("node:test");
const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const { mkdtemp, mkdir, writeFile, rm } = require("node:fs/promises");
const { createServer } = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { _electron } = require("playwright");
const { expect } = require("playwright/test");

test(
  "review, navigate Git history, and trace issue evidence in an Electron window",
  { timeout: 120000 },
  async (t) => {
    const tmp = await mkdtemp(path.join(os.tmpdir(), "bugbot-desktop-test-"));
    t.after(() => rm(tmp, { recursive: true, force: true }));
    const repo = path.join(tmp, "shop");
    await mkdir(repo);
    const git = (...args) =>
      execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" });
    git("init", "-q", "-b", "main");
    git("config", "core.hooksPath", os.devNull);
    git("config", "user.name", "Reviewer Fixture");
    git("config", "user.email", "fixture@example.invalid");
    git("config", "commit.gpgSign", "false");
    const source = path.join(repo, "billing.py");
    await writeFile(source, "def price():\n    return 100\n");
    git("add", ".");
    git("commit", "-qm", "Introduce billing (#42)");
    git("branch", "baseline");
    await writeFile(source, "def price():\n    return 1\n");
    git("add", ".");
    git("commit", "-qm", "Change unit conversion", "-m", "Related to #42");
    const calls = [];
    const server = createServer(async (req, res) => {
      let raw = "";
      for await (const chunk of req) raw += chunk;
      const payload = JSON.parse(raw);
      calls.push([req.url, payload.model]);
      const answer = JSON.stringify({
        findings: [
          {
            severity: "high",
            file: "billing.py",
            line: 2,
            title: "Changes the unit",
            detail: "The caller expects an amount in cents.",
          },
        ],
      });
      const response =
        req.url === "/messages"
          ? { content: [{ type: "text", text: answer }] }
          : req.url === "/api/chat"
            ? { message: { content: answer } }
            : { choices: [{ message: { content: answer } }] };
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(response));
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    t.after(() => new Promise((resolve) => server.close(resolve)));
    const endpoint = "http://127.0.0.1:" + server.address().port;
    const home = path.join(tmp, "data");
    await mkdir(home);
    const checkers = ["openai", "anthropic", "ollama"].map((p, i) => ({
      name: "Checker " + (i + 1),
      provider: p,
      model: "fixture-" + i,
      endpoint,
      keyEnv: "",
      focus: "Review correctness",
    }));
    await writeFile(
      path.join(home, "checkers.json"),
      JSON.stringify({ checkers }),
    );
    const appDir = path.resolve(__dirname, "..");
    const packagedExecutable = process.env.BUGBOT_TEST_PACKAGED_APP;
    const application = await _electron.launch({
      executablePath: packagedExecutable || require("electron"),
      cwd: appDir,
      args: [
        ...(packagedExecutable ? [] : [appDir]),
        "--repo",
        repo,
        "--user-data-dir=" + path.join(tmp, "profile"),
      ],
      env: { ...process.env, REPO_BUGBOT_HOME: home },
    });
    t.after(() => application.close());
    assert.equal(
      await application.evaluate(({ app }) => app.isPackaged),
      Boolean(packagedExecutable),
    );
    const page = await application.firstWindow();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await expect(
      page.getByRole("heading", { name: "Change unit conversion" }),
    ).toBeVisible();
    await page.locator("#search").fill("introduce");
    await expect(page.locator(".commit-row")).toHaveCount(1);
    await page.locator("#search").fill("");
    await page.locator("#graph-filter").selectOption("issues");
    await page.locator(".node.ref").click();
    await expect(page.locator(".inspector h4")).toHaveText("#42");
    await page.locator('[data-tab="changes"]').click();
    await expect(page.locator(".patch")).toContainText("+    return 1");
    await page.locator('[data-tab="risks"]').click();
    await page.getByRole("button", { name: "View connections" }).click();
    await expect(page.locator(".inspector h4")).toHaveText(
      "billing/provisioning",
    );
    await page.locator("#settings-btn").click();
    await expect(page.locator(".checker-editor")).toHaveCount(3);
    await page.getByRole("button", { name: "Add checker" }).click();
    await page.locator('[data-provider="3"]').selectOption("gemini");
    await expect(
      page.locator(".checker-editor").last().locator('[data-field="endpoint"]'),
    ).toHaveValue(/googleapis/);
    await page.getByRole("button", { name: "Remove checker 4" }).click();
    await page.getByRole("button", { name: "Save checkers" }).click();
    await expect(page.locator("dialog")).not.toBeVisible();
    await page.locator("#run-btn").click();
    await expect(page.locator(".checker-results article")).toHaveCount(3, {
      timeout: 30000,
    });
    await expect(page.locator(".finding-card")).toHaveCount(1);
    await expect(page.locator(".finding-card")).toContainText(
      "Checker 1 · Checker 2 · Checker 3",
    );
    assert.deepEqual(calls.map((x) => x[0]).sort(), [
      "/api/chat",
      "/chat/completions",
      "/messages",
    ]);
    await page
      .locator(".finding-card")
      .getByRole("button", { name: "View connections" })
      .click();
    await expect(page.locator(".inspector h4")).toHaveText("Changes the unit");
    await page.getByRole("button", { name: "View diff" }).click();
    await expect(page.locator(".diff-anchor")).toContainText("+    return 1");
    await page.locator("#branch").selectOption("baseline");
    await expect(
      page.getByRole("heading", { name: "Introduce billing (#42)" }),
    ).toBeVisible();
    await page.locator('[data-tab="reviews"]').click();
    await expect(
      page.getByRole("heading", { name: "No reviews for this commit" }),
    ).toBeVisible();
    await page.locator("#branch").selectOption("main");
    await expect(page.locator(".finding-card")).toHaveCount(1);
    await application.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].setSize(940, 700),
    );
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    const empty = path.join(tmp, "empty");
    await mkdir(empty);
    execFileSync("git", ["-C", empty, "init", "-q", "-b", "main"]);
    await application.evaluate(({ dialog }, folder) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [folder],
      });
    }, empty);
    await page.locator("#open").click();
    await expect(
      page.getByRole("heading", { name: "No commits yet" }),
    ).toBeVisible();
    await expect(page.locator("#run-btn")).toBeDisabled();
    assert.deepEqual(errors, []);
  },
);
