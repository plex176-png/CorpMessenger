// Безопасный мост: интерфейс может вызывать системные уведомления Electron.
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("corpNotify", function (count) {
  ipcRenderer.send("corp-notify", { text: count > 0 ? ("Непрочитанных сообщений: " + count) : "" });
});
