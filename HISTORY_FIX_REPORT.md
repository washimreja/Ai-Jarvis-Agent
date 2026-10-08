# JARVIS HISTORY tab — root-cause audit & fix report

Branch: `arena/254a91c6-ai-jarvis-agent` · Commit `ec6f921` · Base `5f9f78e`

---

## 1. Exact root cause of "Loading chat history…" getting stuck

**`ui.py` (old line 1114) — `HistoryWidget._fetch()` called `QTimer.singleShot(0, ...)` from a plain `threading.Thread`.**

```python
def reload(self):
    self._busy = True
    self._show_status("Loading chat history…")
    threading.Thread(target=self._fetch, daemon=True).start()   # plain Python thread

def _fetch(self):
    try:
        rows = fetch_history()
        QTimer.singleShot(0, lambda: self._loaded_rows(rows))   # <-- BUG (old 1114)
    except Exception as exc:
        QTimer.singleShot(0, lambda: self._load_failed(str(exc)))  # <-- same bug (old 1116)
```

Qt creates a timer **in the calling thread**, and that thread must own an event
dispatcher (i.e. be a `QThread` running an event loop). A raw
`threading.Thread` has none, so:

* the 0 ms timer is scheduled into a thread that never dispatches events →
  **the callback silently never runs**;
* `_loaded_rows()` / `_load_failed()` therefore never execute;
* `_busy` is never reset to `False`;
* the loading label is never replaced;
* and because `reload()` starts with `if self._busy: return`, **every later
  click on HISTORY is ignored** — the tab is permanently dead until restart.

### Proof (measured, not inferred)

Three-way comparison in one controlled harness (real PyQt6 6.11, real worker
thread, GUI-thread event loop driven identically in all three):

| Mechanism used to hand data back to the GUI thread | Callback delivered |
|---|---|
| `QTimer.singleShot` from **main** thread (control) | DELIVERED |
| `pyqtSignal.emit` from **worker** thread (the fix) | DELIVERED |
| `QTimer.singleShot` from **worker** thread (**current code**) | **NEVER FIRED** |

Then the same measurement against the **real, unmodified `HistoryWidget`**:

```
label right after reload(): Loading chat history…
fetch_history() call count : 1        <-- the Neon fetch DID run and DID return rows
_busy=True  _loaded=False  widgets_rendered=1
UI text                    : ['Loading chat history…']
STUCK ON LOADING           : True
```

### Same latent bug elsewhere in `ui.py`?

Checked. `ui.py` has exactly four `QTimer.singleShot` call sites:

| Line | Called from | Verdict |
|---|---|---|
| 1078 | GUI thread (typewriter timer in `LogWidget`) | fine |
| 1225 | — (my new warning comment) | n/a |
| 2776 | GUI thread slot, after adding children | fine |
| 2785 | GUI thread slot (`_forget` click handler) | fine |

The nine `threading.Thread(...)` sites in `ui.py` contain no other
`QTimer.singleShot`. The HISTORY tab was the only place this pattern existed.

### A correction to an earlier working assumption of mine

Mid-investigation I reported that the worker's `QTimer.singleShot` also
**deadlocks the main event loop**. That was **wrong**, and I want it on the
record: a control run with **no threads at all** hung in exactly the same way,
so the hang was an artifact of my sandbox (PyQt6 running against stub
`libGL/libEGL/libxkbcommon/libdbus` shims; `QApplication.exec()` never returns
there). I rebuilt the harness to drive the loop with `processEvents()` from
Python, re-ran the control (main-thread `singleShot` → fires correctly), and
only then trusted the comparison above. The **callback-never-fires** finding is
the real one; the deadlock claim is retracted.

---

## 2. Exact files changed

| File | Change |
|---|---|
| `ui.py` | +382 / −53 — only the history helpers + `HistoryWidget`, plus 3 import lines |
| `tests/test_history_ui.py` | new, 397 lines, 29 tests |

Nothing else. Verified untouched: `main.py`, `core/` (incl. `core/chat_history.py`),
`actions/`, `memory/`, `plugins/`, `dashboard/`, `config/` → `git diff --stat`
on those paths is empty.

`MainWindow._on_log_tab_changed` is byte-identical to HEAD:
```python
def _on_log_tab_changed(self, index: int):
    if index == 1:
        self._history.reload()
```

---

## 3. Exact functions changed

**`ui.py` — new module-level pure helpers (no Qt, unit-testable):**

