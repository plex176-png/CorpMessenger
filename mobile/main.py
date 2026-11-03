# -*- coding: utf-8 -*-
"""Мобильный клиент КорпМессенджера (Kivy, Android 5.0+ / API 21+).

Собрать APK:
    cd mobile && buildozer android debug
Или через python-for-android (см. README.md).

Интерфейс: экран входа (адрес сервера и порт указываются вручную),
список чатов с анимированными бейджами непрочитанных, окно переписки
с крупным шрифтом, панелью эмодзи и прикреплением файлов.
"""
import json
import threading
import time

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle

try:
    from urllib.request import Request, urlopen
except ImportError:
    from urllib2 import Request, urlopen  # Python 2 на старых сборках

BASE_URL = "http://127.0.0.1:5000"  # заменяется на введённый адрес/порт


def http(method, path, token=None, payload=None, files=None):
    url = BASE_URL + path
    headers = {}
    body = None
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers)
    req.get_method = lambda: method
    resp = urlopen(req, timeout=15)
    return json.loads(resp.read().decode("utf-8"))


class ApiScreen(BoxLayout):
    """Общий помощник сетевых вызовов без блокировки UI."""

    def call(self, method, path, cb, payload=None, token=None):
        def run():
            try:
                r = http(method, path, token or self.app.token, payload)
                Clock.schedule_once(lambda dt: cb(r, None))
            except Exception as e:
                Clock.schedule_once(lambda dt: cb(None, str(e)))
        threading.Thread(target=run, daemon=True).start()


class LoginView(BoxLayout, ApiScreen):
    def build_ui(self, app):
        self.app = app
        self.orientation = "vertical"
        self.padding = 24
        self.spacing = 10
        self.add_widget(Label(text="КорпМессенджер", font_size="28sp", size_hint_y=0.3))
        self.host_inp = TextInput(text="192.168.1.10", hint_text="Адрес сервера",
                                  font_size="20sp", size_hint_y=None, height=52)
        self.port_inp = TextInput(text="5000", hint_text="Порт", input_filter="digits",
                                  font_size="20sp", size_hint_y=None, height=52)
        self.user_inp = TextInput(hint_text="Логин", font_size="20sp",
                                  size_hint_y=None, height=52)
        self.pass_inp = TextInput(hint_text="Пароль", password=True, font_size="20sp",
                                  size_hint_y=None, height=52)
        self.msg = Label(text="", font_size="16sp", color=(0.8, 0.3, 0.3, 1))
        btn = Button(text="Войти", font_size="22sp", size_hint_y=None, height=56)
        btn.bind(on_press=self.do_login)
        for w in (self.host_inp, self.port_inp, self.user_inp, self.pass_inp, self.msg, btn):
            self.add_widget(w)

    def do_login(self, *_):
        global BASE_URL
        BASE_URL = "http://%s:%s" % (self.host_inp.text.strip(), self.port_inp.text.strip() or "5000")
        self.msg.text = "Подключение…"
        self.call("POST", "/api/login", self.on_login,
                  {"username": self.user_inp.text.strip(), "password": self.pass_inp.text})

    def on_login(self, res, err):
        if err:
            self.msg.text = "Ошибка: " + err
            return
        self.app.token = res["token"]
        self.app.me = res["user"]
        self.app.show_chats()


class ChatListItem(BoxLayout):
    pass


