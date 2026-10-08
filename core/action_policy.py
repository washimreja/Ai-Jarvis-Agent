from __future__ import annotations

from enum import Enum
from typing import Any


class ActionRisk(Enum):
    TRUSTED = "trusted"
    CONTEXTUAL = "contextual"
    HIGH_RISK = "high_risk"


_SAFE_TOOL_NAMES = {
    "open_app",
    "system_status",
    "manage_monitor",
    "save_memory",
    "recall_memory",
    "undo",
    "screen_process",
    "close_camera",
    "web_search",
    "youtube_video",
    "file_processor",
}

_CONTEXTUAL_ACTIONS = {
    "browser_control": {
        "go_to", "search", "new_tab", "switch", "list_browsers",
        "close", "close_all", "back", "forward", "reload",
        "scroll", "click", "type", "fill_form", "smart_click",
        "smart_type", "get_text", "get_url", "press", "close_tab",
        "screenshot",
    },
    "computer_control": {
        "type", "smart_type", "left_click", "double_click", "click",
        "right_click", "move", "drag", "hotkey", "press", "scroll",
        "copy", "paste", "screenshot", "wait", "clear_field",
        "focus_window", "screen_find", "screen_click", "random_data",
        "user_data",
    },
    "computer_settings": {
        "volume_up", "volume_down", "mute", "unmute", "toggle_mute",
        "brightness_up", "brightness_down", "dark_mode", "toggle_dark_mode",
        "toggle_wifi", "wifi_on", "wifi_off", "refresh", "reload",
        "scroll_up", "scroll_down", "type_text", "write_on_screen",
        "press_key", "reload_n", "refresh_n", "reload_page_n",
        "lock_screen", "sleep_display", "screen_off", "open_settings",
        "close_app", "minimize_window", "maximize_window", "restore_window",
        "focus_window", "switch_window", "open_file_explorer",
        "new_tab", "close_tab", "full_screen", "windowed", "toggle_fullscreen",
        "screenshot",
    },
    "file_controller": {
        "list", "read", "find", "largest", "disk_usage", "info",
        "organize_desktop",
    },
}

_HARD_RISK_ACTIONS = {
    "computer_settings": {"restart", "shutdown"},
    "file_controller": {"delete", "move", "copy", "create_file", "create_folder",
                        "rename", "write"},
}

_DESTRUCTIVE_TOOL_NAMES = {"file_controller"}
_ACTION_LEVEL_TOOLS = set(_CONTEXTUAL_ACTIONS)


def normalize_action_name(name: str | None) -> str:
    if not name:
        return ""
    return str(name).strip().lower()


def get_action_risk(action_name: str | None, parameters: dict[str, Any] | None = None) -> ActionRisk:
    """Return the risk level for the resolved action.

    This intentionally classifies the action rather than the user's natural-language phrasing.
    """
    name = normalize_action_name(action_name)
    params = parameters or {}

    if name in _SAFE_TOOL_NAMES:
        return ActionRisk.TRUSTED

    if name in _ACTION_LEVEL_TOOLS:
        inner = normalize_action_name(params.get("action"))
        if inner in _HARD_RISK_ACTIONS.get(name, set()):
            return ActionRisk.HIGH_RISK
        if name in _DESTRUCTIVE_TOOL_NAMES and inner not in _CONTEXTUAL_ACTIONS[name]:
            return ActionRisk.HIGH_RISK
        if inner in _CONTEXTUAL_ACTIONS.get(name, set()):
            return ActionRisk.CONTEXTUAL
        return ActionRisk.CONTEXTUAL

    return ActionRisk.HIGH_RISK


def is_trusted_action(action_name: str | None, parameters: dict[str, Any] | None = None) -> bool:
    return get_action_risk(action_name, parameters) in {ActionRisk.TRUSTED, ActionRisk.CONTEXTUAL}


def requires_confirmation(
    action_name: str | None,
    parameters: dict[str, Any] | None = None,
    required_permission: Any = None,
) -> bool:
    name = normalize_action_name(action_name)
    if get_action_risk(name, parameters) == ActionRisk.HIGH_RISK:
        return True

    # Preserve broad destructive decorators for tools without an explicit
    # action-level policy. Classified tools are gated by their resolved action.
    return (
        getattr(required_permission, "name", "") == "DESTRUCTIVE"
        and name not in _ACTION_LEVEL_TOOLS
    )
