/* КорпМессенджер — веб/Electron клиент. Совместим с Chromium 49+ (Electron 22 / Win7). */
(function () {
"use strict";

var state = {
  base: "", token: "", me: null, tab: "chats",
  dialogs: [], contacts: [], directory: [], groups: [], users: [],
  chat: null, messages: [], sock: null, pollTimer: null,
  lastId: 0, seenIds: {}, notifyOn: true
};

var EMOJI_LIST = ["😀","😁","😂","🤣","😊","🙂","😉","😍","😘","😜",
"🤔","😐","😴","😷","🤒","😎","🥳","😢","😭","😡",
"👍","👎","👏","🙏","💪","✍","👀","🧠","❤","💔",
"🔥","⭐","🎉","🎁","☕","🍕","🚀","⏰","📌","📎",
"✅","❌","❓","❗","💬","📞","💻","🖥","📊","🗂"];

var EMOJI_MAP = [
  [":D","😂"], [":-D","😂"], [":)","🙂"], [":-)","🙂"], [":(","🙁"], [":-(","🙁"],
  [";)","😉"], [";-)","😉"], [":p","😜"], [":P","😜"], ["<3","❤"], [":|","😐"],
  ["+1","👍"], ["-1","👎"], ["100","💯"], [":?","🤔"], ["8)","😎"], [">:(","😡"],
  ["o_O","🤔"], ["zZ","😴"], ["@","📎"]
];

// ---------- утилиты ----------
function $(sel) { return document.querySelector(sel); }
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function showErr(msg) {
  var b = $("#err-banner");
  if (!b) return;
  b.textContent = "Ошибка интерфейса: " + msg;
  b.classList.remove("hidden");
  setTimeout(function () { b.classList.add("hidden"); }, 8000);
}
window.onerror = function (m, src, line) { showErr(m + " (" + line + ")"); };

function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

function api(path, opts) {
  opts = opts || {};
  opts.headers = opts.headers || {};
  if (state.token) opts.headers["Authorization"] = "Bearer " + state.token;
  return fetch(state.base + path, opts).then(function (r) {
    if (r.status === 401 && state.token) { doLogout(false); throw new Error("Сессия истекла"); }
    return r.json().then(function (j) {
      if (!r.ok) throw new Error(j && j.error ? j.error : "HTTP " + r.status);
      return j;
    });
  });
}

function fmtSize(b) {
  if (!b) return "0 Б";
  var u = ["Б", "КБ", "МБ", "ГБ"], i = 0;
  while (b >= 1024 && i < 3) { b /= 1024; i++; }
  return b.toFixed(i ? 1 : 0) + " " + u[i];
}
function fmtTime(ts) {
  var d = new Date(ts * 1000);
  var p = function (n) { return n < 10 ? "0" + n : "" + n; };
  return p(d.getHours()) + ":" + p(d.getMinutes());
}

function statusDot(st) {
  if (st === "online") return '<span class="dot dot-on" title="В сети"></span>';
  if (st === "away") return '<span class="dot dot-away" title="Отошёл"></span>';
  return '<span class="dot dot-off" title="Не в сети"></span>';
}

function renderEmojiInto(el, text) {
  el.textContent = text; // сначала безопасно текст, затем замена паттернов
  var t = el.textContent;
  for (var i = 0; i < EMOJI_MAP.length; i++) {
    t = t.split(EMOJI_MAP[i][0]).join(EMOJI_MAP[i][1]);
  }
  el.textContent = t;
}

function bindClick(root, sel, handler, label) {
  var el = root ? root.querySelector(sel) : null;
  if (!el) { showErr((label || sel) + " не найден (Ctrl+Shift+R — перезагрузить)"); return; }
  el.onclick = handler;
}

// ---------- сервер: адрес и порт вручную ----------
function detectBase() {
  if (location.protocol.indexOf("http") === 0) return location.origin;
  var h = lsGet("srv_host") || "127.0.0.1", p = lsGet("srv_port") || "5000";
  return "http://" + h + ":" + p;
}
function saveServerAddr() {
  var h = $("#srv-host").value.trim() || "127.0.0.1";
  var p = $("#srv-port").value.trim() || "5000";
  lsSet("srv_host", h); lsSet("srv_port", p);
  state.base = "http://" + h + ":" + p;
}

// ---------- авторизация ----------
function showLogin() {
  $("#login-screen").classList.remove("hidden");
  $("#main-screen").classList.add("hidden");
  $("#srv-host").value = lsGet("srv_host") || ((location.hostname) || "127.0.0.1");
  $("#srv-port").value = lsGet("srv_port") || (location.port || "5000");
}
function doLogout(callApi) {
  if (callApi !== false && state.token) {
    api("/api/logout", { method: "POST" })["catch"](function () {});
  }
  state.token = ""; state.me = null;
  lsSet("token", "");
  if (state.sock) { try { state.sock.close(); } catch (e) {} state.sock = null; }
  if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  showLogin();
}

function initLogin() {
  $("#btn-login").onclick = function () {
    saveServerAddr();
    $("#login-msg").textContent = "Подключение…";
    api("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("#login-user").value.trim(), password: $("#login-pass").value })
    }).then(function (j) {
      state.token = j.token; lsSet("token", j.token); state.me = j.user;
      startApp();
    })["catch"](function (e) { $("#login-msg").textContent = e.message; });
  };
  $("#btn-register").onclick = function () {
    saveServerAddr();
    var u = $("#login-user").value.trim(), p = $("#login-pass").value;
    if (!u || !p) { $("#login-msg").textContent = "Заполните логин и пароль"; return; }
    api("/api/register", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: u, password: p, display_name: u })
    }).then(function () { $("#login-msg").textContent = "Аккаунт создан. Войдите."; })
      ["catch"](function (e) { $("#login-msg").textContent = e.message; });
  };
  $("#login-pass").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") $("#btn-login").click();
  });
}

