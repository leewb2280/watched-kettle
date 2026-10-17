"""Settings wire DTOs and command exposure; no Qt, UI or service imports.

This describes the existing version-1 wire format. Runtime validation and state
ownership stay in the host/adapters. Generated clients must not expose native
file/window commands through the renderer request API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
Scalar = str | int | float | bool | None
Provider = Literal["codex", "claude_code"]
ElementKind = Literal["pattern", "ornament", "photo", "frame", "sticker"]
Page = Literal[
    "home", "pet", "bubble", "widget", "usage", "activity", "integration", "app"
]


class Empty(TypedDict):
    pass


class Context(TypedDict, total=False):
    petId: str
    revision: int
    epoch: int


class Appearance(TypedDict):
    theme: Literal["system", "light", "dark"]
    material: Literal["acrylic", "mica", "none"]
    lightOpacity: int
    darkOpacity: int
    reduceMotion: bool


class EffectiveAppearance(Appearance):
    effectiveTheme: Literal["light", "dark"]
    effectiveMaterial: Literal["acrylic", "mica", "none"]
    highContrast: bool


class Option(TypedDict):
    value: Scalar
    label: str


class ControlBase(TypedDict):
    key: str
    label: str
    group: str
    min: NotRequired[float]
    max: NotRequired[float]
    step: NotRequired[float]
    unit: NotRequired[str]
    options: NotRequired[list[Option]]
    presets: NotRequired[list[Option]]
    description: NotRequired[str | None]
    effectiveValue: NotRequired[float]
    fallbackLabel: NotRequired[str]
    disabled: NotRequired[bool]


class BooleanControl(ControlBase):
    kind: Literal["bool"]
    value: bool


class NumberControl(ControlBase):
    kind: Literal["range", "pet_size", "number"]
    value: float


class OptionalControl(ControlBase):
    kind: Literal["optional_number"]
    value: float | None


class SelectControl(ControlBase):
    kind: Literal["select"]
    value: str | float


class ColorControl(ControlBase):
    kind: Literal["color"]
    value: str


Control = (
    BooleanControl | NumberControl | OptionalControl | SelectControl | ColorControl
)


class Startup(TypedDict):
    supported: bool
    enabled: bool
    matches_current_app: bool


class Animation(TypedDict):
    label: str
    value: str


class UpdateState(TypedDict):
    state: Literal[
        "idle",
        "checking",
        "current",
        "available",
        "downloading",
        "preparing",
        "installing",
        "error",
    ]
    version: str
    page_url: str
    received: int
    total: int
    message: str
    can_install: bool
    retry: Literal["", "check", "download"]
    auto_check: bool


class SettingsSnapshot(TypedDict):
    version: str
    revision: int
    epoch: int
    edition: Literal["pet-only", "pet-assistant"]
    pet: PetSnapshot
    controls: list[Control]
    bubbleControls: list[Control]
    appearance: Appearance
    startup: Startup
    animations: list[Animation]
    update: UpdateState


class Saved(TypedDict):
    saved: bool


class Mutation(Saved):
    snapshot: SettingsSnapshot


class Pending(TypedDict):
    pending: bool


class Opened(TypedDict):
    opened: bool


class Accepted(TypedDict):
    accepted: bool


class AssistantMutation(Accepted):
    saved: bool
    epoch: int


class PetCatalogEntry(TypedDict):
    id: str
    name: str
    description: str
    thumbnail: str
    source: Literal["user", "bundled", "external"]
    canDelete: bool
    deletionReason: str


class PetCatalog(TypedDict):
    entries: list[PetCatalogEntry]
    order: list[str]
    hidden: list[str]
    sort: Literal["name", "custom"]
    revision: int
    petId: str


class Size(TypedDict):
    width: int
    height: int


class Bounds(Size):
    x: int
    y: int


class PetPreview(TypedDict):
    petId: str
    revision: int
    image: str
    sourceSize: Size
    contentBounds: Bounds
    cropBounds: Bounds


class PetTrashEntry(TypedDict):
    trashId: str
    id: str
    name: str
    deletedAt: str
    bytes: int
    thumbnail: str
    state: Literal["moving", "trashed", "restoring", "deleting"]


class PetTrashCatalog(TypedDict):
    entries: list[PetTrashEntry]
    offset: int
    total: int
    totalBytes: int
    issues: list[str]
    revision: int
    petId: str


PetBatchAction = Literal["move", "restore", "delete"]


class PetBatchResult(TypedDict):
    id: str
    name: str
    status: Literal["pending", "succeeded", "failed", "notStarted"]
    code: str
    message: str
    trashId: NotRequired[str]


class PetBatchJob(TypedDict):
    undoIds: list[str]
    jobId: str
    operationKey: str
    action: PetBatchAction
    state: Literal["running", "completed", "cancelled", "failed"]
    total: int
    processed: int
    succeeded: int
    failed: int
    message: str
    code: str
    results: list[PetBatchResult]


class BatchResponse(TypedDict):
    job: PetBatchJob | None
    snapshot: SettingsSnapshot


class PetPreparation(TypedDict):
    token: str
    name: str
    thumbnail: str
    spriteVersion: int


class Cancelled(TypedDict):
    cancelled: Literal[True]


class PetRegistration(Mutation):
    id: str
    name: str
    alreadyExists: NotRequired[bool]
    restoreRequired: NotRequired[bool]
    trashId: NotRequired[str]


class TrashMutation(Mutation, total=False):
    id: str
    name: str
    trashId: str
    deleted: int
    failed: list[str]


class RestoredPet(Mutation):
    id: str
    name: str


class Element(TypedDict):
    id: str
    name: str
    kind: str


class ElementImported(TypedDict):
    id: str


class ThemeLimit(TypedDict):
    min: float
    max: float
    step: float
    unit: str


class ThemePreset(TypedDict):
    id: str
    label: str
    values: ThemeBase


class BubbleEditor(TypedDict):
    theme: SpeechBubbleTheme
    packageTheme: SpeechBubbleTheme
    revision: int
    petId: str
    elements: list[Element]
    choices: dict[str, list[str]]
    limits: dict[str, ThemeLimit]
    labels: dict[str, dict[str, str]]
    presets: list[ThemePreset]


class BubbleRender(TypedDict):
    image: str
    theme: SpeechBubbleTheme


class PetId(TypedDict):
    petId: str


class SelectPet(Context):
    id: str


class Offset(TypedDict, total=False):
    offset: int


class Token(TypedDict):
    token: str


class RegisterPet(Token):
    name: NotRequired[str]


class CatalogSave(Context):
    sort: Literal["name", "custom"]
    order: list[str]
    hidden: list[str]


class TrashMove(Context):
    id: str
    replacementId: NotRequired[str]


class TrashId(Context):
    trashId: str


class BatchStart(Context):
    action: PetBatchAction
    ids: list[str]
    operationKey: str
    replacementId: NotRequired[str]


class BatchQuery(Context, total=False):
    jobId: str


class ThemeRequest(Context):
    theme: SpeechBubbleTheme


class RenderTheme(ThemeRequest):
    sample: NotRequired[Literal["notice", "project"]]


class ElementDelete(Context):
    reference: str


class PetAction(Context):
    action: Literal[
        "recenter",
        "recall",
        "movement_test",
        "visibility",
        "restore",
        "folder",
        "resume",
        "durations_reset",
        "duration_overrides_reset",
        "animation",
        "preview",
        "snooze",
    ]
    state: NotRequired[str]
    minutes: NotRequired[Literal[15, 30, 60]]


class BooleanSetting(Context):
    key: Literal[
        "always_on_top",
        "activity_labels",
        "shadow",
        "fade",
        "idle",
        "movement",
        "bubbles",
        "update_auto_check",
        "startup",
    ]
    value: bool


class NumberSetting(Context):
    key: Literal["opacity", "width", "look", "bubble_scale", "bubble_duration"]
    value: int


class DurationSetting(Context):
    key: Literal[
        "duration:result",
        "duration:general",
        "duration:schedule",
        "duration:completion",
    ]
    value: int | None


class StringSetting(Context):
    key: Literal["screen", "bubble_theme", "appearance:theme", "appearance:material"]
    value: str


class AppearanceNumber(Context):
    key: Literal["appearance:lightOpacity", "appearance:darkOpacity"]
    value: int


class AppearanceBoolean(Context):
    key: Literal["appearance:reduceMotion"]
    value: bool


class AppearanceSetting(Context):
    key: Literal["appearance"]
    value: Appearance


SettingRequest = (
    BooleanSetting
    | NumberSetting
    | DurationSetting
    | StringSetting
    | AppearanceNumber
    | AppearanceBoolean
    | AppearanceSetting
)


class NavigationAck(TypedDict):
    navigationId: str


class Confirmed(TypedDict):
    confirmed: bool


class Route(TypedDict):
    page: Page
    section: NotRequired[str]
    navigationId: NotRequired[str]
    notice: NotRequired[NoticeRecord]
    filter: NotRequired[str]


class Ready(TypedDict):
    connected: bool
    edition: NotRequired[Literal["pet-only", "pet-assistant"]]
    route: NotRequired[Route | None]
    appearance: EffectiveAppearance


class Topics(TypedDict, total=False):
    topics: list[Literal["settings", "usage", "activity"]]


class Subscribed(TypedDict):
    subscribed: bool


class Visibility(TypedDict):
    visible: bool


class WindowState(TypedDict, total=False):
    x: int
    y: int
    width: int
    height: int
    maximized: bool


class SaveWindow(TypedDict):
    state: WindowState


class FilePath(TypedDict):
    path: str


class ImportElement(FilePath):
    kind: ElementKind


class Invalidation(TypedDict):
    topics: list[str]
    epoch: int


class NavigateEvent(TypedDict):
    event: Literal["navigate"]
    data: Route


class InvalidateEvent(TypedDict):
    event: Literal["invalidate"]
    data: Invalidation


class VisibilityEvent(TypedDict):
    event: Literal["visibility"]
    data: bool


class AppearanceEvent(TypedDict):
    event: Literal["appearance"]
    data: EffectiveAppearance


SettingsEvent = NavigateEvent | InvalidateEvent | VisibilityEvent | AppearanceEvent


@dataclass(frozen=True)
class Command:
    """Wire type names and least-privilege exposure; not an execution registry."""

    request: str
    response: str
    caller: Literal["renderer", "main"] = "renderer"
    edition: Literal["both", "pet-assistant"] = "both"


COMMANDS = {
    "settings.snapshot": Command("Empty", "SettingsSnapshot"),
    "settings.set": Command("SettingRequest", "Mutation"),
    "pet.catalog": Command("Empty", "PetCatalog"),
    "pet.preview": Command("PetId", "PetPreview"),
    "pet.select": Command("SelectPet", "Mutation"),
    "pet.import.commit": Command("RegisterPet", "PetRegistration"),
    "pet.import.cancel": Command("Token", "Cancelled"),
    "pet.catalog.save": Command("CatalogSave", "Mutation"),
    "pet.trash.list": Command("Offset", "PetTrashCatalog"),
    "pet.trash.move": Command("TrashMove", "TrashMutation"),
    "pet.trash.restore": Command("TrashId", "RestoredPet"),
    "pet.trash.delete": Command("TrashId", "TrashMutation"),
    "pet.trash.empty": Command("Context", "TrashMutation"),
    "pet.trash.batch.start": Command("BatchStart", "BatchResponse"),
    "pet.trash.batch.status": Command("BatchQuery", "BatchResponse"),
    "pet.trash.batch.cancel": Command("BatchQuery", "BatchResponse"),
    "pet.action": Command("PetAction", "Mutation"),
    "bubble.editor": Command("Empty", "BubbleEditor"),
    "bubble.render": Command("RenderTheme", "BubbleRender"),
    "bubble.save": Command("ThemeRequest", "Mutation"),
    "bubble.reset": Command("Context", "Mutation"),
    "element.delete": Command("ElementDelete", "Mutation"),
    "update.check": Command("Empty", "Pending"),
    "update.download": Command("Empty", "Pending"),
    "update.cancel": Command("Empty", "Pending"),
    "update.open": Command("Empty", "Opened"),
    "app.quit": Command("Empty", "Accepted"),
    "navigation.ack": Command("NavigationAck", "Confirmed"),
    "window.subscribe": Command("Topics", "Subscribed"),
    "window.visibility": Command("Visibility", "Visibility", "main"),
    "window.state": Command("SaveWindow", "Saved", "main"),
    "window.restore": Command("Empty", "WindowState", "main"),
    "file.import": Command("ImportElement", "ElementImported", "main"),
    "file.pet.prepare": Command("FilePath", "PetPreparation", "main"),
    "file.pet.cancel": Command("Empty", "Cancelled", "main"),
    "file.export": Command("FilePath", "Saved", "main", "pet-assistant"),
}


class UsageWindow(TypedDict):
    used_percent: float | None
    remaining_percent: float | None
    window_duration_mins: int | None
    resets_at: str | None
    estimated: bool


class RateLimitBucket(TypedDict):
    limit_id: str
    limit_name: str | None
    plan_type: str | None
    primary: UsageWindow | None
    secondary: UsageWindow | None
    credit_balance: float | None
    has_credits: bool | None
    unlimited_credits: bool | None
    spend_control_reached: bool | None
    reached_type: str | None
    individual_limit: str | None
    individual_used: str | None
    individual_remaining_percent: float | None
    individual_resets_at: str | None


class UsageLimitOption(TypedDict):
    key: str
    label: str
    limit_id: str
    slot: str
    window: UsageWindow
    name: str


class AccountUsageSummary(TypedDict):
    lifetime_tokens: int | None
    peak_daily_tokens: int | None
    longest_running_turn_sec: int | None
    current_streak_days: int | None
    longest_streak_days: int | None


class DailyUsageBucket(TypedDict):
    start_date: str
    tokens: int | None


class TaskUsageRecord(TypedDict):
    completed_at: str
    account_hash: str
    thread_hash: str
    outcome: str
    input_tokens: int | None
    net_new_input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_credits_micros: int | None
    estimated_usd_micros: int | None
    model: str | None
    reasoning_effort: str | None
    speed: str | None
    data_quality: str
    turn_hash: str
    source_version: int
    quality_reason: str


class UsageAvailability(TypedDict):
    state: str
    message: str


class UsageRefreshState(TypedDict):
    request_id: int
    state: str
    phase: str
    message: str
    completed_at: str | None


class UsageSnapshot(TypedDict):
    project_mode: bool
    projects: list[ProjectUsageSummary]
    project_search: str
    project_order: str
    project_custom_order: list[str]
    project_offset: int
    projects_has_more: bool
    project_count: int
    selected_project_key: str
    conversation_mode: bool
    conversations: list[ConversationUsage]
    conversation_search: str
    conversation_order: str
    conversation_offset: int
    conversations_has_more: bool
    selected_conversation: ConversationUsage | None
    selected_thread_hash: str
    conversation_status: str
    device_legacy_records: list[TaskUsageRecord]
    device_history_message: str
    availability: UsageAvailability
    account_hash: str
    buckets: list[RateLimitBucket]
    summary: AccountUsageSummary
    daily_buckets: list[DailyUsageBucket]
    recent_tasks: list[TaskUsageRecord]
    latest_tasks: list[TaskUsageRecord]
    recovery_pending: list[tuple[str, str]]
    legacy_tasks: list[TaskUsageRecord]
    task_history_managed: bool
    task_history_search: str
    task_history_order: str
    task_history_limit: int
    task_history_has_more: bool
    hourly_activity: list[HourlyActivityBucket]
    observed_today_tokens: int | None
    unclassified_today_tokens: int | None
    last_sample_at: str | None
    quota_hourly_activity: list[HourlyQuotaBucket]
    trend_hours: dict[str, JsonValue] | None
    trend_quota: dict[str, JsonValue] | None
    observed_today_percent_points: float | None
    selected_quota_observation_count: int
    quota_last_sample_at: str | None
    selected_quota_key: str
    reset_credit_count: int | None
    last_updated_at: str | None
    storage_error: str
    clearing_history: bool
    history_message: str
    refresh: UsageRefreshState
    account_checking: bool
    account_email: str
    account_plan: str


class HourlyActivityBucket(TypedDict):
    hour_start: str
    tokens: int | None
    observed_intervals: int


class HourlyQuotaBucket(TypedDict):
    hour_start: str
    percent_points: float | None
    observed_intervals: int


class ClaudeCodeUsageSnapshot(TypedDict):
    availability: UsageAvailability
    projects: list[ProjectUsageSummary]
    project_search: str
    project_order: str
    project_offset: int
    projects_has_more: bool
    project_count: int
    selected_project_key: str
    conversations: list[ConversationUsage]
    conversation_search: str
    conversation_order: str
    conversation_offset: int
    conversations_has_more: bool
    selected_thread_hash: str
    recent_tasks: list[TaskUsageRecord]
    latest_tasks: list[TaskUsageRecord]
    task_history_search: str
    task_history_order: str
    task_history_limit: int
    task_history_has_more: bool
    import_remaining: int
    history_message: str
    buckets: list[RateLimitBucket]
    limits_observed_at: str | None
    today_hourly_tokens: list[int | None]
    trend_hours: dict[str, JsonValue] | None
    trend_quota: dict[str, JsonValue] | None
    daily_tokens: list[tuple[str, int]]
    account_hash: str


class PetSnapshot(TypedDict):
    pet_id: str
    display_name: str
    visual_state: str
    active_count: int
    visible: bool
    always_on_top: bool
    bubbles_enabled: bool
    activity_labels_enabled: bool
    idle_activities_enabled: bool
    auto_movement_enabled: bool
    pet_width: int
    look_range: int
    bubble_scale: int
    bubble_duration_seconds: int
    bubble_theme_mode: str
    bubbles_snoozed: bool
    bubble_snooze_remaining_minutes: int
    bubble_duration_policy: BubbleDurationPolicy
    working_sources: list[str]
    opacity_percent: int
    shadow: bool
    fade: bool


class HistoryEntry(TypedDict):
    occurred_at: str
    kind: str
    result: str
    summary: str
    action_token: str
    source: str


class NoticeRecord(TypedDict):
    recorded_at: str
    source: str
    message: str
    urgency: str
    record_id: str
    category: str
    replacement_key: str
    action_token: str
    delivery: str
    confirmed: bool


class ThemeBase(TypedDict):
    background: str
    border: str
    text: str
    shadow: str
    shadow_alpha: int
    radius: int
    border_width: float
    shape: str
    tail: str
    gradient: str
    fill_end: str
    border_style: str
    header_style: str
    pattern: str
    ornament_left: str
    ornament_right: str
    ornament_scale: int
    glow: bool
    frame_style: str
    fill_opacity: int
    minimum_width: int
    maximum_width: int
    horizontal_padding: int
    stack_alignment: str
    text_alignment: str
    text_bold: bool


class SpeechBubbleTheme(ThemeBase):
    background_image: str
    background_opacity: int
    background_focus_x: int
    background_focus_y: int
    background_zoom: int
    frame_image: str
    frame_slice: int
    sticker_1: str
    sticker_1_x: int
    sticker_1_y: int
    sticker_1_size: int
    sticker_2: str
    sticker_2_x: int
    sticker_2_y: int
    sticker_2_size: int
    sticker_3: str
    sticker_3_x: int
    sticker_3_y: int
    sticker_3_size: int


class BubbleDurationPolicy(TypedDict):
    common: int
    result: int | None
    general: int | None
    schedule: int | None
    completion: int | None


class ConversationUsage(TypedDict):
    thread_hash: str
    title: str
    project_key: str
    project_name: str
    completed_at: str
    task_count: int
    measured_count: int
    unavailable_count: int
    legacy_count: int
    total_tokens: int | None


class ProjectUsageSummary(TypedDict):
    project_key: str
    name: str
    conversation_count: int
    matched_count: int
    completed_at: str


class DailyPoint(TypedDict):
    date: str
    tokens: int | None
    average: float | None


class DailyTrend(TypedDict):
    days: list[DailyPoint]
    total: int | None
    average: float | None
    peak_date: str | None


class HourTrend(TypedDict):
    hours: list[int | None]
    total: int | None
    peak_hour: int | None
    average_days: int
    date: str
    average: list[float | None] | None
    versus_average: float | None


class QuotaTrend(TypedDict):
    points: list[tuple[str, float]]
    resets: list[str]
    now_remaining: float | None
    spent: float | None
    observed: int


class ProviderTrend(TypedDict):
    enabled: bool
    hours: HourTrend | None
    quota: dict[str, QuotaTrend]
    daily: DailyTrend


class Trends(TypedDict):
    now_hour: int
    codex: ProviderTrend
    claude_code: ProviderTrend


class LimitGroup(TypedDict):
    key: str
    label: str
    limits: list[UsageLimitOption]


class ClaudeUsage(TypedDict):
    data: ClaudeCodeUsageSnapshot
    status_line: str | None


class UsageResponse(TypedDict):
    epoch: int
    enabled: bool
    claude_code_enabled: bool
    any_enabled: bool
    data: UsageSnapshot
    limits: list[UsageLimitOption]
    limit_groups: list[LimitGroup]
    controls: list[Control]
    hours: list[int]
    trends: Trends
    claude_code: ClaudeUsage | None


class ActivityRow(TypedDict):
    title: str
    state: str
    label: str
    action_token: str


class ActivityProject(TypedDict):
    key: str
    label: str
    source: str
    summary: str
    rows: list[ActivityRow]


class ActivityResponse(TypedDict):
    epoch: int
    entries: list[HistoryEntry]
    projects: list[ActivityProject]
    notices: list[NoticeRecord]


class InstallStatus(TypedDict):
    state: str
    message: str
    installed_events: int
    expected_events: int
    detected: NotRequired[bool]


class StatusLineLayout(TypedDict):
    color: bool
    reset_times: bool
    lines: list[list[str]]


class StatusLine(TypedDict):
    state: str
    message: str
    has_original: bool
    observed_at: str | None
    layout: StatusLineLayout


class ClaudeIntegration(TypedDict):
    active: bool
    install: InstallStatus
    work_minutes: int
    waiting_minutes: int
    status_line: StatusLine | None


class TrustDiagnostic(TypedDict, total=False):
    valid: bool
    approved_count: int
    expected_count: int
    possibly_stale: bool


class MonitorDiagnostic(TypedDict, total=False):
    active: bool
    attached: bool
    tracked_files: int
    active_turns: int
    detected_count: int


class EnvironmentDiagnostic(TypedDict, total=False):
    detected: bool


class ProviderDiagnostic(TypedDict, total=False):
    last_hook_received_at: str | None
    transcript_monitor: MonitorDiagnostic
    turn_end_monitor: MonitorDiagnostic


class Diagnostics(TypedDict, total=False):
    last_error: str
    claude_code: ProviderDiagnostic
    claude_code_transcript: MonitorDiagnostic
    global_hook_trust: TrustDiagnostic
    jsonl_monitor: MonitorDiagnostic
    codex_environment: EnvironmentDiagnostic
    last_received_at: str | None
    last_transport: str
    schedule_event_count: int
    providers: dict[str, ProviderDiagnostic]


class StorageStatus(TypedDict):
    available: bool
    message: str
    recovered_path: str | None
    code: str


class ConnectionAlert(TypedDict):
    tool: Provider
    kind: Literal["broken", "found"]


class IntegrationResponse(TypedDict):
    diagnostics: Diagnostics
    codex_active: bool
    codex_detected: bool
    status: str
    install: InstallStatus
    storage: StorageStatus
    claude_code: ClaudeIntegration | None
    # Tools the connection watch asks to (re)connect.
    connection_alerts: list[ConnectionAlert]


class WidgetPreview(Size):
    image: str
    sample: bool


class WidgetPreviewRequest(TypedDict, total=False):
    sample: bool
    expanded: bool


class UsageBoolean(Context):
    key: Literal["quiet_summary", "widget_visible", "widget_tasks", "widget_today"]
    value: bool


class UsageNumber(Context):
    key: Literal["widget_opacity", "widget_scale", "chart_days"]
    value: int


class UsageString(Context):
    key: Literal[
        "widget_shape",
        "widget_emphasis",
        "widget_material",
        "widget_theme",
        "widget_color",
    ]
    value: str


class UsageHours(Context):
    key: Literal["widget_hours"]
    value: list[int]


UsageSetting = UsageBoolean | UsageNumber | UsageString | UsageHours


class QueryOptions(Context, total=False):
    provider: Provider
    search: str
    offset: int


class ProjectQuery(QueryOptions):
    kind: Literal["projects"]
    order: NotRequired[Literal["recent", "name", "custom"]]


class ConversationQuery(QueryOptions):
    kind: Literal["conversations"]
    order: NotRequired[Literal["recent", "top"]]


class TaskQuery(QueryOptions):
    kind: Literal["tasks"]
    order: NotRequired[Literal["recent", "top", "time_asc", "input", "output"]]
    limit: NotRequired[int]


UsageQuery = ProjectQuery | ConversationQuery | TaskQuery


class UsageSelect(Context):
    kind: Literal["project", "conversation"]
    key: str
    provider: NotRequired[Provider]


class UsageMove(Context):
    key: str
    direction: Literal[-1, 1]


class UsageAction(Context):
    action: Literal[
        "refresh",
        "clear",
        "clear_device",
        "reset_widget",
        "reset_style",
        "reset_scale",
        "reset_hours",
        "reset_position",
    ]
    provider: NotRequired[Provider]


class ToolPreview(Context):
    operation: Literal["enable", "disable"]
    provider: Provider


class HookPreview(Context):
    operation: Literal["install", "repair", "remove"]
    provider: NotRequired[Literal["codex", "claude_code", "claude_code_status_line"]]


IntegrationPreview = ToolPreview | HookPreview


class Plan(TypedDict):
    token: str
    canApply: bool
    changes: list[str]
    warnings: list[str]


class TimeoutSetting(Context):
    key: Literal["claude_code_work_minutes", "claude_code_waiting_minutes"]
    value: int


class LayoutSetting(Context):
    key: Literal["status_line_layout"]
    value: StatusLineLayout


IntegrationSetting = TimeoutSetting | LayoutSetting

COMMANDS.update(
    {
        "usage.snapshot": Command("Empty", "UsageResponse", edition="pet-assistant"),
        "usage.widget_preview": Command(
            "WidgetPreviewRequest", "WidgetPreview", edition="pet-assistant"
        ),
        "usage.set": Command(
            "UsageSetting", "AssistantMutation", edition="pet-assistant"
        ),
        "usage.query": Command(
            "UsageQuery", "AssistantMutation", edition="pet-assistant"
        ),
        "usage.select": Command(
            "UsageSelect", "AssistantMutation", edition="pet-assistant"
        ),
        "usage.move": Command(
            "UsageMove", "AssistantMutation", edition="pet-assistant"
        ),
        "usage.action": Command(
            "UsageAction", "AssistantMutation", edition="pet-assistant"
        ),
        "activity.snapshot": Command(
            "Empty", "ActivityResponse", edition="pet-assistant"
        ),
        "activity.clear": Command(
            "Context", "AssistantMutation", edition="pet-assistant"
        ),
        "activity.open": Command("Token", "Opened", edition="pet-assistant"),
        "integration.snapshot": Command(
            "Empty", "IntegrationResponse", edition="pet-assistant"
        ),
        "integration.preview": Command(
            "IntegrationPreview", "Plan", edition="pet-assistant"
        ),
        "integration.apply": Command(
            "Token", "AssistantMutation", edition="pet-assistant"
        ),
        "integration.set": Command(
            "IntegrationSetting", "AssistantMutation", edition="pet-assistant"
        ),
    }
)