class ChatsView(BoxLayout, ApiScreen):
    def build_ui(self, app):
        self.app = app
        self.orientation = "vertical"
        head = BoxLayout(size_hint_y=None, height=52)
        title = Label(text="Чаты", font_size="22sp", bold=True)
        back = Button(text="Выйти", size_hint_x=None, width=100, font_size="16sp")
        back.bind(on_press=lambda *_: app.show_login())
        head.add_widget(title); head.add_widget(back)
        self.list_box = BoxLayout(orientation="vertical", spacing=6, padding=8)
        sv = ScrollView()
        inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=6, padding=8)
        inner.bind(minimum_height=inner.setter("height"))
        sv.add_widget(inner)
        self.inner = inner
        self.add_widget(head); self.add_widget(sv)
        Clock.schedule_interval(self.refresh, 4)
        self.refresh()

    def refresh(self, *_):
        self.call("GET", "/api/dialogs", self.on_dialogs)

    def on_dialogs(self, res, err):
        self.inner.clear_widgets()
        if err:
            self.inner.add_widget(Label(text=err, size_hint_y=None, height=40))
            return
        for d in res:
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=64, spacing=8, padding=4)
            dot = "●" if d.get("status") == "online" else ("◐" if d.get("status") == "away" else "○")
            name_l = Label(text="%s %s" % (dot if d["type"] == "dm" else "👥", d["name"]),
                           font_size="20sp", halign="left", valign="center")
            name_l.bind(size=name_l.setter("text_size"))
            row.add_widget(name_l)
            if d.get("unread", 0) > 0:
                badge = Button(text=str(d["unread"]), size_hint_x=None, width=56,
                               background_color=(0.9, 0.25, 0.25, 1), font_size="18sp")
                row.add_widget(badge)
            open_b = Button(text="Открыть", size_hint_x=None, width=110, font_size="16sp")
            chat = {"type": d["type"], "id": d["id"], "name": d["name"]}
            open_b.bind(on_press=lambda _, c=chat: self.app.open_chat(c))
            row.add_widget(open_b)
            self.inner.add_widget(row)