// ---------- приложение ----------
function startApp() {
  $("#login-screen").classList.add("hidden");
  $("#main-screen").classList.remove("hidden");
  $("#me-name").textContent = state.me.display_name || state.me.username;
  $("#me-avatar").textContent = (state.me.display_name || state.me.username || "?").charAt(0).toUpperCase();
  if (state.me.role === "admin") {
    var a = document.querySelector(".admin-only");
    if (a) a.classList.remove("hidden");
  }
  connectSocket();
  bindTabs();
  refreshAll();
  if (!state.pollTimer) {
    state.pollTimer = setInterval(function () { refreshDialogs(); if (state.chat) loadMessages(true); }, 4000);
  }
}

function bindTabs() {
  var tabs = document.querySelectorAll(".tab");
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].onclick = function () {
      var t = this.getAttribute("data-tab");
      if (!t) return;
      switchTab(t);
    };
  }
}

// Переключение вкладки. Админка открывается В ОСНОВНОМ ОКНЕ (правая панель),
// а не в отдельном окне/модалке.
function switchTab(t) {
  state.tab = t;
  var all = document.querySelectorAll(".tab");
  for (var k = 0; k < all.length; k++) all[k].classList.remove("active");
  var bt = document.querySelector('.tab[data-tab="' + t + '"]');
  if (bt) bt.classList.add("active");
  renderSide();
  var empty = $("#chat-empty"), view = $("#chat-view");
  if (t === "admin") {
    if (empty) empty.classList.add("hidden");
    if (view) view.classList.add("hidden");
    renderAdminMain();
  } else {
    if (state.chat) {
      if (empty) empty.classList.add("hidden");
      if (view) view.classList.remove("hidden");
    } else {
      if (empty) empty.classList.remove("hidden");
      if (view) view.classList.add("hidden");
    }
  }
}

// ---------- админка в основном окне ----------
function renderAdminMain() {
  var view = $("#chat-view"), empty = $("#chat-empty");
  if (!view || !empty) return;
  empty.classList.add("hidden");
  view.classList.remove("hidden");
  $("#chat-title").textContent = "Администрирование";
  var box = $("#msgs-box");
  box.innerHTML = '<div id="admin-main" class="pad"><p class="muted">Загрузка админпанели…</p></div>';
  // отключаем композер, чтобы не отправлять сообщения «в админку»
  setComposerEnabled(false);
  Promise.all([
    api("/api/admin/stats"), api("/api/admin/users"), api("/api/admin/groups"), api("/api/admin/files")
  ]).then(function (res) {
    var el = document.getElementById("admin-main");
    if (!el) return;
    el.innerHTML = buildAdminHtml(res[0], res[1], res[2], res[3]);
    wireAdmin(el);
  })["catch"](function (e) {
    var el = document.getElementById("admin-main");
    if (el) el.innerHTML = '<p class="muted pad">Ошибка загрузки: ' + esc(e.message) + "</p>";
  });
}

function setComposerEnabled(on) {
  var inp = $("#msg-input"), send = $("#send"), att = $("#attach-btn"), em = $("#emoji-btn");
  if (inp) inp.disabled = !on;
  if (send) send.disabled = !on;
  if (att) att.style.visibility = on ? "" : "hidden";
  if (em) em.style.visibility = on ? "" : "hidden";
  if (!on && $("#emoji-panel")) $("#emoji-panel").classList.add("hidden");
}

