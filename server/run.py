# -*- coding: utf-8 -*-
"""Корпоративный мессенджер — HTTP + WebSocket сервер.
Совместимо с Python 3.7+ (Windows 7/10/11). Запуск: python run.py [--port 5000]"""
import os, sys, time, uuid, argparse, mimetypes, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import database as db

try:
    from flask import Flask, request, jsonify, send_from_directory, send_file
    from flask_socketio import SocketIO, emit
except ImportError:
    print("Установите зависимости: pip install -r requirements.txt")
    sys.exit(1)

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"))
app.config["SECRET_KEY"] = "corp-messenger-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

MAX_FILE_MB = 50
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_MB * 1024 * 1024

ONLINE_SOCKETS = {}   # user_id -> set(sid)


def _now():
    return int(time.time())


def current_user():
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not token:
        token = request.args.get("token", "")
    u = db.user_by_token(token)
    if u and u["is_active"]:
        return u
    return None


def auth_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*a, **kw):
        u = current_user()
        if not u:
            return jsonify({"error": "Не авторизован"}), 401
        request._user = u
        return fn(u, *a, **kw)
    return wrapper


def admin_required(fn):
    from functools import wraps
    @auth_required
    @wraps(fn)
    def wrapper(_u, *a, **kw):
        if _u["role"] != "admin":
            return jsonify({"error": "Только для администраторов"}), 403
        return fn(_u, *a, **kw)
    return wrapper


def _pub_message(msg, recipients):
    """Отправка new_message всем участникам чата."""
    for uid in recipients:
        socketio.emit("new_message", msg, room="user_%s" % uid)


def _dm_recipients(sender_id, peer_id):
    return [sender_id, peer_id]


# ---------------- статика / веб-клиент ----------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:fname>")
def static_files(fname):
    return send_from_directory(app.static_folder, fname)


# ---------------- авторизация ----------------

