import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from desktop_chat.online_transcript import OnlineTranscript, MessageSelectionIndicator
from desktop_chat.message_actions import OnlineMessageActions
from desktop_chat.shared import THEME, DARK_BASE, build_palette


class OnlineTranscriptTests(unittest.TestCase):
    def setUp(self):
        THEME.update(build_palette(**DARK_BASE))
        self.root = tk.Tk()
        self.root.geometry("540x400")
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.transcript = OnlineTranscript(self.root, bg=THEME["chat_bg"])
        self.transcript.pack(fill="both", expand=True)

    def tearDown(self):
        self.root.destroy()
        self.assertEqual(self.errors, [])

    def populate(self, count=50):
        for index in range(count):
            tk.Label(self.transcript.inner, text=f"Сообщение {index}", height=2).pack(fill="x")
        self.transcript.scroll_to_end()
        self.root.update()

    def test_initial_layout_and_late_media_sizes_stay_at_bottom(self):
        self.populate()
        self.assertAlmostEqual(self.transcript.canvas.yview()[1], 1, places=3)
        tk.Label(self.transcript.inner, text="Позднее фото", height=12).pack()
        self.root.update()
        self.assertAlmostEqual(self.transcript.canvas.yview()[1], 1, places=3)
        self.assertFalse(self.transcript.down.winfo_manager())

    def test_incoming_message_preserves_history_and_button_returns_to_bottom(self):
        self.populate()
        self.transcript._scrollbar("moveto", 0.2)
        self.root.update()
        self.assertTrue(self.transcript.down.winfo_manager())
        offset = self.transcript.canvas.canvasy(0)
        tk.Label(self.transcript.inner, text="Входящее", height=3).pack()
        self.transcript.message_added()
        self.root.update()
        self.assertAlmostEqual(self.transcript.canvas.canvasy(0), offset, delta=2)
        self.assertEqual(self.transcript.pending_messages, 1)
        self.transcript.down.event_generate("<Button-1>", x=22, y=22)
        self.root.update()
        self.assertAlmostEqual(self.transcript.canvas.yview()[1], 1, places=3)
        self.assertFalse(self.transcript.down.winfo_manager())

    def test_outgoing_message_returns_to_bottom(self):
        self.populate()
        self.transcript._scrollbar("moveto", 0.1)
        self.root.update()
        tk.Label(self.transcript.inner, text="Отправлено", height=3).pack()
        self.transcript.message_added(outgoing=True)
        self.root.update()
        self.assertAlmostEqual(self.transcript.canvas.yview()[1], 1, places=3)

    def test_trackpad_events_coalesce_and_scroll_pixels_not_pages(self):
        self.populate()
        before = self.transcript.canvas.canvasy(0)
        for _ in range(3): self.transcript._wheel(SimpleNamespace(delta=1))
        pending = self.transcript._scroll_job
        self.assertIsNotNone(pending)
        self.transcript.after_cancel(pending)
        self.transcript._flush_scroll()
        self.root.update()
        self.assertAlmostEqual(before - self.transcript.canvas.canvasy(0), 12, delta=2)
        self.assertFalse(self.transcript.follow_tail)

    def test_short_conversation_has_no_down_button(self):
        self.populate(2)
        self.assertTrue(self.transcript.near_bottom)
        self.assertFalse(self.transcript.down.winfo_manager())


class SelectionLayoutTests(unittest.TestCase):
    def setUp(self):
        THEME.update(build_palette(**DARK_BASE))
        self.root = tk.Tk()
        self.root.geometry("600x350")
        self.actions = OnlineMessageActions()
        self.actions.root = self.root
        self.actions.online_selected = set()
        self.actions.online_selection_mode = False
        self.actions.online_reply = None
        self.actions.active_online_chat = "peer"
        self.actions.online_chats = {"peer": [{"local_id": "first", "text": "Текст"}]}
        self.row = tk.Frame(self.root, bg=THEME["chat_bg"])
        self.row.pack(fill="x")
        self.marker = MessageSelectionIndicator(self.row)
        self.marker.pack(side="left")
        self.holder = tk.Frame(self.row, bg=THEME["chat_bg"])
        self.holder.pack(side="right")
        self.bubble = tk.Label(self.holder, text="Сообщение", padx=18, pady=10)
        self.bubble.pack()
        self.row.selection_chrome = (self.marker, self.holder)
        self.actions.online_media_rows = {"first": self.row}
        self.actions.online_message_tools = tk.Frame(self.root, bg=THEME["surface"])
        self.actions.online_message_tools.pack(fill="x")
        self.actions.bind_message_actions(self.row, "first")
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_selection_keeps_geometry_and_toolbar_widgets(self):
        size = (self.row.winfo_height(), self.holder.winfo_x(), self.holder.winfo_width())
        self.actions.select_online_item("first")
        self.root.update()
        self.assertEqual(size, (self.row.winfo_height(), self.holder.winfo_x(), self.holder.winfo_width()))
        children = self.actions.online_message_tools.winfo_children()
        self.actions.select_online_item("first")
        self.root.update()
        self.assertEqual(children, self.actions.online_message_tools.winfo_children())
        self.assertTrue(self.actions.selection_active)
        self.assertEqual(self.actions.online_message_tools.selection_count.cget("text"), "Выбрано: 0")
        self.assertTrue(self.actions.online_message_tools.copy_action._disabled)
        self.actions.clear_message_selection()
        self.assertFalse(self.actions.selection_active)
        self.assertEqual(self.marker.find_all(), ())

    def test_zero_selection_still_intercepts_bubble_actions(self):
        clicked = Mock()
        self.bubble.bind("<Button-1>", lambda _: clicked())
        self.actions.select_online_item("first")
        self.actions.select_online_item("first")
        self.bubble.event_generate("<Button-1>", x=5, y=5)
        self.root.update()
        self.assertEqual(self.actions.online_selected, {"first"})
        clicked.assert_not_called()