function buildAdminHtml(st, users, groups, files) {
  var html = "<h3>Статистика</h3><div class='stats'>" +
    "Пользователей: <b>" + st.users + "</b> (активных " + st.active_users + ", в сети " + st.online + ")<br>" +
    "Групп: <b>" + st.groups + "</b> · Сообщений: <b>" + st.messages + "</b><br>" +
    "Файлов: <b>" + st.files_count + "</b> · Хранилище: <b>" + fmtSize(st.storage_bytes) + "</b></div>";

  html += "<h3>Сотрудники</h3><div class='form-inline'>" +
    "<input id='nu-name' placeholder='Отображаемое имя'><input id='nu-login' placeholder='Логин'>" +
    "<input id='nu-pass' placeholder='Пароль' type='password'><button class='primary sm' id='nu-add'>Добавить</button></div>" +
    "<table class='atable'><tr><th>Имя</th><th>Логин</th><th>Роль</th><th>Статус</th><th></th></tr>";
  for (var i = 0; i < users.length; i++) {
    var uu = users[i];
    var blocked = !uu.is_active;
    html += "<tr><td>" + esc(uu.display_name || "") + "</td><td>" + esc(uu.username) + "</td>" +
      "<td>" + (uu.role === "admin" ? "админ" : "сотр.") + "</td>" +
      "<td>" + (blocked ? "заблокирован" : uu.status === "online" ? "в сети" : uu.status === "away" ? "отошёл" : "не в сети") + "</td>" +
      "<td class='row-actions'>" +
      "<button class='ghost sm au-role' data-uid='" + uu.id + "'>" + (uu.role !== "admin" ? "→ админ" : "→ сотр.") + "</button> " +
      "<button class='ghost sm au-block' data-uid='" + uu.id + "'>" + (blocked ? "Разблок." : "Блок.") + "</button> " +
      (uu.id !== state.me.id ? "<button class='danger sm au-del' data-uid='" + uu.id + "'>Удалить</button>" : "") +
      "</td></tr>";
  }
  html += "</table>";

  html += "<h3>Группы</h3><table class='atable'><tr><th>Название</th><th>Участников</th><th>Владелец</th><th></th></tr>";
  for (var g = 0; g < groups.length; g++) {
    var gg = groups[g];
    html += "<tr><td>" + esc(gg.name) + "</td><td>" + gg.members + "</td><td>" + esc(gg.owner_name || "") + "</td>" +
      "<td class='row-actions'><button class='ghost sm ag-manage' data-gid='" + gg.id + "'>Управление</button> " +
      "<button class='danger sm ag-del' data-gid='" + gg.id + "'>Удалить</button></td></tr>";
  }
  html += "</table>";

  html += "<h3>Модерация сообщений</h3><div class='form-inline'><button class='ghost sm' id='load-msgs'>Показать последние 50</button></div><div id='msgs-box-admin'></div>";

  html += "<h3>Файлы</h3><table class='atable'><tr><th>Имя</th><th>Размер</th><th>Автор</th><th></th></tr>";
  for (var f = 0; f < files.length; f++) {
    var ff = files[f];
    html += "<tr><td>" + esc(ff.filename) + "</td><td>" + fmtSize(ff.size) + "</td><td>" + esc(ff.uploader || "") + "</td>" +
      "<td><button class='danger sm af-del' data-fid='" + ff.id + "'>Удалить</button></td></tr>";
  }
  html += "</table>";
  return html;
}

function wireAdmin(root) {
  bindClick(root, "#nu-add", function () {
    var nm = root.querySelector("#nu-name").value.trim(), lg = root.querySelector("#nu-login").value.trim(), pw = root.querySelector("#nu-pass").value;
    if (!nm || !lg || !pw) { showErr("Заполните имя, логин и пароль"); return; }
    api("/api/admin/users", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: nm, username: lg, password: pw })
    }).then(function () { renderAdminMain(); })["catch"](function (e) { showErr(e.message); });
  }, "#nu-add");

  var roleBtns = root.querySelectorAll(".au-role");
  for (var i = 0; i < roleBtns.length; i++) roleBtns[i].onclick = function () {
    var uid = parseInt(this.getAttribute("data-uid"), 10);
    api("/api/admin/users/" + uid, { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ toggle_role: true })
    }).then(function () { renderAdminMain(); })["catch"](function (e) { showErr(e.message); });
  };
  var blockBtns = root.querySelectorAll(".au-block");
  for (var j = 0; j < blockBtns.length; j++) blockBtns[j].onclick = function () {
    var uid = parseInt(this.getAttribute("data-uid"), 10);
    api("/api/admin/users/" + uid, { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ toggle_block: true })
    }).then(function () { renderAdminMain(); })["catch"](function (e) { showErr(e.message); });
  };
  var delBtns = root.querySelectorAll(".au-del");
  for (var d = 0; d < delBtns.length; d++) delBtns[d].onclick = function () {
    var uid = parseInt(this.getAttribute("data-uid"), 10);
    if (!confirm("Удалить пользователя и все его сообщения?")) return;
    api("/api/admin/users/" + uid, { method: "DELETE" }).then(function () { renderAdminMain(); refreshDialogs(); })["catch"](function (e) { showErr(e.message); });
  };

  var gmBtns = root.querySelectorAll(".ag-manage");
  for (var m = 0; m < gmBtns.length; m++) gmBtns[m].onclick = function () {
    openGroupManageModal(parseInt(this.getAttribute("data-gid"), 10));
  };
  var gdBtns = root.querySelectorAll(".ag-del");
  for (var q = 0; q < gdBtns.length; q++) gdBtns[q].onclick = function () {
    var gid = parseInt(this.getAttribute("data-gid"), 10);
    if (!confirm("Удалить группу вместе с историей?")) return;
    api("/api/admin/groups/" + gid, { method: "DELETE" }).then(function () { renderAdminMain(); refreshDialogs(); })["catch"](function (e) { showErr(e.message); });
  };

  var fmBtns = root.querySelectorAll(".af-del");
  for (var z = 0; z < fmBtns.length; z++) fmBtns[z].onclick = function () {
    var fid = parseInt(this.getAttribute("data-fid"), 10);
    if (!confirm("Удалить файл из хранилища?")) return;
    api("/api/admin/files/" + fid, { method: "DELETE" }).then(function () { renderAdminMain(); })["catch"](function (e) { showErr(e.message); });
  };

  bindClick(root, "#load-msgs", function () { loadAdminMessages(root); }, "#load-msgs");
}

