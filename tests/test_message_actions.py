import tkinter as tk
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from desktop_chat.message_actions import OnlineMessageActions
from desktop_chat.shared import THEME, DARK_BASE, build_palette


class MessageActionTests(unittest.TestCase):
    def setUp(self):
        THEME.update(build_palette(**DARK_BASE))
        self.root = tk.Tk()
        self.actions = OnlineMessageActions()
        self.actions.root = self.root
        self.actions.online_selected = set()
        self.actions.online_media_rows = {}
        self.actions.refresh_message_tools = Mock()

    def tearDown(self):
        self.root.destroy()

    def test_right_click_menu_contains_all_requested_actions(self):
        self.actions.find_online_item = Mock(return_value={"text": "Hello"})
        menu = Mock()
        with patch("desktop_chat.message_actions.tk.Menu", return_value=menu):
            self.actions.message_context(SimpleNamespace(x_root=10, y_root=10), "message-id")
        self.assertEqual([call.kwargs["label"] for call in menu.add_command.call_args_list],
                         ["Скопировать", "Переслать", "Выбрать", "Ответить"])

    def test_selection_intercepts_links_before_they_open(self):
        row = tk.Frame(self.root)
        row.pack()
        child = tk.Label(row, text="link")
        child.pack()
        original = Mock()
        child.bind("<Button-1>", lambda event: original())
        self.actions.online_media_rows["first"] = row
        self.actions.bind_message_actions(row, "first")
        self.root.update()
        self.actions.online_selected.add("second")
        child.event_generate("<Button-1>", x=5, y=5)
        self.root.update()
        self.assertIn("first", self.actions.online_selected)
        original.assert_not_called()