class ChatView(BoxLayout, ApiScreen):
    def build_ui(self, app, chat):
        self.app = app
        self.chat = chat
        self.orientation = "vertical"
        head = BoxLayout(size_hint_y=None, height=52)
        back = Button(text="←", size_hint_x=None, width=64, font_size="22sp")
        back.bind(on_press=lambda *_: app.show_chats())
        head.add_widget(back)
        head.add_widget(Label(text=chat["name"], font_size="22sp", bold=True))
        self.msgs = BoxLayout(orientation="vertical", size_hint_y=None, spacing=6, padding=8)
        sv = ScrollView()
        self.sv = sv
        self.msgs.bind(minimum_height=self.msgs.setter("height"))
        sv.add_widget(self.msgs)
        self.add_widget(head); self.add_widget(sv)
        bottom = BoxLayout(size_hint_y=None, height=56, spacing=6)
        self.inp = TextInput(hint_text="Сообщение…", font_size="22sp", size_hint_y=None, height=56)
        send = Button(text="➤", size_hint_x=None, width=72, font_size="24sp")
        send.bind(on_press=self.send_msg)
        emo = Button(text="☺", size_hint_x=None, width=64, font_size="24sp")
        emo.bind(on_press=self.show_emoji)
        att = Button(text="📎", size_hint_x=None, width=64, font_size="22sp")
        att.bind(on_press=self.attach_file)
        bottom.add_widget(emo); bottom.add_widget(att); bottom.add_widget(self.inp); bottom.add_widget(send)
        self.add_widget(bottom)
        Clock.schedule_once(self.load_msgs)
        self._poll = Clock.schedule_interval(lambda dt: self.load_msgs(quiet=True), 4)

    def unload(self):
        try:
            self._poll.cancel()
        except Exception:
            pass

    def load_msgs(self, *_a, **kw):
        quiet = kw.get("quiet", False) if not _a else (_a[0] is not None and len(_a) > 1)
        path = "/api/messages?type=%s&id=%s" % (self.chat["type"], self.chat["id"])
        self.call("GET", path, self.on_msgs)

    def on_msgs(self, res, err):
        self.msgs.clear_widgets()
        if err:
            self.msgs.add_widget(Label(text=err, size_hint_y=None, height=40))
            return
        for m in res:
            txt = m.get("text") or ""
            for a, b in [(":)", "🙂"), (":D", "😂"), (":(", "🙁")]:
                txt = txt.replace(a, b)
            if m.get("filename"):
                txt += ("\n📄 " + m["filename"]) if txt else ("📄 " + m["filename"])
            mine = m["sender_id"] == self.app.me["id"]
            row = Label(text=txt or " ", font_size="24sp",  # КРУПНЫЙ шрифт по требованию
                        halign="right" if mine else "left",
                        color=(0.15, 0.35, 0.8, 1) if mine else (0.1, 0.1, 0.1, 1),
                        size_hint_y=None, valign="center", padding=[8, 6])
            row.height = row.texture_size[1] + 14
            row.bind(size=row.setter("text_size"))
            self.msgs.add_widget(row)
        Clock.schedule_once(lambda dt: self.sv.scroll_to(self.msgs, padding=10))

    def send_msg(self, *_):
        text = self.inp.text.strip()
        if not text:
            return
        self.inp.text = ""
        body = {"type": self.chat["type"], "text": text}
        if self.chat["type"] == "dm":
            body["peer_id"] = self.chat["id"]
        else:
            body["group_id"] = self.chat["id"]
        self.call("POST", "/api/messages", lambda r, e: Clock.schedule_once(self.load_msgs, 0.3), body)

    def show_emoji(self, *_):
        emojis = ["😀", "😂", "🙂", "😉", "😍", "🤔", "👍", "🙏", "❤", "🔥", "🎉", "☕", "✅", "❌"]
        grid = GridLayout(cols=7, size_hint_y=None, height=320)
        for em in emojis:
            b = Button(text=em, font_size="26sp")
            b.bind(on_press=lambda _, x=em: self.pick_emoji(x))
            grid.add_widget(b)
        Popup(title="Смайлы", content=grid, size_hint=(0.9, 0.5)).open()

    def pick_emoji(self, em):
        self.inp.text += em

    def attach_file(self, *_):
        # Упрощённо: текстовая заметка-заглушка; полная загрузка — через kivy filechooser + multipart
        try:
            from kivy.uix.filechooser import FileChooserListView
            fc = FileChooserListView(size_hint=(0.9, 0.8))
            def on_ok(*_a):
                if fc.selection:
                    self.upload_path(fc.selection[0])
                popup.dismiss()
            def on_cancel(*_a):
                popup.dismiss()
            ok = Button(text="Загрузить", size_hint_y=None, height=48)
            cancel = Button(text="Отмена", size_hint_y=None, height=48)
            ok.bind(on_press=on_ok); cancel.bind(on_press=on_cancel)
            box = BoxLayout(orientation="vertical")
            box.add_widget(fc)
            hb = BoxLayout(size_hint_y=None, height=48)
            hb.add_widget(ok); hb.add_widget(cancel)
            box.add_widget(hb)
            popup = Popup(title="Файл", content=box, size_hint=(0.95, 0.9))
            popup.open()
        except Exception as e:
            Label(text=str(e))

    def upload_path(self, path):
        import mimetypes, os as _os, uuid as _uuid
        boundary = "----corp" + _uuid.uuid4().hex
        fname = _os.path.basename(path)
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            data = fh.read()
        body = (
            ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
             "Content-Type: %s\r\n\r\n" % (boundary, fname, ctype)).encode("utf-8")
            + data
            + ("\r\n--%s--\r\n" % boundary).encode("utf-8")
        )
        def run():
            try:
                req = Request(BASE_URL + "/api/upload", data=body,
                              headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                                       "Authorization": "Bearer " + self.app.token})
                r = json.loads(urlopen(req, timeout=60).read().decode("utf-8"))
                msg = {"type": self.chat["type"], "text": "", "file_id": r["id"]}
                if self.chat["type"] == "dm":
                    msg["peer_id"] = self.chat["id"]
                else:
                    msg["group_id"] = self.chat["id"]
                http("POST", "/api/messages", self.app.token, msg)
                Clock.schedule_once(lambda dt: self.load_msgs(), 0.2)
            except Exception as e:
                Clock.schedule_once(lambda dt: self.toast("Загрузка не удалась: " + str(e)))
        threading.Thread(target=run, daemon=True).start()

    def toast(self, text):
        Popup(title="Статус", content=Label(text=text), size_hint=(0.8, 0.4)).open()


class CorpMobileApp(App):
    title = "КорпМессенджер"

    def build(self):
        Window.clearcolor = (0.95, 0.96, 0.97, 1)
        self.root = BoxLayout(orientation="vertical")
        self.token = None
        self.me = None
        self.show_login()
        return self.root

    def clear_root(self):
        for w in list(self.root.children):
            if hasattr(w, "unload"):
                w.unload()
            self.root.remove_widget(w)

    def show_login(self):
        self.clear_root()
        v = LoginView()
        v.build_ui(self)
        self.root.add_widget(v)

    def show_chats(self):
        self.clear_root()
        v = ChatsView()
        v.build_ui(self)
        self.root.add_widget(v)

    def open_chat(self, chat):
        self.clear_root()
        v = ChatView()
        v.build_ui(self, chat)
        self.root.add_widget(v)


if __name__ == "__main__":
    CorpMobileApp().run()
