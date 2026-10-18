.pragma library
// Shared lookups for the layouts; colors come from the design tokens.

// A length at the widget size, on whole pixels so edges stay crisp.
function px(value, scale) {
    return Math.round(value * scale)
}

function levelColor(theme, level) {
    if (level === "critical")
        return theme.status_failed
    if (level === "low")
        return theme.status_attention
    return theme.accent
}

// The value's color: its level, or the muted ink once it is stale. Stale
// values stay opaque so they read on a see-through background.
function valueColor(theme, provider) {
    if (!hasLimit(provider))
        return theme.float_muted
    if (provider.state === "stale")
        return theme.float_muted
    return levelColor(theme, provider.main.level)
}

function sourceColor(theme, key) {
    return key === "claude_code" ? theme.source_claude_code : theme.source_codex
}

// One short line for a provider that has no limit to draw.
function stateText(provider) {
    const labels = provider.labels || {}
    switch (provider.state) {
    case "loading": return labels.loading
    case "offline": return labels.offline
    case "no_account": return labels.no_account
    case "no_limits":
        return provider.key === "claude_code" ? (labels.terminal_limits || "") : (labels.no_limits || "")
    }
    return ""
}

// A limit past its reset with no new sample is an estimate; limit.estimateMark marks it.
// Big numbers have no room for the mark, so their window label carries it.
function percentText(limit) {
    return valueText(limit) + estimateMark(limit)
}

function valueText(limit) {
    return limit.remaining + "%"
}

function labelText(limit) {
    return limit.label + estimateMark(limit)
}

function estimateMark(limit) {
    return limit.estimated ? (limit.estimateMark || "") : ""
}

function hasLimit(provider) {
    return provider.main !== null && provider.main !== undefined
}
