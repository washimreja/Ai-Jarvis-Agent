from core.action_policy import ActionRisk, get_action_risk, requires_confirmation
from core.permissions import ActionPermission


def test_safe_app_launch_is_trusted():
    assert get_action_risk("open_app", {"app_name": "Chrome"}) == ActionRisk.TRUSTED
    assert not requires_confirmation("open_app", {"app_name": "Chrome"})


def test_browser_navigation_is_trusted():
    assert get_action_risk("browser_control", {"action": "go_to", "url": "https://youtube.com"}) == ActionRisk.CONTEXTUAL
    assert not requires_confirmation("browser_control", {"action": "search", "query": "AI"})


def test_destructive_file_actions_require_confirmation():
    assert get_action_risk("file_controller", {"action": "delete"}) == ActionRisk.HIGH_RISK
    assert requires_confirmation("file_controller", {"action": "delete"})
    assert not requires_confirmation(
        "file_controller",
        {"action": "read"},
        ActionPermission.DESTRUCTIVE,
    )


def test_shutdown_requires_confirmation():
    assert get_action_risk("computer_settings", {"action": "shutdown"}) == ActionRisk.HIGH_RISK
    assert requires_confirmation("computer_settings", {"action": "shutdown"})


def test_unknown_tool_is_not_trusted():
    assert get_action_risk("future_plugin_action") == ActionRisk.HIGH_RISK
    assert requires_confirmation("future_plugin_action")


def test_unknown_inner_actions_are_not_trusted():
    assert get_action_risk(
        "browser_control",
        {"action": "future_browser_action"},
    ) == ActionRisk.CONTEXTUAL
    assert get_action_risk(
        "computer_control",
        {"action": "future_computer_action"},
    ) == ActionRisk.CONTEXTUAL
    assert not requires_confirmation(
        "browser_control",
        {"action": "future_browser_action"},
    )