| Function | Line | Purpose |
|---|---|---|
| `_hist_log` | 1089 | `[History] …` breadcrumbs, off via `JARVIS_HISTORY_DEBUG=0` |
| `_hist_parse_stamp` | 1100 | `sent_at` → aware datetime; handles `+00:00`, `Z`, naive SQLite text, real datetimes; returns `None` instead of raising |
| `_hist_bucket` | 1129 | `TODAY` / `YESTERDAY` / `OLDER` |
| `_hist_is_user_row` | 1148 | user vs JARVIS turn |
| `_hist_title` | 1156 | first meaningful **user** message |
| `group_history` | 1169 | raw rows → conversation list |

**`ui.py` — `HistoryWidget` (line 1217):**

| Member | Line | Status |
|---|---|---|
| `_rows_ready` / `_fetch_error` `pyqtSignal` | 1235–1236 | **new** (the fix) |
| `FETCH_LIMIT = 400`, `TIMEOUT_MS = 20_000` | 1238–1239 | **new** |
| `reload` | 1274 | rewritten — starts the timeout guard |
| `_fetch_worker` | 1289 | **replaces `_fetch`** — emits signals, no Qt timers |
| `_on_timeout` | 1325 | **new** — hard guarantee the loading label dies |
| `_is_stale` | 1338 | **new** — generation check |
| `_loaded_rows` | 1347 | rewritten — `(generation, rows)` payload |
| `_show_error` | 1366 | **replaces `_load_failed`** — error ≠ empty, offers SQLite |
| `_render_list` / `_open_conversation` / `_back_to_list` | 1452 / 1462 / 1470 | **new** |
| `_add_row` | — | **removed** (per-message rows replaced by conversations) |

Removed members have zero remaining references anywhere in the repo
(`_load_failed`: 0, `_add_row`: 0).

---

## 4. Was the Neon fetch actually successful before the UI bug?

**Yes.** The measurement above shows `fetch_history() call count : 1` while the
UI stayed on the loading label — the fetch ran, returned rows, and the result
was thrown away because the callback never fired. This was **never** a Neon
problem, and nothing in `core/chat_history.py` was modified.

