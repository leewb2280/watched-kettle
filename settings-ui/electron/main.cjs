const {
  app,
  BrowserWindow,
  ipcMain,
  nativeTheme,
  dialog,
  screen,
} = require("electron");
const { join } = require("node:path");
const { pathToFileURL } = require("node:url");
const { createConnection } = require("node:net");
const { randomUUID } = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const appearancePolicy = require("./appearance.cjs");

const pipe = process.env.WATCHED_KETTLE_SETTINGS_PIPE;
const token = process.env.WATCHED_KETTLE_SETTINGS_TOKEN;
delete process.env.WATCHED_KETTLE_SETTINGS_TOKEN;
if (process.env.WATCHED_KETTLE_SETTINGS_PROFILE)
  app.setPath("userData", process.env.WATCHED_KETTLE_SETTINGS_PROFILE);
let window,
  socket,
  ready,
  quitting = false,
  visible = false,
  buffer = Buffer.alloc(0);
let appearance = {
  theme: "system",
  material: "acrylic",
  lightOpacity: 60,
  darkOpacity: 36,
  reduceMotion: false,
};
let windowTimer, latestRoute;
const pending = new Map();
const allowed = new Set([
  "settings.snapshot",
  "settings.set",
  "pet.catalog",
  "pet.preview",
  "pet.select",
  "pet.import.commit",
  "pet.import.cancel",
  "pet.catalog.save",
  "pet.trash.list",
  "pet.trash.move",
  "pet.trash.restore",
  "pet.trash.delete",
  "pet.trash.empty",
  "pet.trash.batch.start",
  "pet.trash.batch.status",
  "pet.trash.batch.cancel",
  "pet.action",
  "bubble.editor",
  "bubble.render",
  "bubble.save",
  "bubble.reset",
  "element.delete",
  "update.check",
  "update.download",
  "update.cancel",
  "update.open",
  "app.quit",
  "usage.snapshot",
  "usage.set",
  "usage.query",
  "usage.select",
  "usage.move",
  "usage.action",
  "usage.widget_preview",
  "activity.snapshot",
  "activity.clear",
  "activity.open",
  "integration.snapshot",
  "integration.preview",
  "integration.apply",
  "integration.set",
  "navigation.ack",
  "window.subscribe",
]);
const documentURL = pathToFileURL(join(__dirname, "../dist/index.html")).href;

