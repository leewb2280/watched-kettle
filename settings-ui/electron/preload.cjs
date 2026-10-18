const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("settings", {
  request: (method, args = {}) =>
    ipcRenderer.invoke("settings:request", method, args),
  file: (purpose, kind) => ipcRenderer.invoke("settings:file", purpose, kind),
  onEvent: (callback) => {
    const listener = (_event, value) => callback(value);
    ipcRenderer.on("settings:event", listener);
    return () => ipcRenderer.removeListener("settings:event", listener);
  },
  ready: () => ipcRenderer.invoke("settings:ready"),
  openLanguagePackFolder: () => ipcRenderer.invoke("settings:language-folder"),
});
