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
import sys
from urllib.parse import quote

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

try:
    import objc
    from AppKit import NSApp, NSView, NSButton, NSColor, NSViewWidthSizable, NSViewHeightSizable
    from AVKit import AVPlayerView
    from AVFoundation import AVPlayer
    from Foundation import NSObject, NSURL
except ImportError:
    objc = None
    AVPlayerView = None

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


def resource_path(relative_path):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, relative_path)


def themed_icon_photo(name, size=20, color=None):
    """Загружает готовую Lucide-иконку и окрашивает её под текущую тему."""
    if Image is None or ImageTk is None:
        return None
    try:
        path = resource_path(os.path.join("assets", "attachment_icons", name + ".png"))
        with Image.open(path) as source:
            icon = source.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        red, green, blue = hex_to_rgb(color or THEME["text"])
        tinted = Image.new("RGBA", icon.size, (red, green, blue, 0))
        tinted.putalpha(icon.getchannel("A"))
        return ImageTk.PhotoImage(tinted)
    except Exception as exc:
        log("icon %s: %s" % (name, exc))
        return None


if objc is not None:
    class MediaOverlayTarget(NSObject):
        def initWithOwner_(self, owner):
            self = objc.super(MediaOverlayTarget, self).init()
            if self is not None:
                self.owner = owner
            return self

        @objc.IBAction
        def close_(self, _sender):
            self.owner.close_native_media()


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


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif", ".webp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm"}


def attachment_kind(filename):
    extension = os.path.splitext(str(filename or ""))[1].lower()
    if extension in PHOTO_EXTENSIONS:
        return "photo"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    return "file"


def attachment_icon(filename):
    return {"photo": "▣", "video": "▶", "file": "▤"}[attachment_kind(filename)]


def attachment_preview_text(attachment):
    name = (attachment or {}).get("name") or "Вложение"
    kind = attachment_kind(name)
    return "Фото" if kind == "photo" else ("Видео" if kind == "video" else "📎 " + name)


def file_size_text(size):
    value = max(0, int(size or 0))
    if value >= 1024 * 1024:
        return "%.1f МБ" % (value / (1024 * 1024))
    return "%.0f КБ" % max(1, value / 1024)


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


class ClipButton(tk.Canvas):
    def __init__(self, master, command=None, **kwargs):
        super().__init__(master, width=36, height=36, highlightthickness=0, bd=0, bg=parent_bg(master), cursor="hand2", **kwargs)
        self.command = command
        self.open = False
        self._hover = False
        self._normal_icon = themed_icon_photo("paperclip", 21, THEME["muted"])
        self._active_icon = themed_icon_photo("paperclip", 21, THEME["text"])
        self.bind("<Button-1>", lambda _e: self.command and self.command())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.after_idle(self.redraw)

    def set_open(self, opened):
        self.open = bool(opened)
        self.redraw()

    def _set_hover(self, on):
        self._hover = on
        self.redraw()

    def redraw(self):
        self.delete("all")
        icon = self._active_icon if self._hover or self.open else self._normal_icon
        if icon is not None:
            self.create_image(18, 18, image=icon)
        else:
            self.create_text(18, 18, text="📎", font=ui_font(17), fill=THEME["text"])


class AttachDock(tk.Canvas):
    """Компактное вертикальное меню вложений без тяжёлой покадровой анимации."""

    def __init__(self, master, on_pick, on_close):
        self.width = 250
        self.row_height = 43
        self.padding = 9
        self.items = [
            ("media", "Фото или видео", "image"),
            ("file", "Файл", "file"),
            ("audio", "Звук", "audio-lines"),
            ("location", "Местоположение", "map-pin"),
        ]
        self.height = self.padding * 2 + self.row_height * len(self.items)
        super().__init__(master, width=self.width, height=self.height, highlightthickness=0, bd=0,
                         bg=THEME["chat_bg"], cursor="arrow")
        self.on_pick = on_pick
        self.on_close = on_close
        self.closing = False
        self.hovered = None
        self.icon_photos = {
            kind: themed_icon_photo(icon_name, 20, THEME["text"])
            for kind, _title, icon_name in self.items
        }
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)
        self._draw()

    def dismiss(self, done=None):
        self.closing = True
        if done:
            done()

    def _motion(self, event):
        index = int((event.y - self.padding) // self.row_height)
        hovered = index if 0 <= index < len(self.items) else None
        if hovered != self.hovered:
            self.hovered = hovered
            self._draw()

    def _leave(self, _event):
        if self.hovered is not None:
            self.hovered = None
            self._draw()

    def _click(self, event):
        if self.closing:
            return
        index = int((event.y - self.padding) // self.row_height)
        if 0 <= index < len(self.items):
            self.on_pick(self.items[index][0])

    def _draw(self):
        self.delete("all")
        round_rect(self, 2, 2, self.width - 2, self.height - 2, 20, fill=THEME["surface"], outline="")
        for index, (kind, title, _icon_name) in enumerate(self.items):
            top = self.padding + index * self.row_height
            center_y = top + self.row_height / 2
            if index == self.hovered:
                round_rect(self, 7, top + 2, self.width - 7, top + self.row_height - 2, 12,
                           fill=THEME["surface_alt"], outline="")
            icon = self.icon_photos.get(kind)
            if icon is not None:
                self.create_image(28, center_y, image=icon)
            self.create_text(52, center_y, text=title, anchor="w", fill=THEME["text"], font=ui_font(14))


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

