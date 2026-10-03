"""Desktop application controller and screen composition."""

from .shared import *
from .bluetooth import ble_worker
from .recording import RecordingButton


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
        self.online_auth_mode = "login"
        self.online_auth_challenge = ""
        self.online_auth_purpose = ""
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
        self.online_media_downloads = set()
        self.native_media = None
        self.online_peer_status = None
        self._chats_save_job = None
        self._list_dirty = False
        self._read_job = None
        self.modal_overlay = None
        self.attachment_menu = None
        self.last_coords = None
        self.online_location_pending_peer = None
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
        if self.online_username:
            account_actions = tk.Frame(card, bg=THEME["surface"])
            account_actions.pack(anchor="w", pady=(12, 0))
            PillButton(account_actions, "Сменить аккаунт", command=self.logout_online_account,
                       variant="secondary", width=170, height=38).pack(side="left")
            PillButton(account_actions, "Выйти", command=self.logout_online_account,
                       variant="ghost", width=100, height=38).pack(side="left", padx=(8, 0))
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
        self.auth_title = tk.Label(wrap, text="Вход", bg=THEME["surface"], fg=THEME["text"], font=display_font(26, "bold"), anchor="w")
        self.auth_title.pack(fill="x", padx=22, pady=(22, 6))
        self.auth_description = tk.Label(wrap, text="Введите юз или почту и пароль. Затем подтвердите вход кодом из письма.", bg=THEME["surface"], fg=THEME["muted"], font=ui_font(13), wraplength=560, justify="left", anchor="w")
        self.auth_description.pack(fill="x", padx=22)

        def auth_field(placeholder, secret=False):
            host = tk.Frame(wrap, bg=THEME["surface"])
            tk.Label(host, text=placeholder, bg=THEME["surface"], fg=THEME["muted"], font=ui_font(11), anchor="w").pack(fill="x")
            entry = tk.Entry(host, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"],
                             selectbackground=THEME["primary"], selectforeground=THEME["primary_fg"], relief="flat",
                             font=ui_font(14), highlightbackground=THEME["line"], highlightthickness=1,
                             show="•" if secret else "")
            entry.pack(fill="x", pady=(4, 0), ipady=8)
            return host, entry

        self.auth_identifier_row, self.username_entry = auth_field("Юз или почта")
        self.auth_email_row, self.auth_email_entry = auth_field("Почта")
        self.auth_password_row, self.auth_password_entry = auth_field("Пароль", True)
        self.auth_confirm_row, self.auth_confirm_entry = auth_field("Подтвердите пароль", True)
        for row in (self.auth_identifier_row, self.auth_email_row, self.auth_password_row, self.auth_confirm_row):
            row.pack(fill="x", padx=22, pady=(12, 0))
        self.username_hint = tk.Label(wrap, text="Пароль не короче 10 символов, с буквами и цифрами.", bg=THEME["surface"], fg=THEME["subtle"], font=ui_font(12), anchor="w")
        self.username_hint.pack(fill="x", padx=22, pady=(12, 0))
        actions = tk.Frame(wrap, bg=THEME["surface"])
        actions.pack(anchor="w", padx=22, pady=(14, 22))
        self.auth_submit_button = PillButton(actions, "Получить код", command=self.submit_online_auth, width=170, height=40)
        self.auth_submit_button.pack(side="left")
        self.auth_switch_button = PillButton(actions, "Создать аккаунт", command=self.toggle_online_auth_mode,
                                             variant="ghost", width=180, height=40)
        self.auth_switch_button.pack(side="left", padx=(8, 0))
        self.apply_online_auth_mode()

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

    def logout_online_account(self):
        if not self.online_username:
            self.show("online")
            return
        old_name = self.online_username
        self.close_online_attachment_menu()
        self.online_username = ""
        self.active_online_chat = None
        self.online_transcript = None
        self.online_chats = {}
        self.online_typing_peers.clear()
        save_online_user("")
        save_online_chats({})
        self.online_command_queue.put({"type": "auth_logout"})
        self._online_list_sig = None
        self._list_dirty = True
        self.show("online")
        self.refresh_online_mode()
        self.set_status("Вы вышли", THEME["muted"], "Аккаунт @" + old_name + " сохранён на сервере")

    def online_empty_thread(self):
        if not hasattr(self, "online"):
            return
        for child in self.online.winfo_children():
            child.destroy()
        self.attachment_menu = None
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
        self.attachment_menu = None
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
                media_path=item.get("media_path") or item.get("file_path"),
            )
        transcript.scroll_to_end()
        self.schedule_read(name)
        bar = tk.Frame(self.online, bg=THEME["surface"])
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=THEME["surface_alt"], highlightbackground=THEME["line"], highlightthickness=1)
        inner.pack(fill="x", padx=12, pady=10)
        self.attachment_button = ClipButton(inner, command=self.toggle_online_attachment_menu)
        self.attachment_button.pack(side="left", padx=6, pady=6)
        self.online_entry = tk.Entry(inner, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], disabledforeground=THEME["subtle"], selectbackground=THEME["primary"], selectforeground=THEME["primary_fg"], relief="flat", borderwidth=0, highlightthickness=0, font=ui_font(14))
        self.online_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=12)
        self.online_entry.bind("<Return>", lambda _e: self.send_online_msg())
        self.online_entry.bind("<KeyRelease>", lambda _e: self.ping_online_typing())
        PillButton(inner, "Отправить", command=self.send_online_msg, width=120, height=36).pack(side="right", padx=6, pady=6)
        recording_peer = self.active_online_chat
        RecordingButton(inner, send=lambda path: self.queue_online_file(path, recipient=recording_peer),
                        report=lambda error: self.set_status("Запись", THEME["danger"], error),
                        bg=THEME["surface"], fg=THEME["accent"], font=ui_font(18)).pack(side="right", padx=6)
        self.online_entry.focus()
        self._list_dirty = True

    def add_online_message(self, transcript, text, outgoing=False, status=None, local_id=None, scroll=True,
                           attachment=None, media_path=None):
        row = tk.Frame(transcript.inner, bg=THEME["chat_bg"])
        row.pack(fill="x", padx=16, pady=4)
        holder = tk.Frame(row, bg=THEME["chat_bg"])
        holder.pack(anchor="e" if outgoing else "w")
        bg = THEME["outgoing"] if outgoing else THEME["incoming"]
        fg = THEME["primary_fg"] if outgoing else THEME["text"]
        if attachment:
            kind = attachment_kind(attachment.get("name"))
            if kind == "photo":
                card = tk.Frame(holder, bg=bg, cursor="hand2", padx=5, pady=5)
                card.pack()
                shown = False
                if media_path and os.path.isfile(media_path) and Image is not None and ImageTk is not None:
                    try:
                        with Image.open(media_path) as opened:
                            image = opened.copy()
                        image.thumbnail((360, 260), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(image)
                        preview = tk.Label(card, image=photo, bg=bg, borderwidth=0, highlightthickness=0)
                        preview.image = photo
                        preview.pack()
                        shown = True
                    except Exception as error:
                        log("media preview: %s" % error)
                if not shown:
                    preview = tk.Frame(card, bg=mix_hex(bg, "#000000", 0.20), width=320, height=190)
                    preview.pack_propagate(False)
                    preview.pack()
                    tk.Label(preview, text="Фото", bg=preview["bg"], fg=fg,
                             font=ui_font(16, "bold")).place(relx=0.5, rely=0.47, anchor="center")
                    tk.Label(preview, text=file_size_text(attachment.get("size")), bg=preview["bg"],
                             fg=THEME["subtle"], font=ui_font(10)).place(relx=0.5, rely=0.61, anchor="center")
                bind_click(card, lambda mid=local_id: self.open_online_media(mid))
                if not shown and not outgoing and local_id:
                    self.root.after(80, lambda mid=local_id: self.load_online_media(mid, open_after=False))
            elif kind in ("video", "circle", "voice"):
                if kind == "circle":
                    card = tk.Canvas(holder, bg=THEME["chat_bg"], width=210, height=210, highlightthickness=0, cursor="hand2")
                    card.pack()
                    card.create_oval(2, 2, 208, 208, fill="#171A1F", outline="")
                    card.create_text(105, 92, text="▶", fill="#FFFFFF", font=ui_font(30))
                    card.create_text(105, 135, text="Видеокружок", fill="#D8DADF", font=ui_font(11))
                    card.bind("<Button-1>", lambda event, mid=local_id: self.open_online_media(mid))
                else:
                    self.add_recorded_media_card(holder, kind, attachment, local_id)
            else:
                card = tk.Frame(holder, bg=bg, cursor="hand2", padx=12, pady=10)
                card.pack(fill="x")
                details = tk.Frame(card, bg=bg)
                details.pack(side="left", fill="x", expand=True)
                tk.Label(details, text=attachment.get("name") or "Документ", bg=bg, fg=fg,
                         font=ui_font(13, "bold"), wraplength=310, justify="left").pack(anchor="w")
                tk.Label(details, text=file_size_text(attachment.get("size")), bg=bg,
                         fg=THEME["subtle"] if not outgoing else fg, font=ui_font(10)).pack(anchor="w", pady=(3, 0))
                tk.Label(card, text="↓", bg=bg, fg=fg, font=ui_font(16, "bold")).pack(side="right", padx=(12, 0))
                bind_click(card, lambda mid=local_id: self.download_online_file(mid))
        else:
            tk.Label(holder, text=text, bg=bg, fg=fg, font=ui_font(13), wraplength=420,
                     justify="left", padx=14, pady=10).pack()
        if outgoing:
            mark_color = THEME["danger"] if status == "failed" else (THEME["accent"] if status == "read" else THEME["subtle"])
            mark = tk.Label(holder, text=receipt_mark(status or "sending"), bg=THEME["chat_bg"], fg=mark_color, font=ui_font(10), anchor="e")
            mark.pack(anchor="e")
            if local_id:
                self.online_ticks[local_id] = mark
                mark.bind("<Button-1>", lambda _event, mid=local_id: self.retry_online_message(mid))
        if scroll:
            transcript.scroll_to_end()

    def add_recorded_media_card(self, holder, kind, attachment, local_id):
        card = tk.Frame(holder, bg="#171A1F", cursor="hand2", width=280 if kind == "voice" else 320, height=70 if kind == "voice" else 180)
        card.pack_propagate(False)
        card.pack()
        tk.Label(card, text="▶", bg="#171A1F", fg="#FFFFFF", font=ui_font(22, "bold")).place(relx=0.12 if kind == "voice" else 0.5, rely=0.44, anchor="center")
        tk.Label(card, text=("Голосовое" if kind == "voice" else "Видео") + " · " + file_size_text(attachment.get("size")), bg="#171A1F",
                 fg="#D8DADF", font=ui_font(11, "bold")).place(relx=0.58 if kind == "voice" else 0.5, rely=0.5 if kind == "voice" else 0.69, anchor="center")
        bind_click(card, lambda mid=local_id: self.open_online_media(mid))

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
                    "media_kind": attachment_kind((item.get("attachment") or {}).get("name")) if item.get("attachment") else None,
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
        self.online_entry.delete(0, tk.END)
        self.queue_online_text(self.active_online_chat, text)

    def queue_online_text(self, recipient, text):
        local_id = str(uuid.uuid4())
        item = {
            "text": text, "outgoing": True, "status": "sending", "local_id": local_id,
            "created_at": time.time(), "sort_at": time.time(),
        }
        self.online_chats.setdefault(recipient, []).append(item)
        self.schedule_save_chats()
        self.online_command_queue.put({"type": "online_send", "recipient": recipient, "text": text, "local_id": local_id})
        if self.online_transcript and self.active_online_chat == recipient:
            self.add_online_message(self.online_transcript, text, True, status="sending", local_id=local_id)
        self._list_dirty = True

    def toggle_online_attachment_menu(self):
        if self.attachment_menu is not None:
            self.close_online_attachment_menu()
            return
        if not hasattr(self, "online") or not self.active_online_chat:
            return
        dock = AttachDock(self.online, on_pick=self.choose_online_attachment, on_close=self.close_online_attachment_menu)
        self.attachment_menu = dock
        self.online.update_idletasks()
        try:
            button = self.attachment_button
            ax = button.winfo_rootx() - self.online.winfo_rootx()
            ay = button.winfo_rooty() - self.online.winfo_rooty()
            dock.place(x=max(8, ax - 10), y=max(8, ay - dock.height - 8))
        except Exception:
            dock.place(x=12, rely=1.0, y=-70, anchor="sw")
        if hasattr(self, "attachment_button"):
            self.attachment_button.set_open(True)

    def close_online_attachment_menu(self):
        menu = self.attachment_menu
        if menu is None:
            return
        if hasattr(self, "attachment_button"):
            self.attachment_button.set_open(False)

        def finish():
            if self.attachment_menu is menu:
                self.attachment_menu = None
            try:
                menu.destroy()
            except Exception:
                pass

        if isinstance(menu, AttachDock) and not menu.closing:
            menu.dismiss(finish)
        else:
            finish()

    def choose_online_attachment(self, kind):
        self.close_online_attachment_menu()
        if kind == "location":
            if self.last_coords:
                self.queue_online_text(self.active_online_chat, "📍 Местоположение\nhttps://maps.apple.com/?ll=" + self.last_coords)
                return
            self.online_location_pending_peer = self.active_online_chat
            self.command_queue.put({"type": "gps"})
            self.set_status("Определяем местоположение", THEME["warning"], "Подождите несколько секунд")
            return
        prompts = {"media": "Выберите фотографию или видео — приложение оптимизирует его перед отправкой",
                   "audio": "Выберите аудиофайл до 5 МБ",
                   "file": "Выберите файл до 5 МБ"}
        self.set_status("Выбор вложения", THEME["warning"], prompts.get(kind, prompts["file"]))
        try:
            self.root.update_idletasks()
            filetypes = {
                "media": [("Фото и видео", "*.jpg *.jpeg *.png *.gif *.heic *.heif *.webp *.tif *.tiff *.mov *.mp4 *.m4v *.avi *.mkv *.webm"), ("Все файлы", "*.*")],
                "audio": [("Аудио", "*.mp3 *.m4a *.aac *.wav *.aiff *.flac *.ogg"), ("Все файлы", "*.*")],
                "file": [("Все файлы", "*.*")],
            }
            path = filedialog.askopenfilename(parent=self.root, title=prompts.get(kind, prompts["file"]),
                                              filetypes=filetypes.get(kind, filetypes["file"]))
            if path:
                self.queue_online_file(path, kind)
            else:
                self.set_status("Онлайн", THEME["success"], "Вложение не выбрано")
        except Exception as error:
            self.set_status("Не удалось открыть выбор", THEME["danger"], str(error))

    def send_online_file(self, kind="file"):
        self.choose_online_attachment(kind)

    def queue_online_file(self, path, kind="file", recipient=None):
        recipient = recipient or self.active_online_chat
        if not recipient or not self.online_username:
            return
        if not path:
            return
        try:
            size = os.path.getsize(path)
            input_limit = 200 * 1024 * 1024 if kind == "media" else 5 * 1024 * 1024
            if not 0 < size <= input_limit:
                raise ValueError("Выберите непустой %s размером до %s МБ" %
                                 ("медиафайл" if kind == "media" else "файл",
                                  200 if kind == "media" else 5))
            actual_kind = attachment_kind(path)
            if kind == "media" and actual_kind not in ("photo", "video"):
                raise ValueError("Выбранный файл не является фотографией или видео")
        except (OSError, ValueError) as error:
            self.set_status("Файл не отправлен", THEME["danger"], str(error))
            return
        local_id = str(uuid.uuid4())
        attachment = {"name": os.path.basename(path), "size": size}
        text = attachment_preview_text(attachment)
        item = {"text": text, "attachment": attachment, "file_path": path, "outgoing": True,
                "status": "sending", "local_id": local_id, "created_at": time.time(), "sort_at": time.time()}
        self.online_chats.setdefault(recipient, []).append(item)
        self.schedule_save_chats()
        self.online_command_queue.put({"type": "online_send_file", "recipient": recipient,
                                       "local_id": local_id, "file_path": path, "media_kind": actual_kind})
        if recipient == self.active_online_chat:
            self.add_online_message(self.online_transcript, text, True, status="sending", local_id=local_id,
                                    attachment=attachment, media_path=path)
        self._list_dirty = True

    def download_online_file(self, local_id):
        item = next((m for m in self.online_chats.get(self.active_online_chat, []) if m.get("local_id") == local_id), None)
        if not item or not item.get("sid") or not item.get("attachment"):
            self.set_status("Файл ещё не отправлен", THEME["warning"], "Дождитесь отправки или повторите её")
            return
        attachment = item["attachment"]
        downloads = os.path.expanduser("~/Downloads")
        os.makedirs(downloads, exist_ok=True)
        stem, extension = os.path.splitext(os.path.basename(attachment["name"]))
        destination = os.path.join(downloads, stem + extension)
        counter = 2
        while os.path.exists(destination):
            destination = os.path.join(downloads, "%s (%d)%s" % (stem, counter, extension))
            counter += 1
        self.online_command_queue.put({"type": "online_download_file", "message_id": item["sid"],
                                       "attachment": attachment, "destination": destination})
        self.set_status("Скачивание…", THEME["warning"], "Файл будет сохранён в «Загрузки»")

    def open_online_media(self, local_id):
        item = self.find_online_item(local_id)
        if not item or not item.get("attachment"):
            return
        path = item.get("media_path") or item.get("file_path")
        kind = attachment_kind(item["attachment"].get("name"))
        if path and os.path.isfile(path):
            if kind == "photo":
                self.show_photo_overlay(path)
            else:
                self.show_video_overlay(path)
            return
        self.load_online_media(local_id, open_after=True)

    def load_online_media(self, local_id, open_after=False):
        item = self.find_online_item(local_id)
        if not item or not item.get("attachment") or not item.get("sid") or local_id in self.online_media_downloads:
            return
        self.online_media_downloads.add(local_id)
        kind = attachment_kind(item["attachment"].get("name"))
        extension = os.path.splitext(item["attachment"].get("name") or "media")[1]
        destination = os.path.join(tempfile.gettempdir(), "offlinechat-%s%s" % (local_id, extension))
        self.online_command_queue.put({
            "type": "online_download_file", "message_id": item["sid"], "attachment": item["attachment"],
            "destination": destination, "success_event": "online_media_ready", "local_id": local_id,
            "media_kind": kind, "open_after": bool(open_after),
        })
        self.set_status("Загрузка медиа", THEME["warning"], item["attachment"].get("name") or "")

    def find_online_item(self, local_id):
        for history in self.online_chats.values():
            for item in history:
                if item.get("local_id") == local_id:
                    return item
        return None

    def show_photo_overlay(self, path):
        if Image is None or ImageTk is None:
            subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        self.close_overlay()
        overlay = tk.Frame(self.root, bg="#090B0E")
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.overlay = overlay
        try:
            with Image.open(path) as opened:
                image = opened.copy()
            image.thumbnail((1000, 680), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            label = tk.Label(overlay, image=photo, bg="#090B0E", borderwidth=0, highlightthickness=0)
            label.image = photo
            label.place(relx=0.5, rely=0.5, anchor="center")
        except Exception as error:
            tk.Label(overlay, text="Не удалось открыть фото\n" + str(error), bg="#090B0E", fg="#FFFFFF",
                     font=ui_font(14), justify="center").place(relx=0.5, rely=0.5, anchor="center")
        PillButton(overlay, "Закрыть", command=self.close_overlay, variant="secondary", width=110, height=38).place(x=18, y=18)

    def show_video_overlay(self, path):
        if AVPlayerView is None:
            subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        try:
            self.close_native_media()
            window = NSApp().keyWindow() or NSApp().mainWindow()
            content = window.contentView()
            bounds = content.bounds()
            overlay = NSView.alloc().initWithFrame_(bounds)
            overlay.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            overlay.setWantsLayer_(True)
            overlay.layer().setBackgroundColor_(NSColor.blackColor().CGColor())
            player_view = AVPlayerView.alloc().initWithFrame_(bounds)
            player_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            if attachment_kind(path) == "circle":
                side = min(float(bounds.size.width), float(bounds.size.height)) * 0.75
                player_view.setFrame_((((float(bounds.size.width) - side) / 2, (float(bounds.size.height) - side) / 2), (side, side)))
                player_view.setWantsLayer_(True)
                player_view.layer().setCornerRadius_(side / 2)
                player_view.layer().setMasksToBounds_(True)
            player = AVPlayer.playerWithURL_(NSURL.fileURLWithPath_(path))
            player_view.setPlayer_(player)
            overlay.addSubview_(player_view)
            target = MediaOverlayTarget.alloc().initWithOwner_(self)
            height = float(bounds.size.height)
            button = NSButton.alloc().initWithFrame_(((16, max(16, height - 48)), (92, 32)))
            button.setTitle_("Закрыть")
            button.setTarget_(target)
            button.setAction_(b"close:")
            overlay.addSubview_(button)
            content.addSubview_(overlay)
            self.native_media = {"overlay": overlay, "player": player, "target": target,
                                 "button": button, "view": player_view}
            player.play()
        except Exception as error:
            log("video overlay: %s" % error)
            subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close_native_media(self):
        media = self.native_media
        self.native_media = None
        if not media:
            return
        try:
            media["player"].pause()
            media["overlay"].removeFromSuperview()
        except Exception:
            pass

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

    def apply_online_auth_mode(self):
        if not hasattr(self, "auth_title"):
            return
        registering = self.online_auth_mode == "register"
        self.auth_title.config(text="Регистрация" if registering else "Вход")
        self.auth_description.config(text=(
            "Создайте аккаунт. Мы отправим на почту шестизначный код подтверждения."
            if registering else
            "Введите юз или почту и пароль. Затем подтвердите вход кодом из письма."
        ))
        if registering:
            self.auth_email_row.pack(fill="x", padx=22, pady=(12, 0), after=self.auth_identifier_row)
            self.auth_confirm_row.pack(fill="x", padx=22, pady=(12, 0), after=self.auth_password_row)
        else:
            self.auth_email_row.pack_forget()
            self.auth_confirm_row.pack_forget()
        self.auth_switch_button.label = "У меня есть аккаунт" if registering else "Создать аккаунт"
        self.auth_switch_button.redraw()

    def toggle_online_auth_mode(self):
        self.online_auth_mode = "login" if self.online_auth_mode == "register" else "register"
        self.online_auth_challenge = ""
        self.apply_online_auth_mode()
        self.username_hint.config(text="Пароль не короче 10 символов, с буквами и цифрами.", fg=THEME["subtle"])

    def submit_online_auth(self):
        identifier = self.username_entry.get().strip()
        password = self.auth_password_entry.get()
        if self.online_auth_mode == "register":
            self.online_command_queue.put({
                "type": "auth_register_start", "username": identifier, "display_name": identifier,
                "email": self.auth_email_entry.get().strip(), "password": password,
                "password_confirmation": self.auth_confirm_entry.get(),
            })
        else:
            self.online_command_queue.put({"type": "auth_login_start", "identifier": identifier, "password": password})
        self.username_hint.config(text="Отправляем код…", fg=THEME["warning"])

    def verify_online_auth(self):
        code = self.auth_code_entry.get().strip() if hasattr(self, "auth_code_entry") else ""
        self.online_command_queue.put({"type": "auth_verify", "challenge_id": self.online_auth_challenge,
                                       "purpose": self.online_auth_purpose, "code": code})
        self.username_hint.config(text="Проверяем код…", fg=THEME["warning"])

    def show_online_code_dialog(self, email_hint):
        _overlay, panel = self.open_overlay(430, 300)
        tk.Label(panel, text="Код из письма", bg=THEME["surface"], fg=THEME["text"],
                 font=display_font(22, "bold")).pack(anchor="w", padx=28, pady=(28, 8))
        tk.Label(panel, text="Мы отправили 6 цифр на " + email_hint, bg=THEME["surface"], fg=THEME["muted"],
                 font=ui_font(12), wraplength=360, justify="left").pack(anchor="w", padx=28)
        self.auth_code_entry = tk.Entry(panel, bg=THEME["surface_alt"], fg=THEME["text"],
                                        insertbackground=THEME["text"], relief="flat", font=ui_font(24),
                                        justify="center", highlightbackground=THEME["line"], highlightthickness=1)
        self.auth_code_entry.pack(fill="x", padx=28, pady=20, ipady=8)
        self.auth_code_entry.bind("<Return>", lambda _event: self.verify_online_auth())
        PillButton(panel, "Подтвердить", command=self.verify_online_auth, width=160, height=40).pack(anchor="w", padx=28)
        self.auth_code_entry.focus_set()

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
                parent=self.root, title="Выберите фото профиля",
                filetypes=[("Изображения", "*.jpg *.jpeg *.png *.heic *.heif *.webp"), ("Все файлы", "*.*")],
            )
            if not path:
                return
            try:
                if attachment_kind(path) != "photo":
                    raise ValueError("Выбранный файл не является изображением")
                avatar_state["value"] = self.encode_avatar(path)
                photo_label.config(text="Новое фото выбрано", fg=THEME["success"])
            except Exception as error:
                photo_label.config(text=str(error) or "Не удалось обработать фото", fg=THEME["danger"])

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
            "text": str(message.get("body") or (attachment_preview_text(message["attachment"]) if message.get("attachment") else match.get("text") or "")),
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
            if hasattr(self, "coord_label"):
                self.coord_label.config(text=f"Координаты: {coords}")
            acc = event.get("acc")
            if hasattr(self, "acc_label"):
                self.acc_label.config(text=f"Точность около {acc} м" if acc else message)
            pending_peer = self.online_location_pending_peer
            self.online_location_pending_peer = None
            if pending_peer and self.last_coords:
                self.queue_online_text(pending_peer, "📍 Местоположение\nhttps://maps.apple.com/?ll=" + self.last_coords)
                self.set_status("Местоположение отправлено", THEME["success"], "Ссылка откроется в Картах")
            elif pending_peer:
                self.set_status("Геопозиция недоступна", THEME["danger"], message)
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
                    media_path=item.get("media_path") or item.get("file_path"),
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
            saved_path = event.get("path", "")
            self.set_status("Файл сохранён", THEME["success"], saved_path)
            if saved_path:
                try:
                    subprocess.Popen(["open", "-R", saved_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
        elif kind == "online_media_ready":
            local_id = event.get("local_id")
            self.online_media_downloads.discard(local_id)
            item = self.find_online_item(local_id)
            path = event.get("path", "")
            if item and path:
                item["media_path"] = path
                self.schedule_save_chats()
                active = self.active_online_chat
                if active:
                    self.active_online_chat = None
                    self.open_online_chat(active)
                if event.get("open_after"):
                    if event.get("media_kind") == "photo":
                        self.show_photo_overlay(path)
                    else:
                        self.show_video_overlay(path)
        elif kind == "online_file_error":
            self.online_media_downloads.clear()
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
        elif kind == "online_auth_code_sent":
            self.online_auth_challenge = event.get("challenge_id") or ""
            self.online_auth_purpose = event.get("purpose") or "login"
            self.show_online_code_dialog(event.get("email_hint") or "почту")
            self.username_hint.config(text="Код отправлен. Он действует 10 минут.", fg=THEME["success"])
            self.set_status("Проверьте почту", THEME["success"], event.get("email_hint") or "")
        elif kind == "online_auth_ok":
            name = event.get("name") or ""
            self.online_username = name
            save_online_user(name)
            profile = event.get("profile") or {}
            if profile:
                profile["_stamp"] = time.time()
                self.online_profiles[name] = profile
                save_online_profiles(self.online_profiles)
            if hasattr(self, "username_hint"):
                self.username_hint.config(text=f"Выполнен вход: @{name}", fg=THEME["success"])
            self.close_overlay()
            self.refresh_online_mode()
            self.set_status("Вход выполнен", THEME["success"], f"@{name}")
        elif kind == "online_auth_error":
            if hasattr(self, "username_hint"):
                self.username_hint.config(text=message or "Не удалось войти", fg=THEME["danger"])
            self.set_status("Ошибка входа", THEME["danger"], message)
        elif kind == "online_auth_expired":
            self.online_username = ""
            self.active_online_chat = None
            save_online_user("")
            self.close_overlay()
            self.refresh_online_mode()
            self.username_hint.config(text=message, fg=THEME["danger"])
            self.set_status("Нужно войти снова", THEME["danger"], message)
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