function loadAdminMessages(root) {
  api("/api/admin/messages?limit=50").then(function (ms) {
    var box = root.querySelector("#msgs-box-admin");
    if (!box) return;
    var html = "<table class='atable'><tr><th>ID</th><th>От</th><th>Куда</th><th>Текст</th><th></th></tr>";
    for (var i = 0; i < ms.length; i++) {
      var mm = ms[i];
      html += "<tr><td>" + mm.id + "</td><td>" + esc(mm.sender_name || "") + "</td>" +
        "<td>" + (mm.chat_type === "group" ? "гр." + mm.group_id : "ЛС") + "</td>" +
        "<td>" + esc(String(mm.text || "").slice(0, 80)) + "</td>" +
        "<td><button class='danger sm am-del' data-mid='" + mm.id + "'>🗑</button></td></tr>";
    }
    html += "</table>";
    box.innerHTML = html;
    var ds = box.querySelectorAll(".am-del");
    for (var j = 0; j < ds.length; j++) ds[j].onclick = function () {
      var mid = parseInt(this.getAttribute("data-mid"), 10);
      api("/api/messages/" + mid, { method: "DELETE" }).then(function () {
        loadAdminMessages(root); refreshDialogs();
      })["catch"](function (e) { showErr(e.message); });
    };
  })["catch"](function (e) { showErr(e.message); });
}

function refreshAll() {
  refreshDialogs();
  refreshContacts();
  api("/api/users").then(function (us) { state.users = us; renderSide(); })["catch"](function () {});
}

function refreshDialogs() {
  return api("/api/dialogs").then(function (d) { state.dialogs = d; renderSide(); updateBadge(); })["catch"](function () {});
}

function refreshContacts() {
  return api("/api/contacts").then(function (j) {
    state.contacts = j.contacts || []; state.directory = j.directory || [];
    renderSide();
  })["catch"](function () {});
}

// ---------- уведомления: бейджи, заголовок, анимация ----------
function updateBadge() {
  var total = 0;
  for (var i = 0; i < state.dialogs.length; i++) total += (state.dialogs[i].unread || 0);
  document.title = (total > 0 ? "(" + total + ") " : "") + "КорпМессенджер";
  // Системное уведомление Electron — ТОЛЬКО о новых входящих сообщениях (см. pingIncoming),
  // а не о каждом обновлении счётчика (раньше это вызывало «постоянные» уведомления).
  return total;
}

// Дедупликация и порождение уведомлений: учитываем только сообщения с id больше
// последнего виденного и которых ещё не было в seenIds (WS-эхо + опрос могут
// принести одно и то же сообщение дважды).
function noteMessage(m, fromPoll) {
  if (!m || typeof m.id !== "number") return false;
  var fresh = m.id > state.lastId && !state.seenIds[m.id];
  if (m.id > state.lastId) state.lastId = m.id;
  state.seenIds[m.id] = 1;
  if (fresh && !fromPoll && m.sender_id !== state.me.id) {
    // новое входящее — уведомляем один раз
    pingIncoming(m);
  }
  return fresh;
}

function desktopNotify(text) {
  if (!state.notifyOn) return;
  if (window.corpNotify) { try { window.corpNotify(text); } catch (e) {} }
}

// ---------- боковая панель ----------
function renderSide() {
  var body = $("#side-body");
  if (!body) return;
  if (state.tab === "chats") renderChats(body);
  else if (state.tab === "directory") renderDirectory(body);
  else if (state.tab === "groups") renderGroupsTab(body);
  else if (state.tab === "admin") renderAdmin(body);
}

function chatRow(d) {
  var unreadHtml = d.unread > 0
    ? '<span class="badge unread-anim">' + (d.unread > 99 ? "99+" : d.unread) + '</span>' : "";
  var dot = d.type === "dm" ? statusDot(d.status || "offline") : "";
  var sub = d.last_text ? esc(String(d.last_text)).slice(0, 60) : (d.type === "group" ? "Группа" : "Нет сообщений");
  // В названии чата показываем количество непрочитанных; участников в название не выводим.
  var title = esc(d.name) + (d.unread > 0 ? ' <span class="title-count">(' + (d.unread > 99 ? "99+" : d.unread) + ')</span>' : "");
  return '<div class="chat-item' + (d.unread > 0 ? " has-unread" : "") + '" data-type="' + d.type + '" data-id="' + d.id + '">' +
    '<div class="avatar sm">' + esc((d.name || "?").charAt(0).toUpperCase()) + "</div>" +
    '<div class="ci-main"><div class="ci-title">' + dot + title + "</div>" +
    '<div class="ci-sub">' + sub + "</div></div>" + unreadHtml + "</div>";
}

function bindChatItems(root) {
  var items = root.querySelectorAll(".chat-item");
  for (var i = 0; i < items.length; i++) {
    items[i].onclick = function () {
      openChat({ type: this.getAttribute("data-type"), id: parseInt(this.getAttribute("data-id"), 10),
                 name: this.querySelector(".ci-title").textContent.replace(/[🟢🟡⚪]/g, "").replace(/\(\d+\+?\)/g, "").trim() });
    };
  }
}