**Honest scope limit:** I could not exercise a *live* Neon connection from this
sandbox — there is no `database_url` in `config/api_keys.json` here. Note that
`tests/test_neon_connectivity.py` reports "1 passed" under pytest but actually
returns `False` at step 1 in this environment (it `return`s instead of
asserting — hence pytest's `PytestReturnNotNoneWarning`). So it does **not**
prove live connectivity here; on your machine, with real config, it does.

What I verified instead: the pipeline against rows in the exact shape
`_fetch_db` → `_normalize_row` produces (`sent_at` as an ISO string), driven
through the real `HistoryWidget`.

---

## 5. How the fetched rows are transformed

`fetch_history(400)` → `list[dict]` with
`id, conversation_id, sender_id, sender_name, message_content, sent_at`
→ `group_history()` →

```python
{
  "conversation_id": str,
  "messages":      [ ...chronological... ],
  "title":         "first user message",
  "count":         int,
  "started_at":    datetime | None,
  "last_at":       datetime | None,
  "bucket":        "TODAY" | "YESTERDAY" | "OLDER",
}
```

`sent_at` is normalised by `_hist_parse_stamp` (psycopg returns aware
`timestamptz`; `_normalize_row` stringifies it; the SQLite fallback writes
naive UTC — all three are handled). Non-dict / malformed rows are skipped,
never fatal.

## 6. How conversations are grouped

By `conversation_id` (which `main.py` sets to one UUID per process,
`self._conversation_id = str(uuid.uuid4())`). Messages inside a conversation
are **re-sorted chronologically** — `fetch_history` returns them
`ORDER BY sent_at DESC` then reversed, so the widget does not trust the input
order. Conversations are sorted newest-first by `last_at`; bucket labels come
from `_BUCKET_LABELS`. Titles come from the first row whose `sender_id` is not
in `{"assistant","jarvis","ai","system","bot"}` — `main.py` writes
`"local-user"` for you and `"assistant"` for JARVIS, both verified in source.
**No UUID is ever rendered.**

## 7. How the HISTORY UI is populated

`reload()` → loading label + 20 s guard → worker thread → `_rows_ready.emit((generation, rows))`
→ Qt **queued** connection into the GUI thread → `_loaded_rows` →
`group_history` → `_render_list()` builds bucket headers + one `QPushButton`
per conversation → click → `_open_conversation()` renders the chronological
message view with a `‹ Back to conversations` button → back → `_back_to_list()`.
Styling reuses the existing palette (`C.PANEL2`, `C.BORDER`, `C.PRI`, `C.PRI_DIM`,
`C.TEXT`, `C.TEXT_MED`, `Courier New`) — no redesign.

## 8. How loading / error / empty states are handled now

The loading flag is cleared on **every** path, each covered by a test:

| Path | UI shows | Test |
|---|---|---|
| success | Today / Yesterday / Older list | `test_successful_fetch_clears_loading_and_lists_conversations` |
| empty (0 rows, fetch OK) | `No chat history yet` | `test_empty_fetch_shows_empty_state_not_loading` |
| exception | `Unable to load chat history` + real message; SQLite rows rendered under `Using local history…` if any | `test_exception_shows_error_state_not_loading` |
| timeout (fetch never returns) | `Unable to load chat history / Neon did not respond within 20s.` | `test_timeout_clears_loading_even_if_fetch_never_returns` |
| malformed return type | error state, not a hang | `test_malformed_fetch_return_type_reports_error_not_a_hang` |
| result arriving after timeout | ignored | `test_late_result_after_timeout_is_ignored` |

An exception is **never** reported as empty history. Exceptions print a real
traceback to stderr and put real text in the UI. A generation token makes a
late worker's result unreachable after a timeout or a second HISTORY click.

## 9. Tests passed

```
tests/test_neon_connectivity.py      1 passed   (see caveat in §4)
tests/test_chat_history.py           3 passed
tests/test_action_policy.py          6 passed
tests/test_open_app.py               3 passed
tests/test_history_ui.py            29 passed
------------------------------------------------
                                    42 passed
```

The original 13/13 still pass. `py_compile` clean on `ui.py` and
`tests/test_history_ui.py`.

Two things I had to fix in **my own test code** before this went green (both
were test bugs, not product bugs):
* `NOW - timedelta(hours=1, seconds=-6)` is *later* than `NOW - 1h`, so my
  expected chronological order was wrong — the implementation was sorting
  correctly.
* the helper asserted the loading label *after* `processEvents()`, by which
  point an instant mock had already replaced it — racy assertion.

One genuine product bug surfaced from a pytest warning and was fixed:
`rows = list(rows or [])` raised `TypeError: 'bool' object is not iterable`
**inside the worker thread** when the fetch returned a non-iterable, which
would have left the tab on the loading label until the timeout. Row coercion
now sits inside the `try`.

**Regression guard proven red:** restoring the old `QTimer.singleShot` worker
body on top of the fixed widget makes **8 of the 11** widget-pipeline tests
fail. The tests genuinely guard the bug rather than just describing it.

## 10. Manual test result

I could not launch the full JARVIS app here — no display, no microphone, no
Gemini config. The closest faithful reproduction I ran: the **real
`LogWidget` + real `HistoryWidget` in a `QTabWidget`**, wired exactly as
`MainWindow._build_right_panel` does (ui.py 4226–4230, 4294), under Qt's
offscreen platform, with `fetch_history` returning real Neon-shaped rows:

```
current tab: LIVE
[History] Load requested
[History] Fetch started
[History] Fetch returned 5 rows
[History] Converted 5 rows into 2 conversations
[History] UI update started
[History] UI update completed

>>> after clicking HISTORY:
    Today
    Hello Jarvis / 09:00  •  4 messages
    Yesterday
    Open YouTube / 2026-10-07 18:00  •  1 message

>>> after opening the first conversation:
    ‹  Back to conversations
    Washim   ·   2026-10-08 09:00:00
    Hello Jarvis
    JARVIS   ·   2026-10-08 09:00:04
    Hello sir, how can I help?
    Washim   ·   2026-10-08 09:00:10
    What is my name?
    JARVIS   ·   2026-10-08 09:00:14
    Your name is Washim Reja.

>>> switched back to LIVE: LIVE | live log still alive: LogWidget
```

**Still open — needs your machine:** clicking HISTORY against the *real* Neon
database, and a restart-to-verify. Both require your
`config/api_keys.json` with `database_url`, which this sandbox does not have.
The `[History] …` breadcrumbs are printed to stderr by default; set
`JARVIS_HISTORY_DEBUG=0` to silence them.

---

## Note on the earlier "Neon isn't configured / run schema.sql" report

That was a false alarm and you were right to refuse it. Nothing in this fix
touches the Neon write path, the schema, or `core/chat_history.py`'s
connection handling.
