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
      <Heading
        title="사용량"
        subtitle="남은 한도와 이 기기에서 관측한 작업을 확인합니다."
      >
        <div className="heading-actions">
          <button
            className="button compact"
            disabled={!usage?.any_enabled}
            onClick={() => call("usage.action", { action: "refresh" })}
          >
            <RotateCcw size={14} />
            새로고침
          </button>
        </div>
      </Heading>
      <TabList
        id="usage"
        label="사용량 영역"
        tabs={[
          ["overview", "현황"],
          ["history", "기록"],
          ["settings", "설정"],
        ]}
        value={tab}
        select={selectTab}
      />
      {!u ? (
        <Empty>사용량을 불러오는 중입니다.</Empty>
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
                    ? `마지막 관측 ${time(usage!.claude_code.data.limits_observed_at)}`
                    : "아직 관측 전"}
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
              {u.refresh.message || "최신 사용량 확인 중…"}
            </p>
          )}
          {!usage!.any_enabled && tab !== "settings" && (
            <p className="paused-note">
              사용 중인 도구가 없어 한도를 확인하지 않습니다.{" "}
              <button
                className="text-button inline"
                onClick={() => shell.navigate("integration")}
              >
                연결·진단
              </button>
              에서 Codex나 Claude Code를 켤 수 있습니다.
            </p>
          )}
          {tab === "overview" && (
            <div>
              <div className="section-heading">
                <h2>남은 한도</h2>
                <span>
                  {u.last_updated_at ? `${time(u.last_updated_at)} 확인` : ""}
                </span>
              </div>
              <QuotaGroups usage={usage!} />
              {usage!.enabled && (
                <Section
                  title="오늘의 기기 활동"
                  note={
                    u.last_sample_at
                      ? `마지막 관측 ${time(u.last_sample_at)}`
                      : "아직 관측 전"
                  }
                >
                  {[
                    u.observed_today_tokens,
                    u.unclassified_today_tokens,
                    u.observed_today_percent_points,
                  ].every((value) => typeof value !== "number") ? (
                    <p className="paused-note">
                      오늘 이 기기에서 관측한 Codex 작업이 아직 없습니다. 작업을
                      하면 토큰과 한도 감소가 여기에 표시됩니다.
                    </p>
                  ) : (
                    <div className="activity-summary">
                      {(
                        [
                          ["관측한 토큰", u.observed_today_tokens, ""],
                          ["미분류 토큰", u.unclassified_today_tokens, ""],
                          [
                            "관측한 한도 감소",
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
                  <summary>한도 상세와 계정 통계</summary>
                  {u.buckets.map((bucket) => (
                    <div className="detail-group" key={bucket.limit_id}>
                      <h3>{bucket.limit_name || bucket.limit_id}</h3>
                      <Details value={bucket} />
                    </div>
                  ))}
                  <div className="detail-group">
                    <h3>계정 통계</h3>
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
                      label="기록 출처"
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
                          ? ` · 남은 파일 ${"import_remaining" in h ? h.import_remaining : 0}개`
                          : ""}
                      </span>
                      <button
                        className="text-button danger"
                        onClick={() =>
                          setConfirming({
                            title: "Claude Code 작업 기록 지우기",
                            body: "이 기기에 저장한 Claude Code 작업 기록을 지웁니다. Claude Code의 대화 기록 파일은 지우지 않으며, 이후 작업부터 다시 기록합니다.",
                            label: "지우기",
                            run: () =>
                              call("usage.action", {
                                action: "clear",
                                provider: "claude_code",
                              }),
                          })
                        }
                      >
                        기록 지우기
                      </button>
                    </>
                  )}
                </div>
              )}
              <div className="filter-row">
                <label className="search">
                  <Search size={15} />
                  <input
                    aria-label="사용량 기록 검색"
                    value={search}
                    placeholder="프로젝트·대화 검색"
                    onChange={(event) => setSearch(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") queryProjects();
                    }}
                  />
                </label>
                <button className="button" onClick={() => queryProjects()}>
                  검색
                </button>
              </div>
              <div className="history-columns">
                <section className="section">
                  <div className="section-heading">
                    <h2>프로젝트 · {h.project_count ?? 0}개</h2>
                    <select
                      aria-label="프로젝트 정렬"
                      value={projectOrder}
                      onChange={(event) => {
                        setProjectOrder(event.target.value);
                        queryProjects(0, event.target.value);
                      }}
                    >
                      <option value="recent">최근순</option>
                      <option value="name">이름순</option>
                      {source === "codex" && (
                        <option value="custom">직접 정렬</option>
                      )}
                    </select>
                  </div>
                  <div className="card">
                    {!h.projects?.length && (
                      <Empty>
                        {search
                          ? "검색 결과가 없습니다."
                          : "아직 기록된 프로젝트가 없습니다."}
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
                              <strong title={row.name}>{row.name}</strong>
                              <small>
                                {row.conversation_count ?? 0}개 대화 ·{" "}
                                {time(row.completed_at)}
                              </small>
                            </span>
                          </button>
                          {h.project_order === "custom" && !search && (
                            <>
                              <button
                                className="icon-button"
                                aria-label={`${row.name} 위로`}
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
                                aria-label={`${row.name} 아래로`}
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
                      label="프로젝트"
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
                        ? `${selectedProject.name}의 대화`
                        : "대화"}
                    </h2>
                    <select
                      aria-label="대화 정렬"
                      value={conversationOrder}
                      onChange={(event) => {
                        setConversationOrder(event.target.value);
                        queryConversations(0, event.target.value);
                      }}
                    >
                      <option value="recent">최근순</option>
                      <option value="top">측정 사용량 상위</option>
                    </select>
                  </div>
                  <div className="card">
                    {!h.conversations?.length && (
                      <Empty>
                        {h.projects?.length
                          ? "이 프로젝트에 표시할 대화가 없습니다."
                          : "프로젝트를 고르면 대화가 표시됩니다."}
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
                              <strong title={row.title}>{row.title}</strong>
                              <small>{time(row.completed_at)}</small>
                            </span>
                            <span className="record-tokens">
                              {number(row.total_tokens)} tokens
                            </span>
                            <ChevronRight size={15} />
                          </button>
                        </div>
                      );
                    })}
                    <Pager
                      label="대화"
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
                    이전 형식의 기록 · {h.legacy_tasks!.length}건
                  </summary>
                  {h.legacy_tasks!.map((row, index: number) => (
                    <div className="detail-group" key={index}>
                      <h3>
                        {time(row.completed_at)} · {number(row.total_tokens)}{" "}
                        tokens
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
                  (control: Control) => control.group === "사용량 알림",
                )}
                change={(key, value) =>
                  call("usage.set", { key, value } as UsageSetting)
                }
              />
              {usage!.enabled && (
                <Section title="데이터 관리">
                  <div className="setting-row">
                    <div className="field-label">
                      <label>Codex 기기 관측 기록</label>
                      <p className="field-description">
                        이 Windows 사용자의 Codex 로그에서 관측한 토큰·한도
                        변화입니다.
                      </p>
                    </div>
                    <button
                      className="button danger"
                      onClick={() =>
                        setConfirming({
                          title: "기기 관측 기록 지우기",
                          body: "이 기기의 관측 기록을 지웁니다. 되돌릴 수 없습니다.",
                          label: "지우기",
                          run: () =>
                            call("usage.action", {
                              action: "clear_device",
                            }),
                        })
                      }
                    >
                      지우기
                    </button>
                  </div>
                  <div className="setting-row">
                    <div className="field-label">
                      <label>Codex 현재 계정 작업 기록</label>
                      <p className="field-description">
                        현재 Codex 계정의 프로젝트·대화·작업 사용량입니다.
                        Claude Code 작업 기록은 기록 탭에서 지웁니다.
                      </p>
                    </div>
                    <button
                      className="button danger"
                      disabled={u.clearing_history || u.account_checking}
                      onClick={() =>
                        setConfirming({
                          title: "현재 계정 기록 지우기",
                          body: "현재 계정의 사용량 기록을 지웁니다. 되돌릴 수 없습니다.",
                          label: "지우기",
                          run: () => call("usage.action", { action: "clear" }),
                        })
                      }
                    >
                      지우기
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