function renderChats(body) {
  var html = "";
  if (!state.dialogs.length) html = '<p class="muted pad">Пока нет диалогов. Откройте «Контакты», добавьте коллегу и начните переписку.</p>';
  for (var i = 0; i < state.dialogs.length; i++) html += chatRow(state.dialogs[i]);
  body.innerHTML = html;
  bindChatItems(body);
}

function renderDirectory(body) {
  var html = '<div class="pad"><input id="dir-search" placeholder="Поиск по имени/логину…" class="search"></div><div id="dir-list"></div>';
  body.innerHTML = html;
  function drawList() {
    var q = ($("#dir-search").value || "").toLowerCase();
    var list = "", i, c;
    for (i = 0; i < state.contacts.length; i++) {
      c = state.contacts[i];
      if (q && (c.display_name + " " + c.username).toLowerCase().indexOf(q) < 0) continue;
      list += '<div class="contact-item">' +
        '<div class="avatar sm">' + esc(c.display_name.charAt(0).toUpperCase()) + "</div>" +
        '<div class="ci-main"><div class="ci-title">' + statusDot(c.status) + esc(c.display_name) + "</div>" +
        '<div class="ci-sub">@' + esc(c.username) + "</div></div>" +
        '<button class="ghost sm btn-write" data-id="' + c.id + '">Написать</button>' +
        '<button class="danger sm btn-rm" data-id="' + c.id + '">✕</button></div>';
    }
    for (i = 0; i < state.directory.length; i++) {
      c = state.directory[i];
      if (q && (c.display_name + " " + c.username).toLowerCase().indexOf(q) < 0) continue;
      list += '<div class="contact-item muted-row">' +
        '<div class="avatar sm gray">' + esc(c.display_name.charAt(0).toUpperCase()) + "</div>" +
        '<div class="ci-main"><div class="ci-title">' + statusDot(c.status) + esc(c.display_name) + "</div>" +
        '<div class="ci-sub">@' + esc(c.username) + " · нет в контактах</div></div>" +
        '<button class="primary sm btn-add" data-id="' + c.id + '">+ Контакт</button></div>';
    }
    $("#dir-list").innerHTML = list || '<p class="muted pad">Никого не найдено.</p>';
    bindDirButtons();
  }
  function bindDirButtons() {
    var root = $("#dir-list");
    var addB = root.querySelectorAll(".btn-add");
    for (var i = 0; i < addB.length; i++) addB[i].onclick = function () {
      api("/api/contacts", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contact_id: parseInt(this.getAttribute("data-id"), 10) })
      }).then(refreshContacts)["catch"](function (e) { showErr(e.message); });
    };
    var rmB = root.querySelectorAll(".btn-rm");
    for (var j = 0; j < rmB.length; j++) rmB[j].onclick = function () {
      api("/api/contacts/" + this.getAttribute("data-id"), { method: "DELETE" }).then(refreshContacts)["catch"](function (e) { showErr(e.message); });
    };
    var wB = root.querySelectorAll(".btn-write");
    for (var k = 0; k < wB.length; k++) wB[k].onclick = function () {
      var id = parseInt(this.getAttribute("data-id"), 10), nm = "";
      for (var m = 0; m < state.contacts.length; m++) if (state.contacts[m].id === id) nm = state.contacts[m].display_name;
      openChat({ type: "dm", id: id, name: nm });
    };
  }
  $("#dir-search").oninput = drawList;
  drawList();
}

function renderGroupsTab(body) {
  var html = '<div class="pad"><button id="new-group" class="primary">+ Создать группу</button></div>';
  api("/api/groups").then(function (gs) {
    state.groups = gs;
    for (var i = 0; i < gs.length; i++) {
      var g = gs[i];
      var unreadHtml = g.unread > 0 ? '<span class="badge unread-anim">' + (g.unread > 99 ? "99+" : g.unread) + "</span>" : "";
      // В названии группы — количество непрочитанных; число участников из названия убрано.
      var gTitle = esc(g.name) + (g.unread > 0 ? ' <span class="title-count">(' + (g.unread > 99 ? "99+" : g.unread) + ')</span>' : "");
      html += '<div class="chat-item' + (g.unread > 0 ? " has-unread" : "") + '" data-type="group" data-id="' + g.id + '">' +
        '<div class="avatar sm grp">' + esc(g.name.charAt(0).toUpperCase()) + "</div>" +
        '<div class="ci-main"><div class="ci-title">' + gTitle + "</div>" +
        '<div class="ci-sub">' + esc(String(g.last_text || "").slice(0, 60) || "Нет сообщений") + "</div></div>" + unreadHtml + "</div>";
    }
    if (!gs.length) html += '<p class="muted pad">Групп пока нет.</p>';
    body.innerHTML = html;
    bindChatItems(body);
    bindClick(body, "#new-group", openCreateGroupModal, "#new-group");
  })["catch"](function (e) { body.innerHTML = '<p class="muted pad">' + esc(e.message) + "</p>"; });
}

