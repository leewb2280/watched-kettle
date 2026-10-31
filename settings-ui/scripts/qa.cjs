const { _electron: electron } = require("playwright");
const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const fs = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");
const { performance } = require("node:perf_hooks");
const {
  testBubbleViewport,
  testBubbleLayerTransforms,
  testBubbleBackgroundTransforms,
  selectBubbleSection,
} = require("./bubble-viewport-qa.cjs");

const root = path.resolve(__dirname, "../..");
const edition = process.argv[2] || "pet-assistant";
const executable = process.env.SETTINGS_QA_EXECUTABLE;
// SETTINGS_QA_OUT keeps earlier evidence folders intact for follow-up runs.
const out = process.env.SETTINGS_QA_OUT
  ? path.resolve(root, process.env.SETTINGS_QA_OUT)
  : path.join(
      root,
      "dev-artifacts/stage11",
      edition + (executable ? "-packaged" : ""),
    );
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// A 24x16 pink dot imported as a bubble decoration.
const QA_DECOR_PNG =
  "iVBORw0KGgoAAAANSUhEUgAAABgAAAAQCAYAAAAMJL+VAAAAX0lEQVR42mNgoDFgJKTgTlTFf3zyKss6GEm2gJChpFjGRC3DcellopbhuMxgoqbh2Mxiorbh6JYw0TqZDhMLCGUWSvIEE7E5ktwMx0RKticnNzORWraQWlTQvLCjOQAAkzksGo3g2CIAAAAASUVORK5CYII=";
// Two 192x208 frames joined as a transition between pets.
const QA_LINK_STRIP =
  "iVBORw0KGgoAAAANSUhEUgAAAYAAAADQCAYAAAAOPrb8AAAD5klEQVR42u3c0U0iUBRF0aOxFGqyCCugBCqwCGqiF6zA+KEiuNf6nsyEl8nd9z2JGwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/9uTIwBu5fJ+vH71Zw5vJ3NJAIDK0BcDAQAMfiEQAMDgF4Lf9uwIgEcY/rf4+wUA4I6HswjMExDQGvzzJOQGABj+bgMCABi+IiAAQHnoioAAAOFhKwICAIAAALUt2y1AAIDwcBUBAQDCQ1UEBAAAAQBq27RbgAAA4SEqAgIAgAAAte3ZLeBzL47gto7ny5f/GU+vB7/hEJhfBx0Z+mKArXl+dbQbgKH/2d8jBoAbQGDwuxVg+3cLmB8CG/5/9e8AbgDc8UB2G8D27xbgBhAc/m4DgADEh68IAAIQHroiwDz/+JwC0B22IgAIQHjIigC2Yp9XAMLDVQQAAQgPVREABACY5xCfWwBi27RbACAA4SEqAoAAACAAte3ZLYB5B/f5BaA7NEUAEAAABKC2LbsFMM8fzkEAABCA2JbsFgAIAIAAUNuO3QIAAYD5wSfd8xCA6FbsFgAIAIAAACAA8/zjcwMCAIAA2IJ9fuYbL85FAAAQAAAEAAABmPdv5wAIAAACAIAAACAA8+7tPJjvujsfAQBAAAAQAAAEYN67nQsgAAAIAAACAIAAACAAAAgAgAA4AgABmO+643xAAAAQAAAEAAABAEAAABAAAAQAAAEAQAAAEAAABAC4icPb6ckpOB8BAHADAEAAABAAAAQAAAEAQAAAEIBHcno9+B6085nvuuNc3AAA3AAAEAAABAAAAQBAAID5xovzEAAABGC+6+5cAAEAQAAAEABgfvDpHARg3rudByAAAAgAMM8fPr8AACAA8+7tHAABAEAAgHkH97kFAAABmPdvnx8QAGCeQ+b5RwBswT43IABAciu2/QsAgAA4giWfQzz/AAIArPI84vlHAPJbse0fEAAgsyXb/gUgvx3b/gEBADLbsu1fAPJbsu0fEAAgszXb/gUgvy3b/gEBCA5Nw5/q9mz7FwAgOEQNfwHIb8+2f0AAgkPU8Ke6Tdv+BQAIDlXDXwDy27Ttn+JwNfwFID9UDX9AAILD1fCnumXb/gUgPWQNf6rD1vAXgPSwNfypDl3DXwDSQ9fwpzp8Df/vcXg/4Hi+XA1/6i7vx6vBLwBCYPAjAob/PAHNk5DhzzwJGf5uAG4DBj9uAwa/AIiBoY8QGPwCIAaGPmJg6AMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADwwD4ACPSydKCset8AAAAASUVORK5CYII=";
// Electron shows window.confirm and alert as native message boxes, which
// Playwright's "dialog" event never sees, so a QA run would wait for a person
// to click them. Answer them inside the page instead, on every load.
function answerDialogsInPage(page) {
  const answer = () => {
    window.qaConfirmations = [];
    window.confirm = (message) => {
      window.qaConfirmations.push(String(message));
      return true;
    };
    window.alert = () => {};
  };
  return Promise.all([page.addInitScript(answer), page.evaluate(answer)]);
}

async function until(fn, timeout = 10000) {
  const end = Date.now() + timeout;
  // Attempts and the slowest one tell a slow backend from a lost action.
  let attempts = 0;
  let slowest = 0;
  while (Date.now() < end) {
    const started = Date.now();
    const done = await fn();
    attempts += 1;
    slowest = Math.max(slowest, Date.now() - started);
    if (done) return;
    await pause(40);
  }
  throw Error(
    `condition timed out after ${attempts} attempts (slowest ${slowest}ms)`,
  );
}
// The host sends invalidations 80ms after a change (settings_ui/host.py), and
// the dialog reloads again when one arrives. An action clicked in between is
// dropped, so "settled" means not busy for longer than that delay.
const QUIET_MS = 250;
async function settledFor(locator, timeout = 10000) {
  let quietSince = null;
  await until(async () => {
    if ((await locator.getAttribute("aria-busy")) !== "false") {
      quietSince = null;
      return false;
    }
    quietSince ??= Date.now();
    return Date.now() - quietSince >= QUIET_MS;
  }, timeout);
}

async function testPetBatch({ page, app, connection, out, metrics }) {
  // Multi-selection always captures explicit targets from this screen/page.
  const bulkControl = async (data) => {
    await fs.writeFile(connection.control, JSON.stringify(data));
    await until(async () =>
      fs.access(connection.control).then(
        () => false,
        () => true,
      ),
    );
  };
  await bulkControl({ action: "batch_fixture", count: 55 });
  await page.getByRole("button", { name: "펫 관리", exact: true }).click();
  const bulkManager = page.locator("dialog:has(.pet-manager)");
  const bulkSettled = () =>
    settledFor(bulkManager.locator(".pet-manager"), 30000);
  const bulkStatus = () =>
    page.evaluate(async () => {
      const state = await window.settings.request("settings.snapshot");
      return (
        await window.settings.request("pet.trash.batch.status", {
          epoch: state.epoch,
        })
      ).job;
    });
  const bulkDone = async () => {
    await until(async () => {
      const job = await bulkStatus();
      return job && job.state !== "running";
    }, 60000);
    await bulkSettled();
  };
  await bulkSettled();
  await bulkManager.getByRole("button", { name: "선택", exact: true }).click();
  assert.equal(
    await bulkManager
      .locator('[data-pet-id="mori-bot"]')
      .getByRole("checkbox")
      .isDisabled(),
    true,
  );
  await bulkManager
    .locator('[data-pet-id="batch-qa-00"]')
    .getByRole("checkbox")
    .focus();
  await page.keyboard.press("Space");
  assert.equal(
    await bulkManager
      .getByRole("checkbox", { name: "현재 화면 전체 선택" })
      .evaluate((node) => node.indeterminate),
    true,
  );
  await bulkManager.getByLabel("펫 이름 검색").fill("일괄 QA 중복");
  await until(
    async () =>
      (await bulkManager.getByText("0개 선택", { exact: true }).count()) === 1,
  );
  await bulkManager
    .getByRole("checkbox", { name: "현재 화면 전체 선택" })
    .check();
  assert.equal(
    await bulkManager.locator(".manager-row input:checked").count(),
    2,
  );
  await page.screenshot({ path: path.join(out, "pet-batch-selection.png") });
  await bulkManager.getByLabel("펫 이름 검색").fill("");
  await bulkManager
    .locator('[data-pet-id="batch-qa-00"]')
    .getByRole("checkbox")
    .check();
  await bulkManager
    .locator('[data-pet-id="batch-qa-01"]')
    .getByRole("checkbox")
    .check();
  await bulkControl({
    action: "batch_config",
    failed: ["batch-qa-01"],
    delay: 40,
  });
  await bulkManager
    .getByRole("button", { name: "선택한 펫 이동", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "선택한 펫 이동", exact: true })
    .getByRole("button", { name: "휴지통으로 이동", exact: true })
    .click();
  await bulkDone();
  await bulkManager.getByText("1개 선택", { exact: true }).waitFor();
  assert.equal((await bulkStatus()).failed, 1);
  await page.screenshot({
    path: path.join(out, "pet-batch-partial-failure.png"),
  });
  await bulkManager
    .getByRole("button", { name: "실행 취소 (1개)", exact: true })
    .click();
  await bulkDone();
  await bulkControl({ action: "batch_config", failed: [], delay: 200 });
  await bulkManager.getByRole("button", { name: "선택", exact: true }).click();
  await bulkManager
    .getByRole("checkbox", { name: "현재 화면 전체 선택" })
    .check();
  await bulkManager
    .getByRole("button", { name: "선택한 펫 이동", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "선택한 펫 이동", exact: true })
    .getByRole("button", { name: "휴지통으로 이동", exact: true })
    .click();
  await until(async () => (await bulkStatus())?.processed >= 1, 30000);
  await page.screenshot({ path: path.join(out, "pet-batch-progress.png") });
  // Closing the settings window hides its renderer; the Python job continues.
  await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].close(),
  );
  await until(
    async () =>
      !(await app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows()[0].isVisible(),
      )),
  );
  await until(async () => (await bulkManager.count()) === 0);
  await bulkControl({ action: "show", page: "pet" });
  await until(
    async () =>
      await app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows()[0].isVisible(),
      ),
  );
  await page.getByRole("button", { name: "펫 관리", exact: true }).click();
  await bulkManager
    .getByRole("button", { name: "남은 작업 중단", exact: true })
    .click();
  await bulkDone();
  const cancelled = await bulkStatus();
  assert.equal(cancelled.state, "cancelled");
  assert.ok(cancelled.processed < cancelled.total);
  assert.ok(cancelled.succeeded > 0);
  await bulkManager.getByRole("button", { name: /^실행 취소 \(/ }).click();
  await bulkDone();
  await bulkControl({ action: "batch_config", failed: [], delay: 0 });
  await bulkManager
    .getByRole("button", { name: "닫기", exact: true })
    .last()
    .click();
  // Include a currently used pet; the replacement cannot be another target.
  await page.evaluate(async () => {
    const state = await window.settings.request("settings.snapshot");
    await window.settings.request("pet.select", {
      epoch: state.epoch,
      petId: state.pet.pet_id,
      revision: state.revision,
      id: "batch-qa-00",
    });
  });
  await page.getByRole("button", { name: "펫 관리", exact: true }).click();
  await bulkSettled();
  await bulkManager.getByLabel("펫 이름 검색").fill("일괄 QA");
  await bulkManager.getByRole("button", { name: "선택", exact: true }).click();
  await bulkManager
    .getByRole("checkbox", { name: "현재 화면 전체 선택" })
    .check();
  await bulkManager
    .getByRole("button", { name: "선택한 펫 이동", exact: true })
    .click();
  const bulkConfirm = page.getByRole("dialog", {
    name: "선택한 펫 이동",
    exact: true,
  });
  assert.equal(
    await bulkConfirm
      .getByLabel("대신 사용할 펫")
      .locator('option[value^="batch-qa-"]')
      .count(),
    0,
  );
  await bulkConfirm.getByLabel("대신 사용할 펫").selectOption("mori-bot");
  await bulkConfirm
    .getByRole("button", { name: "휴지통으로 이동", exact: true })
    .click();
  await bulkDone();
  assert.equal((await bulkStatus()).succeeded, 55);
  await bulkManager.getByRole("button", { name: /^휴지통 / }).click();
  await bulkSettled();
  await bulkManager.getByRole("button", { name: "선택", exact: true }).click();
  await bulkManager
    .getByRole("checkbox", { name: "현재 화면 전체 선택" })
    .check();
  await bulkManager.getByText("50개 선택", { exact: true }).waitFor();
  await bulkManager.getByRole("button", { name: "다음", exact: true }).click();
  await bulkSettled();
  await bulkManager.getByText("0개 선택", { exact: true }).waitFor();
  await bulkManager
    .getByRole("checkbox", { name: "현재 화면 전체 선택" })
    .check();
  await bulkManager.getByText("5개 선택", { exact: true }).waitFor();
  await page.screenshot({ path: path.join(out, "pet-batch-trash-page.png") });
  await bulkManager
    .getByRole("button", { name: "선택한 펫 복원", exact: true })
    .click();
  await bulkDone();
  assert.equal((await bulkStatus()).succeeded, 5);
  await bulkManager.getByRole("button", { name: "선택", exact: true }).click();
  await bulkManager
    .getByRole("checkbox", { name: "현재 화면 전체 선택" })
    .check();
  await bulkManager
    .getByRole("button", { name: "선택한 펫 영구 삭제", exact: true })
    .click();
  const bulkDelete = page.getByRole("dialog", {
    name: "선택한 펫 영구 삭제",
    exact: true,
  });
  await bulkDelete.getByText(/복구할 수 없어요/).waitFor();
  await bulkDelete.getByRole("button", { name: "취소", exact: true }).click();
  assert.equal((await bulkStatus()).action, "restore");
  await bulkManager
    .getByRole("button", { name: "선택한 펫 영구 삭제", exact: true })
    .click();
  await bulkDelete
    .getByRole("button", { name: "영구 삭제", exact: true })
    .click();
  await bulkDone();
  assert.equal((await bulkStatus()).succeeded, 50);
  await bulkManager.getByText("휴지통이 비어 있어요.").waitFor();
  await bulkManager
    .getByRole("button", { name: "닫기", exact: true })
    .last()
    .click();
  metrics.petBatch = {
    status: "passed",
    fixtures: 55,
    partialFailure: true,
    cancelAndReopen: true,
    pageScopedSelection: true,
    groupUndo: true,
  };
}