function sendEvent(event, data) {
  if (window && !window.isDestroyed())
    window.webContents.send("settings:event", { event, data });
}
function request(method, args = {}) {
  if (!ready || !socket || socket.destroyed)
    return Promise.reject(
      new Error("설정 연결이 끊겼습니다. 창을 닫고 다시 열어주세요."),
    );
  if (pending.size >= 32)
    return Promise.reject(new Error("진행 중인 요청이 너무 많습니다."));
  const id = randomUUID();
  const body = JSON.stringify({ id, method, args }) + "\n";
  if (Buffer.byteLength(body) > 4 * 1024 * 1024)
    return Promise.reject(new Error("요청이 너무 큽니다."));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(
        new Error(
          "응답을 기다리는 시간이 길어졌습니다. 적용 여부를 새로 확인해 주세요.",
        ),
      );
    }, 15000);
    pending.set(id, { resolve, reject, timer });
    socket.write(body);
  });
}
function validSender(event) {
  if (
    !window ||
    event.sender !== window.webContents ||
    event.senderFrame !== window.webContents.mainFrame ||
    event.senderFrame.url.split("#")[0] !== documentURL
  )
    throw new Error("허용되지 않은 화면입니다.");
}
function effectiveAppearance() {
  return appearancePolicy.effectiveAppearance(
    appearance,
    nativeTheme,
    process.platform,
    os.release(),
  );
}
function applyAppearance() {
  if (!window || window.isDestroyed()) return;
  nativeTheme.themeSource = appearance.theme;
  const value = effectiveAppearance();
  try {
    window.setBackgroundMaterial(value.effectiveMaterial);
  } catch {
    value.effectiveMaterial = "none";
  }
  window.setTitleBarOverlay({
    color: "#00000000",
    symbolColor: value.effectiveTheme === "dark" ? "#e9e5df" : "#303a40",
    height: 47,
  });
  sendEvent("appearance", value);
  return value;
}
ipcMain.handle("settings:ready", (event) => {
  validSender(event);
  return {
    connected: !!ready,
    edition: ready?.edition,
    route: latestRoute,
    appearance: applyAppearance(),
  };
});
ipcMain.handle("settings:request", async (event, method, args) => {
  validSender(event);
  if (
    !allowed.has(method) ||
    (ready?.edition !== "pet-assistant" &&
      /^(usage|activity|integration)\./.test(method)) ||
    !args ||
    typeof args !== "object" ||
    Array.isArray(args)
  )
    throw new Error("허용되지 않은 명령입니다.");
  const result = await request(method, args);
  const settings = method === "settings.snapshot" ? result : result?.snapshot;
  if (settings?.appearance) {
    appearance = settings.appearance;
    applyAppearance();
  }
  return result;
});
ipcMain.handle("settings:file", async (event, purpose, kind) => {
  validSender(event);
  const elementKinds = ["pattern", "ornament", "photo", "frame", "sticker"];
  if (purpose === "pet") {
    // Discard the previous preparation even if the new picker is cancelled.
    await request("file.pet.cancel");
    const selected = await dialog.showOpenDialog(window, {
      title: "펫 스프라이트 선택",
      properties: ["openFile"],
      filters: [{ name: "펫 스프라이트", extensions: ["png", "webp"] }],
    });
    if (selected.canceled) return { cancelled: true };
    return request("file.pet.prepare", { path: selected.filePaths[0] });
  }
  if (purpose === "import" && elementKinds.includes(kind)) {
    const selected = await dialog.showOpenDialog(window, {
      title: "말풍선 요소 이미지 선택",
      properties: ["openFile"],
      filters: [{ name: "이미지", extensions: ["png", "webp", "jpg", "jpeg"] }],
    });
    if (selected.canceled) return { cancelled: true };
    return request("file.import", { path: selected.filePaths[0], kind });
  }
  if (purpose === "export" && ready?.edition === "pet-assistant") {
    const selected = await dialog.showSaveDialog(window, {
      title: "진단 내보내기",
      defaultPath: "WatchedKettle-diagnostics.zip",
      filters: [{ name: "ZIP", extensions: ["zip"] }],
    });
    if (selected.canceled) return { cancelled: true };
    return request("file.export", { path: selected.filePath });
  }
  throw new Error("허용되지 않은 파일 작업입니다.");
});

