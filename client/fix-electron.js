/*
 * КорпМессенджер — восстановление бинарника Electron.
 * Лечит ошибку: "Electron failed to install correctly, please delete node_modules/electron..."
 * Скачивает нужный архив Electron с зеркала npmmirror.com (или ELECTRON_MIRROR)
 * и распаковывает его в node_modules/electron/dist.
 * Запуск:  node fix-electron.js   (из папки client)
 */
"use strict";

var fs = require("fs");
var path = require("path");
var https = require("https");
var http = require("http");
var zlib = require("zlib");
var execSync = require("child_process").execSync;

// ---------- собственный распаковщик zip (без внешних утилит) ----------
function findEOCD(buf) {
  var min = Math.max(0, buf.length - 65558);
  for (var i = buf.length - 22; i >= min; i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) return i;
  }
  return -1;
}
function unzipSync(zipFile, targetDir) {
  var buf = fs.readFileSync(zipFile);
  var eocd = findEOCD(buf);
  if (eocd < 0) throw new Error("Некорректный zip-архив (нет end-of-central-directory)");
  var count = buf.readUInt16LE(eocd + 10);
  var off = buf.readUInt32LE(eocd + 16);
  fs.mkdirSync(targetDir, { recursive: true });
  for (var n = 0; n < count; n++) {
    if (buf.readUInt32LE(off) !== 0x02014b50) break;
    var method = buf.readUInt16LE(off + 10);
    var csize = buf.readUInt32LE(off + 20);
    var nameLen = buf.readUInt16LE(off + 28);
    var extraLen = buf.readUInt16LE(off + 30);
    var commentLen = buf.readUInt16LE(off + 32);
    var lho = buf.readUInt32LE(off + 42);
    var name = buf.slice(off + 46, off + 46 + nameLen).toString("utf8");
    off += 46 + nameLen + extraLen + commentLen;
    if (name.indexOf("..") !== -1 || /^[a-zA-Z]:/.test(name) || name.charAt(0) === "/") continue; // защита от path traversal
    var dest = path.join(targetDir, name);
    if (name.slice(-1) === "/") { fs.mkdirSync(dest, { recursive: true }); continue; }
    // локальный заголовок файла — своё имя/extra, данные идут после него
    var lNameLen = buf.readUInt16LE(lho + 26);
    var lExtraLen = buf.readUInt16LE(lho + 28);
    var dataStart = lho + 30 + lNameLen + lExtraLen;
    var data = buf.slice(dataStart, dataStart + csize);
    if (method === 0) {
      // stored
    } else if (method === 8) {
      data = zlib.inflateRawSync(data);
    } else {
      continue; // не поддерживаемый метод сжатия
    }
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, data);
  }
}

var electronPkg = require("./node_modules/electron/package.json");
var version = electronPkg.version; // напр. 22.3.27

// какая сборка нужна нашей ОС/архитектуре
var platform = process.platform;            // win32
var arch = process.arch;                    // x64 / ia32
if (arch === "x64") arch = "x64";
else if (arch === "ia32") arch = "x64";     // на 64-битной ОС ставим x64-сборку
var zipName = "electron-v" + version + "-" + platform + "-" + arch + ".zip";

var mirror = process.env.ELECTRON_MIRROR || "https://npmmirror.com/mirrors/electron/";
if (mirror[mirror.length - 1] !== "/") mirror += "/";
var url = mirror + version + "/" + zipName;

var distDir = path.join(__dirname, "node_modules", "electron", "dist");
var zipPath = path.join(__dirname, zipName);
var exeName = platform === "win32" ? "electron.exe" : "electron";

function log(m) { console.log("[fix-electron] " + m); }

function download(u, dest, redirects) {
  redirects = redirects || 0;
  if (redirects > 5) return Promise.reject(new Error("Слишком много редиректов"));
  return new Promise(function (resolve, reject) {
    var mod = u.indexOf("https:") === 0 ? https : http;
    log("Загружаю: " + u);
    mod.get(u, function (res) {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        return resolve(download(res.headers.location, dest, redirects + 1));
      }
      if (res.statusCode !== 200) {
        res.resume();
        return reject(new Error("HTTP " + res.statusCode + " для " + u));
      }
      var total = parseInt(res.headers["content-length"] || "0", 10);
      var got = 0, lastPct = -10;
      var out = fs.createWriteStream(dest);
      res.on("data", function (c) {
        got += c.length;
        if (total) {
          var pct = Math.floor(got / total * 100);
          if (pct - lastPct >= 10) { lastPct = pct; log("... " + pct + "% (" + Math.round(got / 1048576) + " МБ)"); }
        }
      });
      res.pipe(out);
      out.on("finish", function () { out.close(function () { resolve(dest); }); });
      out.on("error", reject);
    }).on("error", reject);
  });
}

function unzip(zipFile, targetDir) {
  // Собственный распаковщик: работает на любой Windows (7/10/11) без tar/powershell/unzip.
  unzipSync(zipFile, targetDir);
}

function writePathTxt() {
  fs.writeFileSync(path.join(__dirname, "node_modules", "electron", "path.txt"), exeName);
}

function main() {
  var exePath = path.join(distDir, exeName);
  if (fs.existsSync(exePath)) {
    log("Уже установлено: " + exePath);
    writePathTxt();
    return;
  }
  log("Электрон не установлен корректно (нет " + exeName + "). Версия из package.json: " + version);
  download(url, zipPath).then(function () {
    log("Архив получен: " + zipPath);
    unzip(zipPath, distDir);
    if (!fs.existsSync(exePath)) {
      // иногда архив содержит один корневой каталог
      var subs = fs.readdirSync(distDir);
      for (var i = 0; i < subs.length; i++) {
        var p = path.join(distDir, subs[i], exeName);
        if (fs.existsSync(p)) {
          var tmp = distDir + ".tmp";
          fs.rmSync(tmp, { recursive: true, force: true });
          fs.renameSync(path.join(distDir, subs[i]), tmp);
          fs.rmSync(distDir, { recursive: true, force: true });
          fs.renameSync(tmp, distDir);
          break;
        }
      }
    }
    if (!fs.existsSync(exePath)) throw new Error("После распаковки нет " + exeName);
    writePathTxt();
    fs.unlinkSync(zipPath);
    log("Готово! Теперь можно запускать: npm start");
  }).catch(function (err) {
    console.error("[fix-electron] ОШИБКА: " + err.message);
    console.error("");
    console.error("Что можно сделать:");
    console.error("  1) Другое зеркало:  set ELECTRON_MIRROR=https://registry.npmmirror.com/-/binary/electron/  и повторить node fix-electron.js");
    console.error("  2) Вручную: скачайте " + url);
    console.error("     распакуйте содержимое в  " + distDir);
    console.error("     создайте файл node_modules\\electron\\path.txt со строкой: " + exeName);
    console.error("  3) Без Electron: откройте в браузере адрес сервера (веб-версия клиента полностью функциональна).");
    process.exitCode = 1;
  });
}

main();
