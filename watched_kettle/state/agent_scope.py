"""Small, content-free identifiers for user and background agent activity."""

AGENT_SCOPES = frozenset({"main", "subagent", "internal", "unknown"})


def normalize_agent_scope(value):
    return value if isinstance(value, str) and value in AGENT_SCOPES else "unknown"


def scope_from_session_source(source):
    """Classify rollout metadata without retaining instructions or transcripts."""
    if isinstance(source, dict) and ("subagent" in source or "subAgent" in source):
        subagent = source.get("subagent", source.get("subAgent"))
        if isinstance(subagent, dict) and (
            "thread_spawn" in subagent or "threadSpawn" in subagent
        ):
            return "subagent"
        return "internal"
    if isinstance(source, str) and source in {
        "cli",
        "vscode",
        "exec",
        "mcp",
        "appServer",
    }:
        return "main"
    return "unknown"


def scope_from_thread_metadata(thread):
    """Confirm only explicit, persisted thread identity from thread/read."""
    if thread.get("ephemeral") is True:
        return "internal"
    if thread.get("parentThreadId"):
        return "subagent"
    scope = scope_from_session_source(thread.get("source"))
    if scope in {"internal", "subagent"}:
        return scope
    return scope if thread.get("ephemeral") is False else "unknown"
