"""
Quick permission policy verification script.
Tests that safe actions don't require confirmation.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.action_policy import ActionRisk, get_action_risk, requires_confirmation

def test_case(name, action_name, params, expected_risk, expected_confirmation):
    """Test one permission scenario."""
    actual_risk = get_action_risk(action_name, params)
    actual_confirmation = requires_confirmation(action_name, params)
    
    risk_pass = actual_risk == expected_risk
    conf_pass = actual_confirmation == expected_confirmation
    
    status = "✓" if (risk_pass and conf_pass) else "❌"
    
    print(f"{status} {name}")
    if not risk_pass:
        print(f"   Risk: expected {expected_risk.value}, got {actual_risk.value}")
    if not conf_pass:
        print(f"   Confirmation: expected {expected_confirmation}, got {actual_confirmation}")
    
    return risk_pass and conf_pass


def main():
    print("=" * 70)
    print("JARVIS PERMISSION POLICY VERIFICATION")
    print("=" * 70)
    
    tests = []
    
    # Safe app launches - should NOT require confirmation
    print("\n[Safe Application Launches - No Confirmation]")
    tests.append(test_case(
        "open_app: Chrome",
        "open_app", {"app_name": "Chrome"},
        ActionRisk.TRUSTED, False
    ))
    tests.append(test_case(
        "open_app: YouTube",
        "open_app", {"app_name": "YouTube"},
        ActionRisk.TRUSTED, False
    ))
    tests.append(test_case(
        "open_app: VS Code",
        "open_app", {"app_name": "VS Code"},
        ActionRisk.TRUSTED, False
    ))
    tests.append(test_case(
        "open_app: ChatGPT",
        "open_app", {"app_name": "ChatGPT"},
        ActionRisk.TRUSTED, False
    ))
    
    # Browser actions - contextual, no confirmation
    print("\n[Browser Actions - Contextual, No Confirmation]")
    tests.append(test_case(
        "browser_control: search",
        "browser_control", {"action": "search", "query": "AI"},
        ActionRisk.CONTEXTUAL, False
    ))
    tests.append(test_case(
        "browser_control: go_to",
        "browser_control", {"action": "go_to", "url": "https://youtube.com"},
        ActionRisk.CONTEXTUAL, False
    ))
    tests.append(test_case(
        "browser_control: scroll",
        "browser_control", {"action": "scroll"},
        ActionRisk.CONTEXTUAL, False
    ))
    tests.append(test_case(
        "browser_control: click",
        "browser_control", {"action": "click"},
        ActionRisk.CONTEXTUAL, False
    ))
    
    # Computer control - contextual, no confirmation
    print("\n[Computer Control - Contextual, No Confirmation]")
    tests.append(test_case(
        "computer_control: type",
        "computer_control", {"action": "type"},
        ActionRisk.CONTEXTUAL, False
    ))
    tests.append(test_case(
        "computer_control: click",
        "computer_control", {"action": "click"},
        ActionRisk.CONTEXTUAL, False
    ))
    
    # File operations - read is safe
    print("\n[File Operations - Read is Safe]")
    tests.append(test_case(
        "file_controller: read",
        "file_controller", {"action": "read"},
        ActionRisk.CONTEXTUAL, False
    ))
    tests.append(test_case(
        "file_controller: list",
        "file_controller", {"action": "list"},
        ActionRisk.CONTEXTUAL, False
    ))
    
    # Destructive actions - MUST require confirmation
    print("\n[Destructive Actions - Confirmation Required]")
    tests.append(test_case(
        "file_controller: delete",
        "file_controller", {"action": "delete"},
        ActionRisk.HIGH_RISK, True
    ))
    tests.append(test_case(
        "computer_settings: shutdown",
        "computer_settings", {"action": "shutdown"},
        ActionRisk.HIGH_RISK, True
    ))
    tests.append(test_case(
        "computer_settings: restart",
        "computer_settings", {"action": "restart"},
        ActionRisk.HIGH_RISK, True
    ))
    
    # Unknown actions - should be treated as high risk
    print("\n[Unknown Actions - High Risk by Default]")
    tests.append(test_case(
        "unknown_tool",
        "unknown_tool", {},
        ActionRisk.HIGH_RISK, True
    ))
    
    # Results
    print("\n" + "=" * 70)
    passed = sum(tests)
    total = len(tests)
    
    if passed == total:
        print(f"✅ ALL {total} TESTS PASSED")
        print("=" * 70)
        print("\nPermission policy is correctly configured:")
        print("• open_app (Chrome, YouTube, VS Code) → NO confirmation")
        print("• browser_control (search, navigate, click) → NO confirmation")
        print("• computer_control (type, click) → NO confirmation")
        print("• file_controller (delete) → REQUIRES confirmation")
        print("• computer_settings (shutdown, restart) → REQUIRES confirmation")
        print("=" * 70)
        return True
    else:
        print(f"❌ {total - passed}/{total} TESTS FAILED")
        print("=" * 70)
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
