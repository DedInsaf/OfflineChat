import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog
import os
import json
import time
import logging
import getpass
import socket
import subprocess
import uuid
import base64
import hashlib
import tempfile
from urllib.parse import quote

from online_chat import (
    load_chats as load_online_chats,
    load_profiles as load_online_profiles,
    load_server_url,
    load_username as load_online_user,
    normalize_username,
    online_worker as online_worker_v2,
    save_chats as save_online_chats,
    save_profiles as save_online_profiles,
    save_username as save_online_user,
    valid_username,
)

LOG_DIR = os.path.expanduser("~/Library/Logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "OfflineChat.log")
logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s")


def log(msg):
    logging.debug(msg)
    print(msg, flush=True)


SERVICE_UUID_STRING = "8F3A1000-7A91-4C91-AF20-000000000001"
CHARACTERISTIC_UUID_STRING = "8F3A1000-7A91-4C91-AF20-000000000002"
APP_NAME = "OfflineChat"
CONNECT_REQUEST_PREFIX = "OC_CONNECT_REQUEST|"
CONNECT_ACCEPT_PREFIX = "OC_CONNECT_ACCEPT|"
CONNECT_DENY_PREFIX = "OC_CONNECT_DENY|"
CONNECT_ACK_PREFIX = "OC_CONNECT_ACK|"
CHAT_MESSAGE_PREFIX = "OC_MESSAGE|"
TYPING_PREFIX = "OC_TYPING|"
DELIVERED_PREFIX = "OC_DELIV|"
READ_PREFIX = "OC_READ|"
SOS_PREFIX = "OC_SOS|"
OK_PREFIX = "OC_OK|"
LOC_PREFIX = "OC_LOC|"
ACCEPT_RETRY_LIMIT = 8
CTRL_TYPING = "::oc::t"
CTRL_DELIVERED = "::oc::d::"
CTRL_READ = "::oc::r::"
DATA_DIR = os.path.expanduser("~/Library/Application Support/OfflineChat")
os.makedirs(DATA_DIR, exist_ok=True)
NOTES_PATH = os.path.join(DATA_DIR, "notes.txt")
CARD_PATH = os.path.join(DATA_DIR, "card.json")
THEME_PATH = os.path.join(DATA_DIR, "theme.json")
LIGHT_BASE = {"bg": "#EFEAE2", "text": "#1C1915", "accent": "#1F4F46"}
DARK_BASE = {"bg": "#0B0F14", "text": "#E8EEF4", "accent": "#3EE0B4"}
THEME = {}
FONTS = {"body": "Helvetica Neue", "display": "Helvetica Neue"}

GUIDES = [
    ("Номера", "112 — единый номер.\n101 — пожарные.\n102 — полиция.\n103 — скорая.\n104 — газ.\nС мобильного 112 работает без SIM и без интернета."),
    ("Кровотечение", "Надавите на рану чистой тканью 10–15 минут, не подглядывая. Конечность выше сердца. Жгут — только если кровь фонтанирует. Запишите время наложения."),
    ("Нет дыхания", "Проверьте реакцию и дыхание 10 секунд. Зовите на помощь. 30 нажатий на центр груди (5–6 см) + 2 вдоха. 100–120 нажатий в минуту. Не останавливайтесь."),
    ("Человек давится", "Если кашляет — пусть кашляет. Если не дышит: 5 ударов между лопатками, затем 5 толчков в живот. Чередуйте."),
    ("Ожог", "Прохладная (не ледяная) вода 20 минут. Не масло, не лёд, не вата. Снимите кольца. Накройте чистой тканью."),
    ("Переохлаждение", "Укройте, снимите мокрое, тёплое сладкое питьё если в сознании. Не растирайте и не грейте резко."),
    ("Нет света", "Не открывайте холодильник без нужды. Телефон — в авиарежим, яркость вниз. Свеча дальше от штор. Если пахнет газом — не включайте свет, откройте окна, выйдите."),
    ("Пожар", "Держитесь низа, дышите через ткань. Не открывайте горячую дверь. Если загорелась одежда — катитесь по полу. Точку сбора — на улице."),
    ("Заблудились", "Остановитесь. Не уходите дальше в темноте. Три сигнала (свист, фонарь) — просьба о помощи. Если есть GPS — отметьте точку в приложении и оставайтесь."),
    ("Вода", "Кипятите 1 минуту (в горах — 3). Если нельзя кипятить: фильтр + таблетки. Не пейте из стоячих луж. Снег сначала растопите."),
    ("Фразы EN", "Help! — Помогите!\nI am lost. — Я заблудился.\nI need a doctor. — Нужен врач.\nCall 112. — Вызовите 112.\nI am here. — Я здесь.\nNo internet. — Нет интернета.\nWhere is the road? — Где дорога?"),
]


def hex_to_rgb(value):
    raw = str(value or "").lstrip("#")
    if len(raw) != 6:
        return (20, 20, 20)
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*[max(0, min(255, int(c))) for c in rgb])


def mix_hex(a, b, t):
    ar, ag, ab = hex_to_rgb(a)
    br, bg, bb = hex_to_rgb(b)
    return rgb_to_hex((ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t))


def luminance(value):
    r, g, b = [c / 255.0 for c in hex_to_rgb(value)]

    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def theme_is_dark(bg=None):
    return luminance(bg or THEME.get("bg", "#111")) < 0.45


def contrast_on(bg):
    return "#F4F1EA" if luminance(bg) < 0.45 else "#121418"


def build_palette(bg, text, accent):
    dark = luminance(bg) < 0.45
    surface = mix_hex(bg, text, 0.07 if dark else 0.05)
    surface_alt = mix_hex(bg, text, 0.13 if dark else 0.09)
    return {
        "bg": bg,
        "surface": surface,
        "surface_alt": surface_alt,
        "text": text,
        "muted": mix_hex(text, bg, 0.38),
        "subtle": mix_hex(text, bg, 0.55),
        "line": mix_hex(bg, text, 0.2),
        "primary": accent,
        "primary_hover": mix_hex(accent, text if dark else bg, 0.16),
        "primary_fg": contrast_on(accent),
        "accent": accent,
        "incoming": mix_hex(surface_alt, accent, 0.1),
        "outgoing": accent,
        "success": accent,
        "warning": "#E0B05A",
        "danger": "#E25B5B",
        "danger_hover": "#C94A4A",
        "chat_bg": mix_hex(bg, accent, 0.04),
    }


def default_theme_spec():
    return {"preset": "light", **LIGHT_BASE}


def load_theme_spec():
    try:
        with open(THEME_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict) and data.get("bg"):
                return data
    except Exception:
        pass
    return default_theme_spec()


def save_theme_spec(spec):
    try:
        with open(THEME_PATH, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"theme: {exc}")


def apply_theme_spec(spec):
    preset = spec.get("preset") or "custom"
    if preset == "light":
        base = LIGHT_BASE
    elif preset == "dark":
        base = DARK_BASE
    else:
        base = {
            "bg": spec.get("bg") or DARK_BASE["bg"],
            "text": spec.get("text") or DARK_BASE["text"],
            "accent": spec.get("accent") or DARK_BASE["accent"],
        }
    THEME.clear()
    THEME.update(build_palette(base["bg"], base["text"], base["accent"]))
    THEME["_spec"] = {"preset": preset, "bg": base["bg"], "text": base["text"], "accent": base["accent"]}


def lock_macos_appearance(dark=None, root=None):
    if dark is None:
        dark = theme_is_dark()
    if root is not None:
        try:
            root.tk.call("tk::unsupported::MacWindowStyle", "appearance", root._w, "darkaqua" if dark else "aqua")
        except Exception:
            try:
                root.tk.call("::tk::unsupported::MacWindowStyle", "appearance", ".", "darkaqua" if dark else "aqua")
            except Exception as exc:
                log(f"tk appearance: {exc}")
    try:
        from AppKit import NSApplication, NSAppearance
        app = NSApplication.sharedApplication()
        if app is None:
            return
        names = ["NSAppearanceNameDarkAqua"] if dark else ["NSAppearanceNameAqua"]
        appearance = None
        for name in names:
            appearance = NSAppearance.appearanceNamed_(name)
            if appearance is not None:
                break
        if appearance is None:
            return
        if app.respondsToSelector_("setAppearance:"):
            app.setAppearance_(appearance)
        try:
            for window in list(app.windows() or []):
                if window.respondsToSelector_("setAppearance:"):
                    window.setAppearance_(appearance)
        except Exception:
            pass
    except Exception as exc:
        log(f"appearance: {exc}")


def harden_tk(root):
    dark = theme_is_dark()
    lock_macos_appearance(dark, root=root)
    mapping = {
        "*Foreground": THEME["text"],
        "*Background": THEME["bg"],
        "*selectForeground": THEME["primary_fg"],
        "*selectBackground": THEME["primary"],
        "*insertBackground": THEME["text"],
        "*Entry.Foreground": THEME["text"],
        "*Entry.Background": THEME["surface_alt"],
        "*Entry.insertBackground": THEME["text"],
        "*Text.Foreground": THEME["text"],
        "*Text.Background": THEME["surface_alt"],
        "*Label.Foreground": THEME["text"],
        "*Label.Background": THEME["surface"],
        "*HighlightBackground": THEME["line"],
        "*HighlightColor": THEME["primary"],
    }
    for key, value in mapping.items():
        try:
            root.option_add(key, value)
        except Exception:
            pass
    try:
        root.configure(bg=THEME["bg"], highlightbackground=THEME["bg"])
    except Exception:
        pass


def desktop_notify(title, body):
    try:
        script = "display notification {} with title {} sound name \"Glass\"".format(
            json.dumps(str(body)[:140], ensure_ascii=False),
            json.dumps(str(title)[:48], ensure_ascii=False),
        )
        subprocess.Popen(["osascript", "-e", script])
    except Exception as exc:
        log(f"notify: {exc}")


def receipt_mark(status):
    return {"sending": "···", "sent": "✓", "delivered": "✓✓", "read": "✓✓", "failed": "!"}.get(status or "", "")


def is_control_body(text):
    value = str(text or "")
    return value == CTRL_TYPING or value.startswith(CTRL_DELIVERED) or value.startswith(CTRL_READ)


def parse_chat_payload(payload):
    raw = str(payload or "")
    mid, sep, rest = raw.partition("|")
    if sep and mid.strip().isdigit() and rest != "":
        return mid.strip(), rest
    return None, raw


def bind_click(widget, command):
    widget.bind("<Button-1>", lambda _e: command())
    try:
        widget.configure(cursor="hand2")
    except Exception:
        pass
    for child in widget.winfo_children():
        bind_click(child, command)


apply_theme_spec(load_theme_spec())


def init_fonts(root):
    families = set(tkfont.families(root))
    body = next((n for n in ("SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue", "Helvetica") if n in families), "TkDefaultFont")
    display = next((n for n in ("SF Pro Display", "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue") if n in families), body)
    FONTS["body"] = body
    FONTS["display"] = display
    harden_tk(root)


def ui_font(size=13, weight="normal"):
    return (FONTS["body"], size, weight)


def display_font(size=22, weight="bold"):
    return (FONTS["display"], size, weight)


def parent_bg(widget):
    try:
        return widget.cget("bg")
    except Exception:
        return THEME["surface"]


def default_display_name():
    return f"{(getpass.getuser() or 'User')}@{(socket.gethostname().split('.')[0] or 'Mac')}"


def advertised_name(display_name, sos=False):
    clean = (display_name or default_display_name()).strip() or "User"
    return f"SOS:{clean[:18]}" if sos else f"{APP_NAME}: {clean[:18]}"


def peer_name_from_advertisement(raw_name):
    raw = str(raw_name or APP_NAME)
    if raw.startswith("SOS:"):
        return raw[4:].strip() or "SOS"
    prefix = f"{APP_NAME}: "
    if raw.startswith(prefix):
        return raw[len(prefix):].strip() or "Собеседник"
    return "OfflineChat user" if raw == APP_NAME else raw


def advertisement_is_sos(raw_name):
    return str(raw_name or "").startswith("SOS:")


def parse_coords(value):
    try:
        lat_s, lng_s = str(value).split(",", 1)
        lat, lng = float(lat_s.strip()), float(lng_s.strip())
        if -90 <= lat <= 90 and -180 <= lng <= 180:
            return lat, lng
    except Exception:
        return None
    return None


def open_in_maps(coords, query="Точка"):
    parsed = parse_coords(coords)
    if not parsed:
        return False
    lat, lng = parsed
    label = quote(("".join(ch if ch.isalnum() or ch in " -_" else " " for ch in str(query))[:40]).strip() or "Точка")
    url = f"maps://?ll={lat},{lng}&q={label}&t=m"
    try:
        subprocess.Popen(["open", url])
        return True
    except Exception as exc:
        log(f"maps: {exc}")
        return False


def load_card():
    try:
        with open(CARD_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"blood": "", "allergies": "", "meds": "", "ice": "", "note": ""}


