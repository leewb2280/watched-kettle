const {
  app,
  BrowserWindow,
  ipcMain,
  nativeTheme,
  dialog,
  screen,
  shell,
} = require("electron");
const { join } = require("node:path");
const { pathToFileURL } = require("node:url");
const { createConnection } = require("node:net");
const { randomUUID } = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const appearancePolicy = require("./appearance.cjs");
const { externalLinkAllowed } = require("./external.cjs");
const { t, setCatalog } = require("../localization.cjs");
let localization;

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
const commandExposure = require("./commands.generated.cjs");
const allowed = new Set(commandExposure.renderer);
const assistantCommands = new Set(commandExposure.assistant);
const documentURL = pathToFileURL(join(__dirname, "../dist/index.html")).href;

function sendEvent(event, data) {
  if (window && !window.isDestroyed())
    window.webContents.send("settings:event", { event, data });
}
function request(method, args = {}) {
  if (!ready || !socket || socket.destroyed)
    return Promise.reject(new Error(t("message.1262")));
  if (pending.size >= 32) return Promise.reject(new Error(t("message.1263")));
  const id = randomUUID();
  const body = JSON.stringify({ id, method, args }) + "\n";
  if (Buffer.byteLength(body) > 4 * 1024 * 1024)
    return Promise.reject(new Error(t("message.1264")));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(t("message.1265")));
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
    throw new Error(t("message.1266"));
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
    localization,
    edition: ready?.edition,
    route: latestRoute,
    appearance: applyAppearance(),
  };
});
ipcMain.handle("settings:request", async (event, method, args) => {
  validSender(event);
  if (
    !allowed.has(method) ||
    (ready?.edition !== "pet-assistant" && assistantCommands.has(method)) ||
    !args ||
    typeof args !== "object" ||
    Array.isArray(args)
  )
    throw new Error(t("message.1267"));
  const result = await request(method, args);
  const settings = method === "settings.snapshot" ? result : result?.snapshot;
  if (settings?.appearance) {
    appearance = settings.appearance;
    applyAppearance();
  }
  return result;
});
ipcMain.handle("settings:language-folder", (event) => {
  validSender(event);
  return request("language.open_folder");
});
ipcMain.handle("settings:file", async (event, purpose, kind) => {
  validSender(event);
  const elementKinds = ["pattern", "ornament", "photo", "frame", "sticker"];
  if (purpose === "pet" || purpose === "pet-folder") {
    // Discard the previous preparation even if the new picker is cancelled.
    await request("file.pet.cancel");
    const selected = await dialog.showOpenDialog(window, {
      title: t("message.1268"),
      properties: [purpose === "pet-folder" ? "openDirectory" : "openFile"],
      ...(purpose === "pet"
        ? {
            filters: [
              { name: t("message.1269"), extensions: ["png", "webp", "zip"] },
            ],
          }
        : {}),
    });
    if (selected.canceled) return { cancelled: true };
    return request("file.pet.start", { path: selected.filePaths[0] });
  }
  if (purpose === "import" && elementKinds.includes(kind)) {
    const selected = await dialog.showOpenDialog(window, {
      title: t("message.1270"),
      properties: ["openFile"],
      filters: [
        { name: t("message.1271"), extensions: ["png", "webp", "jpg", "jpeg"] },
      ],
    });
    if (selected.canceled) return { cancelled: true };
    return request("file.import", { path: selected.filePaths[0], kind });
  }
  if (purpose === "export" && ready?.edition === "pet-assistant") {
    const selected = await dialog.showSaveDialog(window, {
      title: t("message.0676"),
      defaultPath: "WatchedKettle-diagnostics.zip",
      filters: [{ name: "ZIP", extensions: ["zip"] }],
    });
    if (selected.canceled) return { cancelled: true };
    return request("file.export", { path: selected.filePath });
  }
  throw new Error(t("message.1272"));
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
    title: t("message.1273"),
    icon: process.env.WATCHED_KETTLE_SETTINGS_ICON || undefined,
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
  window.webContents.setWindowOpenHandler(({ url }) => {
    // Only the About page's repository links leave for the default browser.
    if (externalLinkAllowed(url)) shell.openExternal(url).catch(() => {});
    return { action: "deny" };
  });
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
async function received(message) {
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
    localization = await request("language.bootstrap");
    setCatalog(localization);
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
    dialog.showErrorBox("Watched Kettle", t("message.1274"));
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
        received(JSON.parse(line)).catch(() => {
          quitting = true;
          app.exit(2);
        });
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
      p.reject(new Error(t("message.1275")));
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
