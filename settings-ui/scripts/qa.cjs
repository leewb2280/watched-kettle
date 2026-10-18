const { _electron: electron } = require("playwright");
const { spawn } = require("node:child_process");
const { createInterface } = require("node:readline");
const fs = require("node:fs/promises");
const path = require("node:path");
const assert = require("node:assert/strict");
const { performance } = require("node:perf_hooks");

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
async function until(fn, timeout = 10000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await fn()) return;
    await pause(40);
  }
  throw Error("condition timed out");
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
    until(
      async () =>
        (await bulkManager
          .locator(".pet-manager")
          .getAttribute("aria-busy")) === "false",
      30000,
    );
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
    await page
      .getByRole("heading", { name: "펫", exact: true, level: 1 })
      .waitFor();
    metrics.coldOpenMs = Math.round(performance.now() - start);
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
        .getByRole("button", { name: "추가", exact: true })
        .isDisabled(),
      true,
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
      .getByRole("button", { name: "추가", exact: true })
      .click();
    await importDialog
      .getByText("을(를) 펫 목록에 추가했습니다.", { exact: false })
      .waitFor();
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
      .getByRole("button", { name: "추가", exact: true })
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
      name: "지금 이 화면으로 옮기기",
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
      until(
        async () =>
          (await page
            .locator("dialog:has(.pet-manager) .pet-manager")
            .getAttribute("aria-busy")) === "false",
      );
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
      .getByRole("button", { name: "추가", exact: true })
      .click();
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
    await page.getByRole("button", { name: "짧은 알림", exact: true }).click();
    // Fields fold into groups; open the ones this check uses.
    for (const group of ["모양·테두리", "장식"])
      await page.locator("summary", { hasText: group }).click();
    const radius = page.getByLabel("모서리 곡률", { exact: true });
    // Out-of-range input is clamped on blur to the bound Python applies.
    await page.getByText("6–24px", { exact: true }).waitFor();
    await radius.fill("500");
    await radius.press("Tab");
    assert.equal(await radius.inputValue(), "24");
    assert.equal(
      await draftStatus.textContent(),
      themeModeBefore === "custom"
        ? "적용하지 않은 변경이 있어요."
        : "적용하면 테마가 '내가 꾸민 디자인'으로 바뀝니다.",
    );
    const ornamentOptions = await page
      .getByLabel("왼쪽 장식", { exact: true })
      .locator("option")
      .allTextContents();
    assert.equal(ornamentOptions[0], "없음");
    assert.ok(ornamentOptions.every((label) => !/^[a-z-]+$/.test(label)));
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
      // Claude Code history comes from the isolated transcript fixture.
      const sourceGroup = page.getByRole("group", { name: "기록 출처" });
      await sourceGroup
        .getByRole("button", { name: "Claude Code", exact: true })
        .click();
      await page
        .locator(".project-name strong", { hasText: "qa-folder" })
        .waitFor();
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
      await usageTab("기록").focus();
      await page.keyboard.press("End");
      assert.equal(
        await usageTab("설정").getAttribute("aria-selected"),
        "true",
      );
      await page
        .getByRole("button", { name: "지우기", exact: true })
        .first()
        .click();
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
        .getByRole("button", { name: "활동 기록", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "최근 활동", exact: true })
        .waitFor();
      await page.getByText("확인할 알림이 없어요.").waitFor();
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
        .getByRole("button", { name: "활동 기록", exact: true })
        .click();
      await page
        .locator(".project-activity-heading .source-tag", {
          hasText: "Claude Code",
        })
        .waitFor();
      await page
        .locator(".record-row .source-tag", { hasText: "Claude Code" })
        .first()
        .waitFor();
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
        .getByRole("button", { name: "활동 기록", exact: true })
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
    // Narrow editor: the compact preview must leave the first fields visible.
    await page
      .getByRole("button", { name: "말풍선 꾸미기", exact: true })
      .click();
    await page.getByAltText("현재 말풍선 디자인 미리보기").waitFor();
    const firstField = page.getByLabel("배경색", { exact: true });
    const firstFieldBox = await firstField.boundingBox();
    const viewport = await page.evaluate(() => innerHeight);
    assert.ok(
      firstFieldBox && firstFieldBox.y + firstFieldBox.height < viewport,
    );
    await page.screenshot({ path: path.join(out, "editor-narrow-dark.png") });
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
