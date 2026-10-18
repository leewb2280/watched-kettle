import { t } from "../../localization.cjs";
import {
  ArrowDown,
  ArrowUp,
  ChevronRight,
  Info,
  RotateCcw,
  Search,
} from "lucide-react";
import { Empty, Fields, Heading, Section } from "../components";
import type { Control, Provider, UsageSetting } from "../types";
import {
  Details,
  number,
  Pager,
  Segmented,
  TabList,
  time,
} from "./presentation";
import { QuotaGroups } from "./QuotaGroups";
import { Trends } from "./Trends";
import type { AssistantSettingsState } from "./useAssistantSettings";
export function AssistantUsagePage({
  usage,
  call,
  tab,
  selectTab,
  u,
  shell,
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
}: Pick<
  AssistantSettingsState,
  | "usage"
  | "call"
  | "tab"
  | "selectTab"
  | "u"
  | "shell"
  | "chart"
  | "setChart"
  | "trendProvider"
  | "setTrendProvider"
  | "trendSpan"
  | "setTrendSpan"
  | "h"
  | "source"
  | "historySources"
  | "selectProvider"
  | "setConfirming"
  | "search"
  | "setSearch"
  | "queryProjects"
  | "projectOrder"
  | "setProjectOrder"
  | "read"
  | "selectedProject"
  | "conversationOrder"
  | "setConversationOrder"
  | "queryConversations"
  | "openConversation"
>) {
  return (
    <div className="page">
      <Heading title={t("message.0204")} subtitle={t("message.0680")}>
        <div className="heading-actions">
          <button
            className="button compact"
            disabled={!usage?.any_enabled}
            onClick={() => call("usage.action", { action: "refresh" })}
          >
            <RotateCcw size={14} />
            {t("message.0667")}
          </button>
        </div>
      </Heading>
      <TabList
        id="usage"
        label={t("message.0681")}
        tabs={[
          ["overview", t("message.0682")],
          ["history", t("message.0498")],
          ["settings", t("message.0225")],
        ]}
        value={tab}
        select={selectTab}
      />
      {!u ? (
        <Empty>{t("message.0683")}</Empty>
      ) : (
        <div
          role="tabpanel"
          id="usage-panel"
          aria-labelledby={`usage-tab-${tab}`}
        >
          <div className="availability">
            {usage!.enabled && (
              <span
                className="availability-item"
                data-state={u.availability.state}
              >
                <span className="small-dot" />
                <strong>Codex</strong>
                {[
                  u.account_email,
                  u.account_plan,
                  // A working account needs no sentence; anything else
                  // (checking, offline, no account) says what is wrong.
                  u.availability.state === "available" && u.account_hash
                    ? ""
                    : u.availability.message,
                ]
                  .filter(Boolean)
                  .map((part: string) => (
                    <span key={part}>{part}</span>
                  ))}
              </span>
            )}
            {usage!.claude_code_enabled && usage!.claude_code && (
              <span
                className="availability-item"
                data-state={
                  usage!.claude_code.data?.limits_observed_at
                    ? "available"
                    : "checking"
                }
              >
                <span className="small-dot" />
                <strong>Claude Code</strong>
                <span>
                  {usage!.claude_code.data?.limits_observed_at
                    ? t("message.0684", {
                        value0: time(
                          usage!.claude_code.data.limits_observed_at,
                        ),
                      })
                    : t("message.0685")}
                </span>
              </span>
            )}
          </div>
          {u.storage_error && (
            <div className="error-banner">
              <Info size={16} />
              <span>{u.storage_error}</span>
            </div>
          )}
          {u.refresh?.state === "refreshing" && (
            <p className="footnote" role="status">
              {u.refresh.message || t("message.0686")}
            </p>
          )}
          {!usage!.any_enabled && tab !== "settings" && (
            <p className="paused-note">
              {t("message.0687")}{" "}
              <button
                className="text-button inline"
                onClick={() => shell.navigate("integration")}
              >
                {t("message.0594")}
              </button>
              {t("message.0688")}
            </p>
          )}
          {tab === "overview" && (
            <div>
              <div className="section-heading">
                <h2>{t("message.0662")}</h2>
                <span>
                  {u.last_updated_at
                    ? t("message.0689", { value0: time(u.last_updated_at) })
                    : ""}
                </span>
              </div>
              <QuotaGroups usage={usage!} />
              {usage!.enabled && (
                <Section
                  title={t("message.0690")}
                  note={
                    u.last_sample_at
                      ? t("message.0684", { value0: time(u.last_sample_at) })
                      : t("message.0685")
                  }
                >
                  {[
                    u.observed_today_tokens,
                    u.unclassified_today_tokens,
                    u.observed_today_percent_points,
                  ].every((value) => typeof value !== "number") ? (
                    <p className="paused-note">{t("message.0691")}</p>
                  ) : (
                    <div className="activity-summary">
                      {(
                        [
                          [t("message.0692"), u.observed_today_tokens, ""],
                          [t("message.0693"), u.unclassified_today_tokens, ""],
                          [
                            t("message.0694"),
                            u.observed_today_percent_points,
                            "%p",
                          ],
                        ] as [string, number | null | undefined, string][]
                      ).map(([label, value, unit]) => (
                        <div key={label}>
                          <span>{label}</span>
                          <strong>
                            {number(value)}
                            {typeof value === "number" && unit && (
                              <small>{unit}</small>
                            )}
                          </strong>
                        </div>
                      ))}
                    </div>
                  )}
                </Section>
              )}
              <Trends
                usage={usage!}
                chart={chart}
                setChart={setChart}
                provider={trendProvider}
                setProvider={setTrendProvider}
                span={trendSpan}
                setSpan={setTrendSpan}
                setDays={(value) =>
                  call("usage.set", { key: "chart_days", value })
                }
              />
              {usage!.enabled && (
                <details className="explanation">
                  <summary>{t("message.0695")}</summary>
                  {u.buckets.map((bucket) => (
                    <div className="detail-group" key={bucket.limit_id}>
                      <h3>{bucket.limit_name || bucket.limit_id}</h3>
                      <Details value={bucket} />
                    </div>
                  ))}
                  <div className="detail-group">
                    <h3>{t("message.0696")}</h3>
                    <Details value={u.summary} />
                  </div>
                </details>
              )}
              {usage!.enabled && u.device_history_message && (
                <p className="footnote">{u.device_history_message}</p>
              )}
            </div>
          )}
          {tab === "history" && h && (
            <div
              className={
                (
                  source === "claude_code"
                    ? usage!.claude_code_enabled
                    : usage!.enabled
                )
                  ? ""
                  : "is-paused"
              }
            >
              {(historySources.length > 1 || source === "claude_code") && (
                <div className="chip-row provider-row">
                  {historySources.length > 1 && (
                    <Segmented
                      label={t("message.0697")}
                      options={[
                        ["codex", "Codex"],
                        ["claude_code", "Claude Code"],
                      ]}
                      value={source}
                      select={selectProvider}
                    />
                  )}
                  {source === "claude_code" && (
                    <>
                      <span className="footnote">
                        {h.availability?.message}
                        {("import_remaining" in h ? h.import_remaining : 0)
                          ? t("message.0698", {
                              value0:
                                "import_remaining" in h
                                  ? h.import_remaining
                                  : 0,
                            })
                          : ""}
                      </span>
                      <button
                        className="text-button danger"
                        onClick={() =>
                          setConfirming({
                            title: t("message.0699"),
                            body: t("message.0700"),
                            label: t("message.0628"),
                            run: () =>
                              call("usage.action", {
                                action: "clear",
                                provider: "claude_code",
                              }),
                          })
                        }
                      >
                        {t("message.0701")}
                      </button>
                    </>
                  )}
                </div>
              )}
              <div className="filter-row">
                <label className="search">
                  <Search size={15} />
                  <input
                    aria-label={t("message.0702")}
                    value={search}
                    placeholder={t("message.0703")}
                    onChange={(event) => setSearch(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") queryProjects();
                    }}
                  />
                </label>
                <button className="button" onClick={() => queryProjects()}>
                  {t("message.0643")}
                </button>
              </div>
              <div className="history-columns">
                <section className="section">
                  <div className="section-heading">
                    <h2>
                      {t("usage.projects", { count: h.project_count ?? 0 })}
                    </h2>
                    <select
                      aria-label={t("message.0706")}
                      value={projectOrder}
                      onChange={(event) => {
                        setProjectOrder(event.target.value);
                        queryProjects(0, event.target.value);
                      }}
                    >
                      <option value="recent">{t("message.0707")}</option>
                      <option value="name">{t("message.0708")}</option>
                      {source === "codex" && (
                        <option value="custom">{t("message.0709")}</option>
                      )}
                    </select>
                  </div>
                  <div className="card">
                    {!h.projects?.length && (
                      <Empty>
                        {search ? t("message.0644") : t("message.0710")}
                      </Empty>
                    )}
                    {(h.projects || []).map((row) => {
                      const selected =
                        row.project_key === h.selected_project_key;
                      return (
                        <div
                          className={`project-row ${selected ? "selected" : ""}`}
                          key={row.project_key}
                        >
                          <button
                            className="project-main"
                            aria-current={selected ? "true" : undefined}
                            onClick={() =>
                              read("usage.select", {
                                kind: "project",
                                key: row.project_key,
                                provider: source as Provider,
                              })
                            }
                          >
                            <span className="project-avatar">
                              {(row.name || "?")[0]}
                            </span>
                            <span className="project-name">
                              <strong title={row.name} data-user-text>
                                {row.name}
                              </strong>
                              <small>
                                {t("usage.conversations", {
                                  count: row.conversation_count ?? 0,
                                  time: time(row.completed_at),
                                })}
                              </small>
                            </span>
                          </button>
                          {h.project_order === "custom" && !search && (
                            <>
                              <button
                                className="icon-button"
                                aria-label={t("message.0712", {
                                  value0: row.name,
                                })}
                                onClick={() =>
                                  call("usage.move", {
                                    key: row.project_key,
                                    direction: -1,
                                  })
                                }
                              >
                                <ArrowUp size={14} />
                              </button>
                              <button
                                className="icon-button"
                                aria-label={t("message.0713", {
                                  value0: row.name,
                                })}
                                onClick={() =>
                                  call("usage.move", {
                                    key: row.project_key,
                                    direction: 1,
                                  })
                                }
                              >
                                <ArrowDown size={14} />
                              </button>
                            </>
                          )}
                        </div>
                      );
                    })}
                    <Pager
                      label={t("message.0619")}
                      offset={h.project_offset || 0}
                      hasMore={!!h.projects_has_more}
                      go={(offset) => queryProjects(offset)}
                    />
                  </div>
                </section>
                <section className="section">
                  <div className="section-heading">
                    <h2 title={selectedProject?.name}>
                      {selectedProject?.name
                        ? t("message.0714", { value0: selectedProject.name })
                        : t("message.0620")}
                    </h2>
                    <select
                      aria-label={t("message.0715")}
                      value={conversationOrder}
                      onChange={(event) => {
                        setConversationOrder(event.target.value);
                        queryConversations(0, event.target.value);
                      }}
                    >
                      <option value="recent">{t("message.0707")}</option>
                      <option value="top">{t("message.0639")}</option>
                    </select>
                  </div>
                  <div className="card">
                    {!h.conversations?.length && (
                      <Empty>
                        {h.projects?.length
                          ? t("message.0716")
                          : t("message.0717")}
                      </Empty>
                    )}
                    {(h.conversations || []).map((row) => {
                      const selected =
                        row.thread_hash === h.selected_thread_hash;
                      return (
                        <div
                          className={`project-row ${selected ? "selected" : ""}`}
                          key={row.thread_hash}
                        >
                          <button
                            className="project-main"
                            aria-current={selected ? "true" : undefined}
                            onClick={() => openConversation(row.thread_hash)}
                          >
                            <span className="project-name">
                              <strong title={row.title} data-user-text>
                                {row.title}
                              </strong>
                              <small>{time(row.completed_at)}</small>
                            </span>
                            <span className="record-tokens">
                              {t("message.1258", {
                                count: row.total_tokens,
                                value0: number(row.total_tokens),
                              })}
                            </span>
                            <ChevronRight size={15} />
                          </button>
                        </div>
                      );
                    })}
                    <Pager
                      label={t("message.0620")}
                      offset={h.conversation_offset || 0}
                      hasMore={!!h.conversations_has_more}
                      go={(offset) => queryConversations(offset)}
                    />
                  </div>
                  {h.conversation_status && (
                    <p className="footnote">{h.conversation_status}</p>
                  )}
                </section>
              </div>
              {!!h.legacy_tasks?.length && (
                <details className="explanation">
                  <summary>
                    {t("usage.legacy", { count: h.legacy_tasks!.length })}
                  </summary>
                  {h.legacy_tasks!.map((row, index: number) => (
                    <div className="detail-group" key={index}>
                      <h3>
                        {time(row.completed_at)} ·{" "}
                        {t("message.1258", {
                          count: row.total_tokens,
                          value0: number(row.total_tokens),
                        })}
                      </h3>
                      <Details value={row} />
                    </div>
                  ))}
                </details>
              )}
              {h.history_message && (
                <p className="footnote">{h.history_message}</p>
              )}
            </div>
          )}
          {tab === "settings" && (
            <>
              <Fields
                controls={usage!.controls.filter(
                  (control: Control) => control.groupId === "usage_notices",
                )}
                change={(key, value) =>
                  call("usage.set", { key, value } as UsageSetting)
                }
              />
              {usage!.enabled && (
                <Section title={t("message.0720")}>
                  <div className="setting-row">
                    <div className="field-label">
                      <label>{t("message.0721")}</label>
                      <p className="field-description">{t("message.0722")}</p>
                    </div>
                    <button
                      className="button danger"
                      onClick={() =>
                        setConfirming({
                          title: t("message.0723"),
                          body: t("message.0724"),
                          label: t("message.0628"),
                          run: () =>
                            call("usage.action", {
                              action: "clear_device",
                            }),
                        })
                      }
                    >
                      {t("message.0628")}
                    </button>
                  </div>
                  <div className="setting-row">
                    <div className="field-label">
                      <label>{t("message.0725")}</label>
                      <p className="field-description">{t("message.0726")}</p>
                    </div>
                    <button
                      className="button danger"
                      disabled={u.clearing_history || u.account_checking}
                      onClick={() =>
                        setConfirming({
                          title: t("message.0727"),
                          body: t("message.0728"),
                          label: t("message.0628"),
                          run: () => call("usage.action", { action: "clear" }),
                        })
                      }
                    >
                      {t("message.0628")}
                    </button>
                  </div>
                </Section>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