function openCreateGroupModal() {
  var usersHtml = "";
  for (var i = 0; i < state.users.length; i++) {
    usersHtml += '<label class="chk"><input type="checkbox" value="' + state.users[i].id + '"> ' +
      esc(state.users[i].display_name) + " (@" + esc(state.users[i].username) + ")</label>";
  }
  showModal(
    '<h3>Новая группа</h3>' +
    '<label>Название <input id="ng-name" maxlength="80" placeholder="Например: Отдел разработки"></label>' +
    '<div class="muted small">Участники:</div><div class="chk-list">' + (usersHtml || "<i>нет других пользователей</i>") + "</div>" +
    '<div class="modal-actions"><button class="ghost" id="ng-cancel">Отмена</button>' +
    '<button class="primary" id="ng-ok">Создать</button></div>');
  bindClick($("#modal-box"), "#ng-cancel", hideModal, "#ng-cancel");
  bindClick($("#modal-box"), "#ng-ok", function () {
    var ids = [];
    var boxes = $("#modal-box").querySelectorAll("input[type=checkbox]:checked");
    for (var i = 0; i < boxes.length; i++) ids.push(parseInt(boxes[i].value, 10));
    api("/api/groups", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("#ng-name").value.trim(), member_ids: ids })
    }).then(function (g) {
      hideModal(); refreshDialogs();
      openChat({ type: "group", id: g.id, name: g.name });
    })["catch"](function (e) { showErr(e.message); });
  }, "#ng-ok");
}

// ---------- чат ----------
function openChat(chat) {
  state.chat = chat;
  state.tab = "chats"; // возврат из админки в режим чата
  $("#chat-empty").classList.add("hidden");
  $("#chat-view").classList.remove("hidden");
  setComposerEnabled(true);
  var extra = "";
  if (chat.type === "group") extra = ' <button class="ghost sm" id="grp-manage">Управление группой</button>';
  $("#chat-title").innerHTML = esc(chat.name) + extra;
  var gm = document.getElementById("grp-manage");
  if (gm) gm.onclick = function () { openGroupManageModal(chat.id); };
  loadMessages();
}

function loadMessages(quiet) {
  if (!state.chat) return;
  var c = state.chat;
  api("/api/messages?type=" + c.type + "&id=" + c.id).then(function (msgs) {
    // Дедупликация: помечаем все полученные сообщения как «виденные», но НЕ
    // уведомляем отсюда (уведомление — только из WebSocket new_message).
    for (var i = 0; i < msgs.length; i++) noteMessage(msgs[i], true);
    state.messages = msgs;
    renderMessages();
    if (!quiet) refreshDialogs();
  })["catch"](function (e) { if (!quiet) showErr(e.message); });
}

function fileLink(m) {
  var url = state.base + "/api/files/" + m.file_id + "/raw?token=" + encodeURIComponent(state.token);
  if (/^image\//.test(m.mimetype || "")) {
    return '<img class="msg-img" src="' + url + '" alt="' + esc(m.filename) + '">';
  }
  return '<a class="file-chip" href="' + url + '&dl=1">📄 ' + esc(m.filename) +
    ' <span class="muted small">' + fmtSize(m.size) + "</span></a>";
}

function renderMessages() {
  var box = $("#msgs-box");
  if (!box) return;
  var html = "";
  for (var i = 0; i < state.messages.length; i++) {
    var m = state.messages[i];
    var mine = m.sender_id === state.me.id;
    var canDel = mine || state.me.role === "admin";
    html += '<div class="msg' + (mine ? " mine" : "") + '">' +
      '<div class="msg-author">' + (mine ? "" : esc(m.sender_name)) +
      ' <span class="muted small">' + fmtTime(m.created_at) + "</span></div>" +
      '<div class="msg-text"></div>' +
      (m.file_id ? fileLink(m) : "") +
      (canDel ? '<button class="msg-del" data-mid="' + m.id + '" title="Удалить">🗑</button>' : "") +
      "</div>";
  }
  box.innerHTML = html;
  var texts = box.querySelectorAll(".msg-text");
  for (var k = 0; k < texts.length; k++) {
    renderEmojiInto(texts[k], state.messages[k].text);
  }
  var dels = box.querySelectorAll(".msg-del");
  for (var j = 0; j < dels.length; j++) dels[j].onclick = function () {
    var mid = parseInt(this.getAttribute("data-mid"), 10);
    if (!confirm("Удалить сообщение?")) return;
    api("/api/messages/" + mid, { method: "DELETE" }).then(function () {
      loadMessages(true); refreshDialogs();
    })["catch"](function (e) { showErr(e.message); });
  };
  box.scrollTop = box.scrollHeight;
}

function sendMessage() {
  if (!state.chat) return;
  var inp = $("#msg-input");
  var text = inp.value.trim();
  if (!text) return;
  inp.value = "";
  var body = { type: state.chat.type, text: text };
  if (state.chat.type === "dm") body.peer_id = state.chat.id; else body.group_id = state.chat.id;
  api("/api/messages", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }).then(function (m) {
    appendLocal(m);
    refreshDialogs();
  })["catch"](function (e) { showErr(e.message); });
}

function appendLocal(m) {
  for (var i = 0; i < state.messages.length; i++) if (state.messages[i].id === m.id) return;
  state.messages.push(m);
  renderMessages();
}

