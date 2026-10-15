"""Small, content-free identifiers for user and background agent activity."""

AGENT_SCOPES = frozenset({"main", "subagent", "internal", "unknown"})


def normalize_agent_scope(value):
    return value if isinstance(value, str) and value in AGENT_SCOPES else "unknown"


def scope_from_session_source(source):
    """Classify rollout metadata without retaining instructions or transcripts."""
    if isinstance(source, dict) and "subagent" in source:
        subagent = source["subagent"]
        if isinstance(subagent, dict) and "thread_spawn" in subagent:
            return "subagent"
        return "internal"
    if isinstance(source, str) and source in {"cli", "vscode", "exec", "mcp"}:
        return "main"
    return "unknown"
