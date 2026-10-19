const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { renderer, assistant } = require("../electron/commands.generated.cjs");

test("native file and window commands cannot be sent by renderer", () => {
  for (const method of [
    "language.bootstrap",
    "language.open_folder",
    "file.import",
    "file.export",
    "file.pet.prepare",
    "file.pet.cancel",
    "window.state",
    "window.restore",
    "window.visibility",
  ]) {
    assert.equal(renderer.includes(method), false, method);
  }
  assert.ok(renderer.includes("navigation.ack"));
  assert.ok(renderer.includes("window.subscribe"));
});

test("assistant commands remain unavailable in pet-only", () => {
  for (const method of [
    "usage.snapshot",
    "activity.open",
    "integration.apply",
  ]) {
    assert.ok(assistant.includes(method));
    assert.ok(renderer.includes(method));
  }
  assert.equal(assistant.includes("pet.catalog"), false);
  assert.equal(new Set(renderer).size, renderer.length);
});

function rendererBridge() {
  const handlers = new Map();
  const electron = {
    app: { whenReady: () => ({ then() {} }), on() {}, setPath() {} },
    ipcMain: { handle: (name, callback) => handlers.set(name, callback) },
  };
  const directory = path.resolve(__dirname, "../electron");
  const context = {
    __dirname: directory,
    Buffer,
    setTimeout,
    clearTimeout,
    process: { env: {}, platform: process.platform },
    require: (name) =>
      name === "electron"
        ? electron
        : name.startsWith("./")
          ? require(path.join(directory, name))
          : require(name),
  };
  const main = fs.readFileSync(path.join(directory, "main.cjs"), "utf8");
  // Exercise the real IPC guard without starting Electron or native I/O.
  vm.runInNewContext(
    main +
      `
    window = { webContents: { mainFrame: { url: documentURL } } };
    ready = { edition: "pet-only" };
    request = async (method, args) => ({ method, args });
    globalThis.bridge = {
      event: { sender: window.webContents, senderFrame: window.webContents.mainFrame },
      edition: (value) => { ready.edition = value; }
    };
  `,
    context,
  );
  return { ...context.bridge, invoke: handlers.get("settings:request") };
}

test("the actual Electron IPC guard enforces exposure, edition and sender", async () => {
  const bridge = rendererBridge();
  for (const method of [
    "file.pet.prepare",
    "language.bootstrap",
    "language.open_folder",
    "file.import",
    "window.state",
    "usage.snapshot",
    "activity.open",
    "integration.apply",
    "unknown.method",
  ]) {
    await assert.rejects(
      bridge.invoke(bridge.event, method, {}),
      /허용되지 않은/,
    );
  }
  assert.equal(
    (await bridge.invoke(bridge.event, "pet.catalog", {})).method,
    "pet.catalog",
  );
  bridge.edition("pet-assistant");
  assert.equal(
    (await bridge.invoke(bridge.event, "usage.snapshot", {})).method,
    "usage.snapshot",
  );
  await assert.rejects(
    bridge.invoke(bridge.event, "pet.catalog", []),
    /허용되지 않은/,
  );
  await assert.rejects(
    bridge.invoke({ ...bridge.event, sender: {} }, "pet.catalog", {}),
    /허용되지 않은/,
  );
});

test("only repository links open in the default browser", () => {
  const { externalLinkAllowed } = require("../electron/external.cjs");
  for (const url of [
    "https://github.com/leewb2280/watched-kettle",
    "https://github.com/leewb2280/watched-kettle/releases/tag/v0.15.7",
    "https://github.com/leewb2280/watched-kettle/blob/main/LICENSE",
  ])
    assert.equal(externalLinkAllowed(url), true, url);
  for (const url of [
    "http://github.com/leewb2280/watched-kettle",
    "https://github.com/leewb2280/watched-kettle-evil",
    "https://github.com/other/watched-kettle",
    "https://github.com:8443/leewb2280/watched-kettle",
    "https://user@github.com/leewb2280/watched-kettle",
    "https://github.com.example/leewb2280/watched-kettle",
    "file:///C:/Windows/System32/cmd.exe",
    "javascript:alert(1)",
    "not a url",
  ])
    assert.equal(externalLinkAllowed(url), false, url);
});
