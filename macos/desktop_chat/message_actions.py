"""Online message context menus, reply composer and multi-message forwarding."""
import os
import tempfile
import tkinter as tk
import uuid
import webbrowser
from online_chat.message_content import decode, encode, preview, quote
from online_chat import valid_username, normalize_username
from .shared import THEME, PillButton, ui_font, mix_hex
from .message_widgets import map_url


class OnlineMessageActions:
    def bind_message_actions(self, row, local_id):
        tag = "OnlineMessageSelection" + str(local_id)
        if not hasattr(row, "selection_binding"):
            def select(event):
                if self.selection_active:
                    self.select_online_item(local_id)
                    return "break"
            token = self.root.bind_class(tag, "<Button-1>", select)
            row.selection_binding = token
            def cleanup(event):
                if event.widget is row:
                    self.root.unbind_class(tag, "<Button-1>")
                    self.root.deletecommand(token)
            row.bind("<Destroy>", cleanup, add="+")
        def bind(widget):
            tags = widget.bindtags()
            if tag not in tags: widget.bindtags((tag,) + tags)
            widget.bind("<Button-3>", lambda event: self.message_context(event, local_id))
            widget.bind("<Button-2>", lambda event: self.message_context(event, local_id))
            widget.bind("<Control-Button-1>", lambda event: self.message_context(event, local_id))
            for child in widget.winfo_children(): bind(child)
        bind(row)
        self.paint_message_selection(row, local_id)

    @property
    def selection_active(self):
        return getattr(self, "online_selection_mode", bool(self.online_selected))

    def paint_message_selection(self, row, local_id):
        selected = local_id in self.online_selected
        bg = mix_hex(THEME["chat_bg"], THEME["accent"], 0.10) if selected or getattr(row, "reply_flash", False) else THEME["chat_bg"]
        row.configure(bg=bg)
        if hasattr(row, "selection_chrome"):
            marker, holder = row.selection_chrome
            holder.configure(bg=bg)
            marker.set_selected(self.selection_active, selected, bg)

    def message_context(self, event, local_id):
        item = self.find_online_item(local_id)
        if not item: return "break"
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Скопировать", command=lambda: self.copy_online_items([item]))
        menu.add_command(label="Переслать", command=lambda: self.forward_online_items([item]))
        menu.add_command(label="Выбрать", command=lambda: self.select_online_item(local_id))
        menu.add_command(label="Ответить", command=lambda: self.reply_online_item(item))
        location = decode(item.get("text")).get("location")
        if location:
            menu.add_separator()
            menu.add_command(label="Открыть в Яндекс Картах", command=lambda: webbrowser.open(map_url(location)))
            menu.add_command(label="Открыть в 2ГИС", command=lambda: webbrowser.open(map_url(location, "2gis")))
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()
        return "break"

    def copy_online_items(self, items):
        self.root.clipboard_clear()
        texts = []
        for item in items:
            content = decode(item.get("text"))
            texts.append(map_url(content["location"]) if content.get("location") else preview(item.get("text"), item.get("attachment")))
        self.root.clipboard_append("\n".join(texts))

    def reply_online_item(self, item):
        self.online_reply = quote(item, self.online_username, self.active_online_chat)
        self.refresh_message_tools()
        self.online_entry.focus_set()

    def select_online_item(self, local_id):
        entering = not self.selection_active
        self.online_selection_mode = True
        if local_id in self.online_selected: self.online_selected.remove(local_id)
        else: self.online_selected.add(local_id)
        for mid, row in self.online_media_rows.items():
            if (entering or mid == local_id) and row.winfo_exists(): self.paint_message_selection(row, mid)
        self.refresh_message_tools()

    def jump_online_message(self, local_id):
        row = next((r for mid, r in self.online_media_rows.items() if mid.lower() == local_id.lower()), None)
        if row and row.winfo_exists():
            canvas = self.online_transcript.canvas
            self.online_transcript.follow_tail = False
            def jump():
                if not row.winfo_exists(): return
                height = self.online_transcript.inner.winfo_height()
                canvas.yview_moveto(row.winfo_y() / max(1, height))
                row.reply_flash = True
                self.paint_message_selection(row, local_id)
            self.root.after_idle(jump)
            def end_flash():
                if row.winfo_exists():
                    row.reply_flash = False
                    self.paint_message_selection(row, local_id)
            self.root.after(900, end_flash)
        else: self.set_status("Ответ", THEME["muted"], "Исходное сообщение не загружено в текущем окне")

    def refresh_message_tools(self):
        host = getattr(self, "online_message_tools", None)
        if not host or not host.winfo_exists(): return
        mode = "selection" if self.selection_active else ("reply" if self.online_reply else "normal")
        if mode != getattr(host, "tools_mode", None) or mode == "reply":
            for child in host.winfo_children(): child.destroy()
            host.tools_mode = mode
            if mode == "selection":
                host.selection_count = tk.Label(host, bg=THEME["surface"], fg=THEME["text"], font=ui_font(12, "bold"))
                host.selection_count.pack(side="left", padx=12)
                selected_items = lambda: [m for m in self.online_chats.get(self.active_online_chat, []) if m.get("local_id") in self.online_selected]
                host.copy_action = PillButton(host, "Копировать", lambda: self.copy_online_items(selected_items()), variant="secondary", width=110, height=34)
                host.copy_action.pack(side="left", padx=4, pady=6)
                host.forward_action = PillButton(host, "Переслать", lambda: self.forward_online_items(selected_items()), variant="secondary", width=110, height=34)
                host.forward_action.pack(side="left", padx=4, pady=6)
                PillButton(host, "Отмена", self.clear_message_selection, variant="ghost", width=90, height=34).pack(side="right", padx=8)
        if mode == "selection":
            host.selection_count.configure(text=f"Выбрано: {len(self.online_selected)}")
            host.copy_action.configure_state(not self.online_selected)
            host.forward_action.configure_state(not self.online_selected)
        elif self.online_reply:
            tk.Label(host, text="Ответ @" + self.online_reply["sender"] + " · " + self.online_reply["text"][:60],
                     bg=THEME["surface"], fg=THEME["text"], font=ui_font(11), wraplength=350).pack(side="left", padx=12)
            PillButton(host, "Отмена", self.clear_online_reply, variant="secondary", width=80, height=30).pack(side="right", padx=4)

    def clear_online_reply(self):
        self.online_reply = None
        self.refresh_message_tools()

    def clear_message_selection(self):
        self.online_selection_mode = False
        self.online_selected.clear()
        for mid, row in self.online_media_rows.items():
            if row.winfo_exists(): self.paint_message_selection(row, mid)
        self.refresh_message_tools()

    def forward_online_items(self, items):
        if not items: return
        overlay = tk.Frame(self.root, bg=THEME["surface"], padx=20, pady=20,
                           highlightthickness=1, highlightbackground=THEME["line"])
        overlay.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(overlay, text="Кому переслать?", bg=THEME["surface"], fg=THEME["text"], font=ui_font(15, "bold")).pack(pady=(0, 12))
        entry = tk.Entry(overlay, bg=THEME["surface_alt"], fg=THEME["text"], insertbackground=THEME["text"], font=ui_font(13))
        entry.pack(fill="x")
        error = tk.Label(overlay, text="", bg=THEME["surface"], fg=THEME["danger"])
        error.pack()
        source_peer = self.active_online_chat
        def send(peer=None):
            recipient = normalize_username(peer or entry.get())
            if not valid_username(recipient) or recipient == self.online_username:
                error.configure(text="Укажите юз собеседника")
                return
            overlay.destroy()
            for item in items:
                content = decode(item.get("text"))
                body = encode(content["text"] if not item.get("attachment") else "",
                              forward=quote(item, self.online_username, source_peer), location=content.get("location"))
                if not item.get("attachment"):
                    self.queue_online_text(recipient, body)
                else:
                    path = item.get("media_path") or item.get("file_path")
                    if path and os.path.isfile(path): self.queue_online_file(path, recipient=recipient, body=body)
                    elif item.get("sid"):
                        request_id = str(uuid.uuid4())
                        directory = tempfile.mkdtemp(prefix="oc-forward-")
                        destination = os.path.join(directory, os.path.basename(item["attachment"]["name"]))
                        self.online_forward_pending[request_id] = (recipient, body)
                        self.online_command_queue.put({"type": "online_download_file", "message_id": item["sid"],
                            "attachment": item["attachment"], "destination": destination, "local_id": request_id,
                            "success_event": "online_forward_ready"})
                    else: self.set_status("Пересылка", THEME["warning"], "Дождитесь отправки вложения")
            self.clear_message_selection()
        for peer in list(self.online_chats)[:6]:
            PillButton(overlay, "@" + peer, lambda p=peer: send(p), variant="secondary", width=240, height=32).pack(pady=3)
        PillButton(overlay, "Переслать", send, height=34).pack(pady=6)
        PillButton(overlay, "Отмена", overlay.destroy, variant="secondary", height=32).pack()
        entry.focus_set()
