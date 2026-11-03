# -*- coding: utf-8 -*-
"""Слой работы с БД (SQLite). Совместимо с Python 3.7+.
Для личных сообщений поле messages.group_id хранит id собеседника (peer_id)."""
import os, re, secrets, hashlib, sqlite3, time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "..", "messenger.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "..", "uploads")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'offline',
    last_seen INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS group_members (
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at INTEGER NOT NULL,
    PRIMARY KEY (group_id, user_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_type TEXT NOT NULL,
    group_id INTEGER,
    sender_id INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    file_id INTEGER,
    created_at INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_msg_group ON messages(group_id, created_at);
CREATE INDEX IF NOT EXISTS idx_msg_sender ON messages(sender_id, created_at);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uploader_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    mimetype TEXT NOT NULL DEFAULT 'application/octet-stream',
    size INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reads (
    user_id INTEGER NOT NULL,
    chat_key TEXT NOT NULL,
    last_read_msg_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, chat_key)
);
CREATE TABLE IF NOT EXISTS contacts (
    user_id INTEGER NOT NULL,
    contact_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, contact_id)
);
"""

def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def get_db():
    return _connect()

class Tx:
    def __init__(self): self.conn = None
    def __enter__(self):
        self.conn = _connect(); return self.conn
    def __exit__(self, t, e, tb):
        try:
            if t is None: self.conn.commit()
            else: self.conn.rollback()
        finally: self.conn.close()
        return False

def tx(): return Tx()

def init_db(admin_username="admin", admin_password="admin123"):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    if os.path.exists(DB_PATH):
        try:
            c = _connect(); c.execute("SELECT count(*) FROM users").fetchone(); c.close()
        except sqlite3.DatabaseError:
            try: os.replace(DB_PATH, DB_PATH + ".broken")
            except OSError: os.remove(DB_PATH)
    c = _connect(); c.executescript(SCHEMA); c.commit(); c.close()
    _migrate()
    c = _connect()
    n = c.execute("SELECT count(*) AS n FROM users WHERE role='admin'").fetchone()["n"]
    if n == 0:
        h, s = hash_password(admin_password)
        c.execute("INSERT INTO users(username, display_name, password_hash, salt, role, created_at)"
                  " VALUES(?,?,?,?,?,?)", (admin_username, "Администратор", h, s, "admin", int(time.time())))
        c.commit()
    c.close()

def _migrate():
    c = _connect()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(users)").fetchall()}
    if "status" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'offline'")
    if "last_seen" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN last_seen INTEGER NOT NULL DEFAULT 0")
    if "is_active" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    c.commit(); c.close()

def hash_password(password, salt=None):
    if salt is None: salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return dk.hex(), salt

def verify_password(password, password_hash, salt):
    h, _ = hash_password(password, salt)
    return secrets.compare_digest(h, password_hash)

def create_token(user_id):
    token = secrets.token_hex(32)
    with tx() as c:
        c.execute("INSERT INTO tokens(token, user_id, created_at) VALUES(?,?,?)",
                  (token, user_id, int(time.time())))
    return token

def user_by_token(token):
    if not token: return None
    c = _connect()
    row = c.execute("SELECT u.* FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?",
                    (token,)).fetchone()
    c.close(); return row

def revoke_token(token):
    with tx() as c: c.execute("DELETE FROM tokens WHERE token=?", (token,))

def get_user(user_id):
    c = _connect(); r = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone(); c.close(); return r

def list_users(include_blocked=False):
    c = _connect()
    q = ("SELECT id, username, display_name, role, status, last_seen, is_active FROM users"
         + ("" if include_blocked else " WHERE is_active=1") + " ORDER BY username")
    rows = c.execute(q).fetchall(); c.close()
    return [dict(r) for r in rows]

def set_status(user_id, status):
    if status not in ("online", "away", "offline"): status = "offline"
    with tx() as c:
        c.execute("UPDATE users SET status=?, last_seen=? WHERE id=?",
                  (status, int(time.time()), user_id))

def set_active(user_id, active):
    with tx() as c:
        c.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id))
        if not active:
            c.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))
            c.execute("UPDATE users SET status='offline' WHERE id=?", (user_id,))

def set_role(user_id, role):
    if role not in ("user", "admin"): raise ValueError("bad role")
    with tx() as c: c.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))

def create_user(username, password, display_name="", role="user"):
    username = (username or "").strip()
    if not re.match(r"^[A-Za-z0-9_.-]{3,32}$", username):
        raise ValueError("Логин: 3–32 символа, латиница/цифры/_-.")
    if len(password or "") < 6: raise ValueError("Пароль не короче 6 символов")
    h, s = hash_password(password)
    with tx() as c:
        c.execute("INSERT INTO users(username, display_name, password_hash, salt, role, created_at)"
                  " VALUES(?,?,?,?,?,?)", (username, display_name or username, h, s, role, int(time.time())))

def delete_user(user_id):
    with tx() as c:
        msgs = [r["id"] for r in c.execute("SELECT id FROM messages WHERE sender_id=?", (user_id,)).fetchall()]
        gids = [r["group_id"] for r in c.execute("SELECT group_id FROM group_members WHERE user_id=?", (user_id,)).fetchall()]
        c.execute("DELETE FROM messages WHERE sender_id=?", (user_id,))
        c.execute("DELETE FROM files WHERE uploader_id=?", (user_id,))
        c.execute("DELETE FROM group_members WHERE user_id=?", (user_id,))
        for gid in gids:
            left = c.execute("SELECT count(*) n FROM group_members WHERE group_id=?", (gid,)).fetchone()["n"]
            if left == 0:
                c.execute("DELETE FROM groups WHERE id=?", (gid,))
            else:
                own = c.execute("SELECT owner_id FROM groups WHERE id=?", (gid,)).fetchone()
                if own and own["owner_id"] == user_id:
                    adm = c.execute("SELECT gm.user_id FROM group_members gm JOIN users u ON u.id=gm.user_id"
                                    " WHERE gm.group_id=? AND u.is_active=1"
                                    " ORDER BY CASE WHEN u.role='admin' THEN 0 ELSE 1 END LIMIT 1", (gid,)).fetchone()
                    if adm: c.execute("UPDATE groups SET owner_id=? WHERE id=?", (adm["user_id"], gid))
        c.execute("DELETE FROM contacts WHERE user_id=? OR contact_id=?", (user_id, user_id))
        c.execute("DELETE FROM reads WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM tokens WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
    return {"deleted_messages": len(msgs)}

def add_contact(user_id, contact_id):
    with tx() as c:
        c.execute("INSERT OR IGNORE INTO contacts(user_id, contact_id, created_at) VALUES(?,?,?)",
                  (user_id, contact_id, int(time.time())))

def remove_contact(user_id, contact_id):
    with tx() as c:
        c.execute("DELETE FROM contacts WHERE user_id=? AND contact_id=?", (user_id, contact_id))

def is_contact(user_id, contact_id):
    c = _connect()
    r = c.execute("SELECT 1 FROM contacts WHERE user_id=? AND contact_id=?", (user_id, contact_id)).fetchone()
    c.close(); return r is not None

def list_contacts(user_id):
    c = _connect()
    rows = c.execute("SELECT u.id, u.username, u.display_name, u.status, u.last_seen,"
                     " (SELECT m.text FROM messages m WHERE m.chat_type='dm' AND m.deleted=0"
                     "   AND ((m.sender_id=? AND m.group_id=u.id) OR (m.sender_id=u.id AND m.group_id=?))"
                     "   ORDER BY m.id DESC LIMIT 1) AS last_text"
                     " FROM contacts ct JOIN users u ON u.id=ct.contact_id"
                     " WHERE ct.user_id=? AND u.is_active=1 ORDER BY u.display_name",
                     (user_id, user_id, user_id)).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r); d["unread"] = unread_count(user_id, "dm:%d" % d["id"]); out.append(d)
    return out

def chat_key_for(user_id, chat_type, chat_id):
    """Единый нормализованный ключ чата для reads/unread (для ЛС — симметричный).

    Для личных сообщений в качестве chat_id передаётся id СОБЕСЕДНИКА:
    ключ строится как 'dm:<min>:<max>', поэтому у обеих сторон диалога он одинаков.
    """
    if chat_type == "dm":
        a, b = sorted((int(chat_id), int(user_id)))
        return "dm:%d:%d" % (a, b)
    return "group:%d" % int(chat_id)

def insert_message(chat_type, sender_id, text="", group_id=None, file_id=None, peer_id=None):
    with tx() as c:
        if chat_type == "dm":
            # Для ЛС в колонке group_id хранится id СОБЕСЕДНИКА (не отправителя),
            # иначе диалог не найдётся у получателя.
            other = peer_id if peer_id is not None else sender_id
            cur = c.execute("INSERT INTO messages(chat_type, group_id, sender_id, text, file_id, created_at)"
                            " VALUES('dm', ?,?,?,?,?)", (other, sender_id, text, file_id, int(time.time())))
        else:
            cur = c.execute("INSERT INTO messages(chat_type, group_id, sender_id, text, file_id, created_at)"
                            " VALUES('group', ?,?,?,?,?)", (group_id, sender_id, text, file_id, int(time.time())))
        return cur.lastrowid

def message_with_names(mid):
    c = _connect()
    r = c.execute("SELECT m.*, u.username AS sender_username, u.display_name AS sender_name,"
                  " f.filename, f.mimetype, f.size FROM messages m JOIN users u ON u.id=m.sender_id"
                  " LEFT JOIN files f ON f.id=m.file_id WHERE m.id=?", (mid,)).fetchone()
    c.close(); return dict(r) if r else None

def chat_messages(chat_type, chat_id, user_id, limit=100):
    c = _connect()
    if chat_type == "dm":
        rows = c.execute("SELECT m.*, u.username AS sender_username, u.display_name AS sender_name,"
                         " f.filename, f.mimetype, f.size FROM messages m"
                         " JOIN users u ON u.id=m.sender_id LEFT JOIN files f ON f.id=m.file_id"
                         " WHERE m.deleted=0 AND m.chat_type='dm' AND ("
                         "  (m.sender_id=? AND m.group_id=?) OR (m.sender_id=? AND m.group_id=?))"
                         " ORDER BY m.id DESC LIMIT ?",
                         (user_id, chat_id, chat_id, user_id, limit)).fetchall()
    else:
        rows = c.execute("SELECT m.*, u.username AS sender_username, u.display_name AS sender_name,"
                         " f.filename, f.mimetype, f.size FROM messages m"
                         " JOIN users u ON u.id=m.sender_id LEFT JOIN files f ON f.id=m.file_id"
                         " WHERE m.deleted=0 AND m.chat_type='group' AND m.group_id=?"
                         " ORDER BY m.id DESC LIMIT ?", (chat_id, limit)).fetchall()
    c.close()
    return [dict(r) for r in reversed(rows)]

def mark_read(user_id, chat_key, msg_id):
    # Отметка о прочтении не должна уменьшать уже сохранённую метку.
    with tx() as c:
        cur = c.execute("UPDATE reads SET last_read_msg_id=? WHERE user_id=? AND chat_key=? AND last_read_msg_id<?",
                        (msg_id, user_id, chat_key, msg_id))
        if cur.rowcount == 0:
            exists = c.execute("SELECT 1 FROM reads WHERE user_id=? AND chat_key=?", (user_id, chat_key)).fetchone()
            if not exists:
                c.execute("INSERT INTO reads(user_id, chat_key, last_read_msg_id) VALUES(?,?,?)",
                          (user_id, chat_key, msg_id))

def unread_count(user_id, chat_key):
    """Количество непрочитанных сообщений в чате.

    Ключ 'dm:<id>'/'dm:<a>:<b>' трактуется ОДНОЗНАЧНО: <id>/<a>,<b> — это
    собеседник (или пара id), а не «второй участник относительно user_id».
    Поэтому счётчик у обеих сторон диалога симметричен и не зависит от того,
    кто именно вызвал mark_read."""
    c = _connect()
    try:
        kind, arg = chat_key.split(":", 1)
        if kind == "dm":
            parts = [int(x) for x in arg.split(":") if x != ""]
            if len(parts) == 2:
                a, b = sorted(parts)
                peer = b if a == int(user_id) else a
            else:
                peer = int(arg)
            key = "dm:%d:%d" % tuple(sorted((peer, int(user_id))))
            sql = ("SELECT count(*) n FROM messages WHERE deleted=0 AND chat_type='dm'"
                   " AND ((sender_id=? AND group_id=?) OR (sender_id=? AND group_id=?)) AND id>?")
            args = (user_id, peer, peer, user_id)
        else:
            key = "group:%d" % int(arg)
            sql = ("SELECT count(*) n FROM messages WHERE deleted=0 AND chat_type='group'"
                   " AND group_id=? AND id>? AND sender_id<>?")
            args = (int(arg),)
        lr = c.execute("SELECT last_read_msg_id FROM reads WHERE user_id=? AND chat_key=?",
                       (user_id, key)).fetchone()
        last_read = lr["last_read_msg_id"] if lr else 0
        if kind == "dm":
            n = c.execute(sql, args + (last_read,)).fetchone()["n"]
        else:
            n = c.execute(sql, args + (last_read, user_id)).fetchone()["n"]
        return n
    finally:
        c.close()

def total_unread(user_id):
    keys = set()
    c = _connect()
    for r in c.execute("SELECT DISTINCT group_id AS pid FROM messages WHERE chat_type='dm'"
                      " AND sender_id<>? AND deleted=0 AND group_id IS NOT NULL", (user_id,)).fetchall():
        keys.add("dm:%d" % r["pid"])
    for r in c.execute("SELECT gm.group_id FROM group_members gm JOIN messages m ON m.group_id=gm.group_id"
                       " WHERE gm.user_id=? AND m.chat_type='group' AND m.deleted=0 GROUP BY gm.group_id",
                       (user_id,)).fetchall():
        keys.add("group:%d" % r["group_id"])
    c.close()
    return sum(unread_count(user_id, k) for k in keys)

def delete_message(mid, hard=False):
    c = _connect(); r = c.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone(); c.close()
    if not r: return None
    with tx() as c:
        if hard: c.execute("DELETE FROM messages WHERE id=?", (mid,))
        else: c.execute("UPDATE messages SET deleted=1 WHERE id=?", (mid,))
    return dict(r)

def save_file(user_id, orig_name, stored_name, mimetype, size):
    with tx() as c:
        cur = c.execute("INSERT INTO files(uploader_id, filename, stored_name, mimetype, size, created_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (user_id, orig_name, stored_name, mimetype or "application/octet-stream",
                         size, int(time.time())))
        return cur.lastrowid

def get_file(fid):
    c = _connect(); r = c.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone(); c.close()
    return dict(r) if r else None

def list_files(limit=200):
    c = _connect()
    rows = c.execute("SELECT f.*, u.username AS uploader FROM files f JOIN users u ON u.id=f.uploader_id"
                     " ORDER BY f.id DESC LIMIT ?", (limit,)).fetchall()
    c.close(); return [dict(r) for r in rows]

def create_group(name, owner_id):
    with tx() as c:
        cur = c.execute("INSERT INTO groups(name, owner_id, created_at) VALUES(?,?,?)",
                        (name, owner_id, int(time.time())))
        gid = cur.lastrowid
        c.execute("INSERT INTO group_members(group_id, user_id, role, joined_at) VALUES(?,?,?,?)",
                  (gid, owner_id, "owner", int(time.time())))
        return gid

def my_groups(user_id):
    c = _connect()
    rows = c.execute("SELECT g.id, g.name, g.owner_id, gm.role,"
                     " (SELECT count(*) FROM group_members x WHERE x.group_id=g.id) AS members,"
                     " (SELECT m.text FROM messages m WHERE m.group_id=g.id AND m.deleted=0"
                     "  ORDER BY m.id DESC LIMIT 1) AS last_text"
                     " FROM groups g JOIN group_members gm ON gm.group_id=g.id AND gm.user_id=?"
                     " ORDER BY g.name", (user_id,)).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r); d["unread"] = unread_count(user_id, "group:%d" % d["id"]); out.append(d)
    return out

def group_info(gid):
    c = _connect()
    g = c.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
    if not g: c.close(); return None
    members = c.execute("SELECT gm.user_id, gm.role, u.username, u.display_name, u.status"
                        " FROM group_members gm JOIN users u ON u.id=gm.user_id WHERE gm.group_id=?"
                        " ORDER BY CASE gm.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, u.display_name",
                        (gid,)).fetchall()
    c.close()
    d = dict(g); d["members"] = [dict(m) for m in members]; return d

def all_groups_admin():
    c = _connect()
    rows = c.execute("SELECT g.id, g.name, g.owner_id, o.display_name AS owner_name,"
                     " (SELECT count(*) FROM group_members x WHERE x.group_id=g.id) AS members"
                     " FROM groups g JOIN users o ON o.id=g.owner_id ORDER BY g.name").fetchall()
    c.close(); return [dict(r) for r in rows]

def in_group(gid, uid):
    c = _connect()
    r = c.execute("SELECT 1 FROM group_members WHERE group_id=? AND user_id=?", (gid, uid)).fetchone()
    c.close(); return r is not None

def group_role(gid, uid):
    c = _connect()
    r = c.execute("SELECT role FROM group_members WHERE group_id=? AND user_id=?", (gid, uid)).fetchone()
    c.close(); return r["role"] if r else None

def add_member(gid, uid):
    with tx() as c:
        c.execute("INSERT OR IGNORE INTO group_members(group_id, user_id, role, joined_at) VALUES(?,?,?,?)",
                  (gid, uid, "member", int(time.time())))

def remove_member(gid, uid):
    with tx() as c:
        c.execute("DELETE FROM group_members WHERE group_id=? AND user_id=?", (gid, uid))

def set_member_role(gid, uid, role):
    if role not in ("owner", "admin", "member"): raise ValueError("bad role")
    with tx() as c:
        c.execute("UPDATE group_members SET role=? WHERE group_id=? AND user_id=?", (role, gid, uid))
        if role == "owner": c.execute("UPDATE groups SET owner_id=? WHERE id=?", (uid, gid))

def rename_group(gid, name):
    with tx() as c: c.execute("UPDATE groups SET name=? WHERE id=?", (name, gid))

def delete_group(gid):
    with tx() as c:
        c.execute("DELETE FROM messages WHERE chat_type='group' AND group_id=?", (gid,))
        c.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
        c.execute("DELETE FROM groups WHERE id=?", (gid,))

def dialogs(user_id):
    """Активные диалоги + контакты: единый список для клиента.
    Для ЛС переписка ведётся между id пользователя и id собеседника;
    в messages.group_id для dm хранится peer_id отправителя."""
    items = []
    seen = {}
    for g in my_groups(user_id):
        seen["group:%d" % g["id"]] = True
        items.append({"type": "group", "id": g["id"], "name": g["name"],
                      "unread": g["unread"], "members": g["members"], "last_text": g.get("last_text")})
    peers = {}
    c = _connect()
    rows = c.execute("SELECT sender_id AS s, group_id AS p FROM messages"
                     " WHERE chat_type='dm' AND deleted=0 AND (sender_id=? OR group_id=?)",
                     (user_id, user_id)).fetchall()
    c.close()
    for r in rows:
        other = r["p"] if r["s"] == user_id else r["s"]
        if other and other != user_id:
            peers[other] = True
    for ct in list_contacts(user_id):
        key = "dm:%d" % ct["id"]
        seen[key] = True
        peers[ct["id"]] = True
        items.append({"type": "dm", "id": ct["id"], "name": ct["display_name"],
                      "unread": unread_count(user_id, key), "status": ct["status"],
                      "last_text": ct.get("last_text"), "contact": True})
    for pid in peers:
        key = "dm:%d" % pid
        if key in seen: continue
        u = get_user(pid)
        if not u or not u["is_active"]: continue
        seen[key] = True
        items.append({"type": "dm", "id": pid, "name": u["display_name"],
                      "unread": unread_count(user_id, key), "status": u["status"],
                      "last_text": last_dm_text(user_id, pid)})
    return items


def last_dm_text(user_id, peer_id):
    c = _connect()
    r = c.execute("SELECT text FROM messages WHERE chat_type='dm' AND deleted=0 AND ("
                  "(sender_id=? AND group_id=?) OR (sender_id=? AND group_id=?))"
                  " ORDER BY id DESC LIMIT 1",
                  (user_id, peer_id, peer_id, user_id)).fetchone()
    c.close()
    return r["text"] if r else None

def stats():
    c = _connect()
    s = {
        "users": c.execute("SELECT count(*) n FROM users").fetchone()["n"],
        "active_users": c.execute("SELECT count(*) n FROM users WHERE is_active=1").fetchone()["n"],
        "online": c.execute("SELECT count(*) n FROM users WHERE status='online'").fetchone()["n"],
        "groups": c.execute("SELECT count(*) n FROM groups").fetchone()["n"],
        "messages": c.execute("SELECT count(*) n FROM messages WHERE deleted=0").fetchone()["n"],
    }
    fs = c.execute("SELECT COALESCE(sum(size),0) b, count(*) n FROM files").fetchone()
    c.close()
    s["storage_bytes"] = fs["b"]; s["files_count"] = fs["n"]
    return s
