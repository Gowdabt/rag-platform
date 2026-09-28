const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("ragDesktop", {
  platform: process.platform,
});