(async () => {
  await fs.mkdir(out, { recursive: true });
  const python = spawn(
    process.env.SETTINGS_QA_PYTHON ||
      path.join(root, ".venv/Scripts/python.exe"),
    ["-m", "scripts.settings_ui_qa_server", "--edition", edition],
    {
      cwd: root,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: "1", QT_QPA_PLATFORM: "offscreen" },
    },
  );
  let stderr = "";
  python.stderr.on("data", (data) => (stderr += data.toString()));
  let app, connection;
  const metrics = {
    edition,
    backend: "isolated real Python models and QLocalServer",
    reopened: 0,
    errors: [],
  };
  try {
    connection = await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(Error("Python bridge startup timeout: " + stderr)),
        12000,
      );
      createInterface({ input: python.stdout }).once("line", (line) => {
        clearTimeout(timer);
        resolve(JSON.parse(line));
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
    const start = performance.now();
    app = await electron.launch({
      executablePath: executable
        ? path.resolve(executable)
        : process.env.SETTINGS_QA_ELECTRON
          ? path.resolve(process.env.SETTINGS_QA_ELECTRON)
          : path.join(
              root,
              "settings-ui/node_modules/electron/dist/electron.exe",
            ),
      args: executable ? [] : [path.join(root, "settings-ui")],
      env,
      timeout: 20000,
    });
    const page = await app.firstWindow();
    page.on("pageerror", (error) => metrics.errors.push(error.message));
    page.on("dialog", (dialog) => dialog.accept());
    await answerDialogsInPage(page);
    await page
      .getByRole("heading", { name: "펫", exact: true, level: 1 })
      .waitFor();
    metrics.coldOpenMs = Math.round(performance.now() - start);
    // Focused iteration still uses the same isolated host and real painter.
    // Full QA below always includes these checks too.
    if (process.argv.includes("--bubble-only")) {
      await page.getByRole("button", { name: "말풍선", exact: true }).click();
      await page
        .getByRole("button", { name: "말풍선 꾸미기", exact: true })
        .click();
      await page.locator(".bubble-preview-image").waitFor();
      metrics.bubbleViewport = await testBubbleViewport({ page, app, out });
      await selectBubbleSection(page, "장식");
      const image = path.join(out, "viewport-decor.png");
      await fs.writeFile(image, Buffer.from(QA_DECOR_PNG, "base64"));
      await app.evaluate(({ dialog }, file) => {
        globalThis.qaOriginalPicker = dialog.showOpenDialog;
        dialog.showOpenDialog = async () => ({
          canceled: false,
          filePaths: [file],
        });
      }, image);
      await page
        .getByRole("button", { name: "이미지 가져오기", exact: true })
        .click();
      await page.locator(".canvas-layer.is-selected").waitFor();
      await app.evaluate(({ dialog }) => {
        dialog.showOpenDialog = globalThis.qaOriginalPicker;
      });
      metrics.bubbleLayerTransforms = await testBubbleLayerTransforms({
        page,
        app,
      });
      assert.deepEqual(metrics.errors, []);
      metrics.status = "passed";
      console.log(
        JSON.stringify({
          edition,
          status: metrics.status,
          scope: "bubble-only",
        }),
      );
      return;
    }
    const controlGesture = async () => {
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "double_click" }),
      );
      await until(async () =>
        fs.access(connection.control).then(
          () => false,
          () => true,
        ),
      );
    };
    await page.getByRole("button", { name: "홈", exact: true }).click();
    await page
      .getByRole("heading", { name: "홈", exact: true, level: 1 })
      .waitFor();
    await page.getByRole("heading", { name: "나의 펫", exact: true }).waitFor();
    await page.locator(".pet-home-summary img").waitFor();
    assert.equal(await page.locator("h1").count(), 1);
    await page.screenshot({ path: path.join(out, "common-home.png") });
    // A pet gesture: it lives on the pet page's behavior tab.
    await page.getByRole("button", { name: "펫", exact: true }).first().click();
    await page.getByRole("tab", { name: "동작·화면", exact: true }).click();
    const doubleClick = page.getByLabel("더블클릭 동작", { exact: true });
    assert.equal(await doubleClick.inputValue(), "settings_home");
    assert.equal(await doubleClick.locator("option").count(), 4);
    assert.equal(
      await doubleClick.locator('option[value="claude"]').isDisabled(),
      false,
    );
    for (const value of ["codex", "claude", "wave_only", "settings_home"]) {
      await doubleClick.selectOption(value);
      await until(
        async () =>
          (
            await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            )
          ).doubleClickAction === value,
      );
      await pause(120);
    }
    await page.screenshot({
      path: path.join(out, "double-click-settings.png"),
    });
    await page.getByRole("tab", { name: "외형·표시", exact: true }).click();
    await controlGesture();
    await page
      .getByRole("heading", { name: "홈", exact: true, level: 1 })
      .waitFor();
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].close(),
    );
    await pause(250);
    await controlGesture();
    await until(async () =>
      app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows()[0].isVisible(),
      ),
    );
    await page
      .getByRole("heading", { name: "홈", exact: true, level: 1 })
      .waitFor();
    metrics.doubleClick = {
      commonHome: true,
      choices: 4,
      claudeDisabled: true,
      gestureOpensHome: true,
      hiddenReopen: true,
    };
    await page.getByRole("button", { name: "정보", exact: true }).click();
    await page
      .getByRole("heading", { name: "정보", exact: true, level: 1 })
      .waitFor();
    await page
      .locator("main")
      .getByText(edition === "pet-assistant" ? "펫 + 비서" : "펫만")
      .first()
      .waitFor();
    assert.ok((await page.locator(".about-list li").count()) >= 5);
    assert.equal(
      await page
        .getByRole("button", { name: "라이선스 폴더 열기", exact: true })
        .isDisabled(),
      true,
    );
    // A repository link goes to the default browser, never a new window.
    await app.evaluate(({ shell }) => {
      globalThis.qaOpened = [];
      shell.openExternal = async (url) => globalThis.qaOpened.push(url);
    });
    await page
      .getByRole("link", { name: "전체 패치노트", exact: true })
      .click();
    await until(async () =>
      app.evaluate(() => globalThis.qaOpened.length === 1),
    );
    const opened = await app.evaluate(() => globalThis.qaOpened[0]);
    assert.match(
      opened,
      /^https:\/\/github\.com\/leewb2280\/watched-kettle\/releases\/tag\/v/,
    );
    assert.equal(
      await app.evaluate(
        ({ BrowserWindow }) => BrowserWindow.getAllWindows().length,
      ),
      1,
    );
    await page.screenshot({ path: path.join(out, "about.png") });
    metrics.about = { externalLink: true, licensesDisabled: true };
    await page.getByRole("button", { name: "펫", exact: true }).click();
    await page
      .getByRole("heading", { name: "펫", exact: true, level: 1 })
      .waitFor();
    if (process.env.SETTINGS_QA_FOCUS === "pet-batch") {
      await testPetBatch({ page, app, connection, out, metrics });
      await page.getByRole("button", { name: "앱 설정", exact: true }).click();
      await page.getByLabel("테마", { exact: true }).selectOption("dark");
      await page.getByRole("button", { name: "펫", exact: true }).click();
      await app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows()[0].setSize(720, 600),
      );
      await page.getByRole("button", { name: "펫 관리", exact: true }).click();
      const manager = page.getByRole("dialog", {
        name: "펫 관리",
        exact: true,
      });
      await manager.getByRole("button", { name: "선택", exact: true }).click();
      await manager
        .getByRole("checkbox", { name: "현재 화면 전체 선택" })
        .check();
      await page.screenshot({
        path: path.join(out, "pet-batch-narrow-dark.png"),
      });
      assert.equal(
        await manager.evaluate((node) => node.scrollWidth > node.clientWidth),
        false,
      );
      metrics.status = "passed";
      console.log(
        JSON.stringify({ edition, focus: "pet-batch", status: "passed" }),
      );
      return;
    }

    // Only replace the OS picker result. Electron IPC, authenticated pipe,
    // image validation, storage and the Python pet remain the real instances.
    const importBefore = await page.evaluate(() =>
      window.settings.request("settings.snapshot"),
    );
    const pickerResult = async (file) =>
      app.evaluate(({ dialog }, file) => {
        if (!globalThis.qaOriginalPicker)
          globalThis.qaOriginalPicker = dialog.showOpenDialog;
        dialog.showOpenDialog = async () =>
          file
            ? { canceled: false, filePaths: [file] }
            : { canceled: true, filePaths: [] };
      }, file);
    await pickerResult(null);
    await page
      .getByRole("button", { name: "펫 가져오기", exact: false })
      .click();
    let importDialog = page.getByRole("dialog", {
      name: "펫 가져오기",
      exact: true,
    });
    await importDialog
      .getByRole("button", { name: "파일 선택", exact: true })
      .click();
    assert.equal(
      await importDialog
        .getByRole("button", { name: "펫 추가", exact: true })
        .count(),
      0,
    );
    await pickerResult(connection.petImportInvalid);
    await importDialog
      .getByRole("button", { name: "파일 선택", exact: true })
      .click();
    await until(async () =>
      (await importDialog.getByRole("alert").innerText()).includes("크기"),
    );
    await pickerResult(connection.petImportSource);
    await importDialog
      .getByRole("button", { name: "파일 선택", exact: true })
      .click();
    await importDialog.getByLabel("펫 이름").fill("웹 펫 QA");
    await importDialog.locator(".pet-import-preview img").waitFor();
    await importDialog.screenshot({
      path: path.join(out, "pet-import-preview.png"),
    });
    await importDialog
      .getByRole("button", { name: "펫 추가", exact: true })
      .click();
    await importDialog
      .getByText("을(를) 펫 목록에 추가했습니다.", { exact: false })
      .waitFor();
    assert.equal(await importDialog.locator(".import-animation").count(), 0);
    assert.equal(await importDialog.getByRole("tab").count(), 0);
    const importCatalog = await page.evaluate(() =>
      window.settings.request("pet.catalog"),
    );
    const imported = importCatalog.entries.find(
      (entry) => entry.name === "웹 펫 QA",
    );
    assert.ok(imported);
    assert.equal(importCatalog.petId, importBefore.pet.pet_id);
    await importDialog
      .getByRole("button", { name: "이 펫 사용", exact: true })
      .click();
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.pet_id === imported.id,
    );
    await until(async () => !(await importDialog.count()));
    await page
      .getByRole("button", { name: "펫 가져오기", exact: false })
      .click();
    importDialog = page.getByRole("dialog", {
      name: "펫 가져오기",
      exact: true,
    });
    await importDialog
      .getByRole("button", { name: "파일 선택", exact: true })
      .click();
    await importDialog.getByLabel("펫 이름").fill("이름을 덮어쓰지 않음");
    await importDialog
      .getByRole("button", { name: "펫 추가", exact: true })
      .click();
    await importDialog.getByText(/이미 등록되어 있습니다/).waitFor();
    assert.equal(
      (
        await page.evaluate(() => window.settings.request("pet.catalog"))
      ).entries.filter((entry) => entry.id === imported.id).length,
      1,
    );
    await importDialog.screenshot({
      path: path.join(out, "pet-import-duplicate.png"),
    });
    await importDialog
      .getByRole("button", { name: "닫기", exact: true })
      .last()
      .click();
    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = globalThis.qaOriginalPicker;
    });
    await page.evaluate(async (id) => {
      const state = await window.settings.request("settings.snapshot");
      await window.settings.request("pet.select", {
        id,
        petId: state.pet.pet_id,
        revision: state.revision,
        epoch: state.epoch,
      });
    }, importBefore.pet.pet_id);
    await until(
      async () =>
        (await page.locator(".sidebar-profile strong").innerText()) ===
        importBefore.pet.display_name,
    );
    metrics.petImport = {
      status: "passed",
      id: imported.id,
      nativePicker: "stubbed result; real IPC and backend",
    };
    // Expiration keeps the confirmation form and draft available for recovery.
    await pickerResult(connection.petImportSource);
    await page
      .getByRole("button", { name: "펫 가져오기", exact: false })
      .click();
    importDialog = page.getByRole("dialog", {
      name: "펫 가져오기",
      exact: true,
    });
    await importDialog
      .getByRole("button", { name: "파일 선택", exact: true })
      .click();
    await importDialog.getByLabel("펫 이름").fill("만료된 이름 초안");
    await fs.writeFile(
      connection.control,
      JSON.stringify({ action: "import_expire" }),
    );
    await until(() =>
      fs.access(connection.control).then(
        () => false,
        () => true,
      ),
    );
    await importDialog
      .getByRole("button", { name: "펫 추가", exact: true })
      .click();
    await importDialog.getByRole("alert").getByText(/만료/).waitFor();
    assert.equal(
      await importDialog.getByLabel("펫 이름").inputValue(),
      "만료된 이름 초안",
    );
    assert.equal(await importDialog.locator(".import-result").count(), 0);
    await importDialog
      .getByRole("button", { name: "다른 펫 선택", exact: true })
      .click();
    assert.equal(await importDialog.locator(".pet-import-preview").count(), 0);
    assert.equal(
      await importDialog
        .getByRole("button", { name: "펫 추가", exact: true })
        .count(),
      0,
    );
    await importDialog
      .getByRole("button", { name: "취소", exact: true })
      .click();

    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = globalThis.qaOriginalPicker;
    });
    metrics.petImport.expirationRecovery = true;
    const petSize = page.getByLabel("펫 크기", { exact: true });
    await petSize.fill("2");
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.pet_width === 144,
    );
    assert.equal(
      await page
        .getByText(
          "원본 스프라이트 셀은 192×208px입니다. 80~224px는 표준 크기, 256~352px는 큰 화면용 확장 크기입니다.",
          { exact: true },
        )
        .count(),
      1,
    );
    const petPreview = page.locator(".pet-image");
    await until(
      async () =>
        (await petPreview.getAttribute("data-preview-source")) ===
        "original-cell",
    );
    const previewBox = await petPreview.boundingBox();
    assert.ok(previewBox && previewBox.width > 0 && previewBox.height > 0);
    for (const [label, width, footer] of [
      ["기본", 112, "실제 표시: 112×121px · 기본"],
      ["원본", 192, "실제 표시: 192×208px · 원본 크기"],
      ["표준 최대", 224, "실제 표시: 224×243px · 표준 최대"],
      ["확장 최대", 352, "실제 표시: 352×381px · 확장 최대"],
    ]) {
      await page.getByRole("button", { name: label, exact: true }).click();
      await until(
        async () =>
          (
            await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            )
          ).pet.pet_width === width,
      );
      await page.getByText(footer, { exact: true }).waitFor();
      const nextBox = await petPreview.boundingBox();
      assert.ok(nextBox);
      assert.ok(Math.abs(nextBox.width - previewBox.width) <= 1);
      assert.ok(Math.abs(nextBox.height - previewBox.height) <= 1);
      await page.screenshot({ path: path.join(out, `pet-${width}.png`) });
    }
    await petSize.fill("6");
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.pet_width === 256,
    );
    await page
      .getByText("실제 표시: 256×277px · 확장 크기", { exact: true })
      .waitFor();
    await page.screenshot({ path: path.join(out, "pet.png") });

    const originalSnapshot = await page.evaluate(() =>
      window.settings.request("settings.snapshot"),
    );
    const originalCatalog = await page.evaluate(() =>
      window.settings.request("pet.catalog"),
    );
    const visiblePets = originalCatalog.entries.filter(
      (entry) => !originalCatalog.hidden.includes(entry.id),
    );
    assert.ok(visiblePets.length > 1);
    const originalIndex = visiblePets.findIndex(
      (entry) => entry.id === originalSnapshot.pet.pet_id,
    );
    const nextIndex = originalIndex === 0 ? 1 : 0;
    const originalPreviewImage = await petPreview.getAttribute("src");
    await page.getByRole("button", { name: "다른 펫 선택" }).click();
    await page.getByRole("dialog").waitFor();
    await page.locator(".pet-choice").nth(nextIndex).click();
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.pet_id === visiblePets[nextIndex].id,
    );
    await page.getByRole("button", { name: "다른 펫 선택" }).click();
    await page.getByRole("dialog").waitFor();
    await page.locator(".pet-choice").nth(originalIndex).click();
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.pet_id === originalSnapshot.pet.pet_id,
    );
    await until(
      async () =>
        (await petPreview.getAttribute("data-preview-source")) ===
          "original-cell" &&
        (await petPreview.getAttribute("src")) === originalPreviewImage,
    );
    assert.equal(
      await page.getByText("동작 미리보기", { exact: true }).count(),
      0,
    );
    const stageBox = await page.locator(".pet-stage").boundingBox();
    const stageFooterBox = await page.locator(".stage-footer").boundingBox();
    assert.ok(stageBox && stageFooterBox);
    assert.ok(
      stageBox.y +
        stageBox.height -
        (stageFooterBox.y + stageFooterBox.height) <=
        20,
    );
    const initialVisibility = (
      await page.evaluate(() => window.settings.request("settings.snapshot"))
    ).pet.visible;
    await page
      .getByRole("button", {
        name: initialVisibility ? "펫 숨기기" : "펫 다시 표시",
        exact: true,
      })
      .click();
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.visible !== initialVisibility,
    );
    await page
      .getByRole("button", {
        name: initialVisibility ? "펫 다시 표시" : "펫 숨기기",
        exact: true,
      })
      .click();
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.visible === initialVisibility,
    );
    // The renderer learns the new visibility through the next snapshot event.
    const expectedPill = initialVisibility
      ? /^화면 속 펫 · /
      : /^화면에서 숨김$/;
    await until(async () =>
      expectedPill.test(await page.locator(".pet-stage .pill").textContent()),
    );
    assert.equal(
      await page
        .getByRole("button", { name: "펫 폴더 다시 읽기", exact: true })
        .getAttribute("title"),
      "펫 폴더 다시 읽기",
    );
    // Tabs follow the ARIA pattern: arrows move selection and focus.
    await page.getByRole("tab", { name: "외형·표시", exact: true }).focus();
    await page.keyboard.press("ArrowRight");
    await until(
      async () =>
        (await page
          .getByRole("tab", { name: "동작·화면", exact: true })
          .getAttribute("aria-selected")) === "true",
    );
    assert.equal(
      await page.evaluate(() => document.activeElement?.textContent),
      "동작·화면",
    );
    for (const tabName of ["외형·표시", "동작·화면"]) {
      assert.equal(
        await page.getByRole("heading", { name: tabName, exact: true }).count(),
        0,
      );
    }
    const behaviorPanel = page.getByRole("tabpanel", { name: "동작·화면" });
    await behaviorPanel.waitFor();
    for (const removed of [
      "화면 중앙으로",
      "이동 디스플레이로 보내기",
      "실제 이동 테스트",
    ]) {
      assert.equal(
        await page.getByRole("button", { name: removed, exact: true }).count(),
        0,
      );
    }
    assert.equal(
      await behaviorPanel
        .getByRole("button", { name: "화면 가운데로 불러오기", exact: true })
        .count(),
      1,
    );
    const moveToScreen = page.getByRole("button", {
      name: "선택한 디스플레이로 옮기기",
      exact: true,
    });
    const movementScreenValue = async () =>
      (
        await page.evaluate(() => window.settings.request("settings.snapshot"))
      ).controls.find((control) => control.key === "screen").value;
    const originalScreen = await movementScreenValue();
    const movementScreen = page.getByLabel("이동 디스플레이", { exact: true });
    await movementScreen.selectOption("current");
    await until(async () => (await movementScreenValue()) === "current");
    await until(async () => (await moveToScreen.count()) === 0);
    await movementScreen.selectOption("primary");
    await until(async () => (await movementScreenValue()) === "primary");
    await moveToScreen.waitFor();
    await page.screenshot({ path: path.join(out, "pet-behavior-screen.png") });
    await movementScreen.selectOption(originalScreen);
    await until(async () => (await movementScreenValue()) === originalScreen);
    const lookRange = page.getByLabel("마우스 반응 거리", { exact: true });
    assert.equal(await lookRange.getAttribute("aria-valuetext"), "240px");
    await page.getByText("240px", { exact: true }).waitFor();
    const animationPanel = page.locator("details.animation-panel");
    await animationPanel.waitFor();
    assert.equal(await animationPanel.getAttribute("open"), null);
    assert.equal(
      await animationPanel.locator(".animation-actions button").count(),
      9,
    );
    assert.equal(
      await animationPanel
        .locator(".animation-actions button")
        .first()
        .isVisible(),
      false,
    );
    await animationPanel.locator("summary").focus();
    await page.keyboard.press("Enter");
    assert.notEqual(await animationPanel.getAttribute("open"), null);
    assert.equal(
      await animationPanel
        .getByRole("button", { name: "실제로 걸어보기", exact: true })
        .isVisible(),
      true,
    );
    await page.getByText("현재 동작: 기본", { exact: true }).waitFor();
    const waveButton = page.getByRole("button", {
      name: "손 흔들기",
      exact: true,
    });
    await waveButton.click();
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.visual_state === "waving",
    );
    await page.getByText("현재 동작: 손 흔들기", { exact: true }).waitFor();
    assert.equal(await waveButton.getAttribute("aria-pressed"), "true");
    await page.screenshot({ path: path.join(out, "pet-behavior-open.png") });
    await page
      .getByRole("button", { name: "실제 상태로 돌아가기", exact: true })
      .click();
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.visual_state === "idle",
    );
    await page.getByText("현재 동작: 기본", { exact: true }).waitFor();
    await page.getByRole("tab", { name: "외형·표시", exact: true }).click();
    await page.getByRole("button", { name: "펫 관리", exact: true }).click();
    const catalogDialog = page.getByRole("dialog", {
      name: "펫 관리",
      exact: true,
    });
    const settled = () =>
      settledFor(page.locator("dialog:has(.pet-manager) .pet-manager"));
    const rowFor = (id) => catalogDialog.locator(`[data-pet-id="${id}"]`);
    const menuAction = async (id, label) => {
      const row = rowFor(id);
      await row.locator("summary").click();
      await row.getByRole("button", { name: label, exact: true }).click();
    };
    const managerCatalog = await page.evaluate(() =>
      window.settings.request("pet.catalog"),
    );
    const currentRow = rowFor(managerCatalog.petId);
    assert.equal(await currentRow.getByRole("switch").isDisabled(), true);
    assert.equal(await catalogDialog.locator(".drag-handle").count(), 0);
    assert.equal(
      await catalogDialog
        .getByRole("button", { name: "적용", exact: true })
        .count(),
      0,
    );
    await currentRow.locator("summary").click();
    assert.equal(
      await currentRow
        .getByRole("button", { name: "휴지통으로 이동", exact: true })
        .count(),
      0,
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await currentRow.locator("details").getAttribute("open"),
      null,
    );
    assert.equal(
      await currentRow
        .locator("summary")
        .evaluate((node) => node === document.activeElement),
      true,
    );
    // A second action 20-60ms after the first ran into the reload that the
    // host's late invalidate starts, and the click was lost (fixed in 0.15.11).
    // A short list shows it: with many pets the action outlasts the 80ms delay.
    const rapid = await page.evaluate(
      async ({ ids }) => {
        const manager = document.querySelector("dialog .pet-manager");
        const tick = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const busy = () => manager.getAttribute("aria-busy") === "true";
        const toggle = (id) =>
          manager.querySelector(`[data-pet-id="${id}"] [role="switch"]`);
        const checked = (id) => toggle(id).getAttribute("aria-checked");
        const quiet = async () => {
          let since = null;
          for (;;) {
            await tick(5);
            if (busy()) since = null;
            else if (performance.now() - (since ??= performance.now()) >= 400)
              return;
          }
        };
        const results = [];
        for (const delay of [20, 30, 40, 50, 60]) {
          const [first, second] = ids;
          await quiet();
          const before = checked(second);
          toggle(first).click();
          while (!busy()) await tick(1);
          while (busy()) await tick(1);
          const done = performance.now();
          while (performance.now() - done < delay) await tick(1);
          const disabled = toggle(second).disabled;
          toggle(second).click();
          await quiet();
          results.push({
            delay,
            disabled,
            applied: checked(second) !== before,
          });
          for (const id of ids) {
            toggle(id).click();
            await quiet();
          }
        }
        return results;
      },
      {
        ids: managerCatalog.entries
          .map((entry) => entry.id)
          .filter((id) => id !== managerCatalog.petId),
      },
    );
    metrics.rapidPetActions = rapid;
    assert.deepEqual(
      rapid.filter((result) => !result.applied || result.disabled),
      [],
    );
    await settled();
    await rowFor(imported.id).getByRole("switch").click();
    await until(async () =>
      (
        await page.evaluate(() => window.settings.request("pet.catalog"))
      ).hidden.includes(imported.id),
    );
    await settled();
    await catalogDialog.getByRole("button", { name: /^숨김 / }).click();
    await until(
      async () => (await catalogDialog.locator(".manager-row").count()) === 1,
    );

    await catalogDialog.getByLabel("펫 이름 검색").fill("없는 펫 이름");
    await catalogDialog.getByText("검색 조건에 맞는 펫이 없어요.").waitFor();
    await catalogDialog
      .getByRole("button", { name: "검색·필터 초기화" })
      .click();
    await catalogDialog.getByLabel("펫 이름 검색").fill(imported.name);
    await until(
      async () => (await catalogDialog.locator(".manager-row").count()) === 1,
    );
    assert.equal(
      await catalogDialog
        .getByRole("button", { name: "순서 편집", exact: true })
        .isDisabled(),
      true,
    );
    await catalogDialog.getByLabel("펫 이름 검색").fill("");
    await menuAction(imported.id, "이 펫 사용하기");
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.pet_id === imported.id,
    );
    await settled();
    assert.equal(
      (
        await page.evaluate(() => window.settings.request("pet.catalog"))
      ).hidden.includes(imported.id),
      false,
    );
    await menuAction(imported.id, "휴지통으로 이동");
    const replacementDialog = page.getByRole("dialog", {
      name: "사용 중인 펫 이동",
      exact: true,
    });
    await replacementDialog
      .getByLabel("대신 사용할 펫")
      .selectOption(managerCatalog.petId);
    await page.screenshot({
      path: path.join(out, "pet-manager-current-delete.png"),
    });
    await replacementDialog
      .getByRole("button", { name: "변경 후 휴지통으로 이동", exact: true })
      .click();
    await until(
      async () =>
        (await page.evaluate(() => window.settings.request("pet.trash.list")))
          .total === 1,
    );
    await settled();
    assert.equal(
      (await page.evaluate(() => window.settings.request("settings.snapshot")))
        .pet.pet_id,
      managerCatalog.petId,
    );
    await catalogDialog
      .getByRole("button", { name: "실행 취소", exact: true })
      .click();
    await until(
      async () =>
        (await page.evaluate(() => window.settings.request("pet.trash.list")))
          .total === 0,
    );
    await settled();
    // Immediate order editing still supports both keyboard buttons and dragging.
    await catalogDialog.getByLabel("정렬 방식").selectOption("name");
    await settled();
    const rowIds = () =>
      catalogDialog
        .locator(".manager-row")
        .evaluateAll((nodes) => nodes.map((node) => node.dataset.petId));
    const startOrder = await rowIds();
    await catalogDialog
      .getByRole("button", { name: "순서 편집", exact: true })
      .click();
    await rowFor(startOrder[0])
      .getByRole("button", { name: / 아래로$/ })
      .click();
    await until(async () => (await rowIds())[1] === startOrder[0]);
    await settled();
    for (
      let attempt = 0;
      attempt < 3 && (await rowIds())[0] !== startOrder[0];
      attempt++
    ) {
      await settled();
      await until(
        async () =>
          (await rowFor(startOrder[0])
            .locator(".drag-handle")
            .getAttribute("draggable")) === "true",
      );
      await rowFor(startOrder[0])
        .locator(".drag-handle")
        .dragTo(rowFor(startOrder[1]), { targetPosition: { x: 40, y: 4 } });
      await settled();
    }
    await until(async () => (await rowIds())[0] === startOrder[0]);
    await settled();
    await rowFor(startOrder[0]).locator("summary").click();
    await rowFor(startOrder[0])
      .getByRole("button", { name: "맨 아래로", exact: true })
      .click();
    await until(async () => (await rowIds()).at(-1) === startOrder[0]);
    await settled();
    await catalogDialog
      .getByRole("button", { name: "순서 편집 마치기" })
      .click();
    await page.screenshot({ path: path.join(out, "pet-manager.png") });
    // Re-importing a trashed asset offers restore instead of making a duplicate.
    await menuAction(imported.id, "휴지통으로 이동");
    await until(
      async () =>
        (await page.evaluate(() => window.settings.request("pet.trash.list")))
          .total === 1,
    );
    await settled();
    await pickerResult(connection.petImportSource);
    await catalogDialog
      .getByRole("button", { name: "펫 추가", exact: true })
      .click();
    importDialog = page.getByRole("dialog", {
      name: "펫 가져오기",
      exact: true,
    });
    await importDialog
      .getByRole("button", { name: "파일 선택", exact: true })
      .click();
    await importDialog
      .getByRole("button", { name: "펫 추가", exact: true })
      .click();
    await importDialog.locator('[data-import-step="result"]').waitFor();
    assert.equal(await importDialog.locator(".import-animation").count(), 0);
    await importDialog.screenshot({
      path: path.join(out, "pet-import-restore.png"),
    });
    await importDialog
      .getByRole("button", { name: "휴지통에서 복원", exact: true })
      .click();
    await importDialog
      .getByRole("button", { name: "이 펫 사용", exact: true })
      .waitFor();
    await importDialog
      .getByRole("button", { name: "닫기", exact: true })
      .last()
      .click();
    assert.equal(
      (await page.evaluate(() => window.settings.request("settings.snapshot")))
        .pet.pet_id,
      managerCatalog.petId,
    );
    metrics.petImport.trashRestoreWithoutSelection = true;
    await settled();
    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = globalThis.qaOriginalPicker;
    });
    await menuAction(imported.id, "휴지통으로 이동");
    await until(
      async () =>
        (await page.evaluate(() => window.settings.request("pet.trash.list")))
          .total === 1,
    );
    await settled();
    await catalogDialog.getByRole("button", { name: /^휴지통 / }).click();
    const trashDialog = page.getByRole("dialog", {
      name: "펫 휴지통",
      exact: true,
    });
    await trashDialog
      .getByRole("button", { name: "복원", exact: true })
      .waitFor();
    await page.screenshot({ path: path.join(out, "pet-trash.png") });
    await trashDialog
      .getByRole("button", { name: "복원", exact: true })
      .click();
    await until(
      async () =>
        (await page.evaluate(() => window.settings.request("pet.trash.list")))
          .total === 0,
    );
    await trashDialog.getByText("휴지통이 비어 있어요.").waitFor();
    await settled();
    await trashDialog
      .getByRole("button", { name: "펫 목록", exact: true })
      .click();
    await catalogDialog.waitFor();
    await menuAction(imported.id, "휴지통으로 이동");
    await until(
      async () =>
        (await page.evaluate(() => window.settings.request("pet.trash.list")))
          .total === 1,
    );
    await settled();
    await catalogDialog.getByRole("button", { name: /^휴지통 / }).click();
    await trashDialog
      .getByRole("button", { name: "영구 삭제", exact: true })
      .click();
    const deleteDialog = page.getByRole("dialog", {
      name: "펫 영구 삭제",
      exact: true,
    });
    await deleteDialog.getByText(/삭제 후에는 복원할 수 없어요/).waitFor();
    await deleteDialog
      .getByRole("button", { name: "취소", exact: true })
      .click();
    assert.equal(
      (await page.evaluate(() => window.settings.request("pet.trash.list")))
        .total,
      1,
    );
    await trashDialog
      .getByRole("button", { name: "영구 삭제", exact: true })
      .click();
    await deleteDialog
      .getByRole("button", { name: "영구 삭제", exact: true })
      .click();
    await trashDialog.getByText("휴지통이 비어 있어요.").waitFor();
    // The late invalidate after a change reloads the lists. View navigation
    // must stay enabled through it, or an immediate click is swallowed.
    await page.evaluate(() => {
      window.__navDisabled = 0;
      window.__navObserver = new MutationObserver((records) => {
        for (const record of records)
          if (
            record.oldValue === null &&
            record.target.textContent?.includes("펫 목록")
          )
            window.__navDisabled++;
      });
      window.__navObserver.observe(document.body, {
        subtree: true,
        attributes: true,
        attributeFilter: ["disabled"],
        attributeOldValue: true,
      });
    });
    await pause(1500);
    assert.equal(
      await page.evaluate(() => {
        window.__navObserver.disconnect();
        return window.__navDisabled;
      }),
      0,
      "pet list navigation was disabled by a background reload",
    );
    await trashDialog
      .getByRole("button", { name: "펫 목록", exact: true })
      .click();
    await catalogDialog.waitFor();
    const remaining = await page.evaluate(() =>
      window.settings.request("pet.catalog"),
    );
    const alternate = remaining.entries.find(
      (entry) => entry.canDelete && entry.id !== remaining.petId,
    );
    assert.ok(alternate);
    await menuAction(alternate.id, "휴지통으로 이동");
    await until(
      async () =>
        (await page.evaluate(() => window.settings.request("pet.trash.list")))
          .total === 1,
    );
    await settled();
    await catalogDialog.getByRole("button", { name: /^휴지통 / }).click();
    await trashDialog
      .getByRole("button", { name: "휴지통 비우기", exact: true })
      .click();
    await page
      .getByRole("dialog", { name: "휴지통 비우기", exact: true })
      .getByRole("button", { name: "모두 영구 삭제", exact: true })
      .click();
    await trashDialog.getByText("휴지통이 비어 있어요.").waitFor();
    await trashDialog
      .getByRole("button", { name: "닫기", exact: true })
      .last()
      .click();
    await testPetBatch({ page, app, connection, out, metrics });
    metrics.petManager = {
      status: "passed",
      isolatedData: true,
      immediateSave: true,
      lifecycle: "move, undo, import restore, restore, delete, empty",
    };
    await page.getByRole("button", { name: "말풍선", exact: true }).click();
    const bubbleIntro = page.locator(".bubble-intro");
    assert.equal(
      await bubbleIntro
        .getByRole("button", { name: "펫에서 미리보기", exact: true })
        .count(),
      1,
    );
    assert.equal(
      await bubbleIntro
        .getByRole("button", { name: "말풍선 꾸미기", exact: true })
        .count(),
      1,
    );
    // No custom theme exists yet in the isolated profile.
    const themeSelect = page
      .locator(".bubble-intro-card")
      .getByLabel("테마 선택");
    assert.ok(
      (
        await themeSelect.locator('option[value="custom"]').textContent()
      ).includes("아직 없음"),
    );
    await page
      .locator(".bubble-intro-card .field-description")
      .getByText(/말풍선 꾸미기에서 적용하면/)
      .waitFor();
    await bubbleIntro
      .getByRole("button", { name: "펫에서 미리보기", exact: true })
      .click();
    if (edition === "pet-assistant") {
      const kinds = [
        ["실패·중단", "result", 22, 31],
        ["일반 알림", "general", 22, 32],
        ["일정 알림", "schedule", 22, 33],
        ["완료 강조", "completion", 15, 34],
      ];
      const commonDuration = page.getByLabel("공통 표시 시간", {
        exact: true,
      });
      assert.equal(await commonDuration.getAttribute("aria-valuetext"), "8초");
      await commonDuration.fill("22");
      await until(
        async () =>
          (
            await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            )
          ).pet.bubble_duration_seconds === 22,
      );
      assert.equal(await page.locator('input[type="checkbox"]').count(), 0);
      await until(
        async () =>
          (await page
            .getByText("공통 시간 · 22초", { exact: true })
            .count()) === 3,
      );
      assert.equal(
        await page.getByText("공통 시간 · 22초", { exact: true }).count(),
        3,
      );
      await page.getByText("완료 기본값 · 15초", { exact: true }).waitFor();
      for (const [label, kind, initial, changed] of kinds) {
        const toggle = page.getByRole("switch", {
          name: `${label} 개별 시간 사용`,
          exact: true,
        });
        assert.equal(await toggle.getAttribute("aria-checked"), "false");
        await toggle.click();
        await until(async () => {
          const snapshot = await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          );
          return snapshot.pet.bubble_duration_policy[kind] === initial;
        });
        const slider = page.getByLabel(`${label} 표시 시간`, { exact: true });
        // The backend snapshot can arrive before React accepts the command reply.
        await until(
          async () =>
            (await toggle.getAttribute("aria-checked")) === "true" &&
            (await slider.isEnabled()) &&
            (await slider.getAttribute("aria-valuetext")) === `${initial}초`,
        );
        assert.equal(await slider.isEnabled(), true);
        assert.equal(
          await slider.getAttribute("aria-valuetext"),
          `${initial}초`,
        );
        await slider.fill(String(changed));
        await until(async () => {
          const snapshot = await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          );
          return snapshot.pet.bubble_duration_policy[kind] === changed;
        });
        if (kind === "result") {
          await toggle.click();
          await until(async () => {
            const snapshot = await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            );
            return snapshot.pet.bubble_duration_policy.result === null;
          });
          await until(
            async () =>
              (await toggle.getAttribute("aria-checked")) === "false" &&
              (await slider.isDisabled()) &&
              (await slider.getAttribute("aria-valuetext")) === "22초",
          );
          assert.equal(await slider.isDisabled(), true);
          await toggle.click();
          await until(async () => {
            const snapshot = await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            );
            return snapshot.pet.bubble_duration_policy.result === 22;
          });
          await until(
            async () =>
              (await toggle.getAttribute("aria-checked")) === "true" &&
              (await slider.isEnabled()) &&
              (await slider.getAttribute("aria-valuetext")) === "22초",
          );
          assert.equal(await slider.getAttribute("aria-valuetext"), "22초");
          await slider.fill(String(changed));
          await until(async () => {
            const snapshot = await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            );
            return snapshot.pet.bubble_duration_policy.result === changed;
          });
        }
      }
      const durationReset = page.getByRole("button", {
        name: "종류별 시간을 기본값으로",
        exact: true,
      });
      assert.equal(await durationReset.isEnabled(), true);
      await durationReset.click();
      await until(async () => {
        const snapshot = await page.evaluate(() =>
          window.settings.request("settings.snapshot"),
        );
        const policy = snapshot.pet.bubble_duration_policy;
        return (
          policy.common === 22 &&
          ["result", "general", "schedule", "completion"].every(
            (kind) => policy[kind] === null,
          )
        );
      });
      await until(
        async () =>
          (await durationReset.isDisabled()) &&
          (await page
            .getByText("공통 시간 · 22초", { exact: true })
            .count()) === 3,
      );
      assert.equal(await durationReset.isDisabled(), true);
      assert.equal(
        await page.getByText("공통 시간 · 22초", { exact: true }).count(),
        3,
      );
      await page.getByText("완료 기본값 · 15초", { exact: true }).waitFor();
      await page.screenshot({ path: path.join(out, "bubble-settings.png") });

      const snooze = page.locator(".snooze-card");
      // Snoozing hides every card, not only general/schedule notices.
      await snooze.getByText(/말풍선을 모두 숨깁니다/).waitFor();
      for (const minutes of [15, 30, 60]) {
        assert.equal(
          await snooze
            .getByRole("button", { name: `${minutes}분`, exact: true })
            .count(),
          1,
        );
      }
      assert.equal(
        await snooze
          .getByRole("button", { name: "지금 다시 표시", exact: true })
          .count(),
        0,
      );
      await snooze.getByRole("button", { name: "15분", exact: true }).click();
      await until(
        async () =>
          (
            await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            )
          ).pet.bubbles_snoozed,
      );
      await page.getByText(/약 \d+분 남음/).waitFor();
      assert.equal(await snooze.locator("button").count(), 1);
      await page.screenshot({ path: path.join(out, "bubble-snoozed.png") });
      await snooze
        .getByRole("button", { name: "지금 다시 표시", exact: true })
        .click();
      await until(
        async () =>
          !(
            await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            )
          ).pet.bubbles_snoozed,
      );
      const bubblesEnabled = page.getByRole("switch", {
        name: "말풍선 알림 표시",
        exact: true,
      });
      await bubblesEnabled.click();
      await until(
        async () =>
          !(
            await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            )
          ).pet.bubbles_enabled,
      );
      await page
        .getByText("말풍선 알림이 꺼져 있습니다", { exact: true })
        .waitFor();
      const bubbleScale = page.getByLabel("말풍선 배율", { exact: true });
      await until(async () => await bubbleScale.isDisabled());
      assert.equal(await commonDuration.isDisabled(), true);
      assert.equal(
        await page
          .getByRole("switch", {
            name: "일반 알림 개별 시간 사용",
            exact: true,
          })
          .isDisabled(),
        true,
      );
      assert.equal(
        await page
          .getByRole("button", { name: "펫에서 미리보기", exact: true })
          .isEnabled(),
        true,
      );
      await page.screenshot({ path: path.join(out, "bubble-muted.png") });
      for (const minutes of [15, 30, 60]) {
        assert.equal(
          await snooze
            .getByRole("button", { name: `${minutes}분`, exact: true })
            .isDisabled(),
          true,
        );
      }
      await bubblesEnabled.click();
      await until(
        async () =>
          (
            await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            )
          ).pet.bubbles_enabled,
      );
      await until(async () => await bubbleScale.isEnabled());
      assert.equal(await commonDuration.isEnabled(), true);
    } else {
      assert.equal(
        await page.getByRole("heading", { name: "표시 시간" }).count(),
        0,
      );
      assert.equal(
        await page.getByRole("heading", { name: "알림 잠시 쉬기" }).count(),
        0,
      );
    }
    await page
      .getByRole("button", { name: "말풍선 꾸미기", exact: true })
      .click();
    await page.getByAltText("현재 말풍선 디자인 미리보기").waitFor();
    await page.screenshot({ path: path.join(out, "editor.png") });
    const draftStatus = page.locator(".draft-status");
    assert.equal(await draftStatus.textContent(), "변경 사항 없음");
    const themeModeBefore = (
      await page.evaluate(() => window.settings.request("settings.snapshot"))
    ).pet.bubble_theme_mode;
    // The gallery offers the public presets; the preview shows a project card too.
    assert.ok((await page.locator(".preset-chip").count()) >= 6);
    const noticePreview = await page
      .getByAltText("현재 말풍선 디자인 미리보기")
      .getAttribute("src");
    await page
      .getByRole("button", { name: "프로젝트 카드", exact: true })
      .click();
    await until(
      async () =>
        (await page
          .getByAltText("현재 말풍선 디자인 미리보기")
          .getAttribute("src")) !== noticePreview,
    );
    await page.screenshot({ path: path.join(out, "editor-project.png") });
    const projectPreview = await page
      .getByAltText("현재 말풍선 디자인 미리보기")
      .getAttribute("src");
    await page.getByRole("button", { name: "짧은 알림", exact: true }).click();
    await until(
      async () =>
        (await page
          .getByAltText("현재 말풍선 디자인 미리보기")
          .getAttribute("src")) !== projectPreview,
    );
    metrics.bubbleViewport = await testBubbleViewport({ page, app, out });
    // Fields live in tabs; the shape tab holds the corner radius.
    const editorTab = (name) => selectBubbleSection(page, name);
    await editorTab("테두리·모양");
    const radius = page.getByLabel("모서리 곡률", { exact: true });
    // Theme numbers are sliders that stop at the bound Python applies.
    assert.equal(await radius.getAttribute("type"), "range");
    await radius.focus();
    await page.keyboard.press("End");
    await until(async () => (await radius.inputValue()) === "24");
    assert.equal(
      await draftStatus.textContent(),
      themeModeBefore === "custom"
        ? "적용하지 않은 변경이 있어요."
        : "적용하면 테마가 '내가 꾸민 디자인'으로 바뀝니다.",
    );
    await page.screenshot({ path: path.join(out, "editor-border.png") });
    // Every tab keeps the dialog's height, so switching never moves it.
    const editorHeight = async () =>
      (await page.locator(".bubble-editor-modal").boundingBox()).height;
    const borderHeight = await editorHeight();
    await editorTab("글자·배치");
    assert.equal(await editorHeight(), borderHeight);
    await page.screenshot({ path: path.join(out, "editor-layout.png") });
    await editorTab("장식");
    // Built-in ornaments are added as layers under translated names; the old
    // corner slots show only while a theme still uses them.
    assert.equal(
      await page.getByLabel("왼쪽 장식", { exact: true }).count(),
      0,
    );
    const ornamentOptions = await page
      .getByLabel("기본 장식 추가", { exact: true })
      .locator('option[value^="ornament:"]')
      .allTextContents();
    assert.equal(ornamentOptions.length, 10);
    assert.ok(ornamentOptions.every((label) => !/^[a-z-]+$/.test(label)));
    // Import, library and ornaments share one row; the pet frame field sits
    // in the layer card instead of a group of its own.
    const addTops = await page
      .locator(".decor-add-row > *")
      .evaluateAll((items) =>
        items.map((item) => Math.round(item.getBoundingClientRect().top)),
      );
    assert.equal(new Set(addTops).size, 1);
    assert.equal(
      await page.locator(".decor-panel #field-frame_style").count(),
      1,
    );
    // A decoration: import an image as a layer, drag it on the real preview,
    // undo, redo and delete it with the keyboard.
    const decorImage = path.join(out, "qa-decor.png");
    await fs.writeFile(decorImage, Buffer.from(QA_DECOR_PNG, "base64"));
    await app.evaluate(({ dialog }, file) => {
      if (!globalThis.qaOriginalPicker)
        globalThis.qaOriginalPicker = dialog.showOpenDialog;
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [file],
      });
    }, decorImage);
    const previewImage = page.getByAltText("현재 말풍선 디자인 미리보기");
    const undecorated = await previewImage.getAttribute("src");
    await page
      .getByRole("button", { name: "이미지 가져오기", exact: true })
      .click();
    const decorBox = page.locator(".canvas-layer.is-selected");
    await decorBox.waitFor();
    // Handles follow the preview geometry; wait for the decorated drawing.
    await until(
      async () => (await previewImage.getAttribute("src")) !== undecorated,
    );
    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = globalThis.qaOriginalPicker;
    });
    assert.equal(await page.locator(".layer-row").count(), 1);
    // The position shows as percent of the body like the background photo;
    // the anchor is picked from where the layer is placed.
    const decorX = page.locator("#field-decor_position_x");
    assert.equal(await decorX.getAttribute("type"), "range");
    assert.equal(await page.getByLabel("기준점", { exact: true }).count(), 0);
    const decorPercent = async () => Number(await decorX.inputValue());
    const placed = await decorPercent();
    assert.ok(placed > 50);
    metrics.bubbleLayerTransforms = await testBubbleLayerTransforms({
      page,
      app,
    });
    const decorStart = await decorBox.boundingBox();
    await page.mouse.move(
      decorStart.x + decorStart.width / 2,
      decorStart.y + decorStart.height / 2,
    );
    await page.mouse.down();
    await page.mouse.move(
      decorStart.x - 120,
      decorStart.y + decorStart.height / 2 + 4,
      {
        steps: 8,
      },
    );
    await page.mouse.up();
    // Fields show a new value one render after the drop.
    await until(async () => (await decorPercent()) < placed - 10);
    const moved = await decorPercent();
    await page.screenshot({ path: path.join(out, "editor-decor.png") });
    await page.keyboard.press("Control+z");
    await until(async () => (await decorPercent()) === placed);
    await page.keyboard.press("Control+y");
    await until(async () => (await decorPercent()) === moved);
    await page.keyboard.press("ArrowRight");
    await until(async () => (await decorPercent()) > moved);
    const nudged = await decorPercent();
    // The position slider saves one undo step per change.
    await decorX.focus();
    await page.keyboard.press("End");
    await until(async () => (await decorPercent()) > 140);
    await decorBox.click();
    await page.keyboard.press("Control+z");
    await until(async () => (await decorPercent()) === nudged);
    // Sizes stay typed; rotation is a slider like the other looks.
    assert.equal(
      await page.locator("#field-decor_width").getAttribute("type"),
      "number",
    );
    const rotation = page.locator("#field-decor_rotation");
    assert.equal(await rotation.getAttribute("type"), "range");
    assert.equal(
      await page.locator("#field-decor_alpha").getAttribute("type"),
      "range",
    );
    await rotation.focus();
    await page.keyboard.press("ArrowRight");
    await until(async () => (await rotation.inputValue()) === "1");
    await decorBox.click();
    await page.keyboard.press("Control+z");
    await until(async () => (await rotation.inputValue()) === "0");
    // Layer settings fit one card; flips are toggle buttons on one row.
    assert.equal(await page.locator(".decor-inspector").count(), 1);
    const flipX = page.getByRole("button", { name: "좌우 반전", exact: true });
    assert.equal(await flipX.getAttribute("aria-pressed"), "false");
    await flipX.click();
    await until(
      async () => (await flipX.getAttribute("aria-pressed")) === "true",
    );
    await decorBox.click();
    await page.keyboard.press("Control+z");
    await until(
      async () => (await flipX.getAttribute("aria-pressed")) === "false",
    );
    await page.keyboard.press("Delete");
    await until(async () => (await page.locator(".layer-row").count()) === 0);
    metrics.editorDecorDragUndoDelete = true;
    // A built-in ornament becomes a selected layer drawn in the middle.
    await page
      .getByLabel("기본 장식 추가", { exact: true })
      .selectOption("ornament:cat-ear");
    await until(async () => (await page.locator(".layer-row").count()) === 1);
    await decorBox.waitFor();
    assert.equal(
      await page.locator("#field-decor_image").inputValue(),
      "ornament:cat-ear",
    );
    assert.equal(Math.round(Number(await decorX.inputValue())), 50);
    await decorBox.click();
    await page.keyboard.press("Delete");
    await until(async () => (await page.locator(".layer-row").count()) === 0);
    metrics.editorOrnamentLayer = true;
    // A copied image pasted into the editor becomes a decoration layer.
    await page.locator(".bubble-canvas").evaluate((canvas, data) => {
      const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
      const clipboardData = new DataTransfer();
      clipboardData.items.add(
        new File([bytes], "copied.png", { type: "image/png" }),
      );
      canvas.dispatchEvent(
        new ClipboardEvent("paste", { clipboardData, bubbles: true }),
      );
    }, QA_DECOR_PNG);
    await until(async () => (await page.locator(".layer-row").count()) === 1);
    await page.keyboard.press("Delete");
    await until(async () => (await page.locator(".layer-row").count()) === 0);
    metrics.editorDecorPaste = true;
    // The background photo is a layer of its own on the background tab: drag
    // it, resize it from a corner (shape kept) and a side (one way), undo.
    await editorTab("배경");
    await app.evaluate(({ dialog }, file) => {
      if (!globalThis.qaOriginalPicker)
        globalThis.qaOriginalPicker = dialog.showOpenDialog;
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [file],
      });
    }, decorImage);
    await page
      .getByRole("button", { name: "배경 이미지 추가", exact: true })
      .click();
    const photoLayer = page.locator(".canvas-background");
    await photoLayer.waitFor();
    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = globalThis.qaOriginalPicker;
    });
    const photoFit = page.getByLabel("이미지 채우기", { exact: true });
    assert.equal(await photoFit.inputValue(), "cover");
    const body = await page.locator(".bubble-preview-image").boundingBox();
    await page.mouse.move(body.x + body.width / 2, body.y + body.height / 2);
    await page.mouse.down();
    await page.mouse.move(
      body.x + body.width / 2 - 40,
      body.y + body.height / 2,
      {
        steps: 6,
      },
    );
    await page.mouse.up();
    // The first drag places the photo freely from where it was drawn.
    await until(async () => (await photoFit.inputValue()) === "free");
    const photoX = page.getByLabel("가로 위치", { exact: true });
    assert.ok(Number(await photoX.inputValue()) < 50);
    const photoWidth = page.getByLabel("너비", { exact: true });
    const photoHeight = page.getByLabel("높이", { exact: true });
    // Out-of-range input is clamped on blur to the bound Python applies.
    await page.getByText("8–960px", { exact: true }).first().waitFor();
    await photoWidth.fill("5000");
    await photoWidth.press("Tab");
    assert.equal(await photoWidth.inputValue(), "960");
    await photoWidth.fill("80");
    await photoWidth.press("Tab");
    await photoHeight.fill("60");
    await photoHeight.press("Tab");
    await photoX.fill("50");
    await photoX.press("Tab");
    const photoSize = async () => [
      Number(await photoWidth.inputValue()),
      Number(await photoHeight.inputValue()),
    ];
    await until(async () => {
      const box = await photoLayer.boundingBox();
      return box && Math.abs(box.width / box.height - 80 / 60) < 0.05;
    });
    await photoLayer.click();
    metrics.bubbleBackgroundTransforms = await testBubbleBackgroundTransforms({
      page,
      app,
    });
    const dragHandle = async (handle, dx, dy) => {
      const box = await photoLayer
        .locator(`.canvas-handle-${handle}`)
        .boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(
        box.x + box.width / 2 + dx,
        box.y + box.height / 2 + dy,
        { steps: 6 },
      );
      await page.mouse.up();
    };
    await dragHandle("se", 30, 4);
    await until(async () => (await photoSize())[0] > 80);
    const [cornerWidth, cornerHeight] = await photoSize();
    assert.ok(Math.abs(cornerHeight / cornerWidth - 0.75) < 0.03);
    await dragHandle("e", 24, 0);
    await until(async () => (await photoSize())[0] > cornerWidth);
    assert.equal((await photoSize())[1], cornerHeight);
    await page.screenshot({ path: path.join(out, "editor-background.png") });
    // Esc during a drag keeps the photo where it was.
    const resized = await photoSize();
    const handle = await photoLayer.locator(".canvas-handle-s").boundingBox();
    await page.mouse.move(handle.x + 5, handle.y + 5);
    await page.mouse.down();
    await page.mouse.move(handle.x + 5, handle.y + 40, { steps: 4 });
    await page.keyboard.press("Escape");
    await page.mouse.up();
    assert.deepEqual(await photoSize(), resized);
    await page.keyboard.press("Control+z");
    await until(async () => (await photoSize())[0] === cornerWidth);
    // Background numbers are sliders except the free photo's size; moving
    // one only previews, and letting go saves a single undo step.
    const opacity = page.locator("#field-background_opacity");
    assert.equal(await opacity.getAttribute("type"), "range");
    assert.equal(await photoWidth.getAttribute("type"), "number");
    assert.equal(await photoX.getAttribute("type"), "range");
    const opacityBefore = await opacity.inputValue();
    await opacity.scrollIntoViewIfNeeded();
    const track = await opacity.boundingBox();
    await page.mouse.move(
      track.x + track.width * 0.5,
      track.y + track.height / 2,
    );
    await page.mouse.down();
    await page.mouse.move(
      track.x + track.width * 0.9,
      track.y + track.height / 2,
      { steps: 8 },
    );
    await page.mouse.up();
    await until(async () => Number(await opacity.inputValue()) > 80);
    await photoLayer.click();
    await page.keyboard.press("Control+z");
    await until(async () => (await opacity.inputValue()) === opacityBefore);
    await page.getByLabel("이미지", { exact: true }).selectOption("none");
    await photoLayer.waitFor({ state: "detached" });
    // A pattern template is placed like an attached image; a photo picked
    // while tiled fills the bubble so it can be picked on the preview too.
    const photoImage = page.getByLabel("이미지", { exact: true });
    await photoImage.selectOption("builtin:dots");
    await photoFit.selectOption("tile");
    await until(async () => (await photoLayer.count()) === 0);
    await photoImage.selectOption("builtin:stars");
    await until(async () => (await photoFit.inputValue()) === "free");
    await photoLayer.waitFor();
    assert.equal(await photoWidth.inputValue(), await photoHeight.inputValue());
    // Only the user's own images can be deleted from the image field.
    const deleteChosen = page.getByRole("button", {
      name: "이 이미지 삭제",
      exact: true,
    });
    assert.equal(await deleteChosen.count(), 0);
    await photoFit.selectOption("tile");
    const userPhoto = await photoImage.evaluate(
      (select) =>
        [...select.options].find((option) => option.value.startsWith("user:"))
          .value,
    );
    await photoImage.selectOption(userPhoto);
    await until(async () => (await photoFit.inputValue()) === "cover");
    await photoLayer.waitFor();
    // Deleting the chosen photo removes it from the library and the field.
    await deleteChosen.click();
    await until(async () => (await photoImage.inputValue()) === "none");
    await photoLayer.waitFor({ state: "detached" });
    assert.equal(
      await photoImage.locator(`option[value="${userPhoto}"]`).count(),
      0,
    );
    metrics.editorChosenImageDelete = true;
    metrics.editorBackgroundLayer = true;
    // Library images are deleted from the decoration tab, where the library
    // is folded under a heading that counts its images.
    await editorTab("장식");
    const libraryRows = page.locator(".library-item");
    const libraryCount = await libraryRows.count();
    const libraryHeading = page.locator(".library-details > summary");
    assert.equal(
      await libraryHeading.textContent(),
      `내 이미지 보관함 (${libraryCount})`,
    );
    assert.equal(
      await page
        .getByRole("button", { name: "폴더 열기", exact: true })
        .count(),
      0,
    );
    await libraryHeading.click();
    await page
      .getByRole("button", { name: "폴더 열기", exact: true })
      .waitFor();
    await libraryRows.last().hover();
    await page
      .getByRole("button", { name: "qa-decor 삭제", exact: true })
      .last()
      .click();
    await until(async () => (await libraryRows.count()) === libraryCount - 1);
    metrics.editorImageDelete = true;
    // The deletes above asked through the page, not a native message box.
    metrics.pageConfirmations = await page.evaluate(
      () => window.qaConfirmations.length,
    );
    assert.ok(metrics.pageConfirmations > 0);
    // My themes: save the design, apply it, share it as a file, load the file
    // back and export it for a pet package. Only OS dialogs are replaced.
    await editorTab("내 테마");
    await page.getByLabel("디자인 이름", { exact: true }).fill("QA 디자인");
    await page
      .getByRole("button", { name: "지금 디자인 저장", exact: true })
      .click();
    const themeChip = page.locator(".theme-chip", { hasText: "QA 디자인" });
    await themeChip.waitFor();
    await themeChip.click();
    await page
      .locator(".editor-notice", { hasText: "QA 디자인 디자인을 불러왔어요" })
      .waitFor();
    const themeFile = path.join(out, "qa-theme.zip");
    const packageFolder = path.join(out, "qa-theme-package");
    await fs.mkdir(packageFolder, { recursive: true });
    await app.evaluate(
      ({ dialog }, { file, folder }) => {
        globalThis.qaOriginalSave = dialog.showSaveDialog;
        if (!globalThis.qaOriginalPicker)
          globalThis.qaOriginalPicker = dialog.showOpenDialog;
        dialog.showSaveDialog = async () => ({
          canceled: false,
          filePath: file,
        });
        dialog.showOpenDialog = async (_window, options) => ({
          canceled: false,
          filePaths: [
            options.properties.includes("openDirectory") ? folder : file,
          ],
        });
      },
      { file: themeFile, folder: packageFolder },
    );
    await page
      .getByRole("button", { name: "파일로 공유", exact: true })
      .click();
    await page
      .locator(".editor-notice", { hasText: "디자인 파일을 저장했어요" })
      .waitFor();
    await page
      .getByRole("button", { name: "파일 불러오기", exact: true })
      .click();
    await page
      .locator(".editor-notice", { hasText: "파일을 불러왔어요" })
      .waitFor();
    await page
      .getByRole("button", { name: "펫 패키지용으로 내보내기", exact: true })
      .click();
    await page
      .locator(".editor-notice", { hasText: "펫 패키지용 파일을 만들었어요" })
      .waitFor();
    await app.evaluate(({ dialog }) => {
      dialog.showSaveDialog = globalThis.qaOriginalSave;
      dialog.showOpenDialog = globalThis.qaOriginalPicker;
    });
    const packaged = JSON.parse(
      await fs.readFile(path.join(packageFolder, "bubble-theme.json"), "utf8"),
    );
    assert.ok(packaged.bubbleTheme);
    await page.screenshot({ path: path.join(out, "editor-themes.png") });
    metrics.editorThemes = true;
    await editorTab("테두리·모양");
    // Host navigation and hide/reopen keep the mounted editor's unsaved draft.
    await fs.writeFile(
      connection.control,
      JSON.stringify({ action: "show", page: "app" }),
    );
    await page.getByRole("heading", { name: "앱 설정", exact: true }).waitFor();
    assert.equal(await radius.inputValue(), "24");
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].close(),
    );
    await until(
      async () =>
        !(await app.evaluate(({ BrowserWindow }) =>
          BrowserWindow.getAllWindows()[0].isVisible(),
        )),
    );
    await fs.writeFile(
      connection.control,
      JSON.stringify({ action: "show", page: "bubble" }),
    );
    await page.getByRole("heading", { name: "말풍선", exact: true }).waitFor();
    await radius.waitFor();
    assert.equal(await radius.inputValue(), "24");
    metrics.editorDraftSurvivesNavigationAndHide = true;
    // Conflict keeps the draft; a user-requested rebase re-enables 적용.
    await page.evaluate(async () => {
      const s = await window.settings.request("settings.snapshot");
      await window.settings.request("settings.set", {
        petId: s.pet.pet_id,
        revision: s.revision,
        epoch: s.epoch,
        key: "idle",
        value: !s.pet.idle_activities_enabled,
      });
    });
    const applyButton = page.getByRole("button", { name: "적용", exact: true });
    await applyButton.click();
    const editorDialog = page.getByRole("dialog", { name: /말풍선 꾸미기$/ });
    await editorDialog.getByRole("alert").waitFor();
    assert.equal(await applyButton.isDisabled(), true);
    assert.equal(await radius.inputValue(), "24");
    await page.screenshot({ path: path.join(out, "editor-conflict.png") });
    await editorDialog
      .getByRole("button", { name: "최신 상태 다시 불러오기", exact: true })
      .click();
    await until(
      async () => (await editorDialog.getByRole("alert").count()) === 0,
    );
    assert.equal(await radius.inputValue(), "24");
    assert.equal(await applyButton.isEnabled(), true);
    await applyButton.click();
    await until(
      async () =>
        (await page.evaluate(() => window.settings.request("bubble.editor")))
          .theme.radius === 24,
    );
    await until(
      async () =>
        (
          await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          )
        ).pet.bubble_theme_mode === "custom",
    );
    assert.equal(await themeSelect.inputValue(), "custom");
    await until(
      async () =>
        (await themeSelect.locator('option[value="custom"]').textContent()) ===
        "내가 꾸민 디자인",
    );
    assert.equal(
      await page.locator(".bubble-intro-card .field-description").count(),
      0,
    );
    await page.screenshot({ path: path.join(out, "bubble.png") });
    if (edition === "pet-assistant") {
      await page.getByRole("button", { name: "사용량", exact: true }).click();
      await page.getByRole("heading", { name: "남은 한도" }).waitFor();
      // Providers have separate sections; reserve is last inside Codex.
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "claude_code_limits" }),
      );
      await page
        .locator(".quota-card", { hasText: "Claude Code" })
        .first()
        .waitFor();
      assert.equal(
        await page.locator(".quota-card", { hasText: "Claude Code" }).count(),
        2,
      );
      // Past its reset with no new sample the 5-hour window is estimated
      // full; a fresh sample replaces the estimate.
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "claude_code_limits_expired" }),
      );
      const claudeFiveHour = page.locator(
        '[data-provider="claude_code"] .quota-card',
        { hasText: "5시간" },
      );
      await claudeFiveHour.getByText("추정", { exact: true }).waitFor();
      assert.match(
        await claudeFiveHour.innerText(),
        /100[\s\S]*다음에 사용할 때 새로 시작/,
      );
      await page
        .locator(".quota-note", { hasText: "웹·데스크톱 앱에서 쓴 양" })
        .waitFor();
      await page.screenshot({
        path: path.join(out, "usage-claude-estimated.png"),
      });
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "claude_code_limits" }),
      );
      await until(
        async () => (await claudeFiveHour.getByText("추정").count()) === 0,
      );
      // Synthetic Codex input sends reserve before its normal limits.
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "codex_limits" }),
      );
      await page.locator(".quota-card", { hasText: "Codex" }).first().waitFor();
      assert.equal(
        await page.locator(".quota-card", { hasText: "Codex" }).count(),
        2,
      );
      await page
        .locator('[data-provider="codex"] .quota-card', {
          hasText: "gpt-reserve",
        })
        .waitFor();
      assert.deepEqual(
        await page
          .locator(".quota-provider")
          .evaluateAll((nodes) => nodes.map((node) => node.dataset.provider)),
        ["codex", "claude_code"],
      );
      assert.equal(
        await page.locator('[data-provider="codex"] .quota-card').count(),
        3,
      );
      assert.match(
        await page
          .locator('[data-provider="codex"] .quota-card')
          .last()
          .innerText(),
        /gpt-reserve/,
      );
      assert.equal(
        await page.locator('[data-provider="claude_code"] .quota-card').count(),
        2,
      );
      await page.screenshot({ path: path.join(out, "usage.png") });
      // Overview trends: per tool, bars with an average line, remaining
      // percent per limit window and daily tokens with a moving average.
      const trendChart = page.locator(".trend-chart svg[role=img]");
      const trendLabel = () => trendChart.getAttribute("aria-label");
      const trendButton = (group, name) =>
        page
          .getByRole("group", { name: group, exact: true })
          .getByRole("button", { name, exact: true });
      assert.equal(
        await trendButton("추이 도구", "Codex").getAttribute("aria-pressed"),
        "true",
      );
      await until(async () =>
        /^Codex 오늘 시간대별 토큰/.test((await trendLabel()) || ""),
      );
      // The usual day is a shape behind the bars, split only at unobserved hours.
      assert.ok((await page.locator(".trend-reference").count()) >= 1);
      assert.equal(await page.locator(".trend-line").count(), 0);
      await page.locator(".trend-hit").first().hover();
      await page.locator(".trend-tooltip").waitFor();
      await page.screenshot({ path: path.join(out, "usage-trend-tokens.png") });
      await trendButton("추이 그래프 종류", "오늘 한도").click();
      await until(async () => /5시간 한도/.test((await trendLabel()) || ""));
      await page.screenshot({ path: path.join(out, "usage-trend-quota.png") });
      await trendButton("한도 기간", "7일").click();
      await until(async () => /7일 한도/.test((await trendLabel()) || ""));
      await trendButton("추이 그래프 종류", "일별 토큰").click();
      await page
        .getByLabel("기록 표시 기간", { exact: true })
        .selectOption("14");
      await until(async () =>
        /^Codex 최근 14일 일별 토큰/.test((await trendLabel()) || ""),
      );
      assert.ok((await page.locator(".trend-line.is-reference").count()) >= 1);
      await page.screenshot({ path: path.join(out, "usage-trend-daily.png") });
      await trendButton("추이 도구", "Claude Code").click();
      await trendButton("추이 그래프 종류", "오늘 토큰").click();
      await until(async () =>
        /^Claude Code 오늘 시간대별 토큰/.test((await trendLabel()) || ""),
      );
      // One finished turn in the fixture: too few days for an average.
      await page.getByText(/평균을 낼 기록이 0일뿐입니다/).waitFor();
      await trendButton("추이 그래프 종류", "오늘 한도").click();
      await trendButton("한도 기간", "5시간").click();
      await until(async () =>
        /^Claude Code 5시간 한도/.test((await trendLabel()) || ""),
      );
      await page.screenshot({ path: path.join(out, "usage-trend-claude.png") });
      // Dark chart colors, checked on the same data without leaving the page.
      const theme = await page.evaluate(
        () => document.documentElement.dataset.theme,
      );
      await page.evaluate(() => {
        document.documentElement.dataset.theme = "dark";
      });
      await page.screenshot({
        path: path.join(out, "usage-trend-claude-dark.png"),
      });
      await trendButton("추이 도구", "Codex").click();
      await trendButton("추이 그래프 종류", "일별 토큰").click();
      await page.locator(".trend-line.is-reference").first().waitFor();
      await page.screenshot({
        path: path.join(out, "usage-trend-daily-dark.png"),
      });
      await trendButton("추이 그래프 종류", "오늘 토큰").click();
      await page
        .locator(".trend-reference")
        .first()
        .waitFor({ state: "attached" });
      await page.screenshot({
        path: path.join(out, "usage-trend-tokens-dark.png"),
      });
      await page.evaluate((value) => {
        if (value) document.documentElement.dataset.theme = value;
        else delete document.documentElement.dataset.theme;
      }, theme);
      await trendButton("추이 도구", "Codex").click();
      await trendButton("추이 그래프 종류", "오늘 토큰").click();
      // Each tool's one switch lives on the connections page; here the
      // bridge flips it so the usage page can be checked in place.
      const switchTool = (provider, enabled) =>
        page.evaluate(
          async ([provider, enabled]) => {
            const { epoch } = await window.settings.request("usage.snapshot");
            const plan = await window.settings.request("integration.preview", {
              epoch,
              operation: enabled ? "enable" : "disable",
              provider,
            });
            await window.settings.request("integration.apply", {
              epoch,
              token: plan.token,
            });
          },
          [provider, enabled],
        );
      // No per-tool switch on the usage page any more.
      assert.equal(
        await page.getByRole("switch", { name: /사용량 사용$/ }).count(),
        0,
      );
      await switchTool("codex", false);
      await until(
        async () =>
          (await page
            .locator('[data-provider="codex"] .quota-card')
            .count()) === 0,
      );
      assert.equal(
        (await page.evaluate(() => window.settings.request("usage.snapshot")))
          .claude_code_enabled,
        true,
      );
      assert.equal(
        await page.locator('[data-provider="claude_code"] .quota-card').count(),
        2,
      );
      assert.equal(
        await page.locator(".quota-card", { hasText: "gpt-reserve" }).count(),
        0,
      );
      // A tool whose usage is off takes no room: no group, no trend choice.
      assert.equal(await page.locator('[data-provider="codex"]').count(), 0);
      assert.equal(
        await page.getByRole("group", { name: "추이 도구" }).count(),
        0,
      );
      // Codex-only sections go with it.
      assert.equal(
        await page.getByRole("heading", { name: "오늘의 기기 활동" }).count(),
        0,
      );
      await page.screenshot({ path: path.join(out, "usage-claude-only.png") });
      await switchTool("codex", true);
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "codex_limits" }),
      );
      await page
        .locator('[data-provider="codex"] .quota-card')
        .first()
        .waitFor();
      await switchTool("claude_code", false);
      await until(
        async () =>
          (await page
            .locator('[data-provider="claude_code"] .quota-card')
            .count()) === 0,
      );
      assert.equal(
        (await page.evaluate(() => window.settings.request("usage.snapshot")))
          .enabled,
        true,
      );
      assert.equal(
        await page.locator('[data-provider="codex"] .quota-card').count(),
        3,
      );
      assert.equal(
        await page.locator('[data-provider="claude_code"]').count(),
        0,
      );
      await page.screenshot({ path: path.join(out, "usage-codex-only.png") });
      await switchTool("claude_code", true);
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "claude_code_limits" }),
      );
      await page
        .locator('[data-provider="claude_code"] .quota-card')
        .first()
        .waitFor();
      const usageTab = (name) => page.getByRole("tab", { name, exact: true });
      await usageTab("현황").focus();
      await page.keyboard.press("ArrowRight");
      assert.equal(
        await usageTab("기록").getAttribute("aria-selected"),
        "true",
      );
      await page.getByRole("heading", { name: /^프로젝트 · / }).waitFor();
      // Both sources share one source row and sort box, so switching
      // sources must not move the lists below.
      const historyLayout = async () => ({
        row: (await page.locator(".provider-row").boundingBox()).height,
        order: (await page.getByLabel("프로젝트 정렬").boundingBox()).width,
      });
      const codexLayout = await historyLayout();
      await page.screenshot({
        path: path.join(out, "usage-codex-history.png"),
      });
      // Claude Code history comes from the isolated transcript fixture.
      const sourceGroup = page.getByRole("group", { name: "기록 출처" });
      await sourceGroup
        .getByRole("button", { name: "Claude Code", exact: true })
        .click();
      await page
        .locator(".project-name strong", { hasText: "qa-folder" })
        .waitFor();
      assert.deepEqual(await historyLayout(), codexLayout);
      metrics.historySourceLayoutStable = true;
      await page.screenshot({
        path: path.join(out, "usage-claude-history-list.png"),
      });
      await page.getByLabel("사용량 기록 검색").fill("qa-folder");
      await page.getByLabel("사용량 기록 검색").press("Enter");
      await page.getByLabel("프로젝트 정렬").selectOption("name");
      await until(async () => {
        const snapshot = await page.evaluate(() =>
          window.settings.request("usage.snapshot"),
        );
        return (
          snapshot.claude_code.data.project_search === "qa-folder" &&
          snapshot.claude_code.data.project_order === "name"
        );
      });
      await page
        .locator(".project-name strong", { hasText: "QA 대화 제목" })
        .click();
      await page.getByRole("dialog", { name: "QA 대화 제목" }).waitFor();
      await page
        .locator(".task-list .record-row", { hasText: "완료" })
        .waitFor();
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "show", page: "widget" }),
      );
      await page.locator("h1", { hasText: /^위젯$/ }).waitFor();
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "show", page: "usage" }),
      );
      await page.getByLabel("사용량 기록 검색").waitFor();
      await page.getByRole("dialog", { name: "QA 대화 제목" }).waitFor();
      assert.equal(
        await page.locator('[role="tab"][aria-selected="true"]').textContent(),
        "기록",
      );
      assert.equal(
        await page.getByLabel("사용량 기록 검색").inputValue(),
        "qa-folder",
      );
      assert.equal(await page.getByLabel("프로젝트 정렬").inputValue(), "name");
      assert.equal(
        await page
          .locator('.project-main[aria-current="true"]', {
            hasText: "qa-folder",
          })
          .count(),
        1,
      );
      assert.equal(
        await page
          .locator('.project-main[aria-current="true"]', {
            hasText: "QA 대화 제목",
          })
          .count(),
        1,
      );
      metrics.historyStateSurvivesNavigation = true;
      await page.screenshot({
        path: path.join(out, "usage-claude-history.png"),
      });
      await page.keyboard.press("Escape");
      await page.getByLabel("사용량 기록 검색").fill("");
      await page.getByLabel("사용량 기록 검색").press("Enter");
      await page.getByLabel("프로젝트 정렬").selectOption("recent");
      await sourceGroup
        .getByRole("button", { name: "Codex", exact: true })
        .click();
      // Codex history is cleared from the same row as Claude Code's.
      await page
        .locator(".provider-row")
        .getByRole("button", { name: "기록 지우기", exact: true })
        .click();
      await page
        .getByRole("dialog", { name: "현재 계정 기록 지우기" })
        .waitFor();
      await page.getByRole("button", { name: "취소", exact: true }).click();
      await usageTab("기록").focus();
      await page.keyboard.press("End");
      assert.equal(
        await usageTab("설정").getAttribute("aria-selected"),
        "true",
      );
      // Only the device record is cleared here; account history moved to
      // the history tab.
      await page.getByRole("button", { name: "지우기", exact: true }).click();
      await page
        .getByRole("dialog", { name: "기기 관측 기록 지우기" })
        .waitFor();
      await page.getByRole("button", { name: "취소", exact: true }).click();
      await page.screenshot({ path: path.join(out, "usage-settings.png") });
      // Widget settings live on their own page under 꾸미기.
      await page.getByRole("button", { name: "위젯", exact: true }).click();
      await page
        .getByRole("heading", { name: "위젯", exact: true, level: 1 })
        .waitFor();
      const layout = page.getByLabel("위젯 모양", { exact: true });
      // The preview is the real widget drawn offscreen and follows the shape.
      const preview = page.getByAltText("현재 설정의 사용량 위젯 미리보기");
      await preview.waitFor();
      // The value buttons and note sit inside the card, not on its border.
      const previewCard = await page
        .locator(".card:has(.widget-preview)")
        .boundingBox();
      const previewValues = await page
        .getByRole("group", { name: "미리보기 값" })
        .boundingBox();
      if (previewValues.x - previewCard.x < 12) {
        throw new Error("widget preview options touch the card edge");
      }
      const ringsSize = await preview.boundingBox();
      await layout.selectOption("chips");
      await until(
        async () =>
          (
            await page.evaluate(() => window.settings.request("usage.snapshot"))
          ).controls.find((c) => c.key === "widget_shape").value === "chips",
      );
      await until(async () => {
        const box = await preview.boundingBox();
        return box && box.height !== ringsSize.height;
      });
      const folded = await preview.boundingBox();
      await page
        .getByRole("group", { name: "칩 모양" })
        .getByRole("button", { name: "마우스를 올렸을 때" })
        .click();
      await until(
        async () => (await preview.boundingBox()).height > folded.height,
      );
      const realImage = await preview.getAttribute("src");
      await page
        .getByRole("group", { name: "미리보기 값" })
        .getByRole("button", { name: "예시 값" })
        .click();
      await until(
        async () => (await preview.getAttribute("src")) !== realImage,
      );
      await page.screenshot({ path: path.join(out, "widget-preview.png") });
      // Acrylic only exists on a real desktop; the preview says so and the
      // color and opacity controls step aside. Skipped where unsupported.
      const material = page.getByLabel("배경 재질", { exact: true });
      if (!(await material.isDisabled())) {
        const opaqueImage = await preview.getAttribute("src");
        await material.selectOption("acrylic");
        await until(
          async () => (await preview.getAttribute("src")) !== opaqueImage,
        );
        await page
          .getByText("아크릴은 실제 위젯에서만", { exact: false })
          .waitFor();
        await until(() => page.getByLabel("배경 농도").isDisabled());
        await page.screenshot({ path: path.join(out, "widget-acrylic.png") });
        await material.selectOption("opaque");
        await until(
          async () => !(await page.getByLabel("배경 농도").isDisabled()),
        );
      }
      const widgetSwitch = page.getByRole("switch", {
        name: "사용량 위젯 표시",
      });
      await widgetSwitch.click();
      await until(() => layout.isDisabled());
      await widgetSwitch.click();
      await until(async () => !(await layout.isDisabled()));
      // The hour range saves only after focus leaves both inputs and never
      // sends a half-typed or reversed range.
      const hours = async () =>
        JSON.stringify(
          (await page.evaluate(() => window.settings.request("usage.snapshot")))
            .hours,
        );
      const hoursBefore = await hours();
      const rangeHeading = page.getByRole("heading", {
        name: "오늘 흐름 시간대",
      });
      await page.getByLabel("위젯 시작 시각").fill("15");
      await page.getByLabel("위젯 종료 시각").fill("12");
      await rangeHeading.click();
      await page
        .getByText("시작이 종료보다 빨라야 합니다", { exact: false })
        .waitFor();
      assert.equal(await hours(), hoursBefore);
      await page.getByLabel("위젯 시작 시각").fill("8");
      await page.getByLabel("위젯 종료 시각").fill("20");
      await rangeHeading.click();
      await until(async () => (await hours()) === "[8,20]");
      await page.screenshot({ path: path.join(out, "usage-widget.png") });
      // Home summarizes limits, running work, notices and connections.
      await page.getByRole("button", { name: "홈", exact: true }).click();
      await page.getByRole("heading", { name: "남은 한도" }).waitFor();
      // The usage snapshot can arrive after the heading, e.g. behind preview
      // renders from the widget page.
      await until(async () => (await page.locator(".home-limit").count()) >= 4);
      assert.match(
        await page
          .locator('[data-provider="codex"] .home-limit')
          .last()
          .innerText(),
        /gpt-reserve/,
      );
      assert.deepEqual(
        await page
          .locator(".quota-provider")
          .evaluateAll((nodes) => nodes.map((node) => node.dataset.provider)),
        ["codex", "claude_code"],
      );
      assert.equal(await page.locator(".home-connection").count(), 2);
      await page.screenshot({ path: path.join(out, "home.png") });
      await page
        .getByRole("button", { name: "알림 기록", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "최근 활동", exact: true })
        .waitFor();
      await page.getByText("확인할 알림이 없어요.").waitFor();
      // The info tip opens from the keyboard, not only on hover.
      const infoTip = page.locator(".info-tip").first();
      assert.equal(await infoTip.getAttribute("tabindex"), "0");
      await infoTip.focus();
      await infoTip.locator(".info-tip-text").waitFor({ state: "visible" });
      await page.screenshot({ path: path.join(out, "activity-info-tip.png") });
      await infoTip.blur();
      await page
        .getByRole("button", { name: "연결·진단", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "앱 상태", exact: true })
        .waitFor();
      // Both tools share one layout: heading, state, settings, checks.
      assert.deepEqual(
        await page
          .locator(".provider-block")
          .evaluateAll((nodes) => nodes.map((node) => node.ariaLabel)),
        ["Codex", "Claude Code"],
      );
      assert.equal(
        await page
          .locator(".provider-block .check-heading", { hasText: "연결 점검" })
          .count(),
        2,
      );
      const codexConnectionSwitch = page.getByRole("switch", {
        name: "Codex 사용",
        exact: true,
      });
      assert.equal(
        await codexConnectionSwitch.getAttribute("aria-checked"),
        "true",
      );
      // Turning Codex back on above installed its hook. Without the hook,
      // Codex stays in use and the hero offers to connect it again.
      await fs.rm(
        path.join(path.dirname(connection.control), "codex", "hooks.json"),
      );
      await page.getByRole("button", { name: "새로고침", exact: true }).click();
      const codexHook = page.getByRole("button", {
        name: "hook 연결하기",
        exact: true,
      });
      await until(async () => (await codexHook.count()) === 1);
      assert.equal(
        await codexConnectionSwitch.getAttribute("aria-checked"),
        "true",
      );
      await codexHook.click();
      await page.getByRole("dialog", { name: "연결 변경 검토" }).waitFor();
      await page.getByRole("button", { name: "취소", exact: true }).click();
      assert.equal(await codexHook.count(), 1);
      await page.screenshot({ path: path.join(out, "integration.png") });
      // Applying writes only the isolated QA hook files.
      await codexHook.click();
      await page
        .getByRole("button", { name: "변경 적용", exact: true })
        .click();
      await page.getByText("연결 설정을 적용했습니다.").waitFor();
      await until(
        async () => (await page.locator(".status-hero .button").count()) === 0,
      );
      assert.equal(await page.locator(".error-banner").count(), 0);
      assert.equal(
        await codexConnectionSwitch.getAttribute("aria-checked"),
        "true",
      );
      await page.screenshot({
        path: path.join(out, "integration-applied.png"),
      });
      // Claude Code was turned back on above, which installed its hooks
      // into the isolated QA settings.json only.
      const claudeSwitch = page.getByRole("switch", {
        name: "Claude Code 사용",
      });
      assert.equal(await claudeSwitch.getAttribute("aria-checked"), "true");
      await page
        .getByRole("heading", {
          name: "Claude Code 작업 상태를 받을 준비가 됐어요",
        })
        .waitFor();
      await page.getByText("세부 설정", { exact: true }).click();
      await page
        .getByLabel("작업 중 표시 유지", { exact: true })
        .selectOption("5");
      await until(
        async () =>
          (
            await page.evaluate(() =>
              window.settings.request("integration.snapshot"),
            )
          ).claude_code.work_minutes === 5,
      );
      // Turning Claude Code on also brought the limits; the status line
      // switch still turns off alone and writes only the QA settings.
      const limitSwitch = page.getByRole("switch", {
        name: "Claude Code 한도 가져오기",
      });
      assert.equal(await limitSwitch.getAttribute("aria-checked"), "true");
      for (const expected of ["false", "true"]) {
        await limitSwitch.click();
        await page.getByRole("dialog", { name: "연결 변경 검토" }).waitFor();
        await page
          .getByRole("button", { name: "변경 적용", exact: true })
          .click();
        await until(
          async () =>
            (await limitSwitch.getAttribute("aria-checked")) === expected,
        );
      }
      assert.equal(await claudeSwitch.getAttribute("aria-checked"), "true");
      await until(
        async () =>
          (
            await page.evaluate(() =>
              window.settings.request("integration.snapshot"),
            )
          ).claude_code.status_line.state === "installed",
      );
      assert.equal(await page.locator(".error-banner").count(), 0);
      await page.screenshot({ path: path.join(out, "integration-claude.png") });
      // App-wide rows and per-tool repair/removal at the bottom, light and dark.
      await page.locator("details.advanced > summary").click();
      await page
        .getByRole("button", { name: "Claude Code 복구 검토", exact: true })
        .scrollIntoViewIfNeeded();
      assert.equal(
        await page.getByRole("button", { name: /제거 검토$/ }).count(),
        0,
      );
      await page.screenshot({
        path: path.join(out, "integration-bottom.png"),
      });
      const integrationTheme = await page.evaluate(
        () => document.documentElement.dataset.theme,
      );
      await page.evaluate(() => {
        document.documentElement.dataset.theme = "dark";
      });
      await page
        .getByRole("heading", { name: "Codex", exact: true })
        .scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(out, "integration-dark.png") });
      await page.evaluate((value) => {
        document.documentElement.dataset.theme = value;
      }, integrationTheme);
      await page.locator("details.advanced > summary").click();
      // Turning Codex off removes its hook and its usage together, and
      // leaves Claude Code alone; cancelling changes nothing.
      await codexConnectionSwitch.click();
      await page.getByRole("dialog", { name: "연결 변경 검토" }).waitFor();
      await page.getByRole("button", { name: "취소", exact: true }).click();
      assert.equal(
        await codexConnectionSwitch.getAttribute("aria-checked"),
        "true",
      );
      await codexConnectionSwitch.click();
      await page.getByRole("dialog", { name: "연결 변경 검토" }).waitFor();
      await page
        .getByRole("button", { name: "변경 적용", exact: true })
        .click();
      await until(
        async () =>
          (await codexConnectionSwitch.getAttribute("aria-checked")) ===
          "false",
      );
      assert.equal(await claudeSwitch.getAttribute("aria-checked"), "true");
      const usageAfterDisconnect = await page.evaluate(() =>
        window.settings.request("usage.snapshot"),
      );
      assert.equal(usageAfterDisconnect.enabled, false);
      assert.equal(usageAfterDisconnect.claude_code_enabled, true);
      // A switched-off tool keeps only its switch on this page.
      assert.equal(
        await page
          .locator('.provider-block[aria-label="Codex"] .check-heading')
          .count(),
        0,
      );
      await page.screenshot({
        path: path.join(out, "integration-codex-off.png"),
      });
      await codexConnectionSwitch.click();
      await page.getByRole("dialog", { name: "연결 변경 검토" }).waitFor();
      await page
        .getByRole("button", { name: "변경 적용", exact: true })
        .click();
      await until(
        async () =>
          (await codexConnectionSwitch.getAttribute("aria-checked")) === "true",
      );
      // Built-in status line items: hide the IDE and preview the result.
      // The status line items sit inside the already opened 세부 설정.
      await page
        .getByRole("heading", { name: "상태줄 항목", exact: true })
        .waitFor();
      await page.getByLabel("IDE", { exact: true }).selectOption("-1");
      await until(
        async () =>
          !(
            await page.evaluate(() =>
              window.settings.request("integration.snapshot"),
            )
          ).claude_code.status_line.layout.lines
            .flat()
            .includes("ide"),
      );
      await page.getByLabel("상태줄 미리보기").waitFor();
      await page.screenshot({
        path: path.join(out, "integration-status-line.png"),
      });
      await page
        .getByRole("button", { name: "터미널에서 쓰는 방법", exact: true })
        .click();
      await page
        .getByRole("dialog", { name: "터미널에서 Claude Code 쓰기" })
        .waitFor();
      await page.screenshot({
        path: path.join(out, "integration-terminal-help.png"),
      });
      await page.keyboard.press("Escape");
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "notice" }),
      );
      await page.getByRole("dialog", { name: "알림 내용" }).waitFor();
      await until(async () =>
        (
          await page.evaluate(() =>
            window.settings.request("activity.snapshot"),
          )
        ).notices.some((n) => n.message === "연결 검증 알림" && n.confirmed),
      );
      await page.keyboard.press("Escape");
      // Claude Code work is shown with its source and folder, apart from Codex.
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "claude_code" }),
      );
      await until(async () => {
        const snapshot = await page.evaluate(() =>
          window.settings.request("activity.snapshot"),
        );
        return (
          snapshot.projects.some(
            (card) =>
              card.source === "Claude Code" &&
              card.label === "qa-folder" &&
              card.rows.some((row) => row.title === "QA 대화 제목"),
          ) && snapshot.entries.some((entry) => entry.source === "Claude Code")
        );
      });
      await page
        .getByRole("button", { name: "알림 기록", exact: true })
        .click();
      await page
        .locator(".record-row .source-tag", { hasText: "Claude Code" })
        .first()
        .waitFor();
      // Running conversations live on home; the notice center keeps events.
      assert.equal(await page.locator(".project-activity").count(), 0);
      const kinds = page.getByRole("group", { name: "활동 종류" });
      await kinds.getByRole("button", { name: /^상태 변화 \d+$/ }).click();
      await page
        .locator(".record-row .source-tag", { hasText: "Claude Code" })
        .first()
        .waitFor();
      assert.equal(
        await page
          .locator(".record-row", { hasText: "연결 검증 알림" })
          .count(),
        0,
      );
      await kinds.getByRole("button", { name: /^전체 \d+$/ }).click();
      await page
        .locator(".record-row", { hasText: "연결 검증 알림" })
        .first()
        .waitFor();
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "pending_notices" }),
      );
      await page
        .getByRole("button", { name: "모두 확인", exact: true })
        .click();
      await page.getByText("확인할 알림이 없어요.").waitFor();
      assert.ok(
        (
          await page.evaluate(() =>
            window.settings.request("activity.snapshot"),
          )
        ).notices.every((notice) => notice.confirmed),
      );
      await page.screenshot({ path: path.join(out, "activity-claude.png") });
      // Home lists the running row straight in its card; it keeps the card's
      // padding instead of touching the border.
      await page.getByRole("button", { name: "홈", exact: true }).click();
      const homeRow = page.locator(".home-grid .card > .thread-row").first();
      await homeRow.waitFor();
      const gaps = await homeRow.evaluate((row) => {
        const card = row.parentElement.getBoundingClientRect();
        const text = row
          .querySelector(".record-summary")
          .getBoundingClientRect();
        const icons = row.querySelectorAll("svg");
        const chevron = icons[icons.length - 1].getBoundingClientRect();
        return [text.left - card.left, card.right - chevron.right];
      });
      assert.ok(
        gaps.every((gap) => gap >= 12),
        `home running row padding ${gaps}`,
      );
      await page.screenshot({ path: path.join(out, "home-running.png") });
      await page
        .getByRole("button", { name: "알림 기록", exact: true })
        .click();
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "account" }),
      );
      await until(
        async () =>
          (
            await page.evaluate(() =>
              window.settings.request("settings.snapshot"),
            )
          ).epoch > 0,
      );
    } else {
      assert.equal(
        await page.getByRole("button", { name: "사용량", exact: true }).count(),
        0,
      );
      assert.equal(
        await page.evaluate(() =>
          window.settings.request("usage.snapshot").then(
            () => false,
            () => true,
          ),
        ),
        true,
      );
    }
    await page.getByRole("button", { name: "앱 설정", exact: true }).click();
    // The isolated bridge's update server announces v9.9.9 with no installer
    // asset, so the row offers the release page and no install button.
    await page
      .getByRole("button", { name: "업데이트 확인", exact: true })
      .click();
    await page
      .getByText("v9.9.9 버전이 나왔습니다", { exact: false })
      .waitFor();
    await page
      .getByRole("button", { name: "변경 사항 보기", exact: true })
      .waitFor();
    assert.equal(
      await page.getByRole("button", { name: "업데이트", exact: true }).count(),
      0,
    );
    await page.locator(".update-row").screenshot({
      path: path.join(out, "app-update-available.png"),
    });
    await page.getByLabel("테마", { exact: true }).selectOption("dark");
    await until(
      async () =>
        await page.evaluate(
          () => document.documentElement.dataset.theme === "dark",
        ),
    );
    await page.screenshot({ path: path.join(out, "app-dark.png") });
    await page.getByRole("button", { name: "펫", exact: true }).click();
    await page.locator('[data-preview-source="original-cell"]').waitFor();
    await page.screenshot({ path: path.join(out, "pet-dark.png") });
    await page.getByRole("tab", { name: "동작·화면", exact: true }).click();
    const darkAnimationPanel = page.locator("details.animation-panel");
    await darkAnimationPanel.locator("summary").click();
    await page.screenshot({ path: path.join(out, "pet-behavior-dark.png") });
    await page.getByRole("button", { name: "말풍선", exact: true }).click();
    await page.screenshot({ path: path.join(out, "bubble-dark.png") });
    await page.getByRole("button", { name: "펫", exact: true }).click();
    await page.getByRole("tab", { name: "동작·화면", exact: true }).click();
    const narrowAnimationPanel = page.locator("details.animation-panel");
    await narrowAnimationPanel.locator("summary").click();
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].setSize(720, 600),
    );
    await narrowAnimationPanel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, "pet-behavior-narrow.png") });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await page.getByRole("tab", { name: "외형·표시", exact: true }).click();
    await page.screenshot({ path: path.join(out, "pet-narrow.png") });
    await page.getByRole("button", { name: "펫 관리", exact: true }).click();
    await page
      .getByRole("dialog", { name: "펫 관리", exact: true })
      .locator(".manager-row")
      .first()
      .waitFor();
    await page.screenshot({
      path: path.join(out, "pet-manager-narrow-dark.png"),
    });
    await page
      .getByRole("dialog", { name: "펫 관리", exact: true })
      .getByRole("button", { name: "선택", exact: true })
      .click();
    await page.getByRole("checkbox", { name: "현재 화면 전체 선택" }).check();
    await page.screenshot({
      path: path.join(out, "pet-batch-narrow-dark.png"),
    });

    assert.equal(
      await page
        .getByRole("dialog", { name: "펫 관리", exact: true })
        .evaluate((node) => node.scrollWidth > node.clientWidth),
      false,
    );
    await page
      .getByRole("dialog", { name: "펫 관리", exact: true })
      .getByRole("button", { name: "닫기", exact: true })
      .last()
      .click();

    await page.screenshot({ path: path.join(out, "narrow.png") });
    await page.locator(".pet-size-control").scrollIntoViewIfNeeded();
    await page.screenshot({
      path: path.join(out, "pet-narrow-controls.png"),
    });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await page.getByRole("button", { name: "말풍선", exact: true }).click();
    await page.screenshot({ path: path.join(out, "bubble-narrow-dark.png") });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    // In a short window the overlay panel scrolls independently of the canvas.
    await page
      .getByRole("button", { name: "말풍선 꾸미기", exact: true })
      .click();
    await page.getByAltText("현재 말풍선 디자인 미리보기").waitFor();
    await selectBubbleSection(page, "배경");
    const firstField = page.getByLabel("배경색", { exact: true });
    await firstField.scrollIntoViewIfNeeded();
    const firstFieldBox = await firstField.boundingBox();
    const viewport = await page.evaluate(() => innerHeight);
    assert.ok(
      firstFieldBox && firstFieldBox.y + firstFieldBox.height < viewport,
    );
    const contentBounds = await page
      .locator(".bubble-editor-modal .modal-content")
      .boundingBox();
    assert.ok(
      firstFieldBox.y >= contentBounds.y &&
        firstFieldBox.y + firstFieldBox.height <=
          contentBounds.y + contentBounds.height,
    );
    await page.screenshot({ path: path.join(out, "editor-narrow-dark.png") });
    // Reopened after a cancel, a photo picked from the list is still a layer.
    const pickPhoto = async () => {
      await selectBubbleSection(page, "배경");
      const select = page.getByLabel("이미지", { exact: true });
      await select.selectOption(
        await select.evaluate(
          (element) =>
            [...element.options].find((option) =>
              option.value.startsWith("user:"),
            ).value,
        ),
      );
      await page.locator(".canvas-background").waitFor();
    };
    // The library keeps one copy of a picture and the earlier check deleted
    // it, so add the picture again before picking it from the list.
    await app.evaluate(({ dialog }, file) => {
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [file],
      });
    }, decorImage);
    await page
      .getByRole("button", { name: "배경 이미지 추가", exact: true })
      .click();
    await page.locator(".canvas-background").waitFor();
    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = globalThis.qaOriginalPicker;
    });
    await pickPhoto();
    await page
      .getByRole("dialog", { name: /말풍선 꾸미기$/ })
      .getByRole("button", { name: "취소", exact: true })
      .click();
    await page
      .getByRole("button", { name: "말풍선 꾸미기", exact: true })
      .click();
    await page.getByAltText("현재 말풍선 디자인 미리보기").waitFor();
    await pickPhoto();
    await page
      .getByRole("dialog", { name: /말풍선 꾸미기$/ })
      .getByRole("button", { name: "취소", exact: true })
      .click();
    assert.equal(await page.evaluate(() => typeof window.require), "undefined");
    assert.equal(
      await page.evaluate(() =>
        window.settings
          .request("file.import", { path: "C:\\should-not-be-readable" })
          .then(
            () => false,
            () => true,
          ),
      ),
      true,
    );
    // Join two installed pets: a cross-fade, then a drawn transition whose
    // reverse plays backwards; the new pet appears in the catalog.
    await page.getByRole("button", { name: "펫", exact: true }).click();
    await page.getByRole("tab", { name: "외형·표시", exact: true }).click();
    await page.getByRole("button", { name: /^펫 잇기/ }).click();
    const linkDialog = page.getByRole("dialog", {
      name: "펫 잇기",
      exact: true,
    });
    const addLook = linkDialog.getByLabel("모습 추가", { exact: true });
    await until(async () => (await addLook.locator("option").count()) >= 3);
    await addLook.selectOption({ label: "Mori Bot" });
    // Earlier checks trash the alternate Mori Bot; a batch QA copy remains.
    await addLook.selectOption({ label: "일괄 QA 02" });
    assert.equal(await linkDialog.locator(".link-look-row").count(), 2);
    await linkDialog.getByRole("button", { name: "다음", exact: true }).click();
    await linkDialog
      .getByRole("button", {
        name: "Mori Bot에서 일괄 QA 02(으)로 전환 재생",
        exact: true,
      })
      .click();
    await linkDialog.locator(".link-player img").waitFor();
    assert.equal(
      await linkDialog.locator(".link-player-kind").textContent(),
      "부드럽게 겹쳐 바꾸기",
    );
    const linkStrip = path.join(out, "qa-link-strip.png");
    await fs.writeFile(linkStrip, Buffer.from(QA_LINK_STRIP, "base64"));
    await app.evaluate(({ dialog }, file) => {
      if (!globalThis.qaOriginalPicker)
        globalThis.qaOriginalPicker = dialog.showOpenDialog;
      dialog.showOpenDialog = async () => ({
        canceled: false,
        filePaths: [file],
      });
    }, linkStrip);
    await linkDialog
      .getByRole("button", {
        name: "Mori Bot에서 일괄 QA 02(으)로 가는 전환 이미지 가져오기",
        exact: true,
      })
      .click();
    await until(
      async () =>
        (await linkDialog.locator(".link-player-kind").textContent()) ===
        "전환 이미지 2프레임",
    );
    await app.evaluate(({ dialog }) => {
      dialog.showOpenDialog = globalThis.qaOriginalPicker;
    });
    const pairKinds = await linkDialog
      .locator(".link-pair-kind")
      .allTextContents();
    assert.deepEqual(pairKinds, [
      "전환 이미지 2프레임",
      "반대 방향을 거꾸로 재생",
    ]);
    await page.screenshot({ path: path.join(out, "pet-link-transitions.png") });
    await linkDialog.getByRole("button", { name: "다음", exact: true }).click();
    await linkDialog.getByLabel("펫 이름", { exact: true }).fill("QA 잇기");
    await linkDialog
      .getByRole("button", { name: "펫 만들기", exact: true })
      .click();
    await linkDialog
      .getByRole("heading", { name: "펫을 만들었어요", exact: true })
      .waitFor();
    await page.screenshot({ path: path.join(out, "pet-link-created.png") });
    await linkDialog
      .getByRole("button", { name: "닫기", exact: true })
      .last()
      .click();
    assert.ok(
      (
        await page.evaluate(() => window.settings.request("pet.catalog"))
      ).entries.some((entry) => entry.name === "QA 잇기"),
    );
    metrics.petLinkCreated = true;
    // Editing the joined pet replaces it; the previous one goes to the trash.
    await page.getByRole("button", { name: /^펫 잇기/ }).click();
    const editSelect = linkDialog.getByLabel("묶음 펫 고치기", { exact: true });
    await editSelect.selectOption({ label: "QA 잇기" });
    await until(
      async () => (await linkDialog.locator(".link-look-row").count()) === 2,
    );
    await linkDialog
      .locator(".link-look-row input[type=text]")
      .first()
      .fill("아침");
    await linkDialog.getByRole("button", { name: "다음", exact: true }).click();
    assert.deepEqual(
      await linkDialog.locator(".link-pair-kind").allTextContents(),
      ["전환 이미지 2프레임", "반대 방향을 거꾸로 재생"],
    );
    await linkDialog.getByRole("button", { name: "다음", exact: true }).click();
    await linkDialog.locator(".import-warning").waitFor();
    await linkDialog
      .getByRole("button", { name: "바꿔 저장", exact: true })
      .click();
    await linkDialog
      .getByRole("heading", { name: "펫을 바꿨어요", exact: true })
      .waitFor();
    await linkDialog
      .getByRole("button", { name: "닫기", exact: true })
      .last()
      .click();
    const afterEdit = await page.evaluate(async () => ({
      catalog: (await window.settings.request("pet.catalog")).entries.filter(
        (entry) => entry.name === "QA 잇기",
      ).length,
      trash: (
        await window.settings.request("pet.trash.list", { offset: 0 })
      ).entries.filter((entry) => entry.name === "QA 잇기").length,
    }));
    assert.deepEqual(afterEdit, { catalog: 1, trash: 1 });
    metrics.petLinkEdited = true;
    const pid = app.process().pid;
    const before = await app.evaluate(({ app }) =>
      app
        .getAppMetrics()
        .map((p) => ({ type: p.type, memory: p.memory, cpu: p.cpu })),
    );
    const warm = [];
    for (let i = 0; i < 100; i++) {
      await app.evaluate(({ BrowserWindow }) =>
        BrowserWindow.getAllWindows()[0].close(),
      );
      await until(
        async () =>
          !(await app.evaluate(({ BrowserWindow }) =>
            BrowserWindow.getAllWindows()[0].isVisible(),
          )),
      );
      const started = performance.now();
      await fs.writeFile(
        connection.control,
        JSON.stringify({ action: "show", page: "app" }),
      );
      await until(
        async () =>
          await app.evaluate(({ BrowserWindow }) =>
            BrowserWindow.getAllWindows()[0].isVisible(),
          ),
      );
      warm.push(performance.now() - started);
      metrics.reopened++;
    }
    assert.equal(app.process().pid, pid);
    metrics.warmOpenMeanMs = Math.round(
      warm.reduce((a, b) => a + b, 0) / warm.length,
    );
    metrics.beforeCycles = before;
    await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].close(),
    );
    await pause(500);
    const reportPath = path.join(out, "host.json");
    await fs.writeFile(
      connection.control,
      JSON.stringify({ action: "report", path: reportPath }),
    );
    await until(async () => {
      try {
        await fs.access(reportPath);
        return true;
      } catch {
        return false;
      }
    });
    const report = JSON.parse(await fs.readFile(reportPath, "utf8"));
    assert.equal(report.visible, false);
    assert.deepEqual(report.subscriptions, []);
    metrics.hidden = await app.evaluate(({ app }) =>
      app
        .getAppMetrics()
        .map((p) => ({ type: p.type, memory: p.memory, cpu: p.cpu })),
    );
    assert.deepEqual(metrics.errors, []);
    metrics.status = "passed";
  } catch (error) {
    metrics.status = "failed";
    metrics.failure = String(error);
    if (app) {
      const failedPage = await app.firstWindow().catch(() => null);
      if (failedPage) {
        metrics.failureBanner = await failedPage
          .locator(".error-banner")
          .allTextContents()
          .catch(() => []);
        await failedPage
          .screenshot({ path: path.join(out, "failure.png") })
          .catch(() => {});
      }
    }
    throw error;
  } finally {
    await fs.writeFile(
      path.join(out, "results.json"),
      JSON.stringify(metrics, null, 2),
    );
    if (app) await app.close().catch(() => {});
    if (connection) {
      await fs
        .writeFile(connection.control, JSON.stringify({ action: "quit" }))
        .catch(() => {});
      await pause(300);
    }
    if (python.exitCode === null) python.kill();
    if (metrics.status !== "passed") console.error(stderr);
  }
  console.log(
    JSON.stringify({
      edition,
      status: metrics.status,
      reopened: metrics.reopened,
      coldOpenMs: metrics.coldOpenMs,
      warmOpenMeanMs: metrics.warmOpenMeanMs,
    }),
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
