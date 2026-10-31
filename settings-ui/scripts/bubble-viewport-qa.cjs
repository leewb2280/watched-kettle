// Real Electron input and the real Python painter. Faults are injected only in
// this QA process's IPC handler, never through a product/debug command.
const assert = require("node:assert/strict");
const path = require("node:path");
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(check) {
  const end = Date.now() + 10000;
  while (Date.now() < end) {
    if (await check()) return;
    await pause(40);
  }
  throw new Error("Bubble viewport condition timed out");
}
const near = (a, b, tolerance = 1.5) =>
  assert.ok(Math.abs(a - b) <= tolerance, `${a} != ${b}`);
async function metrics(page) {
  return page.locator(".bubble-viewport").evaluate((node) => {
    const image = node.querySelector(".bubble-preview-image");
    const rect = image.getBoundingClientRect(),
      surface = node.getBoundingClientRect();
    return {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
      surface: {
        x: surface.x,
        y: surface.y,
        width: surface.width,
        height: surface.height,
      },
      src: image.src,
      // The percent label shows only while fitted; round like it did.
      zoom: Math.round(Number(node.dataset.zoom) * 100) / 100,
    };
  });
}
async function foldPanel(page) {
  if (await page.locator(".editor-controls").isVisible())
    await page.getByRole("button", { name: "패널 접기", exact: true }).click();
  assert.equal(await page.locator(".editor-controls").isVisible(), false);
}
async function selectBubbleSection(page, name) {
  const button = page
    .locator(".editor-rail")
    .getByRole("button", { name, exact: true });
  if ((await button.getAttribute("aria-expanded")) !== "true")
    await button.click();
  assert.equal(await page.locator(".editor-controls").isVisible(), true);
}
async function openPanel(page) {
  if (await page.locator(".editor-controls").isVisible()) return;
  const id = await page
    .locator(".editor-controls")
    .getAttribute("aria-labelledby");
  await page.locator("#" + id).click();
  assert.equal(await page.locator(".editor-controls").isVisible(), true);
}
async function setZoom(page, zoom) {
  await page
    .getByLabel("미리보기 확대", { exact: true })
    .selectOption(String(zoom));
  await until(async () => (await metrics(page)).zoom === zoom);
}
async function testBubbleViewport({ page, app, out }) {
  const sizeBefore = await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].getSize(),
  );
  const saved = await page.evaluate(() =>
    window.settings.request("bubble.editor"),
  );
  const undo = page.getByRole("button", { name: "실행 취소", exact: true });
  const dirty = await page.locator(".draft-status").textContent();
  const history = await undo.isDisabled();
  assert.equal(
    await page.locator(".editor-controls").isVisible(),
    await page.evaluate(() => innerWidth >= 960),
  );
  assert.equal(
    await page.getByLabel("미리보기 확대", { exact: true }).inputValue(),
    "fit",
  );
  await foldPanel(page);
  for (const [width, height] of [
    [640, 460],
    [720, 600],
    [1240, 860],
  ]) {
    await app.evaluate(
      ({ BrowserWindow }, size) =>
        BrowserWindow.getAllWindows()[0].setSize(...size),
      [width, height],
    );
    await pause(100);
    const bounds = await page.locator(".bubble-editor-modal").boundingBox();
    assert.ok(bounds.y >= 62 && bounds.x >= 15);
    for (const label of ["배경", "닫기", "적용"]) {
      const button = page
        .locator(label === "배경" ? ".editor-rail" : "body")
        .getByRole("button", { name: label, exact: true });
      const box = await button.boundingBox();
      assert.ok(
        box &&
          box.y >= bounds.y &&
          box.y + box.height <= bounds.y + bounds.height + 1,
        label,
      );
    }
    const view = await metrics(page);
    assert.ok(view.surface.width > 250 && view.surface.height > 60);
    assert.equal(
      await page
        .locator(".bubble-scene")
        .evaluate((n) => getComputedStyle(n).overflow),
      "hidden",
    );
    await page.screenshot({
      path: path.join(out, `editor-workspace-${width}.png`),
    });
    await openPanel(page);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator(".editor-controls").isVisible(), false);
    assert.equal(await page.locator(".bubble-editor-modal[open]").count(), 1);
  }
  // Resize across the breakpoint once; narrow-to-narrow preserves a manually
  // opened overlay, and growing again does not reopen a folded panel.
  await openPanel(page);
  await setZoom(page, 2);
  for (const [width, expected] of [
    [960, true],
    [959, false],
    [960, false],
  ]) {
    await app.evaluate(
      ({ BrowserWindow }, width) =>
        BrowserWindow.getAllWindows()[0].setSize(width, 860),
      width,
    );
    await until(
      async () =>
        (await page.locator(".editor-controls").isVisible()) === expected,
    );
    assert.equal((await metrics(page)).zoom, 2);
  }
  await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setSize(959, 860),
  );
  await openPanel(page);
  await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setSize(720, 600),
  );
  await pause(100);
  assert.equal(await page.locator(".editor-controls").isVisible(), true);
  await foldPanel(page);
  await app.evaluate(
    ({ BrowserWindow }, size) =>
      BrowserWindow.getAllWindows()[0].setSize(...size),
    sizeBefore,
  );
  assert.equal(await page.locator(".editor-controls").isVisible(), false);
  assert.equal(
    await page
      .locator(".preview-mode, .editor-controls [role=tablist]")
      .count(),
    0,
  );
  await setZoom(page, 1);
  const one = await metrics(page);
  for (const zoom of [2, 4, 1]) {
    await setZoom(page, zoom);
    const current = await metrics(page);
    near(current.width, one.width * zoom);
    near(current.height, one.height * zoom);
  }
  // Pointer anchoring and Space/middle pan must not select/copy a pet layer.
  await setZoom(page, 4);
  let start = await metrics(page);
  const anchor = {
    x: start.surface.x + start.surface.width / 2,
    y: start.surface.y + start.surface.height / 2,
  };
  await page.mouse.move(anchor.x, anchor.y);
  await page.mouse.wheel(0, 120);
  await until(async () => (await metrics(page)).zoom < 4);
  let changed = await metrics(page);
  near(
    (anchor.x - start.x) / start.width,
    (anchor.x - changed.x) / changed.width,
    0.015,
  );
  const layerCount = await page
    .locator(".canvas-layer:not(.canvas-background)")
    .count();
  for (const button of ["left", "middle"]) {
    await setZoom(page, 4);
    start = await metrics(page);
    await page.mouse.move(anchor.x, anchor.y);
    if (button === "left") await page.keyboard.down("Space");
    await page.mouse.down({ button });
    await page.mouse.move(anchor.x - 35, anchor.y, { steps: 4 });
    await page.mouse.up({ button });
    if (button === "left") await page.keyboard.up("Space");
    changed = await metrics(page);
    if (start.width + 56 > start.surface.width) near(changed.x, start.x - 35);
    assert.equal(
      await page.locator(".canvas-layer:not(.canvas-background)").count(),
      layerCount,
    );
  }
  await page.locator(".bubble-canvas").focus();
  await page.keyboard.press("Control+0");
  assert.equal(
    await page.getByLabel("미리보기 확대", { exact: true }).inputValue(),
    "fit",
  );
  await page.keyboard.press("Control+-");
  assert.notEqual(
    await page.getByLabel("미리보기 확대", { exact: true }).inputValue(),
    "fit",
  );
  assert.equal(await page.locator(".draft-status").textContent(), dirty);
  assert.equal(await undo.isDisabled(), history);
  assert.deepEqual(
    (await page.evaluate(() => window.settings.request("bubble.editor"))).theme,
    saved.theme,
  );

  await app.evaluate(({ ipcMain }) => {
    const original = ipcMain._invokeHandlers.get("settings:request");
    globalThis.viewportQa = {
      original,
      delay: 0,
      fail: false,
      active: 0,
      maxActive: 0,
      calls: [],
    };
    ipcMain.removeHandler("settings:request");
    ipcMain.handle("settings:request", async (event, method, args) => {
      if (method !== "bubble.render") return original(event, method, args);
      const state = globalThis.viewportQa;
      state.active++;
      state.maxActive = Math.max(state.active, state.maxActive);
      const call = { sample: args.sample, ratio: args.pixelRatio };
      state.calls.push(call);
      const delay = state.delay,
        fail = state.fail;
      try {
        if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
        if (fail) throw new Error("QA preview render failure");
        const result = await original(event, method, args);
        call.actual = result.pixelRatio;
        return result;
      } finally {
        state.active--;
      }
    });
  });
  const cdp = await page.context().newCDPSession(page);
  try {
    // CDP DPR is simulated Chromium output, not a Windows display-scale test.
    for (const dpr of [1, 1.5, 2]) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width: 1200,
        height: 800,
        deviceScaleFactor: dpr,
        mobile: false,
      });
      const actualDpr = await page.evaluate(() => window.devicePixelRatio);
      assert.equal(actualDpr, dpr, "Chromium DPR emulation must take effect");
      const previous = (await metrics(page)).src;
      await page
        .getByRole("button", { name: "프로젝트 카드", exact: true })
        .click();
      await until(async () => (await metrics(page)).src !== previous);
      await setZoom(page, 4);
      await until(async () => {
        const view = await metrics(page);
        const logicalWidth = view.width / 4,
          logicalHeight = view.height / 4;
        let expected = dpr > 1 ? 8 : 4;
        while (
          expected > 1 &&
          (Math.max(logicalWidth, logicalHeight) * expected > 4096 ||
            logicalWidth * logicalHeight * expected ** 2 > 8_388_608)
        )
          expected /= 2;
        return view.naturalWidth >= logicalWidth * expected - 1;
      }).catch(async (error) => {
        throw new Error(
          `${error.message}; DPR=${dpr}; ${JSON.stringify({ ...(await metrics(page)), src: undefined })}; requests=${JSON.stringify(await app.evaluate(() => globalThis.viewportQa.calls))}`,
        );
      });
      const projectImage = (await metrics(page)).src;
      await page
        .getByRole("button", { name: "짧은 알림", exact: true })
        .click();
      await until(async () => (await metrics(page)).src !== projectImage);
    }
    await cdp.send("Emulation.clearDeviceMetricsOverride");
    const old = await metrics(page);
    const beforeSlow = await app.evaluate(
      () => globalThis.viewportQa.calls.length,
    );
    await app.evaluate(() => {
      globalThis.viewportQa.delay = 650;
    });
    await page.getByRole("button", { name: "긴 문장", exact: true }).click();
    await until(() => app.evaluate(() => globalThis.viewportQa.active === 1));
    await page
      .getByRole("button", { name: "프로젝트 카드", exact: true })
      .click();
    await setZoom(page, 4);
    for (let i = 0; i < 8; i++) {
      await page.mouse.move(anchor.x, anchor.y);
      await page.mouse.wheel(0, i % 2 ? -90 : 60);
    }
    assert.ok((await metrics(page)).src);
    await until(() =>
      app.evaluate(
        (offset) =>
          globalThis.viewportQa.calls
            .slice(offset)
            .some((call) => call.sample === "long" && call.actual),
        beforeSlow,
      ),
    );
    await pause(60);
    assert.ok(
      (await metrics(page)).src === old.src,
      "a stale long sample must not replace the last good image",
    );
    await until(() =>
      app.evaluate(
        (offset) =>
          globalThis.viewportQa.active === 0 &&
          globalThis.viewportQa.calls
            .slice(offset)
            .some((call) => call.sample === "project" && call.actual),
        beforeSlow,
      ),
    );
    assert.ok(
      (await metrics(page)).src !== old.src,
      "the latest project sample must replace the old image",
    );
    assert.equal(await app.evaluate(() => globalThis.viewportQa.maxActive), 1);
    await app.evaluate(() => {
      globalThis.viewportQa.delay = 0;
      globalThis.viewportQa.fail = true;
    });
    const lastGood = (await metrics(page)).src;
    await page.getByRole("button", { name: "긴 문장", exact: true }).click();
    await page.locator(".editor-preview [role=alert]").waitFor();
    assert.equal((await metrics(page)).src, lastGood);
    await app.evaluate(() => {
      globalThis.viewportQa.fail = false;
    });
    await page.getByRole("button", { name: "짧은 알림", exact: true }).click();
    await until(
      async () =>
        (await page.locator(".editor-preview [role=alert]").count()) === 0,
    );
  } finally {
    await cdp.send("Emulation.clearDeviceMetricsOverride");
    await cdp.detach();
    await app.evaluate(({ ipcMain }) => {
      ipcMain.removeHandler("settings:request");
      ipcMain.handle("settings:request", globalThis.viewportQa.original);
    });
  }
  await openPanel(page);
  const section = await page
    .locator(".editor-controls")
    .getAttribute("aria-labelledby");
  await page.getByRole("button", { name: "패널 접기", exact: true }).focus();
  await page.keyboard.press("Escape");
  await until(
    async () =>
      (await page.evaluate(() => document.activeElement?.id)) === section,
  );
  assert.equal(await page.locator(".bubble-editor-modal[open]").count(), 1);
  await page.keyboard.press("Space");
  await until(async () => await page.locator(".editor-controls").isVisible());
  await page.locator("#" + section).focus();
  await page.keyboard.press("Space");
  await until(
    async () => !(await page.locator(".editor-controls").isVisible()),
  );
  await openPanel(page);
  // New sessions apply the initial-width policy, not the previous panel state.
  await page.getByRole("button", { name: "취소", exact: true }).click();
  for (const [width, height] of [
    [640, 460],
    [720, 600],
    [1240, 860],
  ]) {
    await app.evaluate(
      ({ BrowserWindow }, size) =>
        BrowserWindow.getAllWindows()[0].setSize(...size),
      [width, height],
    );
    await page
      .getByRole("button", { name: "말풍선 꾸미기", exact: true })
      .click();
    await page.locator(".bubble-preview-image").waitFor();
    assert.equal(
      await page.locator(".editor-controls").isVisible(),
      width >= 960,
    );
    assert.equal(
      await page.getByLabel("미리보기 확대", { exact: true }).inputValue(),
      "fit",
    );
    await page.getByRole("button", { name: "취소", exact: true }).click();
  }
  await app.evaluate(
    ({ BrowserWindow }, size) =>
      BrowserWindow.getAllWindows()[0].setSize(...size),
    sizeBefore,
  );
  await page
    .getByRole("button", { name: "말풍선 꾸미기", exact: true })
    .click();
  await page.locator(".bubble-preview-image").waitFor();
  await openPanel(page);
  await until(() =>
    page
      .locator(".bubble-preview-image")
      .evaluate(
        (node) =>
          node.complete &&
          node.naturalWidth >=
            node.getBoundingClientRect().width * devicePixelRatio - 1,
      ),
  );
  await page.screenshot({ path: path.join(out, "editor-workspace-ready.png") });
  return {
    sizes: ["640x460", "720x600", "1240x860"],
    simulatedDpr: [1, 1.5, 2],
    wheelPanKeyboard: true,
    serialStaleFailure: true,
  };
}

