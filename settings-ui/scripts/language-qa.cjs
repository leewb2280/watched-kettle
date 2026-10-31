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
      activity: "Notification history",
      integration: "Connections & diagnostics",
      widget: "Widget",
      about: "About",
    }
  : {
      pet: "펫",
      bubble: "말풍선",
      app: "앱 설정",
      home: "홈",
      usage: "사용량",
      activity: "알림 기록",
      integration: "연결·진단",
      widget: "위젯",
      about: "정보",
    };
// Language names in the pack picker and user-owned values (pet, project and
// conversation names, paths) keep the text they were given in any language.
const USER_TEXT = "option, [data-user-text]";
// Runs in the page: untranslated Hangul and app text the layout cuts off.
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
      continue;
    }
    // Text that fits its own box can still be pushed past a card that clips.
    let box = element.parentElement;
    while (box && box !== node && getComputedStyle(box).overflowX === "visible")
      box = box.parentElement;
    if (box && box !== node && !scrolls(getComputedStyle(box).overflowX)) {
      const inner = element.getBoundingClientRect();
      const outer = box.getBoundingClientRect();
      if (inner.right > outer.right + 1 || inner.left < outer.left - 1)
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
async function assertSameRow(first, second, label) {
  const [a, b] = await Promise.all([first.boundingBox(), second.boundingBox()]);
  assert.ok(a && b, label + " must be visible");
  assert.ok(
    Math.abs(a.y + a.height / 2 - b.y - b.height / 2) <= 2,
    label + " must share a row",
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
    await answerDialogsInPage(page);
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
        '<div style="width:40px;overflow:hidden;display:flex">' +
        '<span style="flex-shrink:0;white-space:nowrap">Pushed out 100%</span>' +
        "</div>" +
        "<p>Done 건</p><p data-user-text>사용자 제목</p>";
      node.append(box);
    });
    const probe = await page
      .locator("#language-qa-probe")
      .evaluate(inspectText, { english: true, userText: USER_TEXT });
    await page.locator("#language-qa-probe").evaluate((node) => node.remove());
    assert.deepEqual(probe, {
      korean: ["건"],
      clipped: ["A long label that cannot fit", "Pushed out 100%"],
    });
    // App settings stays last: the language checks below start on it.
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
            "about",
            "app",
          ]
        : ["pet", "bubble", "about", "app"];
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
        if (!communityManifest) {
          await page
            .getByRole("button", {
              name: english ? "Import pet" : "펫 가져오기",
              exact: false,
            })
            .click();
          const importer = page.getByRole("dialog");
          await importer.waitFor();
          const importBefore = await page.evaluate(() =>
            window.settings.request("settings.snapshot"),
          );
          const importHeight = (await importer.boundingBox()).height;
          const addPet = () =>
            importer.getByRole("button", {
              name: english ? "Add pet" : "펫 추가",
              exact: true,
            });
          const chooseAnother = () =>
            importer.getByRole("button", {
              name: english ? "Choose another pet" : "다른 펫 선택",
              exact: true,
            });
          assert.equal(await addPet().count(), 0);
          await assertSameRow(
            importer.getByRole("button", {
              name: english ? "Choose file" : "파일 선택",
              exact: true,
            }),
            importer.getByRole("button", {
              name: english ? "Choose folder" : "폴더 선택",
              exact: true,
            }),
            "file and folder actions",
          );
          await page.screenshot({
            path: path.join(out, "pet-import-source.png"),
          });
          await importer
            .getByRole("tab", {
              name: english ? "File or folder" : "파일·폴더",
              exact: true,
            })
            .focus();
          await page.keyboard.press("ArrowRight");
          await page.evaluate(
            () =>
              new Promise((resolve) =>
                requestAnimationFrame(() => requestAnimationFrame(resolve)),
              ),
          );
          assert.equal(
            await importer
              .getByRole("tab", {
                name: english ? "Paste a command" : "명령어 붙여넣기",
                exact: true,
              })
              .evaluate((node) => node === document.activeElement),
            true,
          );
          await page.keyboard.press("ArrowLeft");
          assert.equal(
            await importer
              .getByRole("tab", {
                name: english ? "File or folder" : "파일·폴더",
                exact: true,
              })
              .getAttribute("aria-selected"),
            "true",
          );
          for (const tabName of [
            english ? "File or folder" : "파일·폴더",
            english ? "Paste a command" : "명령어 붙여넣기",
            english ? "Import from Codex" : "Codex에서 가져오기",
          ]) {
            await importer
              .getByRole("tab", { name: tabName, exact: true })
              .click();
            await page.waitForTimeout(150);
            await assertText(importer, "pet import " + tabName);
            if (await importer.locator("#pet-import-command").count()) {
              await assertSameRow(
                importer.locator("#pet-import-command"),
                importer.getByRole("button", {
                  name: english ? "Get pet" : "가져오기",
                  exact: true,
                }),
                "command and fetch action",
              );
              await importer
                .locator("#pet-import-command")
                .fill("npx codexpetdb install PET_ID");
            }
            if (await importer.locator("#pet-import-search").count()) {
              await assertSameRow(
                importer.locator("#pet-import-search"),
                importer.getByRole("button", {
                  name: english ? "Refresh" : "새로고침",
                  exact: true,
                }),
                "search and refresh action",
              );
              await importer
                .locator("#pet-import-search")
                .fill("no-matching-pet");
              await importer
                .getByText(
                  english
                    ? "No pets match your search."
                    : "검색어와 일치하는 펫이 없습니다.",
                  { exact: true },
                )
                .waitFor();
              await importer.locator("#pet-import-search").fill("Mori");
            }
            await page.screenshot({
              path: path.join(
                out,
                "pet-import-source-" +
                  (await importer
                    .locator('[role="tab"][aria-selected="true"]')
                    .getAttribute("id")) +
                  ".png",
              ),
            });
          }
          await importer
            .getByRole("button", { name: /Mori Bot QA Alt/ })
            .click();
          await importer
            .getByLabel(english ? "Pet name" : "펫 이름", { exact: true })
            .waitFor();
          assert.equal(await importer.getByRole("tab").count(), 0);
          assert.equal((await importer.boundingBox()).height, importHeight);
          const petName = importer.getByLabel(
            english ? "Pet name" : "펫 이름",
            { exact: true },
          );
          await until(() =>
            petName.evaluate((node) => node === document.activeElement),
          );
          await petName.fill("");
          assert.equal(await addPet().isDisabled(), true);
          await petName.fill("discarded-name-draft");
          await chooseAnother().click();
          assert.equal(await addPet().count(), 0);
          assert.equal(await importer.locator(".import-animation").count(), 0);
          assert.equal(
            await importer.locator("#pet-import-search").inputValue(),
            "Mori",
          );
          await importer
            .getByRole("tab", {
              name: english ? "Paste a command" : "명령어 붙여넣기",
              exact: true,
            })
            .click();
          assert.equal(
            await importer.locator("#pet-import-command").inputValue(),
            "npx codexpetdb install PET_ID",
          );
          await importer
            .getByRole("tab", {
              name: english ? "Import from Codex" : "Codex에서 가져오기",
              exact: true,
            })
            .click();
          await importer
            .getByRole("button", { name: /Mori Bot QA Alt/ })
            .click();
          await petName.waitFor();
          assert.equal(await petName.inputValue(), "Mori Bot QA Alt");
          await assertSameRow(
            chooseAnother(),
            addPet(),
            "confirmation footer actions",
          );
          await assertSameRow(
            importer.getByLabel(
              english ? "Animation preview" : "동작 미리보기",
              { exact: true },
            ),
            importer.getByRole("button", {
              name: english ? "Pause" : "일시 정지",
              exact: true,
            }),
            "animation and playback action",
          );
          const animation = importer.getByLabel(
            english ? "Animation preview" : "동작 미리보기",
            { exact: true },
          );
          for (const state of [
            "idle",
            "running-right",
            "running-left",
            "waving",
            "jumping",
            "failed",
            "waiting",
            "running",
            "review",
          ]) {
            await animation.selectOption(state);
          }
          await assertText(importer, "pet import preview");
          await page.screenshot({
            path: path.join(out, "pet-import-preview.png"),
          });
          for (const factor of [1.5, 2]) {
            await app.evaluate(
              ({ BrowserWindow }, value) =>
                BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(
                  value,
                ),
              factor,
            );
            await assertText(importer, "pet import zoom " + factor);
            assert.equal(
              await importer.evaluate(
                (node) => node.scrollWidth > node.clientWidth,
              ),
              false,
            );
            assert.equal(
              await importer.evaluate((node) => {
                const box = node.getBoundingClientRect();
                return (
                  box.left >= 0 &&
                  box.right <= innerWidth + 1 &&
                  box.top >= 0 &&
                  box.bottom <= innerHeight + 1
                );
              }),
              true,
              "import dialog must fit the zoomed viewport",
            );
            // Electron zoom changes CSS metrics used by Playwright's screenshot
            // clip. Capture the webContents surface to retain the full window.
            const png = await app.evaluate(async ({ BrowserWindow }) =>
              (await BrowserWindow.getAllWindows()[0].webContents.capturePage())
                .toPNG()
                .toString("base64"),
            );
            await fs.writeFile(
              path.join(out, "pet-import-zoom-" + factor + ".png"),
              Buffer.from(png, "base64"),
            );
          }
          await app.evaluate(({ BrowserWindow }) =>
            BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1),
          );
          const setImportPreference = async (key, value) => {
            await page.evaluate(
              async ({ key, value }) => {
                const state =
                  await window.settings.request("settings.snapshot");
                await window.settings.request("settings.set", {
                  petId: state.pet.pet_id,
                  revision: state.revision,
                  epoch: state.epoch,
                  key: "appearance:" + key,
                  value,
                });
              },
              { key, value },
            );
          };
          await setImportPreference("reduceMotion", true);
          await importer
            .getByRole("button", {
              name: english ? "Play" : "재생",
              exact: true,
            })
            .waitFor();
          await setImportPreference("theme", "dark");
          await until(() =>
            page
              .locator("html")
              .getAttribute("data-theme")
              .then((value) => value === "dark"),
          );
          await app.evaluate(({ BrowserWindow }) =>
            BrowserWindow.getAllWindows()[0].setSize(640, 460),
          );
          await assertText(importer, "pet import minimum window dark");
          assert.equal(
            await importer.evaluate(
              (node) => node.scrollWidth > node.clientWidth,
            ),
            false,
          );
          await page.screenshot({
            path: path.join(out, "pet-import-minimum-dark.png"),
          });
          await app.evaluate(({ BrowserWindow }) =>
            BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(2),
          );
          await assertText(importer, "pet import minimum window 200%");
          assert.equal(
            await importer.evaluate(
              (node) => node.scrollWidth > node.clientWidth,
            ),
            false,
          );
          await app.evaluate(({ BrowserWindow }) => {
            BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(1);
            BrowserWindow.getAllWindows()[0].setSize(1240, 860);
          });
          await setImportPreference("theme", importBefore.appearance.theme);
          await setImportPreference(
            "reduceMotion",
            importBefore.appearance.reduceMotion,
          );
          metrics.petImport = {
            steps: true,
            inlineActions: true,
            draftReset: true,
            inputDraftsPreserved: true,
            minimumWindow: true,
            reducedMotion: true,
          };
          for (const [purpose, source] of [
            ["pet-folder", connection.petImportFolder],
            ["pet", connection.petImportZip],
          ]) {
            await importer
              .getByRole("button", {
                name: english ? "Choose another pet" : "다른 펫 선택",
                exact: true,
              })
              .click();
            await importer
              .getByRole("tab", {
                name: english ? "File or folder" : "파일·폴더",
                exact: true,
              })
              .click();
            await app.evaluate(({ dialog }, file) => {
              if (!globalThis.qaImportPicker)
                globalThis.qaImportPicker = dialog.showOpenDialog;
              dialog.showOpenDialog = async () => ({
                canceled: false,
                filePaths: [file],
              });
            }, source);
            await importer
              .getByRole("button", {
                name:
                  purpose === "pet-folder"
                    ? english
                      ? "Choose folder"
                      : "폴더 선택"
                    : english
                      ? "Choose file"
                      : "파일 선택",
                exact: true,
              })
              .click();
            await importer
              .getByLabel(english ? "Pet name" : "펫 이름", { exact: true })
              .waitFor();
            await assertText(importer, "pet import " + purpose);
            if (purpose === "pet-folder") {
              await importer
                .getByText(
                  english
                    ? "1 package field this app does not use will not be imported:"
                    : "이 앱에서 쓰지 않는 패키지 항목 1개는 가져오지 않습니다:",
                )
                .waitFor();
              await importer
                .getByText(
                  english
                    ? "Bubble settings that point to decorations from another installation cannot be used and were reset to the defaults."
                    : "다른 설치 환경의 장식을 가리키는 말풍선 설정은 쓸 수 없어 기본값으로 바꿨습니다.",
                )
                .waitFor();
              await page.screenshot({
                path: path.join(out, "pet-import-omitted.png"),
              });
            }
          }
          await app.evaluate(({ dialog }) => {
            dialog.showOpenDialog = globalThis.qaImportPicker;
          });
          await importer
            .getByRole("button", {
              name: english ? "Choose another pet" : "다른 펫 선택",
              exact: true,
            })
            .click();
          await importer
            .getByRole("tab", {
              name: english ? "Paste a command" : "명령어 붙여넣기",
              exact: true,
            })
            .click();
          await importer
            .getByRole("textbox", {
              name: english ? "Paste a command" : "명령어 붙여넣기",
              exact: true,
            })
            .fill("npx petscodex install cat --force");
          await importer
            .getByRole("button", {
              name: english ? "Get pet" : "가져오기",
              exact: true,
            })
            .click();
          await importer.getByRole("alert").waitFor();
          await assertText(importer, "pet import invalid command");
          assert.equal(
            (
              await page.evaluate(() =>
                window.settings.request("settings.snapshot"),
              )
            ).pet.pet_id,
            importBefore.pet.pet_id,
          );
          assert.equal(
            await importer.evaluate(
              (node) => node.scrollWidth > node.clientWidth,
            ),
            false,
          );
          await importer
            .getByRole("button", {
              name: english ? "Cancel" : "취소",
              exact: true,
            })
            .last()
            .click();
        }
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
        await page
          .getByRole("tab", {
            name: english ? "Behavior" : "동작·화면",
            exact: true,
          })
          .click();
        const shortcut = page.locator(".hotkey-input").first();
        await shortcut.scrollIntoViewIfNeeded();
        await shortcut
          .getByRole("button", {
            name: english ? "Set shortcut" : "단축키 지정",
            exact: true,
          })
          .click();
        await shortcut
          .getByText(
            english
              ? "Press keys (Esc to cancel)"
              : "키를 누르세요 (Esc: 취소)",
          )
          .waitFor();
        await assertText(page.locator("main"), "pet shortcut recording");
        await page.keyboard.press("Shift+P");
        assert.equal(
          await shortcut.locator("kbd").getAttribute("class"),
          "is-recording",
        );
        await shortcut.locator(".hotkey-status").waitFor();
        await assertText(page.locator("main"), "pet shortcut rejected");
        await page.keyboard.press("Control+Alt+F9");
        await shortcut.getByText("Ctrl+Alt+F9").waitFor();
        assert.equal(await shortcut.locator("kbd").getAttribute("class"), null);
        await assertText(page.locator("main"), "pet shortcut assigned");
        await page.screenshot({ path: path.join(out, "pet-shortcut.png") });
        await shortcut
          .getByRole("button", {
            name: english ? "Clear" : "지우기",
            exact: true,
          })
          .click();
        await shortcut
          .getByText(english ? "Not set" : "지정 안 함", { exact: true })
          .waitFor();
        // Unassigned reads as plain text, not as a second button.
        assert.equal(
          await shortcut.locator("kbd").getAttribute("class"),
          "is-empty",
        );
        await page
          .getByRole("tab", {
            name: english ? "Appearance" : "외형·표시",
            exact: true,
          })
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
          await editor.locator(".preview-mode, [role=tablist]").count(),
          0,
        );
        // A narrow window folds the panel; its rail names the tabs.
        if (!(await editor.locator(".editor-controls").isVisible()))
          await editor
            .locator(".editor-rail")
            .getByRole("button", {
              name: english ? "Background" : "배경",
              exact: true,
            })
            .click();
        await assertText(editor, "bubble workspace");
        for (const tab of english
          ? [
              "Background",
              "Border and shape",
              "Decorations",
              "Text & layout",
              "My themes",
            ]
          : ["배경", "테두리·모양", "장식", "글자·배치", "내 테마"]) {
          // The open tab's rail button would fold the panel instead.
          const rail = editor
            .locator(".editor-rail")
            .getByRole("button", { name: tab, exact: true });
          if ((await rail.getAttribute("aria-pressed")) !== "true")
            await rail.click();
          await assertText(editor, `bubble workspace / ${tab}`);
        }
        await page.screenshot({
          path: path.join(out, "bubble-editor-workspace.png"),
        });
        await page.keyboard.press("Escape");
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
      if (id === "about") {
        // Links leave only through the main process's repository allowlist.
        const links = await page
          .locator("main a")
          .evaluateAll((nodes) =>
            nodes.map((node) => [node.getAttribute("href"), node.target]),
          );
        assert.ok(links.length >= 5, "about links");
        for (const [href, target] of links) {
          assert.match(
            href,
            /^https:\/\/github\.com\/leewb2280\/watched-kettle(\/|$)/,
          );
          assert.equal(target, "_blank", href);
        }
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
      await control({ action: "pending_notices", count: 7 });
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
        if (id === "activity") {
          await page
            .getByRole("button", {
              name: english ? /^Show \d+ more$/ : /^\d+건 더 보기$/,
              exact: true,
            })
            .click();
          await page
            .getByRole("button", {
              name: english ? "Show less" : "접기",
              exact: true,
            })
            .waitFor();
          await assertText(page.locator("main"), "notifications expanded");
          await page.screenshot({
            path: path.join(out, "activity-expanded.png"),
          });
          await page
            .getByRole("button", {
              name: english ? "Mark all as read" : "모두 확인",
              exact: true,
            })
            .click();
          await page
            .getByText(
              english
                ? "No notifications need your attention."
                : "확인할 알림이 없어요.",
              { exact: true },
            )
            .waitFor();
          await assertText(page.locator("main"), "notifications confirmed");
        }
        if (id === "usage") {
          const credits = page.locator(".codex-reset-credits");
          const setCredits = async (values) => {
            await control({ action: "codex_reset_credits", ...values });
          };
          const creditText = (count) =>
            english
              ? `${count} usage reset credit${count === 1 ? "" : "s"}`
              : `사용량 리셋권 ${count}개`;
          for (const count of [0, 1, 3]) {
            await setCredits({ count });
            await until(
              async () => (await credits.textContent()) === creditText(count),
            );
            assert.equal(await credits.count(), 1);
            // A badge beside the provider name, muted when none are left.
            assert.equal(
              await page
                .locator(
                  '[data-provider="codex"] .quota-provider-heading .codex-reset-credits',
                )
                .count(),
              1,
            );
            assert.equal(
              await credits.evaluate((node) =>
                node.classList.contains("is-empty"),
              ),
              count === 0,
            );
            await assertText(credits, "Codex reset credits " + count);
          }
          await page.screenshot({
            path: path.join(out, "usage-codex-reset-credits.png"),
          });
          await setCredits({ count: null });
          await until(async () => (await credits.count()) === 0);
          await setCredits({ count: 3, checking: true });
          await until(async () => (await credits.count()) === 0);
          await setCredits({ count: 3, enabled: false });
          await until(async () => (await credits.count()) === 0);
          await setCredits({ count: 3, enabled: true, clear_limits: true });
          await until(
            async () => (await credits.textContent()) === creditText(3),
          );
          assert.equal(
            await page.locator('[data-provider="codex"] .quota-card').count(),
            0,
          );
          await control({ action: "codex_limits" });
          await page
            .getByRole("button", { name: labels.home, exact: true })
            .first()
            .click();
          await page
            .getByRole("heading", { name: labels.home, exact: true, level: 1 })
            .waitFor();
          assert.equal(
            await credits.count(),
            0,
            "compact home omits reset credits",
          );
          await page
            .getByRole("button", { name: labels.usage, exact: true })
            .first()
            .click();
          await until(
            async () => (await credits.textContent()) === creditText(3),
          );
          metrics.codexResetCredits = {
            counts: [0, 1, 3],
            missingHidden: true,
            checkingHidden: true,
            disabledHidden: true,
            withoutLimits: true,
            usageOnly: true,
          };
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
    await page.screenshot({
      path: path.join(out, "language-restart-wide.png"),
    });
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
