const { contextBridge, ipcRenderer } = require("electron");
const methods = [
  "initial",
  "open",
  "history",
  "inspect",
  "diff",
  "run",
  "settings",
  "saveSettings",
  "issue",
  "openIssue",
];
contextBridge.exposeInMainWorld(
  "bugbot",
  Object.fromEntries(
    methods.map((name) => [
      name,
      (args = {}) => ipcRenderer.invoke("bugbot:" + name, args),
    ]),
  ),
);