def save_card(data):
    try:
        with open(CARD_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        log(f"card: {exc}")


def load_notes():
    try:
        with open(NOTES_PATH, "r", encoding="utf-8") as handle:
            return handle.read()
    except Exception:
        return ""


def save_notes(text):
    try:
        with open(NOTES_PATH, "w", encoding="utf-8") as handle:
            handle.write(text)
    except Exception as exc:
        log(f"notes: {exc}")


def load_online_settings():
    return load_server_url()


def pack_sos(name, lat=None, lng=None, note=""):
    loc = f"{lat:.5f},{lng:.5f}" if lat is not None and lng is not None else "-"
    return SOS_PREFIX + "|".join([name or "SOS", loc, (note or "")[:80]])


def unpack_tagged(text, prefix):
    return [part.strip() for part in text[len(prefix):].split("|")]


def round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def initials_for(name):
    parts = [p for p in str(name or "?").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


class PillButton(tk.Canvas):
    def __init__(self, master, text, command=None, variant="primary", width=148, height=40, **kwargs):
        super().__init__(master, width=width, height=height, highlightthickness=0, bd=0, bg=parent_bg(master), cursor="hand2", **kwargs)
        self.command = command
        self.variant = variant
        self.label = text
        self._disabled = False
        self._hover = False
        palette = {
            "primary": (THEME["primary"], THEME["primary_fg"], THEME["primary_hover"]),
            "secondary": (THEME["surface_alt"], THEME["text"], THEME["line"]),
            "ghost": (THEME["surface"], THEME["muted"], THEME["surface_alt"]),
            "danger": (THEME["danger"], THEME["primary_fg"], THEME["danger_hover"]),
        }
        self.bg0, self.fg0, self.bg1 = palette.get(variant, palette["primary"])
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.after_idle(self.redraw)

    def configure_state(self, disabled):
        self._disabled = disabled
        self.configure(cursor="arrow" if disabled else "hand2")
        self.redraw()

    def set_text(self, text):
        self.label = text
        self.redraw()

    def _set_hover(self, on):
        self._hover = on
        self.redraw()

    def _press(self, _e):
        if not self._disabled and self.command:
            self.command()

    def _release(self, _e):
        pass

    def redraw(self):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        fill = THEME["line"] if self._disabled else (self.bg1 if self._hover else self.bg0)
        round_rect(self, 1, 1, w - 2, h - 2, h // 2, fill=fill, outline="")
        self.create_text(w / 2, h / 2, text=self.label, fill=self.fg0 if not self._disabled else THEME["subtle"], font=ui_font(13, "bold"))


def avatar_photo(encoded, size):
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
        digest = hashlib.sha256(raw).hexdigest()[:24]
        cache_dir = os.path.expanduser("~/Library/Caches/OfflineChat/avatars")
        os.makedirs(cache_dir, exist_ok=True)
        source = os.path.join(cache_dir, digest + ".image")
        rendered = os.path.join(cache_dir, f"{digest}-{int(size)}.png")
        if not os.path.exists(rendered):
            with open(source, "wb") as handle:
                handle.write(raw)
            subprocess.run(
                ["sips", "-Z", str(int(size)), "-s", "format", "png", source, "--out", rendered],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=True,
            )
        return tk.PhotoImage(file=rendered)
    except Exception:
        return None


class Avatar(tk.Canvas):
    def __init__(self, master, name, size=42, profile=None, **kwargs):
        super().__init__(master, width=size, height=size, highlightthickness=0, bd=0, bg=parent_bg(master), **kwargs)
        self.photo = avatar_photo((profile or {}).get("avatar_base64"), size - 4)
        if self.photo:
            self.create_image(size / 2, size / 2, image=self.photo)
        else:
            title = (profile or {}).get("display_name") or name
            self.create_oval(2, 2, size - 2, size - 2, fill=THEME["incoming"], outline="")
            self.create_text(size / 2, size / 2, text=initials_for(title), fill=THEME["accent"], font=ui_font(11 if size < 48 else 14, "bold"))


class ScrollFrame(tk.Frame):
    def __init__(self, master, bg=None, **kwargs):
        bg = bg or THEME["surface"]
        super().__init__(master, bg=bg, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bg)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.vsb = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window_id, width=e.width))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", self._wheel)
        self.canvas.bind("<Button-5>", self._wheel)
        self.inner.bind("<MouseWheel>", self._wheel)
        self.inner.bind("<Button-4>", self._wheel)
        self.inner.bind("<Button-5>", self._wheel)

    def _wheel(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def scroll_to_end(self):
        try:
            self.canvas.yview_moveto(1.0)
        except Exception:
            pass


class OnlineScrollFrame(ScrollFrame):
    """Trackpad handling scoped to the online transcript, including its labels."""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._window = self.winfo_toplevel()
        self._wheel_bindings = {
            sequence: self._window.bind(sequence, self._route_wheel, add="+")
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>")
        }
        self.bind("<Destroy>", self._remove_wheel_bindings, add="+")

    def _remove_wheel_bindings(self, event):
        if event.widget == self:
            for sequence, identifier in self._wheel_bindings.items():
                self._window.unbind(sequence, identifier)

    def _route_wheel(self, event):
        widget = event.widget
        while widget is not None:
            if widget == self:
                return self._wheel(event)
            widget = getattr(widget, "master", None)

    def _wheel(self, event):
        number = getattr(event, "num", None)
        if number in (4, 5):
            amount = -1 if number == 4 else 1
        else:
            delta = event.delta
            if not delta:
                return "break"
            divisor = 1 if self.tk.call("tk", "windowingsystem") == "aqua" else 120
            amount = int(-delta / divisor) or (-1 if delta > 0 else 1)
        if self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(amount, "units")
        return "break"


class IncomingDialog(tk.Frame):
    def __init__(self, master, peer_name, on_allow, on_deny):
        super().__init__(master, bg=THEME["bg"])
        self.on_allow = on_allow
        self.on_deny = on_deny
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lift()
        self.grab_set()
        shell = tk.Frame(self, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        shell.place(relx=0.5, rely=0.5, anchor="center", width=460, height=310)
        body = tk.Frame(shell, bg=THEME["surface"])
        body.pack(fill="both", expand=True, padx=28, pady=26)
        Avatar(body, peer_name, size=64).pack(anchor="w")
        tk.Label(body, text="Кто-то рядом стучится", bg=THEME["surface"], fg=THEME["text"], font=display_font(22, "bold"), anchor="w").pack(fill="x", pady=(16, 6))
        tk.Label(body, text=f"{peer_name} хочет открыть локальный канал.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(13), wraplength=360, justify="left", anchor="w").pack(fill="x")
        actions = tk.Frame(body, bg=THEME["surface"])
        actions.pack(fill="x", pady=(22, 0))
        PillButton(actions, "Отклонить", command=self._deny, variant="ghost", width=130, height=40).pack(side="left")
        PillButton(actions, "Разрешить", command=self._allow, width=140, height=40).pack(side="right")
        self.bind("<Escape>", lambda _event: self._deny())
        self.focus_set()

    def _allow(self):
        self.grab_release()
        self.destroy()
        self.on_allow()

    def _deny(self):
        self.grab_release()
        self.destroy()
        self.on_deny()


def ble_worker(status_queue, command_queue):
    log("[BLE] Поток запущен")
    from Foundation import NSObject, NSRunLoop, NSDate, NSData
    from CoreBluetooth import (
        CBPeripheralManager, CBMutableService, CBMutableCharacteristic, CBUUID,
        CBCharacteristicPropertyRead, CBCharacteristicPropertyWrite, CBCharacteristicPropertyNotify,
        CBAttributePermissionsReadable, CBAttributePermissionsWriteable, CBCentralManager,
        CBAdvertisementDataLocalNameKey, CBAdvertisementDataServiceUUIDsKey,
    )
    CBCharacteristicPropertyWriteWithoutResponse = 0x04
    SERVICE_UUID = CBUUID.UUIDWithString_(SERVICE_UUID_STRING)
    CHARACTERISTIC_UUID = CBUUID.UUIDWithString_(CHARACTERISTIC_UUID_STRING)
    FRAME_MAGIC = b"OCF1"
    FRAME_HEADER_BYTES = 8
    FRAME_BYTES = 20

    def pump(seconds=0.01):
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))

    def nsd(data):
        return NSData.alloc().initWithBytes_length_(bytes(data), len(data))

    class FrameAssembler:
        def __init__(self):
            self.frames = {}
            self.next_id = 1

        def new_message_id(self):
            value = self.next_id
            self.next_id = 1 if self.next_id >= 0xFFFF else self.next_id + 1
            return value

        def accept(self, raw, handler):
            raw = bytes(raw or b"")
            if len(raw) < FRAME_HEADER_BYTES or raw[:4] != FRAME_MAGIC:
                try:
                    text = raw.decode("utf-8")
                except Exception:
                    return
                if text:
                    handler(text)
                return
            msg_id = (raw[4] << 8) | raw[5]
            seq, total = raw[6], raw[7]
            if total == 0 or seq >= total:
                return
            entry = self.frames.setdefault(msg_id, {"total": total, "parts": {}, "last": time.time()})
            if entry["total"] != total:
                self.frames.pop(msg_id, None)
                return
            entry["parts"][seq] = raw[FRAME_HEADER_BYTES:]
            entry["last"] = time.time()
            if len(entry["parts"]) != total:
                return
            payload = b"".join(entry["parts"].get(i, b"") for i in range(total))
            self.frames.pop(msg_id, None)
            try:
                handler(payload.decode("utf-8"))
            except Exception as exc:
                log(f"[BLE] assemble: {exc}")

        def make_frames(self, text, frame_len=FRAME_BYTES):
            data = text.encode("utf-8")
            payload = max(1, frame_len - FRAME_HEADER_BYTES)
            total = max(1, (len(data) + payload - 1) // payload)
            if total > 255:
                raise ValueError("Слишком длинное сообщение")
            msg_id = self.new_message_id()
            frames = []
            for seq in range(total):
                chunk = data[seq * payload:(seq + 1) * payload]
                frames.append(FRAME_MAGIC + bytes([(msg_id >> 8) & 0xFF, msg_id & 0xFF, seq, total]) + chunk)
            return frames

    class PeripheralDelegate(NSObject):
        def initWithQueue_(self, sq):
            self = self.init()
            if self is not None:
                self.status_queue = sq
                self.manager = None
                self.characteristic = None
                self.has_subscriber = False
                self.connection_approved = False
                self.pending_peer_name = None
                self.local_name = default_display_name()
                self.service_added = False
                self.assembler = FrameAssembler()
                self.notify_frame_bytes = FRAME_BYTES
                self.notify_max = 182
                self.notify_queue = []
                self._flushing_notify = False
                self.accept_acked = False
                self.accept_tries = 0
                self.next_msg_id = 1
                self.next_accept_at = 0
                self.sos_active = False
            return self

        def send_event(self, event, message, **extra):
            data = {"event": event, "message": message}
            data.update(extra)
            try:
                self.status_queue.put(data)
            except Exception:
                pass

        def peripheralManagerDidUpdateState_(self, peripheral):
            state = peripheral.state()
            log(f"Peripheral state: {state}")
            if state != 5:
                self.send_event("error", f"Bluetooth недоступен: {state}")
                return
            self.send_event("ready", "Bluetooth готов")
            if self.characteristic is not None:
                self.start_advertising()
                return
            characteristic = CBMutableCharacteristic.alloc().initWithType_properties_value_permissions_(
                CHARACTERISTIC_UUID,
                (CBCharacteristicPropertyRead | CBCharacteristicPropertyWrite | CBCharacteristicPropertyWriteWithoutResponse | CBCharacteristicPropertyNotify),
                None,
                (CBAttributePermissionsReadable | CBAttributePermissionsWriteable),
            )
            self.characteristic = characteristic
            service = CBMutableService.alloc().initWithType_primary_(SERVICE_UUID, True)
            service.setCharacteristics_([characteristic])
            peripheral.addService_(service)

        def peripheralManager_didAddService_error_(self, peripheral, service, error):
            if error:
                self.send_event("error", str(error))
                return
            self.service_added = True
            self.start_advertising()

        def start_advertising(self):
            if not (self.manager and self.service_added):
                return
            try:
                self.manager.stopAdvertising()
            except Exception:
                pass
            self.manager.startAdvertising_({
                CBAdvertisementDataLocalNameKey: advertised_name(self.local_name, sos=self.sos_active),
                CBAdvertisementDataServiceUUIDsKey: [SERVICE_UUID],
            })

        def peripheralManagerDidStartAdvertising_error_(self, peripheral, error):
            if error:
                self.send_event("error", str(error))
                return
            self.send_event("advertising", "Видимы рядом")

        def peripheralManager_didReceiveWriteRequests_(self, peripheral, requests):
            for request in requests:
                try:
                    value = request.value()
                    if value:
                        self.assembler.accept(bytes(value), self.handle_incoming_text)
                    peripheral.respondToRequest_withResult_(request, 0)
                except Exception as exc:
                    log(f"Receive error: {exc}")

        def handle_incoming_text(self, text):
            if text.startswith(CONNECT_REQUEST_PREFIX):
                peer_name = text[len(CONNECT_REQUEST_PREFIX):].strip() or "Собеседник"
                self.pending_peer_name = peer_name
                self.connection_approved = False
                self.accept_acked = False
                self.send_event("connection_request", f"{peer_name} хочет подключиться", name=peer_name)
                return
            if text.startswith(CONNECT_ACK_PREFIX):
                self.accept_acked = True
                self.connection_approved = True
                return
            if text.startswith(CHAT_MESSAGE_PREFIX):
                if not self.connection_approved:
                    self.connection_approved = True
                    self.accept_acked = True
                    self.send_event("peer_connected", "Канал открыт", name=self.pending_peer_name or "Собеседник")
                payload = text[len(CHAT_MESSAGE_PREFIX):]
                mid, rest = parse_chat_payload(payload)
                if mid:
                    self.send_notification(DELIVERED_PREFIX + mid)
                    self.send_event("message_received", rest, mid=mid)
                else:
                    self.send_event("message_received", rest)
                return
            if text.startswith(TYPING_PREFIX):
                self.send_event("peer_typing", "печатает")
                return
            if text.startswith(DELIVERED_PREFIX):
                self.send_event("ble_delivered", text[len(DELIVERED_PREFIX):])
                return
            if text.startswith(READ_PREFIX):
                self.send_event("ble_read", text[len(READ_PREFIX):])
                return
            if text.startswith(SOS_PREFIX):
                parts = unpack_tagged(text, SOS_PREFIX)
                self.send_event("sos_received", "SOS рядом", name=parts[0] if parts else "Кто-то", coords=parts[1] if len(parts) > 1 else "-", note=parts[2] if len(parts) > 2 else "")
                return
            if text.startswith(OK_PREFIX):
                self.send_event("ok_received", "Человек в порядке", name=text[len(OK_PREFIX):].strip() or "Собеседник")
                return
            if text.startswith(LOC_PREFIX):
                parts = unpack_tagged(text, LOC_PREFIX)
                self.send_event("loc_received", "Точка на карте", name=parts[0] if parts else "Собеседник", coords=parts[1] if len(parts) > 1 else "-")
                return
            if text.startswith(CONNECT_ACCEPT_PREFIX):
                return
            self.send_event("message_received", text)

        def send_notification(self, text):
            if not (self.manager and self.characteristic and self.has_subscriber):
                return False
            raw = text.encode("utf-8")
            limit = max(20, int(getattr(self, "notify_max", 182) or 182))
            try:
                packets = [raw] if len(raw) <= limit and not raw.startswith(FRAME_MAGIC) else self.assembler.make_frames(text, self.notify_frame_bytes)
            except ValueError as exc:
                self.send_event("error", str(exc))
                return False
            self.notify_queue.extend(packets)
            return self.flush_notify_queue()

        def flush_notify_queue(self):
            if getattr(self, "_flushing_notify", False):
                return True
            if not (self.manager and self.characteristic and self.has_subscriber):
                return False
            self._flushing_notify = True
            try:
                while self.notify_queue:
                    frame = self.notify_queue.pop(0)
                    try:
                        ok = bool(self.manager.updateValue_forCharacteristic_onSubscribedCentrals_(nsd(frame), self.characteristic, None))
                    except Exception as exc:
                        log(f"notify: {exc}")
                        self.notify_queue.insert(0, frame)
                        return False
                    if not ok:
                        self.notify_queue.insert(0, frame)
                        return False
                return True
            finally:
                self._flushing_notify = False

        def peripheralManagerIsReadyToUpdateSubscribers_(self, peripheral):
            try:
                self.flush_notify_queue()
            except Exception:
                pass

        def approve_connection(self):
            if not self.has_subscriber:
                return False
            self.connection_approved = True
            self.accept_acked = False
            self.accept_tries = 0
            self.next_accept_at = 0
            self.send_accept()
            self.send_event("peer_connected", "Канал открыт", name=self.pending_peer_name or "Собеседник")
            return True

        def send_accept(self):
            if self.notify_queue:
                self.next_accept_at = time.time() + 0.2
                return self.flush_notify_queue()
            self.accept_tries += 1
            self.next_accept_at = time.time() + 0.45
            return self.send_notification(CONNECT_ACCEPT_PREFIX + self.local_name)

        def deny_connection(self):
            self.connection_approved = False
            self.send_notification(CONNECT_DENY_PREFIX + "Подключение отклонено")
            self.send_event("peer_denied", "Отклонено")
            return True

        def peripheralManager_central_didSubscribeToCharacteristic_(self, peripheral, central, characteristic):
            self.has_subscriber = True
            self.connection_approved = False
            self.accept_acked = False
            try:
                mtu = int(central.maximumUpdateValueLength())
            except Exception:
                mtu = FRAME_BYTES
            self.notify_max = max(20, min(512, mtu))
            self.notify_frame_bytes = max(FRAME_HEADER_BYTES + 1, min(FRAME_BYTES, mtu))
            self.send_event("peer_waiting", "Входящее подключение")

        def peripheralManager_central_didUnsubscribeFromCharacteristic_(self, peripheral, central, characteristic):
            self.has_subscriber = False
            self.connection_approved = False
            self.send_event("peer_disconnected", "Собеседник отключился")

    class CentralDelegate(NSObject):
        def initWithQueue_(self, sq):
            self = self.init()
            if self is not None:
                self.status_queue = sq
                self.central = None
                self.peripheral = None
                self.characteristic = None
                self.discovered_peripherals = {}
                self.pending_messages = []
                self.local_name = default_display_name()
                self.peer_approved = False
                self.next_msg_id = 1
                self.assembler = FrameAssembler()
                self.notify_enabled = False
                self.pending_connect_request = False
                self.pending_writes = []
                self.write_busy = False
                self.write_mtu = 182
                self.connect_tries = 0
                self.next_connect_at = 0
            return self

        def send_event(self, event, message, **extra):
            data = {"event": event, "message": message}
            data.update(extra)
            try:
                self.status_queue.put(data)
            except Exception:
                pass

        def centralManagerDidUpdateState_(self, central):
            if central.state() == 5:
                self.send_event("central_ready", "Bluetooth готов")

        def centralManager_didDiscoverPeripheral_advertisementData_RSSI_(self, central, peripheral, adv_data, rssi):
            raw_name = peripheral.name() or adv_data.get("kCBAdvDataLocalName", APP_NAME)
            name = peer_name_from_advertisement(raw_name)
            identifier = str(peripheral.identifier())
            self.discovered_peripherals[identifier] = peripheral
            self.send_event("device_found", "Найден узел", name=name, identifier=identifier, rssi=int(rssi), sos=advertisement_is_sos(raw_name))

        def centralManager_didConnectPeripheral_(self, central, peripheral):
            self.peripheral = peripheral
            self.characteristic = None
            self.peer_approved = False
            self.notify_enabled = False
            self.pending_connect_request = False
            peripheral.setDelegate_(self)
            self.send_event("connected", "Соединение установлено")
            peripheral.discoverServices_([SERVICE_UUID])

        def centralManager_didDisconnectPeripheral_error_(self, central, peripheral, error):
            self.peripheral = None
            self.characteristic = None
            self.peer_approved = False
            self.pending_messages.clear()
            self.send_event("peer_disconnected", "Собеседник отключился")

        def peripheral_didDiscoverServices_(self, peripheral, error):
            if error:
                return
            for service in (peripheral.services() or []):
                if str(service.UUID()).upper() == SERVICE_UUID_STRING:
                    peripheral.discoverCharacteristics_forService_([CHARACTERISTIC_UUID], service)

        def peripheral_didDiscoverCharacteristicsForService_error_(self, peripheral, service, error):
            if error:
                return
            for char in (service.characteristics() or []):
                if str(char.UUID()).upper() == CHARACTERISTIC_UUID_STRING:
                    self.characteristic = char
                    self.notify_enabled = False
                    self.pending_connect_request = True
                    self.connect_tries = 0
                    self.next_connect_at = 0
                    try:
                        mtu_wr = int(peripheral.maximumWriteValueLengthForType_(0))
                    except Exception:
                        mtu_wr = 0
                    try:
                        mtu_wo = int(peripheral.maximumWriteValueLengthForType_(1))
                    except Exception:
                        mtu_wo = 0
                    self.write_mtu = min(512, max(182, mtu_wr, mtu_wo))
                    peripheral.setNotifyValue_forCharacteristic_(True, char)
                    self.write_protocol(CONNECT_REQUEST_PREFIX + self.local_name)
                    self.connect_tries = 1
                    self.next_connect_at = time.time() + 0.8
                    self.send_event("approval_requested", "Запрос отправлен")

        def peripheral_didUpdateNotificationStateForCharacteristic_error_(self, peripheral, characteristic, error):
            if error:
                return
            notifying = True
            try:
                notifying = bool(characteristic.isNotifying())
            except Exception:
                pass
            self.notify_enabled = notifying
            if notifying and self.pending_connect_request:
                self.pending_connect_request = False
                self.write_protocol(CONNECT_REQUEST_PREFIX + self.local_name)
                self.connect_tries = max(self.connect_tries, 1)
                self.next_connect_at = time.time() + 0.35

        def mark_ready(self, peer_name=None):
            already = self.peer_approved
            self.peer_approved = True
            self.connect_tries = ACCEPT_RETRY_LIMIT
            if not already:
                self.send_event("ready_to_chat", "Канал готов", name=peer_name or "Собеседник")
                self.write_protocol(CONNECT_ACK_PREFIX + self.local_name)
                while self.pending_messages:
                    self.send_message(self.pending_messages.pop(0))

        def write_protocol(self, text):
            if not (self.peripheral and self.characteristic):
                return False
            raw = text.encode("utf-8")
            limit = max(20, int(getattr(self, "write_mtu", 182) or 182))
            try:
                if len(raw) <= limit:
                    packets = [raw]
                else:
                    packets = self.assembler.make_frames(text, min(limit, 182))
            except Exception as exc:
                log(f"Write: {exc}")
                return False
            self.pending_writes.extend(packets)
            self.flush_pending_writes()
            return True

        def flush_pending_writes(self):
            if getattr(self, "write_busy", False):
                return
            if not self.pending_writes or not (self.peripheral and self.characteristic):
                return
            frame = self.pending_writes[0]
            self.write_busy = True
            try:
                self.peripheral.writeValue_forCharacteristic_type_(nsd(frame), self.characteristic, 0)
            except Exception as exc:
                log(f"Write: {exc}")
                self.write_busy = False
                self.pending_writes.pop(0)
                self.flush_pending_writes()

        def peripheral_didWriteValueForCharacteristic_error_(self, peripheral, characteristic, error):
            if self.pending_writes:
                self.pending_writes.pop(0)
            self.write_busy = False
            if error:
                log(f"Write err: {error}")
            self.flush_pending_writes()

        def send_message(self, text, mid=None):
            if not self.peer_approved:
                self.pending_messages.append(text)
                self.send_event("waiting_for_approval", "Ждём согласие")
                return False
            mid = str(mid or self.next_msg_id)
            self.next_msg_id += 1
            if not self.write_protocol(CHAT_MESSAGE_PREFIX + mid + "|" + text):
                return False
            self.send_event("message_sent", text, mid=mid)
            return True

        def peripheral_didUpdateValueForCharacteristic_error_(self, peripheral, characteristic, error):
            if error or not characteristic.value():
                return
            try:
                self.assembler.accept(bytes(characteristic.value()), self.handle_incoming_text)
            except Exception as exc:
                log(f"notify in: {exc}")

        def handle_incoming_text(self, text):
            if text.startswith(CONNECT_ACCEPT_PREFIX):
                self.mark_ready(text[len(CONNECT_ACCEPT_PREFIX):].strip() or "Собеседник")
                return
            if text.startswith(CONNECT_ACK_PREFIX):
                self.mark_ready()
                return
            if text.startswith(CONNECT_DENY_PREFIX):
                self.peer_approved = False
                self.send_event("connection_denied", text[len(CONNECT_DENY_PREFIX):].strip() or "Отклонено")
                return
            if text.startswith(CHAT_MESSAGE_PREFIX):
                if not self.peer_approved:
                    self.mark_ready()
                payload = text[len(CHAT_MESSAGE_PREFIX):]
                mid, rest = parse_chat_payload(payload)
                if mid:
                    self.write_protocol(DELIVERED_PREFIX + mid)
                    self.send_event("message_received", rest, mid=mid)
                else:
                    self.send_event("message_received", rest)
                return
            if text.startswith(TYPING_PREFIX):
                self.send_event("peer_typing", "печатает")
                return
            if text.startswith(DELIVERED_PREFIX):
                self.send_event("ble_delivered", text[len(DELIVERED_PREFIX):])
                return
            if text.startswith(READ_PREFIX):
                self.send_event("ble_read", text[len(READ_PREFIX):])
                return
            if text.startswith(SOS_PREFIX):
                parts = unpack_tagged(text, SOS_PREFIX)
                if not self.peer_approved:
                    self.mark_ready()
                self.send_event("sos_received", "SOS", name=parts[0] if parts else "Кто-то", coords=parts[1] if len(parts) > 1 else "-", note=parts[2] if len(parts) > 2 else "")
                return
            if text.startswith(OK_PREFIX):
                self.send_event("ok_received", "В порядке", name=text[len(OK_PREFIX):].strip() or "Собеседник")
                return
            if text.startswith(LOC_PREFIX):
                parts = unpack_tagged(text, LOC_PREFIX)
                self.send_event("loc_received", "Точка", name=parts[0] if parts else "Собеседник", coords=parts[1] if len(parts) > 1 else "-")
                return
            self.send_event("message_received", text)

    p_delegate = PeripheralDelegate.alloc().initWithQueue_(status_queue)
    p_manager = CBPeripheralManager.alloc().initWithDelegate_queue_(p_delegate, None)
    p_delegate.manager = p_manager
    c_delegate = CentralDelegate.alloc().initWithQueue_(status_queue)
    c_manager = CBCentralManager.alloc().initWithDelegate_queue_(c_delegate, None)
    c_delegate.central = c_manager
    location_manager = {"mgr": None}
    next_sos_at = 0

    def read_gps():
        try:
            from CoreLocation import CLLocationManager
            mgr = location_manager["mgr"]
            if mgr is None:
                mgr = CLLocationManager.alloc().init()
                location_manager["mgr"] = mgr
                try:
                    mgr.requestWhenInUseAuthorization()
                except Exception:
                    pass
                try:
                    mgr.startUpdatingLocation()
                except Exception:
                    pass
            loc = mgr.location()
            if not loc:
                return None, None, None
            coord = loc.coordinate()
            acc = float(loc.horizontalAccuracy())
            if acc < 0:
                return None, None, None
            return float(coord.latitude), float(coord.longitude), acc
        except Exception as exc:
            log(f"[GPS] {exc}")
            return None, None, None

    def write_outgoing_packet(packet):
        if c_delegate.peripheral:
            if not c_delegate.peer_approved:
                return False
            return c_delegate.write_protocol(packet)
        if p_delegate.connection_approved:
            return p_delegate.send_notification(packet)
        return False

    shutdown = False
    while not shutdown:
        try:
            while True:
                cmd = command_queue.get_nowait()
                cmd_type = cmd.get("type")
                if cmd_type == "shutdown":
                    shutdown = True
                    break
                if cmd_type == "scan":
                    if c_manager.state() == 5:
                        c_manager.scanForPeripheralsWithServices_options_([SERVICE_UUID], None)
                        status_queue.put({"event": "scanning", "message": "Поиск..."})
                elif cmd_type == "stop_scan":
                    c_manager.stopScan()
                elif cmd_type == "connect":
                    identifier = cmd.get("identifier")
                    peripheral = c_delegate.discovered_peripherals.get(identifier)
                    if peripheral:
                        c_delegate.characteristic = None
                        c_delegate.peer_approved = False
                        c_delegate.notify_enabled = False
                        c_delegate.pending_connect_request = False
                        c_delegate.connect_tries = 0
                        c_delegate.next_connect_at = 0
                        c_delegate.pending_messages.clear()
                        peripheral.setDelegate_(c_delegate)
                        status_queue.put({"event": "connecting", "message": "Подключение..."})
                        c_manager.connectPeripheral_options_(peripheral, None)
                    else:
                        status_queue.put({"event": "error", "message": "Устройство не найдено"})
                elif cmd_type == "message":
                    mid = cmd.get("mid") or str(int(time.time() * 1000) % 100000)
                    text = cmd.get("text", "")
                    payload = CHAT_MESSAGE_PREFIX + str(mid) + "|" + text
                    sent = False
                    if c_delegate.peripheral and c_delegate.characteristic:
                        sent = bool(c_delegate.send_message(text, mid=mid))
                    if not sent and p_delegate.has_subscriber:
                        if not p_delegate.connection_approved:
                            p_delegate.connection_approved = True
                        sent = bool(p_delegate.send_notification(payload))
                    if sent:
                        status_queue.put({"event": "message_sent", "message": text, "mid": str(mid)})
                    else:
                        status_queue.put({"event": "error", "message": "Нет канала"})
                elif cmd_type == "typing":
                    token = TYPING_PREFIX + "1"
                    if c_delegate.peripheral:
                        c_delegate.write_protocol(token)
                    if p_delegate.has_subscriber:
                        p_delegate.send_notification(token)
                elif cmd_type == "ble_read":
                    token = READ_PREFIX + str(cmd.get("mid") or "")
                    if c_delegate.peripheral:
                        c_delegate.write_protocol(token)
                    if p_delegate.has_subscriber:
                        p_delegate.send_notification(token)
                elif cmd_type == "approve_connection":
                    p_delegate.approve_connection()
                elif cmd_type == "deny_connection":
                    p_delegate.deny_connection()
                elif cmd_type == "set_name":
                    name = (cmd.get("name") or default_display_name()).strip() or default_display_name()
                    p_delegate.local_name = name
                    c_delegate.local_name = name
                    p_delegate.start_advertising()
                elif cmd_type == "sos":
                    active = bool(cmd.get("active"))
                    p_delegate.sos_active = active
                    p_delegate.start_advertising()
                    lat, lng, _acc = read_gps() if active else (None, None, None)
                    if active:
                        write_outgoing_packet(pack_sos(p_delegate.local_name, lat, lng, cmd.get("note") or ""))
                        status_queue.put({"event": "sos_on", "message": "Маяк в эфире", "coords": f"{lat:.5f},{lng:.5f}" if lat is not None else "-"})
                    else:
                        status_queue.put({"event": "sos_off", "message": "Маяк выключен"})
                elif cmd_type == "ok":
                    p_delegate.sos_active = False
                    p_delegate.start_advertising()
                    write_outgoing_packet(OK_PREFIX + p_delegate.local_name)
                    status_queue.put({"event": "ok_sent", "message": "Отметили: я в порядке"})
                elif cmd_type == "loc":
                    lat, lng, acc = read_gps()
                    if lat is None:
                        status_queue.put({"event": "error", "message": "Нет GPS. Разрешите Геопозицию."})
                    elif write_outgoing_packet(LOC_PREFIX + f"{p_delegate.local_name}|{lat:.5f},{lng:.5f}|{acc:.0f}"):
                        status_queue.put({"event": "loc_sent", "message": f"{lat:.5f}, {lng:.5f}", "coords": f"{lat:.5f},{lng:.5f}"})
                    else:
                        status_queue.put({"event": "error", "message": "Сначала откройте связь рядом"})
                elif cmd_type == "gps":
                    lat, lng, acc = read_gps()
                    if lat is None:
                        status_queue.put({"event": "gps", "message": "GPS пока молчит", "coords": "-"})
                    else:
                        status_queue.put({"event": "gps", "message": f"{lat:.5f}, {lng:.5f}", "coords": f"{lat:.5f},{lng:.5f}", "acc": f"{acc:.0f}"})
        except queue.Empty:
            pass
        if shutdown:
            break
        if p_delegate.connection_approved and not p_delegate.accept_acked and p_delegate.has_subscriber and p_delegate.accept_tries < ACCEPT_RETRY_LIMIT and time.time() >= p_delegate.next_accept_at:
            try:
                p_delegate.send_accept()
            except Exception:
                pass
        if c_delegate.characteristic and not c_delegate.peer_approved and c_delegate.connect_tries < 3 and time.time() >= getattr(c_delegate, "next_connect_at", 0):
            try:
                if not getattr(c_delegate, "write_busy", False):
                    c_delegate.write_protocol(CONNECT_REQUEST_PREFIX + c_delegate.local_name)
                    c_delegate.connect_tries = int(getattr(c_delegate, "connect_tries", 0) or 0) + 1
                    c_delegate.next_connect_at = time.time() + 0.8
            except Exception:
                pass
        try:
            p_delegate.flush_notify_queue()
        except Exception:
            pass
        try:
            c_delegate.flush_pending_writes()
        except Exception:
            pass
        if p_delegate.sos_active and time.time() >= next_sos_at:
            lat, lng, _acc = read_gps()
            write_outgoing_packet(pack_sos(p_delegate.local_name, lat, lng, ""))
            next_sos_at = time.time() + 8
        pump(0.05)


class App:
    def __init__(self, root, status_queue, command_queue, online_command_queue, ble_thread):
        self.root = root
        self.status_queue = status_queue
        self.command_queue = command_queue
        self.online_command_queue = online_command_queue
        self.ble_thread = ble_thread
        self.section = "guide"
        self.mode = "online"
        self.devices = {}
        self.connected = False
        self.current_device_name = None
        self.display_name = default_display_name()
        self.incoming_dialog = None
        self.pages = {}
        self.page_factories = {}
        self.online_username = load_online_user()
        self.online_chats = load_online_chats()
        for history in self.online_chats.values():
            for item in history:
                if item.get("attachment") and item.get("status") == "sending":
                    item["status"] = "failed"
        self.online_profiles = load_online_profiles()
        self.online_typing_peers = set()
        self.active_online_chat = None
        self.online_transcript = None
        self._online_list_sig = None
        self.online_server_url = load_online_settings()
        self.theme_spec = dict(THEME.get("_spec") or load_theme_spec())
        self.online_typing_until = 0
        self.ble_typing_until = 0
        self.last_typing_sent = 0
        self.ble_ticks = {}
        self.online_ticks = {}
        self.online_peer_status = None
        self._chats_save_job = None
        self._list_dirty = False
        self._read_job = None
        self.modal_overlay = None
        init_fonts(root)
        harden_tk(root)
        self.build()
        self.command_queue.put({"type": "set_name", "name": self.display_name})
        if self.online_username:
            self.online_command_queue.put({
                "type": "set_username",
                "name": self.online_username,
                "reset_cursor": not bool(self.online_chats),
            })
        self.root.after(100, self.tick)

    def build(self):
        self.root.title("Связь")
        self.root.geometry("1100x720")
        self.root.minsize(900, 600)
        self.root.configure(bg=THEME["bg"])
        shell = tk.Frame(self.root, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        shell.pack(fill="both", expand=True, padx=16, pady=16)

        header = tk.Frame(shell, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=THEME["surface"])
        inner.pack(fill="x", padx=18, pady=14)
        mark = tk.Canvas(inner, width=40, height=40, highlightthickness=0, bd=0, bg=THEME["surface"])
        mark.pack(side="left")
        round_rect(mark, 1, 1, 39, 39, 12, fill=THEME["primary"], outline="")
        mark.create_oval(8, 8, 32, 32, outline=THEME["primary_fg"], width=1.4)
        titles = tk.Frame(inner, bg=THEME["surface"])
        titles.pack(side="left", padx=12)
        tk.Label(titles, text="Связь", bg=THEME["surface"], fg=THEME["text"], font=display_font(22, "bold")).pack(anchor="w")
        self.status_detail = tk.Label(titles, text="Онлайн-мессенджер с оффлайн-режимом", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(11))
        self.status_detail.pack(anchor="w")
        right = tk.Frame(inner, bg=THEME["surface"])
        right.pack(side="right")
        self.status_chip = tk.Label(right, text="  ●  Запуск  ", bg=THEME["surface_alt"], fg=THEME["warning"], font=ui_font(11, "bold"), padx=8, pady=6)
        self.status_chip.pack(side="left", padx=(0, 8))
        self.name_entry = tk.Entry(right, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], disabledforeground=THEME["subtle"], selectbackground=THEME["primary"], selectforeground=THEME["primary_fg"], relief="flat", font=ui_font(12), highlightbackground=THEME["line"], highlightthickness=1, width=16)
        self.name_entry.insert(0, self.display_name)
        self.name_entry.pack(side="left", ipady=7)
        self.name_entry.bind("<Return>", lambda e: self.save_name())
        PillButton(right, "Устройство", command=self.save_name, variant="secondary", width=110, height=36).pack(side="left", padx=(8, 0))
        PillButton(right, "Тёмная" if not theme_is_dark() else "Светлая", command=self.toggle_theme, variant="ghost", width=90, height=36).pack(side="left", padx=(8, 0))

        body = tk.Frame(shell, bg=THEME["surface"])
        body.pack(fill="both", expand=True)
        nav = tk.Frame(body, bg=THEME["surface"], width=220, highlightbackground=THEME["line"], highlightthickness=1)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Label(nav, text="МЕССЕНДЖЕР", bg=THEME["surface"], fg=THEME["accent"], font=ui_font(10, "bold")).pack(anchor="w", padx=18, pady=(18, 8))
        self.nav_btns = {}
        for key, title in (("online", "Онлайн-чаты"), ("profile", "Мой профиль"), ("chat", "Рядом по Bluetooth")):
            btn = PillButton(nav, title, command=lambda k=key: self.show(k), variant="ghost", width=180, height=40)
            btn.pack(anchor="w", padx=18, pady=4)
            self.nav_btns[key] = btn
        tk.Label(nav, text="ОФФЛАЙН-ИНСТРУМЕНТЫ", bg=THEME["surface"], fg=THEME["accent"], font=ui_font(10, "bold")).pack(anchor="w", padx=18, pady=(22, 8))
        for key, title in (("guide", "Справочник"), ("map", "Карта и GPS"), ("notes", "Заметки"), ("card", "Карточка"), ("theme", "Тема")):
            btn = PillButton(nav, title, command=lambda k=key: self.show(k), variant="ghost", width=180, height=40)
            btn.pack(anchor="w", padx=18, pady=4)
            self.nav_btns[key] = btn
        tk.Label(nav, text="Всё сохранено на устройстве и доступно без интернета.", bg=THEME["surface"], fg=THEME["subtle"], font=ui_font(10), wraplength=180, justify="left").pack(anchor="w", padx=18, pady=(18, 0))

        self.content = tk.Frame(body, bg=THEME["chat_bg"])
        self.content.pack(side="right", fill="both", expand=True)
        self.page_factories = {
            "online": self.make_online,
            "profile": self.make_online_profile,
            "guide": self.make_guide,
            "map": self.make_map,
            "notes": self.make_notes,
            "card": self.make_card,
            "theme": self.make_theme,
            "chat": self.make_chat,
        }
        # These views receive background Bluetooth/GPS callbacks even before navigation.
        self.pages["chat"] = self.make_chat()
        self.pages["map"] = self.make_map()
        self.show("online")

    def show(self, key):
        self.close_overlay()
        if key == "profile" and key in self.pages:
            self.pages.pop(key).destroy()
        self.section = key
        if key not in self.pages:
            factory = self.page_factories.get(key)
            if factory is None:
                return
            self.pages[key] = factory()
        for name, page in self.pages.items():
            if name == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        for name, btn in self.nav_btns.items():
            btn.variant = "primary" if name == key else "ghost"
            btn.bg0, btn.fg0, btn.bg1 = (
                (THEME["primary"], THEME["primary_fg"], THEME["primary_hover"]) if name == key
                else (THEME["surface"], THEME["muted"], THEME["surface_alt"])
            )
            btn.redraw()

    def close_overlay(self):
        overlay = self.modal_overlay
        self.modal_overlay = None
        if overlay is not None:
            try:
                overlay.grab_release()
                overlay.destroy()
            except Exception:
                pass

    def open_overlay(self, width, height):
        self.close_overlay()
        overlay = tk.Frame(self.content, bg=THEME["chat_bg"])
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()
        panel = tk.Frame(overlay, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        panel.place(relx=0.5, rely=0.5, anchor="center", width=width, height=height)
        overlay.bind("<Escape>", lambda _event: self.close_overlay())
        overlay.focus_set()
        overlay.grab_set()
        self.modal_overlay = overlay
        return overlay, panel

    def make_online_profile(self):
        page = tk.Frame(self.content, bg=THEME["chat_bg"])
        card = tk.Frame(page, bg=THEME["surface"], padx=32, pady=28)
        card.pack(fill="x", padx=28, pady=28)
        profile = self.online_profiles.get(self.online_username) or {}
        Avatar(card, self.online_username or "?", size=88, profile=profile).pack(anchor="w")
        tk.Label(card, text=profile.get("display_name") or "Мой профиль", bg=THEME["surface"], fg=THEME["text"], font=display_font(26, "bold")).pack(anchor="w", pady=(18, 6))
        tk.Label(card, text="@" + self.online_username if self.online_username else "Профиль ещё не создан", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(14)).pack(anchor="w")
        tk.Label(card, text=profile.get("bio") or "Добавьте несколько слов о себе", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(13), wraplength=480, justify="left").pack(anchor="w", pady=20)
        PillButton(card, "Редактировать" if self.online_username else "Создать профиль", command=self.open_online_profile_editor if self.online_username else lambda: self.show("online"), width=180, height=40).pack(anchor="w")
        tk.Label(card, text="Сервер: " + self.online_server_url, bg=THEME["surface"], fg=THEME["subtle"], font=ui_font(11)).pack(anchor="w", pady=(28, 0))
        return page

    def make_online(self):
        page = tk.Frame(self.content, bg=THEME["chat_bg"])
        connection_bar = tk.Frame(page, bg=THEME["surface"])
        connection_bar.pack(fill="x")
        tk.Label(connection_bar, text="Сервер: " + (self.online_server_url or "не настроен"),
                 bg=THEME["surface"], fg=THEME["muted"], font=ui_font(11)).pack(side="left", padx=12, pady=8)
        def copy_server():
            self.root.clipboard_clear()
            self.root.clipboard_append(self.online_server_url)
        PillButton(connection_bar, "Копировать", command=copy_server, variant="ghost", width=110, height=30).pack(side="right", padx=8)
        self.online_setup = tk.Frame(page, bg=THEME["chat_bg"])
        wrap = tk.Frame(self.online_setup, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=28, pady=28)
        tk.Label(wrap, text="Ваш юз", bg=THEME["surface"], fg=THEME["text"], font=display_font(26, "bold"), anchor="w").pack(fill="x", padx=22, pady=(22, 6))
        tk.Label(wrap, text="Как в Telegram: уникальный @username. По нему вас находят. Имя устройства для Bluetooth отдельно сверху.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(13), wraplength=520, justify="left", anchor="w").pack(fill="x", padx=22)
        self.username_entry = tk.Entry(wrap, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], disabledforeground=THEME["subtle"], selectbackground=THEME["primary"], selectforeground=THEME["primary_fg"], relief="flat", font=ui_font(16), highlightbackground=THEME["line"], highlightthickness=1)
        self.username_entry.pack(fill="x", padx=22, pady=16, ipady=10)
        if self.online_username:
            self.username_entry.insert(0, self.online_username)
        self.username_hint = tk.Label(wrap, text="Латиница, цифры и _. От 3 символов. Например: anna_k", bg=THEME["surface"], fg=THEME["subtle"], font=ui_font(12), anchor="w")
        self.username_hint.pack(fill="x", padx=22)
        PillButton(wrap, "Занять юз", command=self.claim_username, width=160, height=40).pack(anchor="w", padx=22, pady=(16, 22))

        self.online_main = tk.Frame(page, bg=THEME["chat_bg"])
        left = tk.Frame(self.online_main, bg=THEME["surface"], width=280, highlightbackground=THEME["line"], highlightthickness=1)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        top = tk.Frame(left, bg=THEME["surface"])
        top.pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(top, text="Чаты", bg=THEME["surface"], fg=THEME["text"], font=display_font(20, "bold")).pack(side="left")
        self.me_label = tk.Label(top, text="", bg=THEME["surface"], fg=THEME["accent"], font=ui_font(11, "bold"))
        self.me_label.pack(side="right", padx=(8, 0))
        bind_click(self.me_label, self.open_online_profile_editor)
        search = tk.Frame(left, bg=THEME["surface"])
        search.pack(fill="x", padx=16, pady=(8, 8))
        self.find_entry = tk.Entry(search, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], disabledforeground=THEME["subtle"], selectbackground=THEME["primary"], selectforeground=THEME["primary_fg"], relief="flat", font=ui_font(12), highlightbackground=THEME["line"], highlightthickness=1)
        self.find_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.find_entry.insert(0, "")
        self.find_entry.bind("<Return>", lambda _e: self.find_user())
        PillButton(search, "Найти", command=self.find_user, variant="secondary", width=78, height=32).pack(side="right", padx=(8, 0))
        tk.Label(left, text="Введите юз человека — не список всех подряд.", bg=THEME["surface"], fg=THEME["subtle"], font=ui_font(10), wraplength=240, justify="left", anchor="w").pack(fill="x", padx=16, pady=(0, 8))
        self.online_chat_list = tk.Frame(left, bg=THEME["surface"])
        self.online_chat_list.pack(fill="both", expand=True, padx=8)
        self.online = tk.Frame(self.online_main, bg=THEME["chat_bg"])
        self.online.pack(side="right", fill="both", expand=True)
        self.refresh_online_mode()
        return page

    def refresh_online_mode(self):
        if self.online_username:
            self.online_setup.pack_forget()
            self.online_main.pack(fill="both", expand=True)
            if hasattr(self, "me_label"):
                self.me_label.config(text="Профиль · @" + self.online_username)
            self.render_online_chats()
            if self.active_online_chat:
                self.open_online_chat(self.active_online_chat)
            else:
                self.online_empty_thread()
        else:
            self.online_main.pack_forget()
            self.online_setup.pack(fill="both", expand=True)

    def online_empty_thread(self):
        if not hasattr(self, "online"):
            return
        for child in self.online.winfo_children():
            child.destroy()
        self.online_transcript = None
        wrap = tk.Frame(self.online, bg=THEME["chat_bg"])
        wrap.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(wrap, text="Найдите человека", bg=THEME["chat_bg"], fg=THEME["text"], font=display_font(22, "bold")).pack()
        tk.Label(wrap, text="Слева введите его @юз.\nЧужие диалоги сюда не подтягиваются.", bg=THEME["chat_bg"], fg=THEME["muted"], font=ui_font(13), justify="center").pack(pady=8)

    def render_online_chats(self):
        if not hasattr(self, "online_chat_list"):
            return
        names = sorted(
            self.online_chats.keys(),
            key=lambda peer: float((self.online_chats.get(peer) or [{}])[-1].get("sort_at") or 0),
            reverse=True,
        )
        previews = tuple(
            (
                name,
                (self.online_chats.get(name) or [{}])[-1].get("text", "")[:28] if self.online_chats.get(name) else "",
                tuple((item.get("local_id"), item.get("status")) for item in (self.online_chats.get(name) or [])[-20:]),
                (self.online_profiles.get(name) or {}).get("_stamp"),
            )
            for name in names
        )
        sig = (self.active_online_chat, previews)
        if sig == self._online_list_sig and self.online_chat_list.winfo_children():
            return
        self._online_list_sig = sig
        for child in self.online_chat_list.winfo_children():
            child.destroy()
        if not names:
            tk.Label(self.online_chat_list, text="Пока пусто. Найдите юз.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(12), wraplength=220, justify="left").pack(pady=12, padx=8)
            return
        for name in names:
            selected = name == self.active_online_chat
            bg = THEME["surface_alt"] if selected else THEME["surface"]
            profile = self.online_profiles.get(name) or {}
            title = str(profile.get("display_name") or "").strip() or "@" + name
            row = tk.Frame(self.online_chat_list, bg=bg, cursor="hand2")
            row.pack(fill="x", pady=2)
            Avatar(row, name, size=34, profile=profile).pack(side="left", padx=8, pady=8)
            meta = tk.Frame(row, bg=bg)
            meta.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=8)
            tk.Label(meta, text=title, bg=bg, fg=THEME["text"], font=ui_font(12, "bold"), anchor="w").pack(fill="x")
            history = [item for item in self.online_chats.get(name, []) if not is_control_body(item.get("text"))]
            preview = history[-1].get("text", "") if history else "Нет сообщений"
            unread = sum(1 for item in history if not item.get("outgoing") and item.get("status") != "read")
            subtitle = preview[:25] + (f"   • {unread}" if unread else "")
            tk.Label(meta, text=subtitle, bg=bg, fg=THEME["accent"] if unread else THEME["muted"], font=ui_font(10, "bold" if unread else "normal"), anchor="w").pack(fill="x")
            bind_click(row, lambda chat=name: self.open_online_chat(chat))

    def open_online_chat(self, name):
        if name == self.online_username:
            return
        if self.active_online_chat == name and getattr(self, "online_transcript", None) is not None:
            self.schedule_read(name)
            self._list_dirty = True
            return
        self.active_online_chat = name
        self.online_chats.setdefault(name, [])
        if not hasattr(self, "online"):
            return
        for child in self.online.winfo_children():
            child.destroy()
        head = tk.Frame(self.online, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        head.pack(fill="x")
        profile = self.online_profiles.get(name) or {}
        Avatar(head, name, size=40, profile=profile).pack(side="left", padx=14, pady=10)
        meta = tk.Frame(head, bg=THEME["surface"])
        meta.pack(side="left", pady=10)
        title = str(profile.get("display_name") or "").strip() or "@" + name
        title_label = tk.Label(meta, text=title, bg=THEME["surface"], fg=THEME["text"], font=ui_font(15, "bold"), cursor="hand2")
        title_label.pack(anchor="w")
        title_label.bind("<Button-1>", lambda _event: self.open_peer_profile(name))
        self.online_peer_status = tk.Label(meta, text="@" + name, bg=THEME["surface"], fg=THEME["muted"], font=ui_font(11))
        self.online_peer_status.pack(anchor="w")
        transcript = OnlineScrollFrame(self.online, bg=THEME["chat_bg"])
        transcript.pack(fill="both", expand=True)
        self.online_transcript = transcript
        self.online_ticks = {}
        history = [item for item in self.online_chats.get(name, []) if not is_control_body(item.get("text"))][-40:]
        for item in history:
            self.add_online_message(
                transcript,
                item.get("text", ""),
                bool(item.get("outgoing")),
                status=item.get("status"),
                local_id=item.get("local_id"),
                scroll=False,
                attachment=item.get("attachment"),
            )
        transcript.scroll_to_end()
        self.schedule_read(name)
        bar = tk.Frame(self.online, bg=THEME["surface"])
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=THEME["surface_alt"], highlightbackground=THEME["line"], highlightthickness=1)
        inner.pack(fill="x", padx=12, pady=10)
        PillButton(inner, "Файл", command=self.send_online_file, width=64, height=36).pack(side="left", padx=6)
        self.online_entry = tk.Entry(inner, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], disabledforeground=THEME["subtle"], selectbackground=THEME["primary"], selectforeground=THEME["primary_fg"], relief="flat", borderwidth=0, highlightthickness=0, font=ui_font(14))
        self.online_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=12)
        self.online_entry.bind("<Return>", lambda _e: self.send_online_msg())
        self.online_entry.bind("<KeyRelease>", lambda _e: self.ping_online_typing())
        PillButton(inner, "Отправить", command=self.send_online_msg, width=120, height=36).pack(side="right", padx=6, pady=6)
        self.online_entry.focus()
        self._list_dirty = True

    def add_online_message(self, transcript, text, outgoing=False, status=None, local_id=None, scroll=True, attachment=None):
        row = tk.Frame(transcript.inner, bg=THEME["chat_bg"])
        row.pack(fill="x", padx=16, pady=4)
        holder = tk.Frame(row, bg=THEME["chat_bg"])
        holder.pack(anchor="e" if outgoing else "w")
        bg = THEME["outgoing"] if outgoing else THEME["incoming"]
        fg = THEME["primary_fg"] if outgoing else THEME["text"]
        tk.Label(holder, text=text, bg=bg, fg=fg, font=ui_font(13), wraplength=420, justify="left", padx=14, pady=10).pack()
        if attachment:
            label = tk.Label(holder, text="Сохранить файл · %.1f КБ" % (attachment.get("size", 0) / 1024),
                             bg=bg, fg=fg, cursor="hand2", padx=14, pady=6)
            label.pack(fill="x")
            label.bind("<Button-1>", lambda _event, mid=local_id: self.download_online_file(mid))
        if outgoing:
            mark_color = THEME["danger"] if status == "failed" else (THEME["accent"] if status == "read" else THEME["subtle"])
            mark = tk.Label(holder, text=receipt_mark(status or "sending"), bg=THEME["chat_bg"], fg=mark_color, font=ui_font(10), anchor="e")
            mark.pack(anchor="e")
            if local_id:
                self.online_ticks[local_id] = mark
                mark.bind("<Button-1>", lambda _event, mid=local_id: self.retry_online_message(mid))
        if scroll:
            transcript.scroll_to_end()

    def update_online_tick(self, local_id, status):
        mark = self.online_ticks.get(local_id)
        if mark:
            try:
                color = THEME["danger"] if status == "failed" else (THEME["accent"] if status == "read" else THEME["subtle"])
                mark.config(text=receipt_mark(status), fg=color, cursor="hand2" if status == "failed" else "arrow")
            except Exception:
                pass

    def retry_online_message(self, local_id):
        if not self.active_online_chat:
            return
        for item in self.online_chats.get(self.active_online_chat, []):
            if item.get("local_id") == local_id and item.get("outgoing") and item.get("status") == "failed":
                item["status"] = "sending"
                self.update_online_tick(local_id, "sending")
                self.online_command_queue.put({
                    "type": "online_send_file" if item.get("file_path") else "online_send", "recipient": self.active_online_chat,
                    "file_path": item.get("file_path"),
                    "text": item.get("text", ""), "local_id": local_id,
                })
                self.schedule_save_chats()
                return

    def schedule_save_chats(self):
        if self._chats_save_job is not None:
            try:
                self.root.after_cancel(self._chats_save_job)
            except Exception:
                pass
        self._chats_save_job = self.root.after(700, self._flush_chats)

    def _flush_chats(self):
        self._chats_save_job = None
        save_online_chats(self.online_chats)

    def ping_online_typing(self):
        now = time.time()
        if now - self.last_typing_sent < 2.2 or not self.active_online_chat or not self.online_username:
            return
        self.last_typing_sent = now
        self.online_command_queue.put({"type": "online_typing", "recipient": self.active_online_chat})

    def schedule_read(self, sender):
        if self._read_job is not None:
            try:
                self.root.after_cancel(self._read_job)
            except Exception:
                pass
        self._read_job = self.root.after(700, lambda: self.mark_online_read(sender))

    def mark_online_read(self, sender):
        self._read_job = None
        if self.section != "online" or self.active_online_chat != sender or not self.window_active():
            return
        history = self.online_chats.get(sender) or []
        message_ids = [item.get("sid") for item in history
                       if not item.get("outgoing") and item.get("sid") and item.get("status") != "read"]
        if message_ids:
            self.online_command_queue.put({"type": "online_read", "peer": sender, "message_ids": message_ids})

    def window_active(self):
        try:
            return self.root.focus_displayof() is not None
        except Exception:
            return True

    def send_online_msg(self):
        if not hasattr(self, "online_entry") or not self.active_online_chat or not self.online_username:
            return
        text = self.online_entry.get().strip()
        if not text:
            return
        local_id = str(uuid.uuid4())
        item = {
            "text": text, "outgoing": True, "status": "sending", "local_id": local_id,
            "created_at": time.time(), "sort_at": time.time(),
        }
        self.online_chats.setdefault(self.active_online_chat, []).append(item)
        self.schedule_save_chats()
        self.online_command_queue.put({"type": "online_send", "recipient": self.active_online_chat, "text": text, "local_id": local_id})
        self.online_entry.delete(0, tk.END)
        if self.online_transcript:
            self.add_online_message(self.online_transcript, text, True, status="sending", local_id=local_id)
        self._list_dirty = True

    def send_online_file(self):
        if not self.active_online_chat or not self.online_username:
            return
        path = filedialog.askopenfilename(title="Отправить файл до 5 МБ")
        if not path:
            return
        try:
            size = os.path.getsize(path)
            if not 0 < size <= 5 * 1024 * 1024:
                raise ValueError("Выберите непустой файл размером до 5 МБ")
        except (OSError, ValueError) as error:
            self.set_status("Файл не отправлен", THEME["danger"], str(error))
            return
        local_id = str(uuid.uuid4())
        attachment = {"name": os.path.basename(path), "size": size}
        text = "📎 " + attachment["name"]
        item = {"text": text, "attachment": attachment, "file_path": path, "outgoing": True,
                "status": "sending", "local_id": local_id, "created_at": time.time(), "sort_at": time.time()}
        self.online_chats.setdefault(self.active_online_chat, []).append(item)
        self.schedule_save_chats()
        self.online_command_queue.put({"type": "online_send_file", "recipient": self.active_online_chat,
                                       "local_id": local_id, "file_path": path})
        self.add_online_message(self.online_transcript, text, True, status="sending", local_id=local_id, attachment=attachment)
        self._list_dirty = True

    def download_online_file(self, local_id):
        item = next((m for m in self.online_chats.get(self.active_online_chat, []) if m.get("local_id") == local_id), None)
        if not item or not item.get("sid") or not item.get("attachment"):
            self.set_status("Файл ещё не отправлен", THEME["warning"], "Дождитесь отправки или повторите её")
            return
        attachment = item["attachment"]
        destination = filedialog.asksaveasfilename(title="Сохранить файл", initialfile=os.path.basename(attachment["name"]))
        if destination:
            self.online_command_queue.put({"type": "online_download_file", "message_id": item["sid"],
                                           "attachment": attachment, "destination": destination})
            self.set_status("Скачивание…", THEME["warning"], attachment["name"])

    def find_user(self):
        query = valid_username(self.find_entry.get() if hasattr(self, "find_entry") else "")
        if not query:
            self.set_status("Так юз не выглядит", THEME["danger"], "Латиница, цифры и _")
            return
        if query == self.online_username:
            self.set_status("Это вы", THEME["warning"], "Нельзя писать себе")
            return
        self.online_command_queue.put({"type": "find_user", "name": query})
        self.set_status("Ищем", THEME["warning"], f"@{query}")

    def claim_username(self):
        raw = self.username_entry.get() if hasattr(self, "username_entry") else ""
        self.online_command_queue.put({"type": "claim_username", "name": raw, "display_name": raw})
        self.set_status("Проверяем юз", THEME["warning"], "Смотрим, не занят ли")

    def new_online_chat(self):
        self.find_user()

    def open_peer_profile(self, username):
        profile = self.online_profiles.get(username) or {"name": username}
        _overlay, body = self.open_overlay(420, 440)
        Avatar(body, username, size=96, profile=profile).pack(pady=(28, 14))
        title = str(profile.get("display_name") or "").strip() or "@" + username
        tk.Label(body, text=title, bg=THEME["surface"], fg=THEME["text"], font=display_font(22, "bold")).pack()
        tk.Label(body, text="@" + username, bg=THEME["surface"], fg=THEME["accent"], font=ui_font(13, "bold")).pack(pady=(4, 14))
        bio = str(profile.get("bio") or "").strip()
        tk.Label(body, text=bio or "О себе пока ничего нет", bg=THEME["surface"], fg=THEME["muted"],
                 font=ui_font(13), wraplength=330, justify="center").pack(padx=24)
        PillButton(body, "Закрыть", command=self.close_overlay, variant="secondary", width=120, height=38).pack(side="bottom", pady=24)

    def open_online_profile_editor(self):
        if not self.online_username:
            return
        profile = dict(self.online_profiles.get(self.online_username) or {"name": self.online_username})
        dialog, body = self.open_overlay(500, 590)
        self.online_profile_dialog = dialog
        tk.Label(body, text="Профиль", bg=THEME["surface"], fg=THEME["text"], font=display_font(24, "bold")).pack(anchor="w", padx=24, pady=(22, 14))

        avatar_state = {"value": profile.get("avatar_base64")}
        avatar_host = tk.Frame(body, bg=THEME["surface"])
        avatar_host.pack(fill="x", padx=24)
        avatar_widget = Avatar(avatar_host, self.online_username, size=78, profile=profile)
        avatar_widget.pack(side="left")
        photo_label = tk.Label(avatar_host, text="Фото профиля" if avatar_state["value"] else "Фото не выбрано",
                               bg=THEME["surface"], fg=THEME["muted"], font=ui_font(12))
        photo_label.pack(side="left", padx=14)

        def choose_photo():
            path = filedialog.askopenfilename(
                parent=self.root,
                title="Выберите фото",
                filetypes=[("Изображения", "*.jpg *.jpeg *.png *.heic"), ("Все файлы", "*.*")],
            )
            if not path:
                return
            try:
                avatar_state["value"] = self.encode_avatar(path)
                photo_label.config(text="Новое фото выбрано", fg=THEME["success"])
            except Exception as exc:
                photo_label.config(text="Не удалось обработать фото", fg=THEME["danger"])
                log(f"avatar: {exc}")

        PillButton(avatar_host, "Выбрать", command=choose_photo, variant="secondary", width=100, height=34).pack(side="right")

        def field(label, value):
            tk.Label(body, text=label, bg=THEME["surface"], fg=THEME["muted"], font=ui_font(11, "bold"), anchor="w").pack(fill="x", padx=24, pady=(16, 4))
            entry = tk.Entry(body, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], relief="flat", font=ui_font(14), highlightbackground=THEME["line"], highlightthickness=1)
            entry.pack(fill="x", padx=24, ipady=8)
            entry.insert(0, value)
            return entry

        name_entry = field("Имя", profile.get("display_name") or "")
        username_entry = field("Username", self.online_username)
        tk.Label(body, text="О себе", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(11, "bold"), anchor="w").pack(fill="x", padx=24, pady=(16, 4))
        bio_text = tk.Text(body, height=4, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], relief="flat", font=ui_font(13), highlightbackground=THEME["line"], highlightthickness=1)
        bio_text.pack(fill="x", padx=24)
        bio_text.insert("1.0", profile.get("bio") or "")
        self.online_profile_error = tk.Label(body, text="", bg=THEME["surface"], fg=THEME["danger"], font=ui_font(11), anchor="w")
        self.online_profile_error.pack(fill="x", padx=24, pady=(8, 0))

        def save():
            self.online_command_queue.put({
                "type": "update_online_profile",
                "username": username_entry.get(),
                "display_name": name_entry.get(),
                "bio": bio_text.get("1.0", "end").strip(),
                "avatar_base64": avatar_state["value"],
            })
            self.online_profile_error.config(text="Сохраняем…", fg=THEME["warning"])

        actions = tk.Frame(body, bg=THEME["surface"])
        actions.pack(fill="x", padx=24, pady=18)
        PillButton(actions, "Отмена", command=self.close_overlay, variant="ghost", width=110, height=38).pack(side="left")
        PillButton(actions, "Сохранить", command=save, width=130, height=38).pack(side="right")

    def encode_avatar(self, source_path):
        temporary = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        temporary.close()
        try:
            subprocess.run(
                ["sips", "-Z", "512", "-s", "format", "jpeg", "-s", "formatOptions", "72",
                 source_path, "--out", temporary.name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=True,
            )
            with open(temporary.name, "rb") as handle:
                raw = handle.read()
            if len(raw) > 500_000:
                raise ValueError("avatar is too large")
            return base64.b64encode(raw).decode("ascii")
        finally:
            try:
                os.unlink(temporary.name)
            except Exception:
                pass

    def make_theme(self):
        page = tk.Frame(self.content, bg=THEME["chat_bg"])
        wrap = tk.Frame(page, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=24, pady=24)
        tk.Label(wrap, text="Тема", bg=THEME["surface"], fg=THEME["text"], font=display_font(24, "bold"), anchor="w").pack(fill="x", padx=22, pady=(22, 6))
        tk.Label(wrap, text="Светлая, тёмная или свои цвета. Системная тема Mac больше не перекрашивает текст.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(13), wraplength=560, justify="left", anchor="w").pack(fill="x", padx=22)
        row = tk.Frame(wrap, bg=THEME["surface"])
        row.pack(fill="x", padx=22, pady=16)
        PillButton(row, "Светлая", command=lambda: self.set_theme_preset("light"), variant="secondary", width=120, height=40).pack(side="left")
        PillButton(row, "Тёмная", command=lambda: self.set_theme_preset("dark"), variant="secondary", width=120, height=40).pack(side="left", padx=8)
        custom = tk.Frame(wrap, bg=THEME["surface"])
        custom.pack(fill="x", padx=22, pady=(8, 22))
        tk.Label(custom, text="Свои цвета", bg=THEME["surface"], fg=THEME["text"], font=ui_font(15, "bold"), anchor="w").pack(fill="x")
        tk.Label(custom, text="Выберите фон, текст и акцент — остальное приложение подстроит само.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(12), wraplength=520, justify="left", anchor="w").pack(fill="x", pady=(0, 10))
        spec = self.theme_spec
        for key, title in (("bg", "Фон"), ("text", "Текст"), ("accent", "Акцент")):
            line = tk.Frame(custom, bg=THEME["surface"])
            line.pack(fill="x", pady=4)
            swatch = tk.Frame(line, bg=spec.get(key) or THEME[key if key != "accent" else "primary"], width=36, height=28, highlightbackground=THEME["line"], highlightthickness=1)
            swatch.pack(side="left")
            swatch.pack_propagate(False)
            tk.Label(line, text=title, bg=THEME["surface"], fg=THEME["text"], font=ui_font(13)).pack(side="left", padx=10)
            PillButton(line, "Выбрать", command=lambda k=key: self.pick_theme_color(k), variant="ghost", width=100, height=32).pack(side="right")
        return page

    def set_theme_preset(self, preset):
        base = LIGHT_BASE if preset == "light" else DARK_BASE
        spec = {"preset": preset, **base}
        self.apply_theme(spec)

    def toggle_theme(self):
        self.set_theme_preset("light" if theme_is_dark() else "dark")

    def pick_theme_color(self, key):
        harden_tk(self.root)
        current = self.theme_spec.get(key) or THEME.get(key) or "#888888"
        picked = colorchooser.askcolor(color=current, title="Цвет")
        harden_tk(self.root)
        if not picked or not picked[1]:
            return
        spec = dict(self.theme_spec)
        spec["preset"] = "custom"
        spec[key] = picked[1]
        if not spec.get("bg"):
            spec["bg"] = THEME["bg"]
        if not spec.get("text"):
            spec["text"] = THEME["text"]
        if not spec.get("accent"):
            spec["accent"] = THEME["primary"]
        self.apply_theme(spec)

    def apply_theme(self, spec):
        apply_theme_spec(spec)
        save_theme_spec(spec)
        self.theme_spec = dict(THEME.get("_spec") or spec)
        section = self.section
        active = self.active_online_chat
        peer = self.current_device_name
        connected = self.connected
        for child in self.root.winfo_children():
            child.destroy()
        self.pages = {}
        self.online_ticks = {}
        self.ble_ticks = {}
        harden_tk(self.root)
        self.build()
        self.show(section)
        if section == "online" and active:
            self.open_online_chat(active)
        if section == "chat" and peer:
            self.open_peer(peer, connected=connected)

    def make_guide(self):
        page = tk.Frame(self.content, bg=THEME["chat_bg"])
        scroll = ScrollFrame(page, bg=THEME["chat_bg"])
        scroll.pack(fill="both", expand=True, padx=8, pady=8)
        tk.Label(scroll.inner, text="Справочник офлайн", bg=THEME["chat_bg"], fg=THEME["text"], font=display_font(26, "bold"), anchor="w").pack(fill="x", padx=18, pady=(18, 6))
        tk.Label(scroll.inner, text="То, что обычно гуглят. Здесь лежит в телефоне и на Маке без сети.", bg=THEME["chat_bg"], fg=THEME["muted"], font=ui_font(13), wraplength=520, justify="left", anchor="w").pack(fill="x", padx=18, pady=(0, 12))
        for title, body in GUIDES:
            card = tk.Frame(scroll.inner, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
            card.pack(fill="x", padx=18, pady=6)
            tk.Label(card, text=title, bg=THEME["surface"], fg=THEME["text"], font=ui_font(15, "bold"), anchor="w").pack(fill="x", padx=14, pady=(12, 4))
            tk.Label(card, text=body, bg=THEME["surface"], fg=THEME["muted"], font=ui_font(13), wraplength=520, justify="left", anchor="w").pack(fill="x", padx=14, pady=(0, 14))
        return page

    def make_map(self):
        page = tk.Frame(self.content, bg=THEME["chat_bg"])
        wrap = tk.Frame(page, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=24, pady=24)
        tk.Label(wrap, text="Карта без интернета", bg=THEME["surface"], fg=THEME["text"], font=display_font(24, "bold"), anchor="w").pack(fill="x", padx=22, pady=(22, 6))
        tk.Label(wrap, text="GPS ловит спутники сам. «Карты» откроют метку локально, без маршрута и без сети.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(13), wraplength=560, justify="left", anchor="w").pack(fill="x", padx=22)
        self.coord_label = tk.Label(wrap, text="Координаты: —", bg=THEME["surface"], fg=THEME["text"], font=ui_font(16, "bold"), anchor="w")
        self.coord_label.pack(fill="x", padx=22, pady=(20, 4))
        self.acc_label = tk.Label(wrap, text="Нажмите «Обновить GPS».", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(12), anchor="w")
        self.acc_label.pack(fill="x", padx=22)
        self.last_coords = None
        row = tk.Frame(wrap, bg=THEME["surface"])
        row.pack(fill="x", padx=22, pady=18)
        PillButton(row, "Обновить GPS", command=lambda: self.command_queue.put({"type": "gps"}), variant="secondary", width=150, height=40).pack(side="left")
        PillButton(row, "Открыть Карты", command=self.open_maps, width=160, height=40).pack(side="left", padx=8)
        PillButton(row, "Скопировать", command=self.copy_coords, variant="ghost", width=130, height=40).pack(side="left")
        row2 = tk.Frame(wrap, bg=THEME["surface"])
        row2.pack(fill="x", padx=22, pady=(0, 12))
        PillButton(row2, "Отправить точку рядом", command=self.send_loc, variant="secondary", width=220, height=40).pack(side="left")
        PillButton(row2, "Маяк SOS", command=self.toggle_sos, variant="danger", width=130, height=40).pack(side="left", padx=8)
        self.sos_on = False
        tk.Label(wrap, text="Точка уходит по Bluetooth только если канал связи уже открыт. Маяк SOS виден в поиске даже без чата.", bg=THEME["surface"], fg=THEME["subtle"], font=ui_font(12), wraplength=560, justify="left", anchor="w").pack(fill="x", padx=22, pady=(8, 22))
        return page

    def make_notes(self):
        page = tk.Frame(self.content, bg=THEME["chat_bg"])
        wrap = tk.Frame(page, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=24, pady=24)
        tk.Label(wrap, text="Заметки", bg=THEME["surface"], fg=THEME["text"], font=display_font(24, "bold"), anchor="w").pack(fill="x", padx=22, pady=(22, 6))
        tk.Label(wrap, text="Адреса, пароли от роутера, что взять с собой. Лежит только на этом устройстве.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(13), wraplength=560, justify="left", anchor="w").pack(fill="x", padx=22)
        self.notes = tk.Text(wrap, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], font=ui_font(14), relief="flat", wrap="word", highlightthickness=0, padx=12, pady=12)
        self.notes.pack(fill="both", expand=True, padx=22, pady=16)
        self.notes.insert("1.0", load_notes())
        PillButton(wrap, "Сохранить", command=self.save_notes, width=140, height=40).pack(anchor="w", padx=22, pady=(0, 22))
        return page

    def make_card(self):
        page = tk.Frame(self.content, bg=THEME["chat_bg"])
        wrap = tk.Frame(page, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=24, pady=24)
        tk.Label(wrap, text="Карточка", bg=THEME["surface"], fg=THEME["text"], font=display_font(24, "bold"), anchor="w").pack(fill="x", padx=22, pady=(22, 6))
        tk.Label(wrap, text="Покажите экран, если сами не можете объяснить. Интернет не нужен.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(13), wraplength=560, justify="left", anchor="w").pack(fill="x", padx=22)
        form = tk.Frame(wrap, bg=THEME["surface"])
        form.pack(fill="x", padx=22, pady=16)
        self.card_fields = {}
        data = load_card()
        for key, label in (("blood", "Группа крови"), ("allergies", "Аллергии"), ("meds", "Лекарства"), ("ice", "Кому звонить"), ("note", "Заметка о себе")):
            tk.Label(form, text=label, bg=THEME["surface"], fg=THEME["muted"], font=ui_font(11)).pack(anchor="w")
            entry = tk.Entry(form, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], disabledforeground=THEME["subtle"], selectbackground=THEME["primary"], selectforeground=THEME["primary_fg"], relief="flat", font=ui_font(13), highlightbackground=THEME["line"], highlightthickness=1)
            entry.insert(0, data.get(key, ""))
            entry.pack(fill="x", ipady=7, pady=(0, 10))
            self.card_fields[key] = entry
        PillButton(form, "Сохранить карточку", command=self.save_card_ui, width=200, height=40).pack(anchor="w", pady=(4, 22))
        return page

    def make_chat(self):
        page = tk.Frame(self.content, bg=THEME["chat_bg"])
        left = tk.Frame(page, bg=THEME["surface"], width=300, highlightbackground=THEME["line"], highlightthickness=1)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="Кто рядом", bg=THEME["surface"], fg=THEME["text"], font=display_font(20, "bold"), anchor="w").pack(fill="x", padx=16, pady=(16, 4))
        tk.Label(left, text="Bluetooth 10–40 м. Это запасной канал, не основной экран.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(11), wraplength=260, justify="left", anchor="w").pack(fill="x", padx=16)
        self.scan_btn = PillButton(left, "Найти", command=self.scan, width=140, height=36)
        self.scan_btn.pack(anchor="w", padx=16, pady=12)
        self.device_scroll = ScrollFrame(left, bg=THEME["surface"])
        self.device_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 12))
        self.empty_label = tk.Label(self.device_scroll.inner, text="Никого. Нажмите «Найти».", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(12), justify="left")
        self.empty_label.pack(fill="x", padx=8, pady=12)

        self.chat = tk.Frame(page, bg=THEME["chat_bg"])
        self.chat.pack(side="right", fill="both", expand=True)
        self.chat_empty()
        return page

    def chat_empty(self):
        for child in self.chat.winfo_children():
            child.destroy()
        wrap = tk.Frame(self.chat, bg=THEME["chat_bg"])
        wrap.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(wrap, text="Связь рядом", bg=THEME["chat_bg"], fg=THEME["text"], font=display_font(22, "bold")).pack()
        tk.Label(wrap, text="Найдите устройство слева,\nесли нужно передать точку или короткое сообщение.", bg=THEME["chat_bg"], fg=THEME["muted"], font=ui_font(13), justify="center").pack(pady=8)

    def open_peer(self, name, connected=False):
        self.current_device_name = name
        self.connected = connected
        for child in self.chat.winfo_children():
            child.destroy()
        head = tk.Frame(self.chat, bg=THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
        head.pack(fill="x")
        inner = tk.Frame(head, bg=THEME["surface"])
        inner.pack(fill="x", padx=14, pady=10)
        Avatar(inner, name, size=40).pack(side="left")
        meta = tk.Frame(inner, bg=THEME["surface"])
        meta.pack(side="left", padx=10)
        tk.Label(meta, text=name, bg=THEME["surface"], fg=THEME["text"], font=ui_font(15, "bold")).pack(anchor="w")
        self.peer_status = tk.Label(meta, text="Канал готов" if connected else "Ждём согласие", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(11))
        self.peer_status.pack(anchor="w")
        self.transcript = ScrollFrame(self.chat, bg=THEME["chat_bg"])
        self.transcript.pack(fill="both", expand=True)
        self.ble_ticks = {}
        self.add_system(f"Канал с {name}")
        bar = tk.Frame(self.chat, bg=THEME["surface"])
        bar.pack(fill="x")
        inner_b = tk.Frame(bar, bg=THEME["surface_alt"], highlightbackground=THEME["line"], highlightthickness=1)
        inner_b.pack(fill="x", padx=12, pady=10)
        self.entry = tk.Entry(inner_b, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], disabledforeground=THEME["subtle"], selectbackground=THEME["primary"], selectforeground=THEME["primary_fg"], relief="flat", font=ui_font(14), highlightthickness=0)
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, padx=12)
        self.entry.bind("<Return>", lambda e: self.send_msg())
        self.entry.bind("<KeyRelease>", lambda e: self.ping_ble_typing())
        self.loc_btn = PillButton(inner_b, "Точка", command=self.send_loc, variant="secondary", width=80, height=36)
        self.loc_btn.pack(side="right", padx=4, pady=6)
        self.send_btn = PillButton(inner_b, "Отправить", command=self.send_msg, width=120, height=36)
        self.send_btn.pack(side="right", padx=6, pady=6)
        self.set_connected(connected)
        self.entry.focus()

    def set_connected(self, connected):
        self.connected = connected
        if hasattr(self, "peer_status"):
            self.peer_status.config(text="Канал готов" if connected else "Ждём согласие")
        if hasattr(self, "entry"):
            self.entry.config(state="normal" if connected else "disabled")
        if hasattr(self, "send_btn"):
            self.send_btn.configure_state(not connected)
        if hasattr(self, "loc_btn"):
            self.loc_btn.configure_state(not connected)

    def add_system(self, text):
        if not hasattr(self, "transcript"):
            return
        row = tk.Frame(self.transcript.inner, bg=THEME["chat_bg"])
        row.pack(fill="x", pady=8)
        tk.Label(row, text=text, bg=THEME["chat_bg"], fg=THEME["subtle"], font=ui_font(11)).pack()
        self.transcript.scroll_to_end()

    def add_message(self, text, outgoing=False, status=None, mid=None):
        if not hasattr(self, "transcript"):
            return
        _, text = parse_chat_payload(text)
        row = tk.Frame(self.transcript.inner, bg=THEME["chat_bg"])
        row.pack(fill="x", padx=16, pady=4)
        holder = tk.Frame(row, bg=THEME["chat_bg"])
        holder.pack(anchor="e" if outgoing else "w")
        bg = THEME["outgoing"] if outgoing else THEME["incoming"]
        fg = THEME["primary_fg"] if outgoing else THEME["text"]
        tk.Label(holder, text=text, bg=bg, fg=fg, font=ui_font(13), wraplength=340, justify="left", padx=14, pady=10).pack()
        if outgoing:
            mark = tk.Label(holder, text=receipt_mark(status or "sent"), bg=THEME["chat_bg"], fg=THEME["accent"] if status == "read" else THEME["subtle"], font=ui_font(10), anchor="e")
            mark.pack(anchor="e")
            if mid:
                self.ble_ticks[str(mid)] = mark
        self.transcript.scroll_to_end()

    def ping_ble_typing(self):
        if not self.connected:
            return
        now = time.time()
        if now - self.last_typing_sent < 1.4:
            return
        self.last_typing_sent = now
        self.command_queue.put({"type": "typing"})

    def send_msg(self):
        if not hasattr(self, "entry"):
            return
        text = self.entry.get().strip()
        if not text or not self.connected:
            return
        mid = str(int(time.time() * 1000) % 100000000)
        self.add_message(text, outgoing=True, status="sending", mid=mid)
        self.entry.delete(0, tk.END)
        self.command_queue.put({"type": "message", "text": text, "mid": mid})

    def add_place(self, name, coords, outgoing=False):
        if not hasattr(self, "transcript"):
            return
        row = tk.Frame(self.transcript.inner, bg=THEME["chat_bg"])
        row.pack(fill="x", padx=16, pady=6)
        holder = tk.Frame(row, bg=THEME["chat_bg"])
        holder.pack(anchor="e" if outgoing else "w")
        bg = THEME["outgoing"] if outgoing else THEME["incoming"]
        fg = THEME["primary_fg"] if outgoing else THEME["text"]
        card = tk.Frame(holder, bg=bg)
        card.pack()
        tk.Label(card, text=name or "Точка", bg=bg, fg=fg, font=ui_font(13, "bold"), padx=14, pady=8).pack(anchor="w")
        tk.Label(card, text=coords, bg=bg, fg=fg, font=ui_font(11), padx=14).pack(anchor="w")
        tk.Button(card, text="Открыть в Картах", command=lambda: open_in_maps(coords, name or "Точка"), bg=bg, fg=fg, bd=0, font=ui_font(11, "bold"), cursor="hand2", padx=14, pady=8).pack(anchor="w")
        self.transcript.scroll_to_end()

    def save_name(self):
        name = self.name_entry.get().strip() or default_display_name()
        self.display_name = name
        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, name)
        self.command_queue.put({"type": "set_name", "name": name})
        self.set_status("Имя устройства", THEME["success"], "Только для Bluetooth рядом")

    def save_notes(self):
        save_notes(self.notes.get("1.0", "end-1c"))
        self.set_status("Заметки сохранены", THEME["success"])

    def save_card_ui(self):
        save_card({k: f.get().strip() for k, f in self.card_fields.items()})
        self.set_status("Карточка сохранена", THEME["success"])

    def open_maps(self):
        if not self.last_coords:
            self.command_queue.put({"type": "gps"})
            self.acc_label.config(text="Сначала обновляю GPS…")
            return
        if not open_in_maps(self.last_coords, "Я здесь"):
            self.acc_label.config(text="Не открылось. Скопируйте координаты.")

    def copy_coords(self):
        if not self.last_coords:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_coords)
        self.acc_label.config(text="Скопировано.")

    def send_loc(self):
        self.command_queue.put({"type": "loc"})

    def toggle_sos(self):
        self.sos_on = not self.sos_on
        note = ""
        if hasattr(self, "card_fields"):
            note = self.card_fields.get("note").get().strip() if self.card_fields.get("note") else ""
        self.command_queue.put({"type": "sos", "active": self.sos_on, "note": note})

    def scan(self):
        self.devices.clear()
        self.render_devices()
        self.command_queue.put({"type": "scan"})
        self.set_status("Поиск", THEME["warning"], "Сканируем Bluetooth рядом")
        self.root.after(10000, lambda: self.command_queue.put({"type": "stop_scan"}))

    def render_devices(self):
        for child in self.device_scroll.inner.winfo_children():
            child.destroy()
        if not self.devices:
            self.empty_label = tk.Label(self.device_scroll.inner, text="Никого. Нажмите «Найти».", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(12))
            self.empty_label.pack(fill="x", padx=8, pady=12)
            return
        for device in self.devices.values():
            row = tk.Frame(self.device_scroll.inner, bg=THEME["incoming"] if device.get("sos") else THEME["surface"], highlightbackground=THEME["line"], highlightthickness=1)
            row.pack(fill="x", padx=6, pady=4)
            inner = tk.Frame(row, bg=row["bg"])
            inner.pack(fill="x", padx=8, pady=8)
            Avatar(inner, device["name"], size=36).pack(side="left")
            meta = tk.Frame(inner, bg=row["bg"])
            meta.pack(side="left", fill="x", expand=True, padx=8)
            tk.Label(meta, text=device["name"], bg=row["bg"], fg=THEME["danger"] if device.get("sos") else THEME["text"], font=ui_font(12, "bold"), anchor="w").pack(fill="x")
            tk.Label(meta, text=("SOS · рядом" if device.get("sos") else f"{device.get('rssi', 0)} дБ"), bg=row["bg"], fg=THEME["muted"], font=ui_font(10), anchor="w").pack(fill="x")
            PillButton(inner, "Связь", command=lambda d=device: self.connect(d), variant="secondary", width=80, height=30).pack(side="right")

    def connect(self, device):
        self.current_device_name = device["name"]
        self.open_peer(device["name"], connected=False)
        self.command_queue.put({"type": "connect", "identifier": device["identifier"]})
        self.show("chat")

    def set_status(self, text, color=None, detail=None):
        self.status_chip.config(text=f"  ●  {text}  ")
        if color:
            self.status_chip.config(fg=color)
        if detail is not None:
            self.status_detail.config(text=detail)

    def tick(self):
        for _ in range(24):
            try:
                event = self.status_queue.get_nowait()
            except queue.Empty:
                break
            self.handle(event)
        now = time.time()
        if self.ble_typing_until and now > self.ble_typing_until:
            self.ble_typing_until = 0
            if hasattr(self, "peer_status") and self.connected:
                self.peer_status.config(text="Канал готов")
        if self.online_typing_until and now > self.online_typing_until:
            self.online_typing_until = 0
            if self.online_peer_status:
                try:
                    self.online_peer_status.config(text="Онлайн · по юзу")
                except Exception:
                    pass
        if self._list_dirty:
            self._list_dirty = False
            self.render_online_chats()
        self.root.after(160, self.tick)

    def upsert_online_message(self, message):
        if not isinstance(message, dict):
            return None, None, False
        sender = str(message.get("sender") or "")
        recipient = str(message.get("recipient") or "")
        if self.online_username not in (sender, recipient):
            return None, None, False
        peer = recipient if sender == self.online_username else sender
        if not peer or peer == self.online_username:
            return None, None, False
        local_id = str(message.get("client_id") or "")
        sid = message.get("id")
        incoming_status = str(message.get("status") or "sent")
        history = self.online_chats.setdefault(peer, [])
        match = None
        for item in history:
            if local_id and item.get("local_id") == local_id:
                match = item
                break
            if sid is not None and str(item.get("sid") or "") == str(sid):
                match = item
                break
        was_new = match is None
        if match is None:
            match = {}
            history.append(match)
            match["sort_at"] = time.time()
        ranks = {"failed": -1, "sending": 0, "sent": 1, "delivered": 2, "read": 3}
        current_status = match.get("status") or "sending"
        status = current_status if ranks.get(current_status, 0) > ranks.get(incoming_status, 0) else incoming_status
        match.update({
            "text": str(message.get("body") or ("📎 " + message["attachment"]["name"] if message.get("attachment") else match.get("text") or "")),
            "attachment": message.get("attachment"),
            "outgoing": sender == self.online_username,
            "status": status,
            "local_id": local_id or match.get("local_id"),
            "sid": sid if sid is not None else match.get("sid"),
            "created_at": message.get("created_at") or match.get("created_at") or time.time(),
            "sort_at": match.get("sort_at") or time.time(),
        })
        if len(history) > 500:
            del history[:-500]
        return peer, match, was_new

    def handle(self, event):
        kind = event.get("event")
        message = event.get("message", "")
        if kind in ("ready", "advertising", "central_ready"):
            self.set_status("Готово", THEME["success"], message or "Bluetooth работает")
        elif kind == "scanning":
            self.set_status("Поиск", THEME["warning"], message)
        elif kind == "device_found":
            ident = event.get("identifier")
            entry = {"name": event.get("name", "Узел"), "identifier": ident, "rssi": event.get("rssi", 0), "sos": bool(event.get("sos"))}
            prev = self.devices.get(ident)
            self.devices[ident] = entry
            if not prev or prev.get("name") != entry["name"] or prev.get("sos") != entry["sos"] or abs((prev.get("rssi") or 0) - entry["rssi"]) >= 8:
                self.render_devices()
            if event.get("sos"):
                self.set_status("SOS рядом", THEME["danger"], event.get("name"))
        elif kind == "connecting":
            self.set_status("Подключение", THEME["warning"], message)
        elif kind == "connected":
            self.set_status("Ждём согласие", THEME["warning"], "На другом устройстве нужно разрешить")
        elif kind == "approval_requested":
            self.set_status("Ждём согласие", THEME["warning"], message)
        elif kind == "ready_to_chat":
            self.connected = True
            name = event.get("name") or self.current_device_name or "Собеседник"
            self.current_device_name = name
            if not hasattr(self, "transcript") or self.current_device_name:
                self.open_peer(name, connected=True)
            else:
                self.set_connected(True)
            self.set_status("Связь", THEME["success"], "Канал готов")
            self.show("chat")
        elif kind == "connection_request":
            name = event.get("name", "Собеседник")
            self.current_device_name = name
            if self.incoming_dialog and self.incoming_dialog.winfo_exists():
                self.incoming_dialog.destroy()
            self.incoming_dialog = IncomingDialog(self.root, name, on_allow=lambda: self.command_queue.put({"type": "approve_connection"}), on_deny=lambda: self.command_queue.put({"type": "deny_connection"}))
        elif kind == "peer_connected":
            self.connected = True
            name = event.get("name") or self.current_device_name or "Собеседник"
            self.open_peer(name, connected=True)
            self.set_status("Связь", THEME["success"], "Канал открыт")
            self.show("chat")
        elif kind in ("connection_denied", "peer_denied"):
            self.connected = False
            self.set_connected(False)
            self.set_status("Отклонено", THEME["danger"], message)
        elif kind == "peer_disconnected":
            self.connected = False
            self.set_connected(False)
            self.add_system("Собеседник отключился")
            self.set_status("Нет канала", THEME["danger"], message)
        elif kind == "message_received":
            if not hasattr(self, "transcript"):
                self.open_peer(self.current_device_name or "Собеседник", connected=True)
            self.add_message(message, outgoing=False)
            mid = event.get("mid")
            if mid:
                self.command_queue.put({"type": "ble_read", "mid": mid})
            if self.section != "chat" or not self.window_active():
                desktop_notify(self.current_device_name or "Рядом", message)
            self.show("chat")
        elif kind == "message_sent":
            mid = str(event.get("mid") or "")
            mark = self.ble_ticks.get(mid)
            if mark:
                try:
                    mark.config(text=receipt_mark("sent"))
                except Exception:
                    pass
        elif kind == "peer_typing":
            self.ble_typing_until = time.time() + 3.2
            if hasattr(self, "peer_status"):
                self.peer_status.config(text="печатает…")
        elif kind == "ble_delivered":
            mid = str(event.get("message") or "")
            mark = self.ble_ticks.get(mid)
            if mark:
                try:
                    mark.config(text=receipt_mark("delivered"))
                except Exception:
                    pass
        elif kind == "ble_read":
            for mark in self.ble_ticks.values():
                try:
                    mark.config(text=receipt_mark("read"), fg=THEME["accent"])
                except Exception:
                    pass
        elif kind == "loc_sent":
            self.last_coords = event.get("coords")
            if hasattr(self, "transcript"):
                self.add_place("Я здесь", event.get("coords", "-"), outgoing=True)
            self.set_status("Точка ушла", THEME["success"], message)
        elif kind == "loc_received":
            coords = event.get("coords", "-")
            if not hasattr(self, "transcript"):
                self.open_peer(event.get("name") or "Собеседник", connected=True)
            self.add_place(event.get("name") or "Точка", coords, outgoing=False)
            self.show("chat")
        elif kind == "gps":
            coords = event.get("coords", "-")
            self.last_coords = None if coords == "-" else coords
            self.coord_label.config(text=f"Координаты: {coords}")
            acc = event.get("acc")
            self.acc_label.config(text=f"Точность около {acc} м" if acc else message)
        elif kind == "sos_on":
            self.set_status("Маяк", THEME["danger"], message)
        elif kind == "sos_off":
            self.set_status("Маяк выключен", THEME["muted"], message)
        elif kind == "sos_received":
            name = event.get("name", "Кто-то")
            coords = event.get("coords", "-")
            self.set_status("SOS", THEME["danger"], f"{name} · {coords}")
            if coords and coords != "-":
                if not hasattr(self, "transcript"):
                    self.open_peer(name, connected=True)
                self.add_place(f"SOS · {name}", coords, outgoing=False)
                self.show("chat")
            try:
                self.root.bell()
            except Exception:
                pass
        elif kind == "ok_received":
            self.add_system(f"{event.get('name', 'Собеседник')}: я в порядке")
        elif kind == "online_connected":
            self.set_status("Онлайн", THEME["success"], "Сообщения синхронизированы")
        elif kind == "online_profile":
            profile = event.get("profile") or {}
            name = profile.get("name")
            if name:
                profile["_stamp"] = time.time()
                self.online_profiles[name] = profile
                save_online_profiles(self.online_profiles)
                self._online_list_sig = None
                self._list_dirty = True
        elif kind == "online_profile_updated":
            profile = event.get("profile") or {}
            old_name = event.get("old_name") or self.online_username
            name = event.get("name") or profile.get("name") or old_name
            profile["_stamp"] = time.time()
            self.online_profiles.pop(old_name, None)
            self.online_profiles[name] = profile
            self.online_username = name
            save_online_user(name)
            save_online_profiles(self.online_profiles)
            if hasattr(self, "me_label"):
                self.me_label.config(text="Профиль · @" + name)
            dialog = getattr(self, "online_profile_dialog", None)
            if dialog and dialog.winfo_exists():
                self.close_overlay()
            self._online_list_sig = None
            self._list_dirty = True
            self.set_status("Профиль сохранён", THEME["success"], "@" + name)
            if self.section == "profile":
                self.show("profile")
        elif kind == "online_profile_error":
            label = getattr(self, "online_profile_error", None)
            if label:
                label.config(text=message or "Не удалось сохранить", fg=THEME["danger"])
            self.set_status("Профиль не сохранён", THEME["danger"], message)
        elif kind == "online_message_sync":
            peer, item, was_new = self.upsert_online_message(event.get("message"))
            if not peer:
                return
            viewing = self.section == "online" and self.active_online_chat == peer and self.window_active()
            if was_new and self.active_online_chat == peer and self.online_transcript:
                self.add_online_message(
                    self.online_transcript, item.get("text", ""), item.get("outgoing", False),
                    status=item.get("status"), local_id=item.get("local_id"),
                    attachment=item.get("attachment"),
                )
            elif not was_new and item.get("outgoing"):
                self.update_online_tick(item.get("local_id"), item.get("status"))
            if not item.get("outgoing"):
                if viewing:
                    self.schedule_read(peer)
                elif was_new and event.get("source") == "sync":
                    desktop_notify((self.online_profiles.get(peer) or {}).get("display_name") or "@" + peer, item.get("text", ""))
            self.schedule_save_chats()
            self._list_dirty = True
        elif kind == "online_file_saved":
            self.set_status("Файл сохранён", THEME["success"], event.get("path", ""))
        elif kind == "online_file_error":
            self.set_status("Не удалось скачать", THEME["danger"], message)
        elif kind == "online_send_failed":
            recipient = event.get("recipient")
            local_id = event.get("local_id")
            for item in self.online_chats.get(recipient, []):
                if item.get("local_id") == local_id:
                    if item.get("status") in ("sent", "delivered", "read"):
                        return
                    item["status"] = "failed"
                    self.update_online_tick(local_id, "failed")
                    break
            self.schedule_save_chats()
            self.set_status("Не отправлено", THEME["danger"], str(message) + " · Нажмите ! для повтора")
        elif kind == "online_local_read":
            ids = {str(value) for value in event.get("message_ids") or []}
            peer = event.get("peer")
            for item in self.online_chats.get(peer, []):
                if not item.get("outgoing") and str(item.get("sid") or "") in ids:
                    item["status"] = "read"
            self.schedule_save_chats()
            self._list_dirty = True
        elif kind == "online_typing_state":
            self.online_typing_peers = set(event.get("senders") or [])
            if self.online_peer_status and self.active_online_chat:
                text = "печатает…" if self.active_online_chat in self.online_typing_peers else "@" + self.active_online_chat
                self.online_peer_status.config(text=text, fg=THEME["accent"] if self.active_online_chat in self.online_typing_peers else THEME["muted"])
        elif kind == "online_username_ok":
            name = event.get("name") or ""
            self.online_username = name
            save_online_user(name)
            profile = event.get("profile") or {}
            if profile:
                profile["_stamp"] = time.time()
                self.online_profiles[name] = profile
                save_online_profiles(self.online_profiles)
            if hasattr(self, "username_hint"):
                self.username_hint.config(text=f"Юз закреплён: @{name}", fg=THEME["success"])
            self.refresh_online_mode()
            self.set_status("Юз готов", THEME["success"], f"@{name}")
        elif kind == "online_username_error":
            if hasattr(self, "username_hint"):
                self.username_hint.config(text=message or "Юз занять не вышло", fg=THEME["danger"])
            self.set_status("Юз занят", THEME["danger"], message)
        elif kind == "online_network_error":
            self.set_status("Онлайн недоступен", THEME["warning"], message or "Проверьте интернет")
        elif kind == "online_find":
            name = event.get("name") or ""
            if event.get("found"):
                if name == self.online_username:
                    self.set_status("Это вы", THEME["warning"], "Нельзя писать себе")
                else:
                    profile = event.get("profile") or {}
                    if profile:
                        profile["_stamp"] = time.time()
                        self.online_profiles[name] = profile
                        save_online_profiles(self.online_profiles)
                    self.online_chats.setdefault(name, [])
                    self.schedule_save_chats()
                    if self.active_online_chat != name:
                        self.open_online_chat(name)
                    self.set_status("Нашли", THEME["success"], f"@{name}")
            else:
                self.set_status("Не найден", THEME["warning"], message or f"@{name} не существует")
        elif kind == "online_message":
            sender = event.get("sender", "Собеседник")
            text = event.get("text", "")
            if sender == self.online_username or is_control_body(text):
                return
            history = self.online_chats.setdefault(sender, [])
            history.append({"text": text, "outgoing": False, "sid": event.get("sid")})
            self.schedule_save_chats()
            viewing = self.section == "online" and self.active_online_chat == sender
            if viewing and self.online_transcript:
                self.add_online_message(self.online_transcript, text, False)
                self.schedule_read(sender)
            else:
                desktop_notify("@" + sender, text)
            self._list_dirty = True
        elif kind == "online_sent":
            local_id = event.get("local_id")
            sid = event.get("sid")
            status = "sent" if event.get("ok") else "sending"
            recipient = event.get("recipient")
            for item in self.online_chats.get(recipient, []):
                if item.get("local_id") == local_id:
                    item["status"] = status
                    if sid:
                        item["sid"] = sid
            self.schedule_save_chats()
            self.update_online_tick(local_id, status)
        elif kind == "online_typing":
            sender = event.get("sender")
            if sender == self.active_online_chat and self.section == "online":
                self.online_typing_until = time.time() + 3.8
                if self.online_peer_status:
                    try:
                        self.online_peer_status.config(text="печатает…")
                    except Exception:
                        pass
        elif kind == "online_delivered":
            sid = str(event.get("sid") or "")
            sender = event.get("sender")
            for item in self.online_chats.get(sender, []):
                if str(item.get("sid") or "") == sid and item.get("outgoing"):
                    item["status"] = "delivered"
                    self.update_online_tick(item.get("local_id"), "delivered")
            self.schedule_save_chats()
        elif kind == "online_read":
            sid = event.get("sid")
            sender = event.get("sender")
            try:
                sid_n = int(sid)
            except Exception:
                sid_n = None
            for item in self.online_chats.get(sender, []):
                if item.get("outgoing") and (sid_n is None or int(item.get("sid") or 0) <= sid_n):
                    item["status"] = "read"
                    self.update_online_tick(item.get("local_id"), "read")
            self.schedule_save_chats()
        elif kind == "error":
            self.set_status("Ошибка", THEME["danger"], message)


def main():
    log("=== Связь запущена ===")
    status_queue = queue.Queue()
    command_queue = queue.Queue()
    online_command_queue = queue.Queue()
    server_url = load_online_settings()
    root = tk.Tk()
    harden_tk(root)
    ble_thread = threading.Thread(target=ble_worker, args=(status_queue, command_queue), daemon=True, name="BLE-Thread")
    ble_thread.start()
    online_thread = threading.Thread(
        target=online_worker_v2,
        args=(status_queue, online_command_queue, load_online_user(), server_url, None),
        daemon=True,
        name="Online-Client",
    )
    online_thread.start()
    root.after_idle(lambda: harden_tk(root))
    App(root, status_queue, command_queue, online_command_queue, ble_thread)

    def on_close():
        command_queue.put({"type": "shutdown"})
        online_command_queue.put({"type": "shutdown"})
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    try:
        root.mainloop()
    finally:
        command_queue.put({"type": "shutdown"})
        online_command_queue.put({"type": "shutdown"})


if __name__ == "__main__":
    main()