function boundsState() {
  return { ...window.getNormalBounds(), maximized: window.isMaximized() };
}
function scheduleWindowSave() {
  clearTimeout(windowTimer);
  windowTimer = setTimeout(
    () => request("window.state", { state: boundsState() }).catch(() => {}),
    350,
  );
}
async function createWindow() {
  const snapshot = await request("settings.snapshot");
  appearance = snapshot.appearance;
  nativeTheme.themeSource = appearance.theme;
  const saved = await request("window.restore");
  const size = {
    width: Math.min(1240, screen.getPrimaryDisplay().workArea.width),
    height: Math.min(860, screen.getPrimaryDisplay().workArea.height),
  };
  if (Number.isFinite(saved.width) && Number.isFinite(saved.height)) {
    size.width = Math.max(720, Math.min(saved.width, 2500));
    size.height = Math.max(500, Math.min(saved.height, 1800));
  }
  const bounds = { ...size };
  if (Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
    const display = screen.getDisplayMatching({
      x: saved.x,
      y: saved.y,
      ...size,
    }).workArea;
    bounds.width = Math.min(size.width, display.width);
    bounds.height = Math.min(size.height, display.height);
    bounds.x = Math.max(
      display.x,
      Math.min(saved.x, display.x + display.width - bounds.width),
    );
    bounds.y = Math.max(
      display.y,
      Math.min(saved.y, display.y + display.height - bounds.height),
    );
  }
  window = new BrowserWindow({
    ...bounds,
    minWidth: 640,
    minHeight: 460,
    show: false,
    title: "Watched Kettle · 설정",
    backgroundColor: "#00000000",
    backgroundMaterial: "acrylic",
    titleBarStyle: "hidden",
    titleBarOverlay: { color: "#00000000", symbolColor: "#e9e5df", height: 47 },
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  window.webContents.session.setPermissionRequestHandler(
    (_wc, _permission, callback) => callback(false),
  );
  window.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      window.hide();
    }
  });
  window.on("hide", () => {
    visible = false;
    sendEvent("visibility", false);
    request("window.visibility", { visible: false }).catch(() => {});
  });
  window.on("show", () => {
    visible = true;
    sendEvent("visibility", true);
    request("window.visibility", { visible: true }).catch(() => {});
  });
  window.on("resize", scheduleWindowSave);
  window.on("move", scheduleWindowSave);
  window.webContents.on("render-process-gone", () => {
    quitting = true;
    app.quit();
  });
  await window.loadFile(join(__dirname, "../dist/index.html"));
  applyAppearance();
  if (saved.maximized) window.maximize();
  window.show();
  window.focus();
}
// The pet grants this process the foreground before it asks (host.py). If
// Windows still refuses, a brief always-on-top toggle at least raises the
// window above the others instead of only flashing its taskbar button.
function bringToFront() {
  if (window.isMinimized()) window.restore();
  window.show();
  window.moveTop();
  window.focus();
  if (!window.isFocused()) {
    window.setAlwaysOnTop(true);
    window.setAlwaysOnTop(false);
  }
}
function received(message) {
  if (message.event === "ready") {
    let edition;
    try {
      edition = JSON.parse(
        fs.readFileSync(join(__dirname, "../edition.json"), "utf8"),
      ).edition;
    } catch {
      edition = "pet-assistant";
    }
    if (
      message.data.version !== 1 ||
      (edition === "pet-only" && message.data.edition !== edition)
    ) {
      quitting = true;
      app.exit(2);
      return;
    }
    ready = message.data;
    latestRoute = ready.route;
    createWindow().catch((error) => {
      console.error("Settings window startup failed:", error.message);
      quitting = true;
      app.exit(2);
    });
    return;
  }
  if (message.event === "navigate") {
    latestRoute = message.data;
    if (window && !window.isDestroyed()) {
      bringToFront();
      sendEvent("navigate", latestRoute);
    }
    return;
  }
  if (message.event === "hide") {
    window?.hide();
    return;
  }
  if (message.event === "quit") {
    quitting = true;
    app.quit();
    return;
  }
  if (message.event) {
    sendEvent(message.event, message.data);
    return;
  }
  const entry = pending.get(message.id);
  if (entry) {
    clearTimeout(entry.timer);
    pending.delete(message.id);
    message.ok
      ? entry.resolve(message.result)
      : entry.reject(
          new Error(`${message.error.code}: ${message.error.message}`),
        );
  }
}
app.whenReady().then(() => {
  if (!pipe || !token) {
    dialog.showErrorBox(
      "Watched Kettle",
      "펫 앱의 트레이에서 설정을 열어주세요.",
    );
    app.exit(1);
    return;
  }
  if (!app.requestSingleInstanceLock()) {
    app.quit();
    return;
  }
  app.on("second-instance", () => {
    if (window && !window.isDestroyed()) bringToFront();
  });
  socket = createConnection(pipe);
  const startupTimer = setTimeout(() => {
    if (!ready) app.exit(2);
  }, 10000);
  socket.on("connect", () =>
    socket.write(JSON.stringify({ version: 1, token }) + "\n"),
  );
  socket.on("data", (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    if (buffer.length > 4 * 1024 * 1024) {
      app.exit(2);
      return;
    }
    let end;
    while ((end = buffer.indexOf(10)) >= 0) {
      const line = buffer.subarray(0, end);
      buffer = buffer.subarray(end + 1);
      try {
        received(JSON.parse(line));
      } catch {
        app.exit(2);
        return;
      }
      if (ready) clearTimeout(startupTimer);
    }
  });
  socket.on("error", () => {
    quitting = true;
    app.quit();
  });
  socket.on("close", () => {
    for (const p of pending.values()) {
      clearTimeout(p.timer);
      p.reject(new Error("런타임 연결이 종료되었습니다."));
    }
    pending.clear();
    quitting = true;
    app.quit();
  });
  nativeTheme.on("updated", () => applyAppearance());
});
app.on("before-quit", () => {
  quitting = true;
  clearTimeout(windowTimer);
});
app.on("window-all-closed", () => {
  if (quitting) app.quit();
});
