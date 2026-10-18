import { t } from "../../localization.cjs";
import { useState } from "react";
import type {
  ActivityProject,
  ActivityRow,
  Control,
  HistoryEntry,
  IntegrationPreview,
  NoticeRecord,
  Page,
  Plan,
  Shell,
} from "../types";
import { assistantCommands } from "./commands";
import { claudeHeroes, heroFor } from "./Connections";
import { ACTIVITY_PAGE, Confirmation } from "./presentation";
import { useAssistantSnapshots } from "./useAssistantSnapshots";
import { useNavigationAck } from "./useNavigationAck";
import { useUsageHistory } from "./useUsageHistory";
/** Keeps state alive across page changes; the shell remains mounted. */
export function useAssistantSettings(shell: Shell, page: Page) {
  const { command, notify, reportError } = shell;
  const { call, read } = assistantCommands(command);
  const {
    usage,
    setUsage,
    activity,
    setActivity,
    integration,
    setIntegration,
  } = useAssistantSnapshots(
    page,
    shell.visible,
    shell.eventVersion,
    reportError,
  );
  const {
    tab,
    setTab,
    search,
    setSearch,
    projectOrder,
    setProjectOrder,
    conversationOrder,
    setConversationOrder,
    taskSearch,
    setTaskSearch,
    taskOrder,
    setTaskOrder,
    tasksOpen,
    setTasksOpen,
    provider,
    setProvider,
    expandedTask,
    setExpandedTask,
    taskError,
    setTaskError,
    u,
    claudeHistory,
    historySources,
    source,
    h,
    queryProjects,
    queryConversations,
    queryTasks,
    selectTab,
    selectProvider,
    openConversation,
    selectedProject,
  } = useUsageHistory(usage, command, read);

  const [chart, setChart] = useState("tokens");

  const [trendProvider, setTrendProvider] = useState("");

  const [trendSpan, setTrendSpan] = useState("five_hour");

  const [notice, setNotice] = useState<NoticeRecord | null>(null);

  const [plan, setPlan] = useState<Plan | null>(null);

  const [planError, setPlanError] = useState("");

  const [filter, setFilter] = useState("");

  const [shown, setShown] = useState(ACTIVITY_PAGE);

  const [confirming, setConfirming] = useState<Confirmation | null>(null);

  const [terminalHelp, setTerminalHelp] = useState(false);

  const [busy, setBusy] = useState(false);
  useNavigationAck(
    shell,
    page,
    usage,
    activity,
    integration,
    notice,
    setNotice,
    tab,
    setTab,
    setFilter,
    reportError,
  );

  const preview = async (operation: string, provider = "codex") => {
    const result = await read("integration.preview", {
      operation,
      provider,
    } as IntegrationPreview);
    if (result && result !== true) {
      setPlanError("");
      setPlan(result);
    }
  };

  const widgetVisible = !!usage?.controls.find(
    (control: Control) => control.key === "widget_visible",
  )?.value;

  const allEntries: HistoryEntry[] = activity?.entries || [];

  const kinds = [...new Set<string>(allEntries.map((entry) => entry.kind))];

  if (filter && !kinds.includes(filter)) kinds.push(filter);

  const entries = allEntries.filter(
    (entry) => !filter || entry.kind === filter,
  );

  const unconfirmed: NoticeRecord[] = (activity?.notices || [])
    .filter((row) => !row.confirmed)
    .reverse();

  const hero = integration ? heroFor(integration) : null;

  // Home lists each running conversation with the project it belongs to.
  const homeRows: { project: ActivityProject; row: ActivityRow }[] = (
    activity?.projects || []
  ).flatMap((project) => (project.rows || []).map((row) => ({ project, row })));

  // Tools in use; a switched-off one lives on the connections page unless the
  // connection watch just found it.
  const codexActive = integration?.codex_active !== false;

  const claudeActive = !!integration?.claude_code?.active;

  // A switched-off tool found after install is offered once it appears.
  const found = new Set(
    (integration?.connection_alerts || [])
      .filter((alert) => alert.kind === "found")
      .map((alert) => alert.tool),
  );
  const offer = { tone: "warn", title: t("message.0958") };
  const connections: [string, { tone: string; title: string }][] = integration
    ? [
        ...(codexActive
          ? ([["Codex", heroFor(integration)]] as [
              string,
              { tone: string; title: string },
            ][])
          : found.has("codex")
            ? ([["Codex", offer]] as [
                string,
                { tone: string; title: string },
              ][])
            : []),
        ...(claudeActive
          ? ([
              [
                "Claude Code",
                claudeHeroes[integration.claude_code!.install?.state] ||
                  claudeHeroes.invalid,
              ],
            ] as [string, { tone: string; title: string }][])
          : found.has("claude_code")
            ? ([["Claude Code", offer]] as [
                string,
                { tone: string; title: string },
              ][])
            : []),
      ]
    : [];
  return {
    usage,
    activity,
    integration,
    unconfirmed,
    call,
    shell,
    homeRows,
    connections,
    tab,
    selectTab,
    u,
    chart,
    setChart,
    trendProvider,
    setTrendProvider,
    trendSpan,
    setTrendSpan,
    h,
    source,
    historySources,
    selectProvider,
    setConfirming,
    search,
    setSearch,
    queryProjects,
    projectOrder,
    setProjectOrder,
    read,
    selectedProject,
    conversationOrder,
    setConversationOrder,
    queryConversations,
    openConversation,
    widgetVisible,
    allEntries,
    kinds,
    filter,
    setFilter,
    setShown,
    entries,
    shown,
    setIntegration,
    reportError,
    hero,
    codexActive,
    preview,
    claudeActive,
    setTerminalHelp,
    busy,
    setBusy,
    notify,
    tasksOpen,
    setTasksOpen,
    taskError,
    taskSearch,
    setTaskSearch,
    queryTasks,
    taskOrder,
    setTaskOrder,
    expandedTask,
    setExpandedTask,
    terminalHelp,
    notice,
    setNotice,
    plan,
    setPlan,
    planError,
    command,
    setPlanError,
    confirming,
  };
}
export type AssistantSettingsState = ReturnType<typeof useAssistantSettings>;
