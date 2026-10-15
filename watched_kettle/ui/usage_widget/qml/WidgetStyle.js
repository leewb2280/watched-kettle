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
    switch (provider.state) {
    case "loading": return "불러오는 중"
    case "offline": return "연결 안 됨"
    case "no_account": return "로그인 필요"
    case "no_limits":
        return provider.key === "claude_code" ? "한도는 터미널에서" : "한도 정보 없음"
    }
    return ""
}

// A limit past its reset with no new sample is an estimate; "(추정)" marks it.
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
    return limit.estimated ? "(추정)" : ""
}

function hasLimit(provider) {
    return provider.main !== null && provider.main !== undefined
}