@app.route("/api/register", methods=["POST"])
def register():
    d = request.get_json(force=True, silent=True) or {}
    try:
        db.create_user(d.get("username", ""), d.get("password", ""), d.get("display_name", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Логин уже занят"}), 409
    return jsonify({"ok": True})


@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json(force=True, silent=True) or {}
    u = db.user_by_username(d.get("username", "")) if hasattr(db, "user_by_username") else None
    if u is None:
        c = db.get_db()
        r = c.execute("SELECT * FROM users WHERE username=?", (d.get("username", ""),)).fetchone()
        c.close()
        u = dict(r) if r else None
    if not u or not db.verify_password(d.get("password", ""), u["password_hash"], u["salt"]):
        return jsonify({"error": "Неверный логин или пароль"}), 401
    if not u["is_active"]:
        return jsonify({"error": "Учётная запись заблокирована"}), 403
    token = db.create_token(u["id"])
    db.set_status(u["id"], "online")
    socketio.emit("presence", {"user_id": u["id"], "status": "online"},
                  room=None, skip_sid=request.sid if hasattr(request, "sid") else None)
    return jsonify({"token": token, "user": {"id": u["id"], "username": u["username"],
                                             "display_name": u["display_name"], "role": u["role"]}})


@app.route("/api/logout", methods=["POST"])
@auth_required
def logout(u):
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip() \
        or request.args.get("token", "")
    db.revoke_token(token)
    db.set_status(u["id"], "offline")
    socketio.emit("presence", {"user_id": u["id"], "status": "offline"})
    return jsonify({"ok": True})


@app.route("/api/me")
@auth_required
def me(u):
    return jsonify({"id": u["id"], "username": u["username"], "display_name": u["display_name"],
                    "role": u["role"], "status": u["status"],
                    "unread_total": db.total_unread(u["id"])})


@app.route("/api/status", methods=["POST"])
@auth_required
def set_my_status(u):
    d = request.get_json(force=True, silent=True) or {}
    st = d.get("status", "online")
    db.set_status(u["id"], st)
    socketio.emit("presence", {"user_id": u["id"], "status": st})
    return jsonify({"ok": True, "status": st})


# ---------------- диалоги / контакты ----------------

@app.route("/api/dialogs")
@auth_required
def dialogs(u):
    return jsonify(db.dialogs(u["id"]))


@app.route("/api/users")
@auth_required
def users(u):
    return jsonify([x for x in db.list_users() if x["id"] != u["id"]])


@app.route("/api/contacts")
@auth_required
def contacts(u):
    mine = db.list_contacts(u["id"])
    ids = {c["id"] for c in mine}
    directory = [x for x in db.list_users() if x["id"] != u["id"] and x["id"] not in ids]
    return jsonify({"contacts": mine, "directory": directory})


@app.route("/api/contacts", methods=["POST"])
@auth_required
def add_contact(u):
    d = request.get_json(force=True, silent=True) or {}
    cid = int(d.get("contact_id", 0))
    target = db.get_user(cid)
    if not target or not target["is_active"]:
        return jsonify({"error": "Пользователь не найден"}), 404
    if cid == u["id"]:
        return jsonify({"error": "Нельзя добавить себя"}), 400
    db.add_contact(u["id"], cid)
    socketio.emit("contact_added", {"user_id": cid, "from": {
        "id": u["id"], "username": u["username"], "display_name": u["display_name"]}},
        room="user_%s" % cid)
    return jsonify({"ok": True})


@app.route("/api/contacts/<int:cid>", methods=["DELETE"])
@auth_required
def del_contact(u, cid):
    db.remove_contact(u["id"], cid)
    return jsonify({"ok": True})


# ---------------- сообщения ----------------

@app.route("/api/messages")
@auth_required
def get_messages(u):
    chat_type = request.args.get("type", "dm")
    chat_id = int(request.args.get("id", 0))
    if chat_type == "group" and not db.in_group(chat_id, u["id"]):
        return jsonify({"error": "Нет доступа к группе"}), 403
    msgs = db.chat_messages(chat_type, chat_id, u["id"])
    key = db.chat_key_for(u["id"], chat_type, chat_id)
    if msgs:
        db.mark_read(u["id"], key, msgs[-1]["id"])
    return jsonify(msgs)


@app.route("/api/messages", methods=["POST"])
@auth_required
def send_message(u):
    d = request.get_json(force=True, silent=True) or {}
    chat_type = d.get("type", "dm")
    text = (d.get("text") or "").strip()[:4000]
    file_id = d.get("file_id")
    if not text and not file_id:
        return jsonify({"error": "Пустое сообщение"}), 400
    if chat_type == "dm":
        peer_id = int(d.get("peer_id", 0))
        peer = db.get_user(peer_id)
        if not peer or not peer["is_active"]:
            return jsonify({"error": "Получатель не найден"}), 404
        mid = db.insert_message("dm", u["id"], text, file_id=file_id, peer_id=peer_id)
        recips = _dm_recipients(u["id"], peer_id)
    elif chat_type == "group":
        gid = int(d.get("group_id", 0))
        if not db.in_group(gid, u["id"]):
            return jsonify({"error": "Вы не в группе"}), 403
        mid = db.insert_message("group", u["id"], text, group_id=gid, file_id=file_id)
        gi = db.group_info(gid)
        recips = [m["user_id"] for m in gi["members"]]
    else:
        return jsonify({"error": "Неверный тип чата"}), 400
    msg = db.message_with_names(mid)
    _pub_message(msg, recips)
    return jsonify(msg)


@app.route("/api/messages/<int:mid>/read", methods=["POST"])
@auth_required
def read_msg(u, mid):
    m = db.message_with_names(mid)
    if not m:
        return jsonify({"error": "not found"}), 404
    key = db.chat_key_for(u["id"], m["chat_type"], m["group_id"])
    db.mark_read(u["id"], key, mid)
    return jsonify({"ok": True})


@app.route("/api/messages/<int:mid>", methods=["DELETE"])
@auth_required
def delete_msg(u, mid):
    m = db.message_with_names(mid)
    if not m:
        return jsonify({"error": "not found"}), 404
    hard = request.args.get("hard") == "1"
    allowed = (m["sender_id"] == u["id"] and not hard) or u["role"] == "admin"
    if not allowed:
        return jsonify({"error": "Нет прав"}), 403
    info = db.delete_message(mid, hard=hard)
    if info:
        if info["chat_type"] == "group":
            gi = db.group_info(info["group_id"])
            recips = [mm["user_id"] for mm in gi["members"]] if gi else []
        else:
            recips = _dm_recipients(info["sender_id"], info["group_id"])
        for uid in recips:
            socketio.emit("message_deleted", {"id": mid, "hard": hard}, room="user_%s" % uid)
    return jsonify({"ok": True})


# ---------------- файлы ----------------

def _safe_name(name):
    name = os.path.basename(name or "file.bin")
    return re.sub(r"[^\w.\-\u0400-\u04FF ]+", "_", name)[:120]


@app.route("/api/upload", methods=["POST"])
@auth_required
def upload(u):
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Файл не передан"}), 400
    stored = "%s%s" % (uuid.uuid4().hex, os.path.splitext(f.filename)[1][:12])
    path = os.path.join(db.UPLOAD_DIR, stored)
    os.makedirs(db.UPLOAD_DIR, exist_ok=True)
    f.save(path)
    size = os.path.getsize(path)
    mt = f.mimetype or mimetypes.guess_type(f.filename)[0] or "application/octet-stream"
    fid = db.save_file(u["id"], _safe_name(f.filename), stored, mt, size)
    return jsonify({"id": fid, "filename": _safe_name(f.filename), "mimetype": mt, "size": size})


def _file_access_allowed(f, u):
    if u["role"] == "admin":
        return True
    if f["uploader_id"] == u["id"]:
        return True
    # доступ, если файл прикреплён к сообщению пользователя
    c = db.get_db()
    rows = c.execute("SELECT chat_type, group_id, sender_id FROM messages WHERE file_id=? AND deleted=0",
                     (f["id"],)).fetchall()
    ok = False
    for r in rows:
        if r["chat_type"] == "dm" and u["id"] in (r["sender_id"], r["group_id"]):
            ok = True; break
        if r["chat_type"] == "group" and r["group_id"] and db.in_group(r["group_id"], u["id"]):
            ok = True; break
    c.close()
    return ok


def _serve_file(fid, download=False):
    u = current_user()
    if not u:
        return jsonify({"error": "Не авторизован"}), 401
    f = db.get_file(fid)
    if not f:
        return jsonify({"error": "Файл не найден"}), 404
    if not _file_access_allowed(f, u):
        return jsonify({"error": "Нет доступа"}), 403
    path = os.path.join(db.UPLOAD_DIR, f["stored_name"])
    if not os.path.exists(path):
        return jsonify({"error": "Файл утрачен"}), 404
    return send_file(path, mimetype=f["mimetype"], as_attachment=download,
                     download_name=f["filename"])


@app.route("/api/files/<int:fid>")
def file_meta_redirect(fid):
    return _serve_file(fid, download=False)


@app.route("/api/files/<int:fid>/raw")
def file_raw(fid):
    dl = request.args.get("dl") == "1"
    return _serve_file(fid, download=dl)


# ---------------- группы ----------------

@app.route("/api/groups", methods=["POST"])
@auth_required
def create_group(u):
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get("name") or "").strip()[:80]
    if len(name) < 2:
        return jsonify({"error": "Название группы от 2 символов"}), 400
    gid = db.create_group(name, u["id"])
    added = []
    for uid in (d.get("member_ids") or [])[:200]:
        t = db.get_user(int(uid))
        if t and t["is_active"] and t["id"] != u["id"]:
            db.add_member(gid, t["id"])
            added.append(t["id"])
    for uid in added:
        socketio.emit("group_invite", {"group_id": gid, "name": name}, room="user_%s" % uid)
    return jsonify({"id": gid, "name": name})


@app.route("/api/groups")
@auth_required
def my_groups(u):
    return jsonify(db.my_groups(u["id"]))


@app.route("/api/groups/<int:gid>")
@auth_required
def group_view(u, gid):
    if not db.in_group(gid, u["id"]) and u["role"] != "admin":
        return jsonify({"error": "Нет доступа"}), 403
    gi = db.group_info(gid)
    if not gi:
        return jsonify({"error": "Группа не найдена"}), 404
    gi["my_role"] = db.group_role(gid, u["id"])
    return jsonify(gi)


@app.route("/api/groups/<int:gid>/members", methods=["POST"])
@auth_required
def group_add_member(u, gid):
    role = db.group_role(gid, u["id"])
    if role not in ("owner", "admin") and u["role"] != "admin":
        return jsonify({"error": "Только владелец/админ группы"}), 403
    d = request.get_json(force=True, silent=True) or {}
    target = db.get_user(int(d.get("user_id", 0)))
    if not target or not target["is_active"]:
        return jsonify({"error": "Пользователь не найден"}), 404
    db.add_member(gid, target["id"])
    socketio.emit("group_invite", {"group_id": gid,
                                   "name": (db.group_info(gid) or {}).get("name", "")},
                  room="user_%s" % target["id"])
    return jsonify({"ok": True})


@app.route("/api/groups/<int:gid>/members/<int:uid>", methods=["DELETE"])
@auth_required
def group_del_member(u, gid, uid):
    role = db.group_role(gid, u["id"])
    if uid == u["id"]:
        db.remove_member(gid, uid)
        return jsonify({"ok": True, "left": True})
    if role not in ("owner", "admin") and u["role"] != "admin":
        return jsonify({"error": "Нет прав"}), 403
    if db.group_role(gid, uid) == "owner" and u["role"] != "admin":
        return jsonify({"error": "Нельзя удалить владельца"}), 400
    db.remove_member(gid, uid)
    socketio.emit("group_removed", {"group_id": gid}, room="user_%s" % uid)
    return jsonify({"ok": True})


@app.route("/api/groups/<int:gid>/roles/<int:uid>", methods=["PATCH"])
@auth_required
def group_set_role(u, gid, uid):
    if db.group_role(gid, u["id"]) != "owner" and u["role"] != "admin":
        return jsonify({"error": "Только владелец группы"}), 403
    d = request.get_json(force=True, silent=True) or {}
    try:
        db.set_member_role(gid, uid, d.get("role", "member"))
    except ValueError:
        return jsonify({"error": "Неверная роль"}), 400
    return jsonify({"ok": True})


@app.route("/api/groups/<int:gid>", methods=["PATCH", "DELETE"])
@auth_required
def group_edit(u, gid):
    role = db.group_role(gid, u["id"])
    if role not in ("owner", "admin") and u["role"] != "admin":
        return jsonify({"error": "Нет прав"}), 403
    if request.method == "DELETE":
        if role != "owner" and u["role"] != "admin":
            return jsonify({"error": "Только владелец"}), 403
        db.delete_group(gid)
        return jsonify({"ok": True})
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get("name") or "").strip()[:80]
    if len(name) >= 2:
        db.rename_group(gid, name)
    return jsonify({"ok": True})


