"""Dependency-free event name normalization shared with the hook bridge.

Kept free of dataclasses so the packaged hook bridge starts quickly (ADR 0004).
Adapted from the event normalization design of yangbuyiya/desktop-pet; see
THIRD_PARTY_NOTICES.md for attribution.
"""

SOURCE_ALIASES = {
    "codex": "codex",
    "codex-cli": "codex",
    "openai-codex": "codex",
    "claude": "claude_code",
    "claude-code": "claude_code",
    "claude_code": "claude_code",
    "calendar": "schedule",
    "reminder": "schedule",
    "schedule": "schedule",
}

SOURCE_LABELS = {
    "codex": "Codex",
    "claude_code": "Claude Code",
    "schedule": "일정",
    "system": "비서",
}

# Coding agents whose hook events drive pet work states. Other sources
# (schedule, manual) only raise notifications.
AGENT_SOURCES = frozenset({"codex", "claude_code"})

URGENCY_ALIASES = {
    "urgent": "high",
    "high": "high",
    "important": "high",
    "normal": "normal",
    "medium": "normal",
    "default": "normal",
    "low": "low",
    "quiet": "low",
}

EVENT_ALIASES = {
    "sessionstart": "session_start",
    "subagentstart": "task_start",
    "start": "task_start",
    "taskstart": "task_start",
    "userpromptsubmit": "prompt",
    "prompt": "prompt",
    "thinking": "thinking",
    "review": "review",
    "pretooluse": "tool_start",
    "toolstart": "tool_start",
    "posttooluse": "tool_end",
    "toolend": "tool_end",
    "posttoolfailure": "tool_failed",
    "posttoolusefailure": "tool_failed",
    "permissionrequest": "permission",
    "permission": "permission",
    "permissionresolved": "permission_resolved",
    "waiting": "waiting",
    "questionwait": "question_wait",
    "questionresolved": "question_resolved",
    "notification": "notification",
    "remind": "notification",
    "scheduledue": "notification",
    "reminderdue": "notification",
    "calendarreminder": "notification",
    "stop": "done",
    "taskend": "done",
    "success": "done",
    "done": "done",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "interrupted": "cancelled",
    "stopfailure": "failed",
    "fail": "failed",
    "failed": "failed",
    "error": "failed",
    "sessionend": "session_end",
    "subagentstop": "done",
    "precompact": "review",
    "postcompact": "review",
    "idle": "idle",
}


def normalize_agent_source(value):
    key = str(value or "manual").strip().lower()
    return SOURCE_ALIASES.get(key, key or "manual")


def source_display_label(value):
    source = normalize_agent_source(value)
    return SOURCE_LABELS.get(source, source)


def normalize_urgency(value):
    key = str(value or "normal").strip().lower()
    return URGENCY_ALIASES.get(key, "normal")


def normalize_event_name(value):
    raw = str(value or "").strip().lower()
    compact = raw.replace(" ", "").replace(".", "").replace("-", "").replace("_", "")
    return EVENT_ALIASES.get(raw, EVENT_ALIASES.get(compact, raw))


def approval_actor(payload):
    value = payload.get(
        "approval_actor",
        payload.get("approvalsReviewer", payload.get("approvals_reviewer")),
    )
    return {
        "user": "user",
        "auto": "auto",
        "auto_review": "auto",
        "guardian_subagent": "auto",
    }.get(str(value), "unknown")