async function testBubbleLayerTransforms({ page, app }) {
  const selected = page.locator(
    ".canvas-layer.is-selected:not(.canvas-background)",
  );
  const xField = page.locator("#field-decor_position_x");
  const original = Number(await xField.inputValue());
  const dirty = await page.locator(".draft-status").textContent();
  await foldPanel(page);
  const reveal = async () => {
    const box = await selected.boundingBox(),
      view = await metrics(page);
    const x = view.surface.x + view.surface.width / 2;
    const y = view.surface.y + view.surface.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down({ button: "middle" });
    await page.mouse.move(
      x + x - box.x - box.width / 2,
      y + y - box.y - box.height / 2,
      { steps: 4 },
    );
    await page.mouse.up({ button: "middle" });
  };
  for (const scale of ["fit", 1, 2, 4]) {
    await page
      .getByLabel("미리보기 확대", { exact: true })
      .selectOption(String(scale));
    await pause(80);
    await reveal();
    let box = await selected.boundingBox();
    const [zoom, bodyWidth] = await page
      .locator(".bubble-viewport")
      .evaluate((node) => [
        Number(node.dataset.zoom),
        Number(node.dataset.bodyWidth),
      ]);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.keyboard.down("Alt");
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 12, box.y + box.height / 2, {
      steps: 4,
    });
    await page.mouse.up();
    await page.keyboard.up("Alt");
    await until(async () => Number(await xField.inputValue()) !== original);
    near(
      Number(await xField.inputValue()),
      original - (12 / zoom / bodyWidth) * 100,
      0.8,
    );
    await page.keyboard.press("Control+z");
    await until(async () => Number(await xField.inputValue()) === original);
    // Resizing and rotation share logical coordinates, while handles stay 10px.
    const widthField = page.locator("#field-decor_width");
    const initialWidth = Number(await widthField.inputValue());
    const corner = await selected.locator(".canvas-handle-se").boundingBox();
    near(corner.width, 10, 0.01);
    await page.mouse.move(corner.x + 5, corner.y + 5);
    await page.mouse.down();
    await page.mouse.move(corner.x + 17, corner.y + 5, { steps: 4 });
    await page.mouse.up();
    await until(
      async () => Number(await widthField.inputValue()) !== initialWidth,
    );
    near(Number(await widthField.inputValue()), initialWidth + 12 / zoom, 0.2);
    await page.keyboard.press("Control+z");
    await until(
      async () => Number(await widthField.inputValue()) === initialWidth,
    );
    const rotation = page.locator("#field-decor_rotation");
    const initialRotation = Number(await rotation.inputValue());
    box = await selected.boundingBox();
    const rotate = await selected.locator(".canvas-rotate").boundingBox();
    await page.mouse.move(rotate.x + 5, rotate.y + 5);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width + 18, box.y + box.height / 2, {
      steps: 4,
    });
    await page.mouse.up();
    await until(
      async () => Number(await rotation.inputValue()) !== initialRotation,
    );
    near(Number(await rotation.inputValue()), 90, 1);
    await page.keyboard.press("Control+z");
    await until(
      async () => Number(await rotation.inputValue()) === initialRotation,
    );
    // Cancellation is not an undo step and keeps the selected layer.
    box = await selected.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(
      box.x + box.width / 2 + 10,
      box.y + box.height / 2 + 4,
    );
    await page.keyboard.press("Escape");
    await page.mouse.up();
    assert.equal(Number(await xField.inputValue()), original);
    assert.equal(await selected.count(), 1);
    assert.equal(await page.locator(".bubble-editor-modal[open]").count(), 1);
    for (const interruption of ["pointercancel", "blur", "resize"]) {
      box = await selected.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2 - 16, box.y + box.height / 2);
      if (interruption === "pointercancel")
        await selected.dispatchEvent("pointercancel", { pointerId: 1 });
      else if (interruption === "blur")
        await page.evaluate(() => window.dispatchEvent(new Event("blur")));
      else {
        const size = await app.evaluate(({ BrowserWindow }) =>
          BrowserWindow.getAllWindows()[0].getSize(),
        );
        await app.evaluate(
          ({ BrowserWindow }, size) =>
            BrowserWindow.getAllWindows()[0].setSize(size[0] - 8, size[1]),
          size,
        );
        await pause(80);
        await app.evaluate(
          ({ BrowserWindow }, size) =>
            BrowserWindow.getAllWindows()[0].setSize(...size),
          size,
        );
      }
      await page.mouse.up();
      assert.equal(Number(await xField.inputValue()), original);
    }
  }
  assert.equal(await page.locator(".draft-status").textContent(), dirty);
  await openPanel(page);
  await page.keyboard.press("Escape");
  assert.equal(await selected.count(), 1);
  const box = await selected.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 - 16, box.y + box.height / 2, {
    steps: 4,
  });
  await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].hide(),
  );
  await pause(120);
  await app.evaluate(({ BrowserWindow }) => {
    const win = BrowserWindow.getAllWindows()[0];
    win.show();
    win.focus();
  });
  await page.mouse.up();
  assert.equal(Number(await xField.inputValue()), original);
  assert.equal(await selected.count(), 1);
  await page.locator(".bubble-canvas").focus();
  await page.keyboard.press("Escape");
  assert.equal(await selected.count(), 0);
  assert.equal(await page.locator(".bubble-editor-modal[open]").count(), 1);
  await page.evaluate(() => {
    window.qaWorkspaceConfirm = window.confirm;
    window.confirm = (message) => {
      window.qaConfirmations.push(String(message));
      return false;
    };
  });
  const confirmations = await page.evaluate(
    () => window.qaConfirmations.length,
  );
  await page.keyboard.press("Escape");
  assert.equal(await page.locator(".bubble-editor-modal[open]").count(), 1);
  assert.equal(
    await page.evaluate(() => window.qaConfirmations.length),
    confirmations + 1,
  );
  await page.evaluate(() => {
    window.confirm = window.qaWorkspaceConfirm;
  });
  await page
    .locator(".canvas-layer:not(.canvas-background):not(.canvas-pet-layer)")
    .first()
    .click();
  await openPanel(page);
  assert.equal(await selected.count(), 1);
  assert.equal(await page.locator(".draft-status").textContent(), dirty);
  await page.getByLabel("미리보기 확대", { exact: true }).selectOption("fit");
  return true;
}
async function testBubbleBackgroundTransforms({ page, app }) {
  const photo = page.locator(".canvas-background");
  const xField = page.getByLabel("가로 위치", { exact: true });
  const widthField = page.getByLabel("너비", { exact: true });
  const original = Number(await xField.inputValue());
  const originalWidth = Number(await widthField.inputValue());
  await foldPanel(page);
  for (const scale of ["fit", 1, 2, 4]) {
    await page
      .getByLabel("미리보기 확대", { exact: true })
      .selectOption(String(scale));
    await pause(80);
    let box = await photo.boundingBox();
    const view = await metrics(page);
    const x = view.surface.x + view.surface.width / 2,
      y = view.surface.y + view.surface.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down({ button: "middle" });
    await page.mouse.move(
      x + x - box.x - box.width / 2,
      y + y - box.y - box.height / 2,
      { steps: 4 },
    );
    await page.mouse.up({ button: "middle" });
    box = await photo.boundingBox();
    const [zoom, bodyWidth] = await page
      .locator(".bubble-viewport")
      .evaluate((node) => [
        Number(node.dataset.zoom),
        Number(node.dataset.bodyWidth),
      ]);
    await page.keyboard.down("Alt");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 12, box.y + box.height / 2, {
      steps: 4,
    });
    await page.mouse.up();
    await page.keyboard.up("Alt");
    await until(async () => Number(await xField.inputValue()) !== original);
    near(
      Number(await xField.inputValue()),
      original - (12 / zoom / bodyWidth) * 100,
      1,
    );
    await page.keyboard.press("Control+z");
    await until(async () => Number(await xField.inputValue()) === original);
    const handle = await photo.locator(".canvas-handle-e").boundingBox();
    await page.mouse.move(handle.x + 5, handle.y + 5);
    await page.mouse.down();
    await page.mouse.move(handle.x + 17, handle.y + 5, { steps: 4 });
    await page.mouse.up();
    await until(
      async () => Number(await widthField.inputValue()) !== originalWidth,
    );
    near(Number(await widthField.inputValue()), originalWidth + 12 / zoom, 1);
    await page.keyboard.press("Control+z");
    await until(
      async () => Number(await widthField.inputValue()) === originalWidth,
    );
    for (const interruption of ["pointercancel", "blur", "resize"]) {
      box = await photo.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(
        box.x + box.width / 2 - 16,
        box.y + box.height / 2,
        { steps: 4 },
      );
      if (interruption === "pointercancel")
        await photo.dispatchEvent("pointercancel", { pointerId: 1 });
      else if (interruption === "blur")
        await page.evaluate(() => window.dispatchEvent(new Event("blur")));
      else {
        const size = await app.evaluate(({ BrowserWindow }) =>
          BrowserWindow.getAllWindows()[0].getSize(),
        );
        await app.evaluate(
          ({ BrowserWindow }, size) =>
            BrowserWindow.getAllWindows()[0].setSize(size[0] - 8, size[1]),
          size,
        );
        await pause(80);
        await app.evaluate(
          ({ BrowserWindow }, size) =>
            BrowserWindow.getAllWindows()[0].setSize(...size),
          size,
        );
      }
      await page.mouse.up();
      assert.equal(Number(await xField.inputValue()), original);
    }
  }
  await openPanel(page);
  await page.getByLabel("미리보기 확대", { exact: true }).selectOption("fit");
  return true;
}
module.exports = {
  testBubbleViewport,
  testBubbleLayerTransforms,
  testBubbleBackgroundTransforms,
  selectBubbleSection,
};