# ---------------- админка ----------------

def require_admin():
    """Возвращает (user, None) либо (None, ответ-ошибка). Без декораторов —
    устойчиво к изменению тела функций на клиенте."""
    u = current_user()
    if not u:
        return None, (jsonify({"error": "Не авторизован"}), 401)
    if u["role"] != "admin":
        return None, (jsonify({"error": "Только для администраторов"}), 403)
    return u, None


@app.route("/api/admin/stats")
def admin_stats():
    _u, err = require_admin()
    if err: return err
    return jsonify(db.stats())


@app.route("/api/admin/users")
def admin_users():
    _u, err = require_admin()
    if err: return err
    return jsonify(db.list_users(include_blocked=True))


@app.route("/api/admin/users", methods=["POST"])
def admin_create_user():
    _u, err = require_admin()
    if err: return err
    d = request.get_json(force=True, silent=True) or {}
    try:
        db.create_user(d.get("username", ""), d.get("password", ""),
                       d.get("display_name", ""), d.get("role", "user"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Логин уже занят"}), 409
    return jsonify({"ok": True})


@app.route("/api/admin/users/<int:uid>", methods=["PATCH", "DELETE"])
def admin_user_edit(uid):
    _u, err = require_admin()
    if err: return err
    target = db.get_user(uid)
    if not target:
        return jsonify({"error": "Не найден"}), 404
    if request.method == "DELETE":
        if uid == _u["id"]:
            return jsonify({"error": "Нельзя удалить себя"}), 400
        admins = [x for x in db.list_users(True) if x["role"] == "admin" and x["is_active"]]
        if target["role"] == "admin" and len(admins) <= 1:
            return jsonify({"error": "Нельзя удалить последнего админа"}), 400
        db.delete_user(uid)
        return jsonify({"ok": True})
    d = request.get_json(force=True, silent=True) or {}
    if "role" in d:
        if uid == _u["id"] and d["role"] != "admin":
            return jsonify({"error": "Нельзя снять права с себя"}), 400
        try:
            db.set_role(uid, d["role"])
        except ValueError:
            pass
    if "is_active" in d:
        db.set_active(uid, bool(d["is_active"]))
    return jsonify({"ok": True})


@app.route("/api/admin/groups")
def admin_groups():
    _u, err = require_admin()
    if err: return err
    return jsonify(db.all_groups_admin())


@app.route("/api/admin/files")
def admin_files():
    _u, err = require_admin()
    if err: return err
    return jsonify(db.list_files())


@app.route("/api/admin/messages")
def admin_messages():
    _u, err = require_admin()
    if err: return err
    limit = min(int(request.args.get("limit", 50)), 500)
    c = db.get_db()
    rows = c.execute("SELECT m.id, m.chat_type, m.text, m.created_at, m.deleted,"
                     " u.display_name AS sender, g.name AS group_name"
                     " FROM messages m JOIN users u ON u.id=m.sender_id"
                     " LEFT JOIN groups g ON g.id=m.group_id AND m.chat_type='group'"
                     " ORDER BY m.id DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return jsonify([dict(r) for r in rows])


# ---------------- WebSocket ----------------

@socketio.on("connect")
def ws_connect():
    token = (request.args.get("token") or "").strip()
    u = db.user_by_token(token)
    if not u or not u["is_active"]:
        return False
    from flask import session
    session["uid"] = u["id"]
    ONLINE_SOCKETS.setdefault(u["id"], set()).add(request.sid)
    emit("joined", {"user_id": u["id"]})
    socketio.enter_room("user_%s" % u["id"])
    if len(ONLINE_SOCKETS[u["id"]]) == 1:
        db.set_status(u["id"], "online")
        socketio.emit("presence", {"user_id": u["id"], "status": "online"})


@socketio.on("disconnect")
def ws_disconnect():
    from flask import session
    uid = session.get("uid")
    if not uid:
        return
    s = ONLINE_SOCKETS.get(uid, set())
    s.discard(request.sid)
    if not s:
        ONLINE_SOCKETS.pop(uid, None)
        db.set_status(uid, "offline")
        socketio.emit("presence", {"user_id": uid, "status": "offline"})


@socketio.on("ping_alive")
def ws_ping():
    from flask import session
    uid = session.get("uid")
    if uid:
        db.set_status(uid, "online")


@socketio.on("set_away")
def ws_away():
    from flask import session
    uid = session.get("uid")
    if uid:
        db.set_status(uid, "away")
        socketio.emit("presence", {"user_id": uid, "status": "away"})


@socketio.on("set_online")
def ws_online():
    from flask import session
    uid = session.get("uid")
    if uid:
        db.set_status(uid, "online")
        socketio.emit("presence", {"user_id": uid, "status": "online"})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5000)))
    p.add_argument("--host", default="0.0.0.0")
    a = p.parse_args()
    db.init_db()
    print("Сервер КорпМессенджера: http://%s:%d  (логин по умолчанию admin/admin123)"
          % ("127.0.0.1", a.port))
    socketio.run(app, host=a.host, port=a.port, debug=False, allow_unsafe_werkzeug=True)
