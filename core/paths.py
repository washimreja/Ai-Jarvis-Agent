"""Writable application data paths, independent of the source checkout."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _data_dir() -> Path:
    override = os.environ.get("MARKLIV_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / "MarkLIV"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MarkLIV"
    root = os.environ.get("XDG_CONFIG_HOME")
    return (Path(root) / "markliv") if root else Path.home() / ".config" / "markliv"


DATA_DIR = _data_dir()
CONFIG_DIR = DATA_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"
MEMORY_DIR = DATA_DIR / "memory"
MEMORY_FILE = MEMORY_DIR / "long_term.json"
CHAT_DB_FILE = MEMORY_DIR / "chat_history.db"
LOG_DIR = DATA_DIR / "logs"


def ensure_data_dirs() -> None:
    for directory in (CONFIG_DIR, MEMORY_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
