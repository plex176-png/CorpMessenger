const fs = require("fs");
const { JSDOM } = require("jsdom");
// упрощённый прогон renderMessages через jsdom + стили для проверки структуры
const html = fs.readFileSync("server/static/index.html","utf8");
const dom = new JSDOM(html, { runScripts: "outside-only" });
const { window } = dom;
global.window = window; global.document = window.document;
// подставим app.js и вызовем renderMessages с фейковым состоянием
let src = fs.readFileSync("server/static/app.js","utf8");
src += `
window.__t = function(){
  state.me = {id:1, role:"admin", display_name:"A"};
  state.chat = {type:"dm", id:2};
  state.messages = [
    {id:1, sender_id:2, sender_name:"Pete", text:"privet", created_at:"2026-11-04T10:00:00"},
    {id:2, sender_id:1, text:"oya", created_at:"2026-11-04T10:00:05"},
    {id:3, sender_id:2, sender_name:"Pete", text:"dolgoe "+ "x".repeat(900), created_at:"2026-11-04T10:00:06"}
  ];
  document.getElementById("msgs-box") || null;
  renderMessages();
  var box = document.querySelector("#msgs-box") || (function(){var d=document.createElement("div"); d.id="msgs-box"; document.body.appendChild(d); return d;})();
  renderMessages();
  var cols = box.querySelectorAll(".msgs-col").length;
  var rows = box.querySelectorAll(".msg").length;
  var mine = box.querySelectorAll(".msg.mine").length;
  var bodies = box.querySelectorAll(".msg-body").length;
  console.log(JSON.stringify({cols:cols, rows:rows, mine:mine, bodies:bodies}));
};`;
window.eval(src);
// нужен элемент #msgs-box — из index.html он есть? проверим
if (!window.document.getElementById("msgs-box")) {
  const d = window.document.createElement("div"); d.id="msgs-box"; window.document.body.appendChild(d);
}
try { window.__t(); } catch(e){ console.log("ERR", e.message); }
