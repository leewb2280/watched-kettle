const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("settings", {
  request: (method, args = {}) =>
    ipcRenderer.invoke("settings:request", method, args),
  file: (purpose, kind, options) =>
    ipcRenderer.invoke("settings:file", purpose, kind, options),
  // Only files from the user's disk have a path; others are skipped here.
  dropImages: (files, kind, options) =>
    ipcRenderer.invoke(
      "settings:drop-import",
      Array.from(files)
        .map((file) => webUtils.getPathForFile(file))
        .filter(Boolean),
      kind,
      options,
    ),
  pasteImage: async (file, kind, options) =>
    ipcRenderer.invoke(
      "settings:paste-import",
      await file.arrayBuffer(),
      kind,
      options,
    ),
  onEvent: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("settings:event", listener);
    return () => ipcRenderer.removeListener("settings:event", listener);
  },
  ready: () => ipcRenderer.invoke("settings:ready"),
  openLanguagePackFolder: () => ipcRenderer.invoke("settings:language-folder"),
});
