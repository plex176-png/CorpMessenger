#!/usr/bin/env python3
import json, urllib.request

BASE = "http://127.0.0.1:5000"

def req(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]

st, j = req("POST", "/api/login", body={"username": "admin", "password": "admin123"})
assert st == 200, (st, j)
adm = j["token"]

st, j = req("POST", "/api/admin/users", adm, {"username": "pete", "password": "pete12345", "display_name": "Пётр", "role": "user"})
print("create user:", st, str(j)[:80])

st, j = req("POST", "/api/login", body={"username": "pete", "password": "pete12345"})
assert st == 200, (st, j)
pete = j["token"]; pete_id = j["user"]["id"]

st, j = req("POST", "/api/contacts", pete, {"contact_id": 1})
print("add contact:", st, j)
assert st == 200, "контакт не добавлен!"

st, j = req("GET", "/api/contacts", pete)
print("contacts list:", st, len(j.get("contacts", [])))

st, j = req("POST", "/api/messages", pete, {"type": "dm", "peer_id": 1, "text": "Привет, это тест"})
print("send msg:", st, str(j)[:80])
mid = j.get("id")
assert mid, "нет id сообщения"

st, j = req("POST", "/api/messages/%d/react" % mid, adm, {"emoji": "\U0001F44D"})
print("reaction thumbs-up:", st, j)
assert st == 200, "реакция не поставлена! (баг 500)"

st, j = req("POST", "/api/messages/%d/react" % mid, adm, {"emoji": "\u2764\ufe0f"})
print("reaction heart replaces:", st, j)
assert st == 200 and len(j["reactions"]) == 1, j

st, j = req("POST", "/api/messages/%d/react" % mid, adm, {"emoji": "\u2764\ufe0f"})
print("toggle-off:", st, j)
assert st == 200 and len(j["reactions"]) == 0, j

st, j = req("POST", "/api/messages/%d/react" % mid, adm, {"emoji": "\U0001F44D"})
st, j = req("GET", "/api/messages?type=dm&id=%d" % pete_id, adm)
msgs = j if isinstance(j, list) else j.get("messages", [])
found = [m for m in msgs if m["id"] == mid]
print("history has reactions field:", bool(found) and "reactions" in found[0], found[0].get("reactions") if found else None)

st, j = req("GET", "/api/profile/%d" % pete_id, adm)
print("profile:", st, str(j)[:120])

print("\nALL TESTS PASSED")
