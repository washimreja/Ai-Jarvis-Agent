"""
Action Permission Architecture.
Defines the permission levels for actions and a decorator to enforce them.
"""
from enum import Enum, auto
from typing import Callable, Any

class ActionPermission(Enum):
    READ_ONLY = auto()        # Safe actions like getting weather or reading a file
    REVERSIBLE = auto()       # Actions that can be easily undone
    SIDE_EFFECTING = auto()   # Actions that change state, like sending a message or clicking a button
    DESTRUCTIVE = auto()      # Actions that delete data or perform irreversible operations

def requires_permission(level: ActionPermission):
    """
    Decorator to specify the permission level required for an action handler.
    If the level is SIDE_EFFECTING or DESTRUCTIVE, the system must intercept
    and ask for user confirmation before executing.
    """
    def decorator(func: Callable) -> Callable:
        setattr(func, "_required_permission", level)
        return func
    return decorator
