// КорпМессенджер — Electron-клиент. Electron 22 (Chromium 108) — последняя версия,
// поддерживающая Windows 7 SP1. Для Win7 запускать 32-битную (ia32) сборку.
const { app, BrowserWindow, Notification, ipcMain, Tray, Menu } = require("electron");
const path = require("path");
const fs = require("fs");

let win = null;
let tray = null;

// Настройки запуска: client/config.json (см. config.json.example)
//   startHidden     — запускать сразу свёрнутым в трей
//   minimizeToTray  — кнопка «свернуть» прячет окно в трей
//   closeToTray     — крестик закрывает в трей (выход через меню трея)
function loadCfg() {
  var cfg = { startHidden: false, minimizeToTray: true, closeToTray: true };
  try {
    var p = path.join(__dirname, "config.json");
    if (fs.existsSync(p)) {
      var j = JSON.parse(fs.readFileSync(p, "utf8"));
      for (var k in j) cfg[k] = j[k];
    }
  } catch (e) { /* повреждённый конфиг — используем значения по умолчанию */ }
  return cfg;
}
var CFG = loadCfg();

function createWindow() {
  win = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 720,
    minHeight: 520,
    title: "КорпМессенджер",
    autoHideMenuBar: true,
    show: !CFG.startHidden,          // настройка запуска: сразу скрыто/показано
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js")
    }
  });

  // Клиент берётся из сервера: адрес и порт указываются вручную на экране входа.
  const port = process.env.CORP_PORT || "5000";
  const host = process.env.CORP_HOST || "127.0.0.1";
  win.loadURL("http://" + host + ":" + port + "/?desktop=1");

  win.on("minimize", function () {
    if (CFG.minimizeToTray && tray) setTimeout(function () { win.hide(); }, 150);
  });

  win.on("close", function (e) {
    if (!app.isQuiting && CFG.closeToTray) {
      e.preventDefault();
      win.hide();
      if (tray) tray.displayBalloon && tray.displayBalloon({ content: "КорпМессенджер работает в трее." });
    }
  });
}

function trayMenu() {
  return Menu.buildFromTemplate([
    { label: "Показать окно", click: function () { win.show(); win.focus(); } },
    { label: "Свернуть в трей", click: function () { win.hide(); } },
    { type: "separator" },
    { label: "Перезагрузить интерфейс", click: function () { win.reload(); } },
    { type: "separator" },
    { label: "Выход", click: function () { app.isQuiting = true; app.quit(); } }
  ]);
}

app.on("ready", function () {
  createWindow();

  tray = new Tray(path.join(__dirname, "tray-icon.png"));
  tray.setToolTip("КорпМессенджер");
  tray.setContextMenu(trayMenu());
  tray.on("click", function () { win.isVisible() ? win.focus() : win.show(); });
  tray.on("double-click", function () { win.show(); win.focus(); });
});

app.on("window-all-closed", function () { app.quit(); });

// Уведомления из интерфейса (новый чат/сообщение) — системные, для Windows 7 совместимы.
ipcMain.on("corp-notify", function (event, data) {
  try {
    var n = new Notification({ title: "КорпМессенджер", body: String(data && data.text || "Новое сообщение") });
    n.on("click", function () { if (win) { win.show(); win.focus(); } });
    n.show();
    if (win && !win.isFocused() && win.flashFrame) win.flashFrame(true);
  } catch (e) { /* Win7 без Toast API — игнорируем, бейдж в заголовке виден */ }
});
