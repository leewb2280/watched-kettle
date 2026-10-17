import { useEffect, useState } from "react";
import { errorText } from "../errors";
import type {
  ClaudeCodeUsageSnapshot,
  ConversationQuery,
  ConversationUsage,
  ProjectQuery,
  Provider,
  Shell,
  TaskQuery,
  TaskUsageRecord,
  UsageResponse,
  UsageSnapshot,
} from "../types";
import type { AssistantRead } from "./commands";
import { PAGE_SIZE } from "./presentation";
export function useUsageHistory(
  usage: UsageResponse | null,
  command: Shell["command"],
  read: AssistantRead,
) {
  const [tab, setTab] = useState("overview");

  const [search, setSearch] = useState("");

  const [projectOrder, setProjectOrder] = useState("recent");

  const [conversationOrder, setConversationOrder] = useState("recent");

  const [taskSearch, setTaskSearch] = useState("");

  const [taskOrder, setTaskOrder] = useState("recent");

  const [tasksOpen, setTasksOpen] = useState(false);

  const [provider, setProvider] = useState("codex");

  const [expandedTask, setExpandedTask] = useState<string | null>(null);

  const [taskError, setTaskError] = useState("");

  const u = usage?.data;

  // Claude Code history reuses the history tab with its own source data.
  const claudeHistory = usage?.claude_code?.data;

  // A tool whose usage switch is off is not offered as a history source.
  const historySources: string[] = [
    ...(usage?.enabled ? ["codex"] : []),
    ...(usage?.claude_code_enabled && claudeHistory ? ["claude_code"] : []),
  ];

  const source = historySources.includes(provider)
    ? provider
    : historySources[0] || "codex";

  type HistoryData = (UsageSnapshot | ClaudeCodeUsageSnapshot) & {
    import_remaining?: number;
    conversation_status?: string;
    legacy_tasks?: TaskUsageRecord[];
    selected_conversation?: ConversationUsage | null;
  };

  const h: HistoryData | undefined =
    source === "claude_code" ? claudeHistory : u;

  useEffect(() => {
    if (!h) return;
    setSearch(h.project_search ?? "");
    setProjectOrder(h.project_order || "recent");
    setConversationOrder(h.conversation_order || "recent");
  }, [source, h?.project_search, h?.project_order, h?.conversation_order]);

  const queryProjects = (
    offset = 0,
    order = projectOrder,
    from: string = source,
  ) =>
    read("usage.query", {
      kind: "projects",
      search,
      order: order as ProjectQuery["order"],
      offset,
      provider: from as Provider,
    });

  const queryConversations = (offset = 0, order = conversationOrder) =>
    read("usage.query", {
      kind: "conversations",
      search,
      order: order as ConversationQuery["order"],
      offset,
      provider: source as Provider,
    });

  // Runs inside the task dialog, whose backdrop would hide the page banner.
  const queryTasks = (limit = PAGE_SIZE, order = taskOrder) =>
    command(
      "usage.query",
      {
        kind: "tasks",
        search: taskSearch,
        order: order as TaskQuery["order"],
        limit,
        provider: source as Provider,
      },
      { inline: true, quiet: true },
    ).then(
      () => setTaskError(""),
      (e) => setTaskError(errorText(e)),
    );

  const selectTab = (next: string) => {
    if (next === "history" && tab !== "history")
      queryProjects(h?.project_offset || 0);
    setTab(next);
  };

  const selectProvider = (next: string) => {
    setProvider(next);
    setTasksOpen(false);
    queryProjects(0, "recent", next);
  };

  const openConversation = async (key: string) => {
    if (
      !(await read("usage.select", {
        kind: "conversation",
        key,
        provider: source as Provider,
      }))
    )
      return;
    setTaskSearch("");
    setTaskOrder("recent");
    setExpandedTask(null);
    setTaskError("");
    setTasksOpen(true);
  };

  const selectedProject = h?.projects?.find(
    (row) => row.project_key === h.selected_project_key,
  );
  return {
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
  };
}