// ---------- управление группой ----------
function openGroupManageModal(gid) {
  api("/api/groups/" + gid).then(function (gi) {
    var myRole = gi.my_role;
    var canManage = (myRole === "owner" || myRole === "admin" || state.me.role === "admin");
    var rows = "";
    for (var i = 0; i < gi.members.length; i++) {
      var mm = gi.members[i];
      var roleBtn = "";
      if (canManage && myRole === "owner" && mm.user_id !== state.me.id && mm.role !== "owner") {
        roleBtn = '<button class="ghost sm btn-promote" data-uid="' + mm.user_id + '">→ админ</button>';
      }
      var rmBtn = "";
      if (canManage && mm.role !== "owner") {
        rmBtn = '<button class="danger sm btn-kick" data-uid="' + mm.user_id + '">Исключить</button>';
      } else if (mm.user_id === state.me.id) {
        rmBtn = '<button class="ghost sm btn-leave" data-uid="' + mm.user_id + '">Выйти</button>';
      }
      rows += '<div class="member-row">' + statusDot(mm.status) + " " + esc(mm.display_name) +
        ' <span class="muted small">(' + mm.role + ") </span>" + roleBtn + rmBtn + "</div>";
    }
    var addOpts = "";
    for (var j = 0; j < state.users.length; j++) {
      var u = state.users[j], inG = false;
      for (var k2 = 0; k2 < gi.members.length; k2++) if (gi.members[k2].user_id === u.id) inG = true;
      if (!inG) addOpts += '<option value="' + u.id + '">' + esc(u.display_name) + "</option>";
    }
    var actions = "";
    if (canManage) actions += '<button class="ghost" id="gm-rename">Переименовать</button>';
    if (myRole === "owner" || state.me.role === "admin") actions += ' <button class="danger" id="gm-delete">Удалить группу</button>';

    showModal("<h3>Группа: " + esc(gi.name) + "</h3>" +
      (addOpts && canManage ? '<div class="form-inline"><select id="gm-add-user">' + addOpts +
        '</select><button class="primary sm" id="gm-add">Добавить в группу</button></div>' : "") +
      '<div class="members-list">' + rows + "</div>" +
      '<div class="modal-actions">' + actions + ' <button id="gm-close">Закрыть</button></div>');

    var box = $("#modal-box");
    bindClick(box, "#gm-close", hideModal, "#gm-close");
    if (document.getElementById("gm-add")) bindClick(box, "#gm-add", function () {
      api("/api/groups/" + gid + "/members", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: parseInt($("#gm-add-user").value, 10) })
      }).then(function () { openGroupManageModal(gid); refreshDialogs(); })["catch"](function (e) { showErr(e.message); });
    }, "#gm-add");
    var ks = box.querySelectorAll(".btn-kick");
    for (var a = 0; a < ks.length; a++) ks[a].onclick = function () {
      kickMember(gid, parseInt(this.getAttribute("data-uid"), 10));
    };
    var lv = box.querySelectorAll(".btn-leave");
    for (var b2 = 0; b2 < lv.length; b2++) lv[b2].onclick = function () {
      kickMember(gid, parseInt(this.getAttribute("data-uid"), 10));
    };
    var pr = box.querySelectorAll(".btn-promote");
    for (var c2 = 0; c2 < pr.length; c2++) pr[c2].onclick = function () {
      api("/api/groups/" + gid + "/roles/" + this.getAttribute("data-uid"), {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: "admin" })
      }).then(function () { openGroupManageModal(gid); })["catch"](function (e) { showErr(e.message); });
    };
    if (document.getElementById("gm-rename")) bindClick(box, "#gm-rename", function () {
      var nn = prompt("Новое название группы:", gi.name);
      if (!nn) return;
      api("/api/groups/" + gid, { method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nn.trim() })
      }).then(function () { hideModal(); refreshDialogs(); })["catch"](function (e) { showErr(e.message); });
    }, "#gm-rename");
    if (document.getElementById("gm-delete")) bindClick(box, "#gm-delete", function () {
      if (!confirm("Удалить группу вместе с историей сообщений?")) return;
      api("/api/groups/" + gid, { method: "DELETE" }).then(function () {
        hideModal(); state.chat = null;
        $("#chat-view").classList.add("hidden"); $("#chat-empty").classList.remove("hidden");
        refreshDialogs();
      })["catch"](function (e) { showErr(e.message); });
    }, "#gm-delete");
  })["catch"](function (e) { showErr(e.message); });
}

function kickMember(gid, uid) {
  api("/api/groups/" + gid + "/members/" + uid, { method: "DELETE" })
    .then(function () { openGroupManageModal(gid); refreshDialogs(); })
    ["catch"](function (e) { showErr(e.message); });
}

// ---------- модалки ----------
function showModal(html) {
  $("#modal-box").innerHTML = html;
  $("#modal-root").classList.remove("hidden");
}
function hideModal() { $("#modal-root").classList.add("hidden"); }

// ---------- админка (сайдбар: краткая сводка; полное управление — в основном окне) ----------
function renderAdmin(body) {
  if (state.me.role !== "admin") { body.innerHTML = '<p class="muted pad">Нет доступа.</p>'; return; }
  body.innerHTML = '<div class="pad"><p class="muted">Админпанель открыта в основном окне.<br>'+
    'Сотрудники, группы, модерация и файлы — справа.</p></div>';
}

