"""Regression tests for the HISTORY tab pipeline (ui.HistoryWidget).

Background: the HISTORY tab used to hang on "Loading chat history…" forever.
`HistoryWidget._fetch` ran in a plain `threading.Thread` and handed its result
back with `QTimer.singleShot(0, ...)`. Qt creates that timer in the *calling*
thread, which has no event dispatcher, so the callback never ran: `_busy` was
never cleared and the loading label was never replaced.

The first group of tests covers the pure Neon-rows -> conversations transform
(no Qt needed). The second group drives the real widget and asserts the loading
state is always cleared — that is the regression that used to fail.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from ui import _hist_bucket, _hist_parse_stamp, _hist_title, group_history

# A fixed "now" so the Today/Yesterday/Older buckets are deterministic.
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _msg(cid, sender_id, sender_name, content, when):
    return {
        "id": f"{cid}-{content[:6]}",
        "conversation_id": cid,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "message_content": content,
        "sent_at": when.isoformat(),
    }


def _u(cid, content, when):
    return _msg(cid, "local-user", "Washim", content, when)


def _a(cid, content, when):
    return _msg(cid, "assistant", "JARVIS", content, when)


class GroupHistoryTests(unittest.TestCase):
    """Rows in Neon -> the conversation list the HISTORY tab renders."""

    def test_groups_by_conversation_id_newest_first(self):
        rows = [
            _u("c1", "Hello Jarvis", NOW - timedelta(hours=3)),
            _a("c1", "Hello sir", NOW - timedelta(hours=3) + timedelta(seconds=4)),
            _u("c2", "Neon database setup", NOW - timedelta(days=1)),
            _u("c3", "Explain Java JDBC", NOW - timedelta(days=9)),
        ]
        convs = group_history(rows, now=NOW)

        self.assertEqual([c["conversation_id"] for c in convs], ["c1", "c2", "c3"])
        self.assertEqual([c["count"] for c in convs], [2, 1, 1])

    def test_messages_inside_a_conversation_are_chronological(self):
        # Handed over newest-first, as a DESC fetch would: the widget must
        # re-sort them chronologically before rendering.
        rows = [
            _a("c1", "Your name is Washim Reja.", NOW - timedelta(minutes=57)),
            _u("c1", "What is my name?", NOW - timedelta(hours=1)),
            _a("c1", "Hello sir", NOW - timedelta(hours=1, minutes=3)),
            _u("c1", "Hello Jarvis", NOW - timedelta(hours=2)),
        ]
        conv = group_history(rows, now=NOW)[0]
        self.assertEqual(
            [m["message_content"] for m in conv["messages"]],
            ["Hello Jarvis", "Hello sir", "What is my name?",
             "Your name is Washim Reja."],
        )

    def test_title_comes_from_first_user_message_not_from_jarvis(self):
        rows = [
            _a("c1", "Good morning, how can I help?", NOW - timedelta(hours=2)),
            _u("c1", "Open YouTube", NOW - timedelta(hours=1)),
        ]
        self.assertEqual(group_history(rows, now=NOW)[0]["title"], "Open YouTube")

    def test_title_falls_back_to_assistant_when_no_user_message(self):
        rows = [_a("c1", "System notice", NOW - timedelta(hours=1))]
        self.assertEqual(group_history(rows, now=NOW)[0]["title"], "System notice")

    def test_buckets_are_today_yesterday_older(self):
        rows = [
            _u("today", "a", NOW - timedelta(hours=1)),
            _u("yday", "b", NOW - timedelta(days=1, hours=1)),
            _u("old", "c", NOW - timedelta(days=40)),
        ]
        buckets = {c["conversation_id"]: c["bucket"] for c in group_history(rows, now=NOW)}
        self.assertEqual(buckets, {"today": "TODAY", "yday": "YESTERDAY", "old": "OLDER"})

    def test_uuids_are_not_used_as_titles(self):
        rows = [_u("b3f1c2a4-9d5e-4a1f-8c2b-771122334455", "Open YouTube", NOW)]
        conv = group_history(rows, now=NOW)[0]
        self.assertEqual(conv["title"], "Open YouTube")
        self.assertNotIn("b3f1c2a4", conv["title"])

    def test_empty_rows_yield_no_conversations(self):
        self.assertEqual(group_history([], now=NOW), [])
        self.assertEqual(group_history(None, now=NOW), [])

    def test_malformed_rows_are_skipped_not_fatal(self):
        rows = ["not-a-dict", None, _u("c1", "kept", NOW)]
        convs = group_history(rows, now=NOW)
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["title"], "kept")

    def test_missing_sent_at_does_not_crash_and_sorts_last(self):
        rows = [
            {"conversation_id": "c1", "sender_id": "local-user",
             "sender_name": "Washim", "message_content": "no timestamp"},
            _u("c2", "has timestamp", NOW),
        ]
        convs = group_history(rows, now=NOW)
        self.assertEqual([c["conversation_id"] for c in convs], ["c2", "c1"])
        self.assertEqual(convs[1]["bucket"], "OLDER")


class StampParsingTests(unittest.TestCase):
    def test_parses_neon_iso_utc(self):
        dt = _hist_parse_stamp("2026-10-08T09:00:00+00:00")
        self.assertEqual(dt, datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))

    def test_parses_zulu_suffix(self):
        dt = _hist_parse_stamp("2026-10-08T09:00:00Z")
        self.assertEqual(dt, datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc))

    def test_parses_naive_sqlite_text_as_utc(self):
        dt = _hist_parse_stamp("2026-10-08 09:00:00.123456")
        self.assertIsNotNone(dt.tzinfo)
        self.assertEqual(dt.year, 2026)

    def test_accepts_real_datetime_objects(self):
        aware = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(_hist_parse_stamp(aware), aware)

    def test_unusable_values_return_none(self):
        for bad in (None, "", "   ", "not a date", 12345):
            self.assertIsNone(_hist_parse_stamp(bad), f"{bad!r} should be None")

    def test_bucket_of_none_is_older(self):
        self.assertEqual(_hist_bucket(None, now=NOW), "OLDER")


class TitleTests(unittest.TestCase):
    def test_ignores_sender_name_when_sender_id_says_assistant(self):
        rows = [{"sender_id": "assistant", "sender_name": "Washim-bot",
                 "message_content": "hi"}]
        self.assertFalse(__import__("ui")._hist_is_user_row(rows[0]))

    def test_title_strips_whitespace_runs(self):
        rows = [_u("c1", "  what   is\n my name?  ", NOW)]
        self.assertEqual(_hist_title(rows), "what is my name?")

    def test_title_of_nothing_is_placeholder(self):
        self.assertEqual(_hist_title([]), "(empty conversation)")
        self.assertEqual(_hist_title([_u("c1", "   ", NOW)]), "(empty conversation)")


# ── The actual HISTORY-tab regression ─────────────────────────────────────────
try:
    from PyQt6.QtWidgets import QApplication, QLabel, QPushButton
    import ui as _ui_module
    _QT_AVAILABLE = True
    _QT_IMPORT_ERROR = ""
except Exception as exc:            # pragma: no cover — headless CI without Qt
    _QT_AVAILABLE = False
    _QT_IMPORT_ERROR = str(exc)


@unittest.skipUnless(_QT_AVAILABLE, f"PyQt6 not importable: {_QT_IMPORT_ERROR}")
class HistoryWidgetPipelineTests(unittest.TestCase):
    """Drives the real HistoryWidget and asserts the loading state clears.

    Against the pre-fix code every test here fails: the widget stays on
    "Loading chat history…" with `_busy` still True.
    """

    SETTLE_SECS = 1.5

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ["JARVIS_HISTORY_DEBUG"] = "0"
        self.widget = _ui_module.HistoryWidget()

    def _settle(self, seconds=None):
        """Pump the GUI-thread event loop until the worker's signal lands."""
        deadline = time.time() + (seconds or self.SETTLE_SECS)
        while time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    def _visible_text(self):
        out = []
        layout = self.widget._rows
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None:
                out.append(w.text())
        return out

    def _click(self, needle):
        layout = self.widget._rows
        for i in range(layout.count()):
            w = layout.itemAt(i).widget()
            if isinstance(w, QPushButton) and needle in w.text():
                w.click()
                return True
        return False

    def _reload_and_settle(self, seconds=None):
        """Pump the GUI-thread event loop until the worker's signal lands."""
        self.widget.reload()
        # Asserted *before* processEvents(): the queued signal from the worker
        # can only be delivered by the event loop, so this is deterministic.
        self.assertTrue(self.widget._busy, "reload() did not enter the loading state")
        self.assertIn("Loading chat history", self._visible_text()[0])
        self._settle(seconds)

    def test_successful_fetch_clears_loading_and_lists_conversations(self):
        rows = [
            _u("c1", "Hello Jarvis", NOW - timedelta(hours=1)),
            _a("c1", "Hello sir", NOW - timedelta(hours=1) + timedelta(seconds=4)),
            _u("c2", "Open YouTube", NOW - timedelta(days=1)),
        ]
        with patch("core.chat_history.fetch_history", return_value=rows):
            self._reload_and_settle()

        self.assertFalse(self.widget._busy, "loading flag was never cleared")
        self.assertTrue(self.widget._loaded)
        text = " | ".join(self._visible_text())
        self.assertNotIn("Loading chat history", text)
        self.assertIn("Today", text)
        self.assertIn("Yesterday", text)
        self.assertIn("Hello Jarvis", text)
        self.assertIn("Open YouTube", text)

    def test_empty_fetch_shows_empty_state_not_loading(self):
        with patch("core.chat_history.fetch_history", return_value=[]):
            self._reload_and_settle()

        self.assertFalse(self.widget._busy)
        text = " | ".join(self._visible_text())
        self.assertNotIn("Loading", text)
        self.assertIn("No chat history yet", text)

    def test_exception_shows_error_state_not_loading(self):
        with patch("core.chat_history.fetch_history",
                   side_effect=ConnectionError("Neon unreachable")), \
             patch("core.chat_history._fetch_sqlite", return_value=[]):
            self._reload_and_settle()

        self.assertFalse(self.widget._busy)
        text = " | ".join(self._visible_text())
        self.assertNotIn("Loading", text)
        self.assertIn("Unable to load chat history", text)
        self.assertIn("Neon unreachable", text)

    def test_timeout_clears_loading_even_if_fetch_never_returns(self):
        import threading
        never = threading.Event()
        self.addCleanup(never.set)
        self.widget.TIMEOUT_MS = 400
        with patch("core.chat_history.fetch_history", side_effect=lambda limit=100: never.wait(30)):
            self._reload_and_settle(seconds=1.5)

        self.assertFalse(self.widget._busy, "timeout did not clear the loading state")
        text = " | ".join(self._visible_text())
        self.assertNotIn("Loading", text)
        self.assertIn("Unable to load chat history", text)

    def test_selecting_a_conversation_shows_its_messages_in_order(self):
        rows = [
            _u("c1", "Hello Jarvis", NOW - timedelta(hours=2)),
            _a("c1", "Hello sir, how can I help?", NOW - timedelta(hours=2) + timedelta(seconds=4)),
            _u("c1", "What is my name?", NOW - timedelta(hours=1)),
            _a("c1", "Your name is Washim Reja.", NOW - timedelta(hours=1) + timedelta(seconds=3)),
        ]
        with patch("core.chat_history.fetch_history", return_value=rows):
            self._reload_and_settle()

        self.assertTrue(self._click("message"), "conversation row was not clickable")
        self._settle(0.4)

        text = self._visible_text()
        self.assertIn("Hello Jarvis", text)
        self.assertIn("Your name is Washim Reja.", text)
        self.assertLess(text.index("Hello Jarvis"), text.index("What is my name?"),
                        "messages are not in chronological order")
        self.assertLess(text.index("What is my name?"),
                        text.index("Your name is Washim Reja."))

    def test_back_button_returns_to_the_conversation_list(self):
        rows = [_u("c1", "Hello Jarvis", NOW - timedelta(hours=1)),
                _u("c2", "Open YouTube", NOW - timedelta(days=1))]
        with patch("core.chat_history.fetch_history", return_value=rows):
            self._reload_and_settle()
        self.assertTrue(self._click("message"))
        self._settle(0.4)
        self.assertTrue(self._click("Back"))
        self._settle(0.4)

        text = " | ".join(self._visible_text())
        self.assertIn("Today", text)
        self.assertIn("Yesterday", text)

    def test_malformed_fetch_return_type_reports_error_not_a_hang(self):
        """fetch_history returning a non-iterable must not die silently in the
        worker thread and leave the tab on 'Loading chat history…'."""
        with patch("core.chat_history.fetch_history", return_value=True), \
             patch("core.chat_history._fetch_sqlite", return_value=[]):
            self._reload_and_settle()

        self.assertFalse(self.widget._busy)
        text = " | ".join(self._visible_text())
        self.assertNotIn("Loading", text)
        self.assertIn("Unable to load chat history", text)

    def test_late_result_after_timeout_is_ignored(self):
        """A worker that returns *after* the timeout must not overwrite state."""
        import threading
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.widget.TIMEOUT_MS = 300

        def slow_fetch(limit=100):
            gate.wait(10)
            return [_u("late", "I arrived too late", NOW - timedelta(hours=1))]

        with patch("core.chat_history.fetch_history", side_effect=slow_fetch):
            self.widget.reload()
            self._settle(0.9)                       # timeout fires first
            self.assertFalse(self.widget._busy)
            self.assertIn("Unable to load chat history",
                          " | ".join(self._visible_text()))

            gate.set()                              # worker finally returns
            self._settle(0.6)

        self.assertFalse(self.widget._busy)
        self.assertNotIn("I arrived too late", " | ".join(self._visible_text()),
                         "stale fetch result overwrote the timeout state")

    def test_reload_while_busy_does_not_stack_loads(self):
        rows = [_u("c1", "Hello Jarvis", NOW - timedelta(hours=1))]
        with patch("core.chat_history.fetch_history", return_value=rows):
            self.widget.reload()
            self.widget.reload()
            self.widget.reload()
            self._settle()

        self.assertFalse(self.widget._busy)
        self.assertEqual(len(self.widget._conversations), 1)

    def test_worker_thread_hands_results_back_through_a_signal(self):
        """The regression itself: no QTimer.singleShot from the worker thread."""
        self.assertTrue(hasattr(_ui_module.HistoryWidget, "_rows_ready"))
        self.assertTrue(hasattr(_ui_module.HistoryWidget, "_fetch_error"))

        import inspect
        source = inspect.getsource(_ui_module.HistoryWidget._fetch_worker)
        self.assertNotIn("QTimer.singleShot", source,
                         "QTimer.singleShot from a worker thread never fires — "
                         "this is what froze the HISTORY tab on 'Loading chat history…'")

    def test_fetch_limit_is_bounded(self):
        """Never ask Neon for unlimited rows."""
        seen = []

        def fake_fetch(limit=100):
            seen.append(limit)
            return []

        with patch("core.chat_history.fetch_history", side_effect=fake_fetch):
            self._reload_and_settle()

        self.assertEqual(len(seen), 1)
        self.assertLessEqual(seen[0], 1000)
        self.assertGreaterEqual(seen[0], 1)


if __name__ == "__main__":
    unittest.main()
