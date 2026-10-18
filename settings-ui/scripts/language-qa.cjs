// Isolated real Python + Electron language QA. Never opens the user's settings.
const { _electron: electron } = require("playwright");
const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const fs = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "../..");
const edition = process.argv[2] || "pet-assistant";
const language = process.argv[3] || "en";
const communityFolder = process.argv[4];
const out = path.join(
  root,
  process.env.LANGUAGE_QA_ROOT || "dev-artifacts/language-qa",
  edition +
    "-" +
    language +
    (process.env.SETTINGS_QA_EXECUTABLE ? "-packaged" : "") +
    (communityFolder ? "-community" : ""),
);
const english = language === "en";
const labels = english
  ? {
      pet: "Pet",
      bubble: "Bubbles",
      app: "App settings",
      home: "Home",
      usage: "Usage",
      activity: "Activity",
      integration: "Connections & diagnostics",
      widget: "Widget",
    }
  : {
      pet: "펫",
      bubble: "말풍선",
      app: "앱 설정",
      home: "홈",
      usage: "사용량",
      activity: "활동 기록",
      integration: "연결·진단",
      widget: "위젯",
    };
// Language names in the pack picker and user-owned values (pet, project and
// conversation names, paths) keep the text they were given in any language.
const USER_TEXT = "option, [data-user-text]";
// Runs in the page: untranslated Hangul and app text the layout cuts off.
function inspectText(node, { english, userText }) {
  const clone = node.cloneNode(true);
  clone.querySelectorAll(userText).forEach((child) => child.remove());
  const korean = english
    ? (clone.textContent.match(/[가-힣][가-힣\s·]*/g) || []).map((text) =>
        text.trim(),
      )
    : [];
  const clipped = [];
  for (const element of node.querySelectorAll("*")) {
    // Rows shorten long user values on purpose; only app-only text must fit.
    if (element.closest(userText) || element.querySelector(userText)) continue;
    const ownText = [...element.childNodes].some(
      (child) => child.nodeType === Node.TEXT_NODE && child.textContent.trim(),
    );
    // Inline boxes report no client size; their block parent is measured.
    if (!ownText || !element.clientWidth) continue;
    const style = getComputedStyle(element);
    const scrolls = (value) => value === "auto" || value === "scroll";
    // Text wider than its box is either cut off or spills over neighbours.
    const cutY =
      style.webkitLineClamp !== "none" ||
      style.overflowY === "hidden" ||
      style.overflowY === "clip";
    if (
      (!scrolls(style.overflowX) &&
        element.scrollWidth > element.clientWidth + 1) ||
      (cutY && element.scrollHeight > element.clientHeight + 1)
    ) {
      clipped.push(element.textContent.trim().slice(0, 80));
    }
  }
  return { korean, clipped };
}
async function assertText(locator, label) {
  const { korean, clipped } = await locator.evaluate(inspectText, {
    english,
    userText: USER_TEXT,
  });
  assert.deepEqual(
    korean,
    [],
    "untranslated app text on " + label + ": " + korean.join("; "),
  );
  assert.deepEqual(
    clipped,
    [],
    "clipped app text on " + label + ": " + clipped.join("; "),
  );
}
async function until(fn, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await fn()) return;
    await new Promise((resolve) => setTimeout(resolve, 60));
  }
  throw Error("Condition timed out");
}
(async () => {
  await fs.mkdir(out, { recursive: true });
  const communityManifest = communityFolder
    ? JSON.parse(
        await fs.readFile(path.join(communityFolder, "manifest.json"), "utf8"),
      )
    : null;
  const communityMessages = communityFolder
    ? JSON.parse(
        await fs.readFile(path.join(communityFolder, "messages.json"), "utf8"),
      )
    : null;
  const python = spawn(
    path.join(root, ".venv/Scripts/python.exe"),
    [
      "-m",
      "scripts.settings_ui_qa_server",
      "--edition",
      edition,
      "--language",
      language,
      ...(communityFolder ? ["--language-pack", communityFolder] : []),
    ],
    {
      cwd: root,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: "1", QT_QPA_PLATFORM: "offscreen" },
    },
  );
  let stderr = "",
    app;
  python.stderr.on("data", (data) => (stderr += data.toString()));
  const errors = [],
    metrics = { edition, language, pages: [], errors };
  try {
    const connection = await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(Error("Python startup: " + stderr)),
        20000,
      );
      createInterface({ input: python.stdout }).once("line", (line) => {
        clearTimeout(timer);
        try {
          resolve(JSON.parse(line));
        } catch (error) {
          reject(error);
        }
      });
      python.once("exit", (code) => {
        clearTimeout(timer);
        reject(Error("Python exited " + code + ": " + stderr));
      });
    });
    const env = {
      ...process.env,
      WATCHED_KETTLE_SETTINGS_PIPE: connection.pipe,
      WATCHED_KETTLE_SETTINGS_TOKEN: connection.token,
      WATCHED_KETTLE_SETTINGS_PROFILE: connection.profile,
    };
    delete env.ELECTRON_RUN_AS_NODE;
    app = await electron.launch({
      executablePath:
        process.env.SETTINGS_QA_EXECUTABLE ||
        path.join(root, "settings-ui/node_modules/electron/dist/electron.exe"),
      args: process.env.SETTINGS_QA_EXECUTABLE
        ? []
        : [path.join(root, "settings-ui")],
      env,
      timeout: 20000,
    });
    const page = await app.firstWindow();
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("dialog", (dialog) => dialog.accept());
    await page
      .getByRole("heading", { name: labels.pet, exact: true, level: 1 })
      .waitFor();
    assert.equal(
      await page.locator("html").getAttribute("lang"),
      communityManifest?.locale || (english ? "en-US" : "ko"),
    );
    assert.equal(
      await page.title(),
      english ? "Watched Kettle · Settings" : "Watched Kettle · 설정",
    );
    // The detector must see a single Hangul syllable and cut-off text in the
    // real renderer, but not user-owned values.
    await page.locator("main").evaluate((node) => {
      const box = document.createElement("div");
      box.id = "language-qa-probe";
      box.innerHTML =
        '<p style="width:40px;white-space:nowrap;overflow:hidden;' +
        'text-overflow:ellipsis">A long label that cannot fit</p>' +
        "<p>Done 건</p><p data-user-text>사용자 제목</p>";
      node.append(box);
    });
    const probe = await page
      .locator("#language-qa-probe")
      .evaluate(inspectText, { english: true, userText: USER_TEXT });
    await page.locator("#language-qa-probe").evaluate((node) => node.remove());
    assert.deepEqual(probe, {
      korean: ["건"],
      clipped: ["A long label that cannot fit"],
    });
    const tabs =
      edition === "pet-assistant"
        ? [
            "home",
            "usage",
            "activity",
            "integration",
            "widget",
            "pet",
            "bubble",
            "app",
          ]
        : ["pet", "bubble", "app"];
    for (const id of tabs) {
      await page
        .getByRole("button", { name: labels[id], exact: true })
        .first()
        .click();
      await page
        .getByRole("heading", { name: labels[id], exact: true, level: 1 })
        .waitFor();
      await page.waitForTimeout(450);
      assert.equal(
        await page
          .locator("main")
          .evaluate((node) => node.scrollWidth > node.clientWidth),
        false,
        "horizontal overflow: " + id,
      );
      const text = await page.locator("main").innerText();
      assert.equal(
        /\bmessage\.\d{4}\b/.test(text),
        false,
        "unresolved message ID: " + id,
      );
      await assertText(page.locator("main"), id);
      await page.screenshot({ path: path.join(out, id + ".png") });
      if (id === "pet") {
        await page
          .getByRole("button", {
            name: english ? "Manage pets" : "펫 관리",
            exact: true,
          })
          .click();
        const manager = page.getByRole("dialog");
        await manager.waitFor();
        assert.equal(
          /\bmessage\.\d{4}\b/.test(await manager.innerText()),
          false,
        );
        await assertText(manager, "pet manager");
        await page.screenshot({ path: path.join(out, "pet-manager.png") });
        assert.equal(
          await manager.evaluate((node) => node.scrollWidth > node.clientWidth),
          false,
        );
        await manager
          .getByRole("button", {
            name: english ? "Close" : "닫기",
            exact: true,
          })
          .last()
          .click();
      }
      if (id === "bubble") {
        await page
          .getByRole("button", {
            name: english ? "Edit bubble design" : "말풍선 꾸미기",
            exact: true,
          })
          .click();
        const editor = page.getByRole("dialog");
        await editor.waitFor();
        await page.locator(".bubble-preview-image").waitFor();
        assert.equal(
          /\bmessage\.\d{4}\b/.test(await editor.innerText()),
          false,
        );
        await assertText(editor, "bubble editor");
        await page.screenshot({ path: path.join(out, "bubble-editor.png") });
        assert.equal(
          await editor.evaluate((node) => node.scrollWidth > node.clientWidth),
          false,
        );
        await editor
          .getByRole("button", {
            name: english ? "Cancel" : "취소",
            exact: true,
          })
          .click();
      }
      if (id === "app" && communityManifest) {
        await page
          .getByRole("heading", {
            name: communityMessages["language.title"].value,
            exact: true,
          })
          .waitFor();
        const state = await page.evaluate(() =>
          window.settings.request("settings.snapshot"),
        );
        assert.equal(state.language.current, communityManifest.id);
        assert.equal(state.language.selected, communityManifest.id);
        assert.equal(state.language.recovered, false);
        assert.equal(state.language.restartRequired, false);
        // Missing messages come from the same-language pack, otherwise English.
        const fallback = communityManifest.locale.startsWith("ko")
          ? /한국어 문구로 표시합니다/
          : /missing messages? (is|are) shown in English/;
        await page.getByText(fallback).waitFor();
        // Packs with invalid entries list each key and reason without paths.
        const problems = page.locator(".language-problems");
        if (await problems.count()) {
          await problems.locator("summary").click();
          const listed = await problems.locator("li").allInnerTexts();
          assert.ok(listed.length > 0);
          // Grouped so the public privacy scan does not read it as a path.
          assert.equal(
            /[A-Za-z]:\\|(?:\/Users\/)/.test(listed.join("\n")),
            false,
          );
          await page.screenshot({
            path: path.join(out, "community-problems.png"),
          });
          metrics.communityProblems = listed.length;
        }
        await page
          .getByRole("button", {
            name: english ? "Copy as editable pack" : "편집용 팩으로 복사",
            exact: true,
          })
          .click();
        await page
          .getByText(
            english
              ? /Created and selected an editable pack/
              : /편집용 팩을 만들고 선택했습니다/,
          )
          .waitFor();
        const copied = await page.evaluate(() =>
          window.settings.request("settings.snapshot"),
        );
        assert.equal(copied.language.current, communityManifest.id);
        assert.match(
          copied.language.selected,
          new RegExp("^custom\\." + communityManifest.locale.toLowerCase()),
        );
        assert.equal(copied.language.restartRequired, true);
        await page.screenshot({ path: path.join(out, "community-copied.png") });
        metrics.community = {
          id: communityManifest.id,
          locale: communityManifest.locale,
          translatedHeading: true,
          copiedTo: copied.language.selected,
        };
      }
      if (id === "usage") {
        await page.locator(".trend-card").waitFor();
        if (communityManifest) {
          await fs.writeFile(
            connection.control,
            JSON.stringify({ action: "codex_limits" }),
          );
          await page.locator(".trend-hit").first().waitFor();
          await page.locator(".trend-hit").first().hover();
          await page.locator(".trend-tooltip").waitFor();
          assert.match(
            await page.locator(".trend-tooltip").innerText(),
            /0 jeton(?!s)/,
          );
          await page
            .getByRole("button", {
              name: english ? "Daily tokens" : "일별 토큰",
              exact: true,
            })
            .click();
          await page.locator(".trend-hit").last().hover();
          await until(async () =>
            /jetons/.test(await page.locator(".trend-tooltip").innerText()),
          );
          assert.match(
            await page.locator(".trend-tooltip").innerText(),
            /jetons/,
          );
          await page.screenshot({
            path: path.join(out, "community-token-plural.png"),
          });
          metrics.communityTokenPlural = true;
        }
        for (const chart of english
          ? ["Today's tokens", "Today's limits", "Daily tokens"]
          : ["오늘 토큰", "오늘 한도", "일별 토큰"]) {
          await page.getByRole("button", { name: chart, exact: true }).click();
          await page.waitForTimeout(150);
          if (english)
            assert.equal(
              /[가-힣]/.test(await page.locator("main").innerText()),
              false,
              "trend text: " + chart,
            );
        }
        await page.screenshot({ path: path.join(out, "usage-trends.png") });
      }
      metrics.pages.push(id);
    }
    if (edition === "pet-assistant") {
      // The first pass sees empty history; repeat with limits and a running
      // Claude Code conversation so cards, rows and chart labels are checked.
      const control = async (data) => {
        await fs.writeFile(connection.control, JSON.stringify(data));
        await until(async () =>
          fs.access(connection.control).then(
            () => false,
            () => true,
          ),
        );
      };
      for (const action of [
        "codex_limits",
        "claude_code",
        "claude_code_limits",
      ]) {
        await control({ action });
      }
      metrics.filledPages = [];
      for (const id of ["home", "usage", "activity", "integration", "widget"]) {
        await page
          .getByRole("button", { name: labels[id], exact: true })
          .first()
          .click();
        await page
          .getByRole("heading", { name: labels[id], exact: true, level: 1 })
          .waitFor();
        await page.waitForTimeout(450);
        assert.equal(
          /\bmessage\.\d{4}\b/.test(await page.locator("main").innerText()),
          false,
          "unresolved message ID with data: " + id,
        );
        await assertText(page.locator("main"), id + " with data");
        await page.screenshot({ path: path.join(out, id + "-data.png") });
        if (id === "usage") {
          // History rows and the conversation dialog show token counts.
          const title = english ? "QA conversation title" : "QA 대화 제목";
          await page
            .getByRole("tab", {
              name: english ? "History" : "기록",
              exact: true,
            })
            .click();
          await page
            .getByRole("button", { name: "Claude Code", exact: true })
            .click();
          await page
            .locator(".project-name strong", { hasText: "qa-folder" })
            .click();
          await page
            .locator(".project-name strong", { hasText: title })
            .waitFor();
          await assertText(page.locator("main"), "usage history");
          await page.screenshot({ path: path.join(out, "usage-history.png") });
          await page
            .locator(".project-name strong", { hasText: title })
            .click();
          const record = page.getByRole("dialog", { name: title });
          await record.waitFor();
          await assertText(record, "usage conversation");
          await page.screenshot({
            path: path.join(out, "usage-conversation.png"),
          });
          await page.keyboard.press("Escape");
          await record.waitFor({ state: "hidden" });
          await page
            .getByRole("tab", {
              name: english ? "Overview" : "현황",
              exact: true,
            })
            .click();
        }
        metrics.filledPages.push(id);
      }
      // The language checks below run on App settings, as after the first pass.
      await page
        .getByRole("button", { name: labels.app, exact: true })
        .first()
        .click();
      await page
        .getByRole("heading", { name: labels.app, exact: true, level: 1 })
        .waitFor();
    }
    // Chromium zoom checks text scaling independently of the host Windows DPI.
    metrics.zoomFactors = [];
    for (const factor of [1.5, 2]) {
      await app.evaluate(
        ({ BrowserWindow }, value) =>
          BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value),
        factor,
      );
      await page.waitForTimeout(150);
      assert.equal(
        await page
          .locator("main")
          .evaluate((node) => node.scrollWidth > node.clientWidth),
        false,
        "zoom overflow: " + factor,
      );
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth,
        ),
        false,
        "document zoom overflow: " + factor,
      );
      // Playwright screenshots crop Chromium zoomed Electron surfaces. Capture
      // the native compositor output to preserve the full visible window.
      const png = await app.evaluate(async ({ BrowserWindow }) =>
        (await BrowserWindow.getAllWindows()[0].capturePage())
          .toPNG()
          .toString("base64"),
      );
      await fs.writeFile(
        path.join(out, "app-zoom-" + factor + ".png"),
        Buffer.from(png, "base64"),
      );
      metrics.zoomFactors.push(factor);
    }
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1),
    );
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].setSize(720, 600),
    );
    await page.screenshot({ path: path.join(out, "app-narrow.png") });
    assert.equal(
      await page
        .locator("main")
        .evaluate((node) => node.scrollWidth > node.clientWidth),
      false,
    );
    const previous = await page.evaluate(() =>
      window.settings.request("settings.snapshot"),
    );
    const languageSelect = page.getByLabel(
      english ? "Language pack" : "사용할 언어팩",
      { exact: true },
    );
    const restartButton = page.locator(".language-details .language-restart");
    const folderButton = page.getByRole("button", {
      name: english ? "Open language pack folder" : "언어팩 폴더 열기",
      exact: true,
    });
    if (previous.language.restartRequired) {
      await languageSelect.selectOption(previous.language.current);
      await until(async () => (await restartButton.count()) === 0);
    }
    await languageSelect.scrollIntoViewIfNeeded();
    const beforeSelection = await languageSelect.boundingBox();
    assert.equal(await restartButton.count(), 0);
    await languageSelect.selectOption(english ? "official.ko" : "official.en");
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).language.restartRequired,
    );
    const next = await page.evaluate(() =>
      window.settings.request("settings.snapshot"),
    );
    assert.equal(next.language.current, previous.language.current);
    await restartButton.waitFor({ state: "visible" });
    const afterSelection = await languageSelect.boundingBox();
    const restartPosition = await restartButton.boundingBox();
    const folderPosition = await folderButton.boundingBox();
    assert.ok(Math.abs(afterSelection.x - beforeSelection.x) < 1);
    assert.ok(Math.abs(afterSelection.y - beforeSelection.y) < 1);
    assert.ok(restartPosition.y >= afterSelection.y + afterSelection.height);
    // Part of the folder / reload / copy row; this narrow window wraps it.
    assert.equal(
      await restartButton.evaluate((node) =>
        node.parentElement.classList.contains("button-row"),
      ),
      true,
    );
    assert.ok(restartPosition.y >= folderPosition.y);
    // Near the default window size the four buttons share one line.
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].setSize(1000, 700),
    );
    await until(async () => {
      const wide = await restartButton.boundingBox();
      const folder = await folderButton.boundingBox();
      return wide && folder && Math.abs(wide.y - folder.y) < 1;
    });
    const wideSelection = await languageSelect.boundingBox();
    const wideRestart = await restartButton.boundingBox();
    assert.ok(
      Math.abs(
        wideRestart.x +
          wideRestart.width -
          wideSelection.x -
          wideSelection.width,
      ) < 1,
    );
    await page.screenshot({ path: path.join(out, "language-restart-wide.png") });
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].setSize(720, 600),
    );
    await until(
      async () => (await page.evaluate(() => window.innerWidth)) <= 720,
    );
    assert.ok(
      Math.abs(
        restartPosition.x +
          restartPosition.width -
          afterSelection.x -
          afterSelection.width,
      ) < 1,
    );
    assert.equal(
      await page
        .getByText(
          english
            ? "Restart the app to use the selected language."
            : "앱을 다시 실행하면 선택한 언어로 표시됩니다.",
          { exact: true },
        )
        .count(),
      0,
    );
    await assertText(page.locator("main"), "language restart pending");
    await page.screenshot({ path: path.join(out, "language-restart.png") });
    await page
      .getByRole("heading", { name: labels.app, exact: true, level: 1 })
      .waitFor();
    await page
      .getByRole("button", {
        name: english ? "Reload language packs" : "언어팩 다시 읽기",
        exact: true,
      })
      .click();
    assert.equal(
      (await page.evaluate(() => window.settings.request("settings.snapshot")))
        .language.current,
      previous.language.current,
    );
    await languageSelect.selectOption(previous.language.current);
    await until(async () => (await restartButton.count()) === 0);
    await languageSelect.selectOption(english ? "official.ko" : "official.en");
    await until(
      async () =>
        (await restartButton.count()) === 1 &&
        (await restartButton.isEnabled()),
    );
    await restartButton.click();
    await until(async () => await restartButton.isDisabled());
    const restartReport = path.join(out, "restart-request.json");
    await fs.writeFile(
      connection.control,
      JSON.stringify({ action: "report", path: restartReport }),
    );
    await until(async () => {
      const report = await fs
        .readFile(restartReport, "utf8")
        .then(JSON.parse)
        .catch(() => null);
      return report?.restartRequests === 1;
    });
    metrics.restart = {
      requestedOnce: true,
      selectorStayedInPlace: true,
      buttonBelowSelector: true,
    };
    assert.deepEqual(errors, []);
    metrics.status = "passed";
  } catch (error) {
    metrics.status = "failed";
    metrics.failure = error.stack;
    metrics.stderr = stderr.slice(-5000);
    throw error;
  } finally {
    await fs.writeFile(
      path.join(out, "metrics.json"),
      JSON.stringify(metrics, null, 2),
    );
    if (app) await app.close().catch(() => {});
    python.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