// ---------- WebSocket + фолбэк-опрос ----------
function connectSocket() {
  if (typeof io === "undefined") return;
  try {
    state.sock = io(state.base, { query: "token=" + state.token });
    state.sock.on("new_message", function (m) {
      if (!m || m.sender_id === state.me.id) { refreshDialogs(); return; }
      // Уведомление — только если это ДЕЙСТВИТЕЛЬНО новое сообщение (дедуп по id).
      var fresh = noteMessage(m, false);
      if (!state.chat) { refreshDialogs(); return; }
      var related = (m.chat_type === "dm" && (m.sender_id === state.chat.id || m.group_id === state.chat.id)) ||
                    (m.chat_type === "group" && m.group_id === state.chat.id);
      if (related) { appendLocal(m); markLastRead(m); }
      else if (fresh) { pingIncoming(m); } // не в открытом чате — всплывающее + система
      refreshDialogs();
    });
    state.sock.on("message_deleted", function (d) {
      state.messages = state.messages.filter(function (x) { return x.id !== d.id; });
      renderMessages(); refreshDialogs();
    });
    state.sock.on("contact_added", function () { refreshContacts(); });
    state.sock.on("group_invite", function (g) {
      refreshDialogs();
      showNewChatToast("Вас добавили в группу «" + g.name + "»");
    });
    state.sock.on("group_removed", function () { refreshDialogs(); });
    state.sock.on("presence", function (p) {
      for (var i = 0; i < state.dialogs.length; i++)
        if (state.dialogs[i].type === "dm" && state.dialogs[i].id === p.user_id)
          state.dialogs[i].status = p.status;
      for (var j = 0; j < state.contacts.length; j++)
        if (state.contacts[j].id === p.user_id) state.contacts[j].status = p.status;
      renderSide();
    });
  } catch (e) { /* фолбэк — опрос раз в 4 сек уже идёт */ }
}

function markLastRead(m) {
  api("/api/messages/" + m.id + "/read", { method: "POST" })["catch"](function () {});
}

function pingIncoming(m) {
  var text = (m.sender_name || "") + ": " + (m.text || "📎 файл");
  showNewChatToast(text);
  desktopNotify(text); // системное уведомление Electron — ровно одно на новое сообщение
  if (navigator.vibrate) { try { navigator.vibrate(120); } catch (e) {} }
}

function showNewChatToast(text) {
  var t = document.createElement("div");
  t.className = "toast unread-anim";
  t.textContent = text;
  document.body.appendChild(t);
  setTimeout(function () { t.classList.add("fade"); }, 3500);
  setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 4200);
}

// ---------- смайлы ----------
function initEmojiPanel() {
  var panel = $("#emoji-panel");
  var html = "";
  for (var i = 0; i < EMOJI_LIST.length; i++) html += '<button class="emoji-pick" data-e="' + EMOJI_LIST[i] + '">' + EMOJI_LIST[i] + "</button>";
  panel.innerHTML = html;
  var picks = panel.querySelectorAll(".emoji-pick");
  for (var j = 0; j < picks.length; j++) picks[j].onclick = function () {
    var inp = $("#msg-input");
    inp.value += this.getAttribute("data-e");
    inp.focus();
  };
  $("#emoji-btn").onclick = function () { panel.classList.toggle("hidden"); };
}

// ---------- файлы ----------
function initAttach() {
  $("#attach-btn").onclick = function () { $("#file-input").click(); };
  $("#file-input").onchange = function () {
    var f = this.files[0];
    if (!f || !state.chat) return;
    var fd = new FormData();
    fd.append("file", f);
    api("/api/upload", { method: "POST", body: fd }).then(function (up) {
      var body = { type: state.chat.type, text: "", file_id: up.id };
      if (state.chat.type === "dm") body.peer_id = state.chat.id; else body.group_id = state.chat.id;
      return api("/api/messages", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) });
    }).then(function (m) { appendLocal(m); refreshDialogs(); })
      ["catch"](function (e) { showErr(e.message); });
    this.value = "";
  };
}

// ---------- статусы ----------
function initStatus() {
  var sel = $("#my-status");
  sel.onchange = function () {
    var v = this.value;
    api("/api/status", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: v }) })["catch"](function () {});
    if (state.sock) {
      if (v === "away") state.sock.emit("set_away");
      else if (v === "online") state.sock.emit("set_online");
    }
  };
  // авто-«отошёл» после 5 минут бездействия, возврат активности
  var awayTimer = null;
  function activity() {
    if (awayTimer) clearTimeout(awayTimer);
    if (sel.value === "away") { sel.value = "online"; sel.onchange.call(sel); }
    awayTimer = setTimeout(function () {
      sel.value = "away"; sel.onchange.call(sel);
    }, 5 * 60 * 1000);
  }
  document.addEventListener("mousemove", activity);
  document.addEventListener("keydown", activity);
  activity();
}

// ---------- старт ----------
function boot() {
  state.base = detectBase();
  initLogin();
  initEmojiPanel();
  initAttach();
  initStatus();
  bindClick(document, "#logout", function () { doLogout(true); }, "#logout");
  bindClick(document, "#send", sendMessage, "#send");
  $("#msg-input").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); sendMessage(); }
  });
  var savedToken = lsGet("token");
  if (savedToken) {
    state.token = savedToken;
    api("/api/me").then(function (me) { state.me = me; startApp(); })
      ["catch"](function () { lsSet("token", ""); showLogin(); });
  } else {
    showLogin();
  }
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
})();
