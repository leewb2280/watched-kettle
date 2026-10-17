import { Check, ChevronRight, Ellipsis, Info } from "lucide-react";
import { Empty, Heading, Section } from "../components";
import {
  ACTIVITY_PAGE,
  clock,
  dayLabel,
  Segmented,
  SourceTag,
  time,
} from "./presentation";

import type { AssistantSettingsState } from "./useAssistantSettings";
export function AssistantActivityPage({
  activity,
  unconfirmed,
  call,
  setConfirming,
  allEntries,
  kinds,
  filter,
  setFilter,
  setShown,
  entries,
  shown,
}: Pick<
  AssistantSettingsState,
  | "activity"
  | "unconfirmed"
  | "call"
  | "setConfirming"
  | "allEntries"
  | "kinds"
  | "filter"
  | "setFilter"
  | "setShown"
  | "entries"
  | "shown"
>) {
  return (
    <div className="page">
      <Heading
        title="활동 기록"
        subtitle="확인할 알림과 진행 중인 작업, 최근 활동을 모아 봅니다."
      />
      {!activity ? (
        <Empty>활동을 불러오는 중입니다.</Empty>
      ) : (
        <>
          <Section
            title="확인하지 않은 알림"
            note={unconfirmed.length ? `${unconfirmed.length}건` : ""}
          >
            {unconfirmed.length ? (
              unconfirmed.slice(0, 5).map((row) => (
                <button
                  className="record-row"
                  key={row.record_id}
                  onClick={() =>
                    call("activity.open", { token: row.action_token })
                  }
                >
                  <span className="record-time">{time(row.recorded_at)}</span>
                  <span className="record-summary">{row.message}</span>
                  <ChevronRight size={14} />
                </button>
              ))
            ) : (
              <p className="quiet-row">
                <Check size={14} />
                확인할 알림이 없어요.
              </p>
            )}
          </Section>
          <Section title="진행 중">
            {activity.projects.length ? (
              activity.projects.map((project) => (
                <div className="project-activity" key={project.key}>
                  <div className="project-activity-heading">
                    <h3>{project.label || "프로젝트"}</h3>
                    {project.source && <SourceTag name={project.source} />}
                    {project.summary && <span>{project.summary}</span>}
                  </div>
                  {(project.rows || []).map((row, j: number) => (
                    <button
                      className="thread-row"
                      key={j}
                      onClick={() =>
                        call("activity.open", { token: row.action_token })
                      }
                    >
                      <span className="record-summary">
                        {row.title || "대화"}
                      </span>
                      <span className="pill">{row.label || row.state}</span>
                      <ChevronRight size={14} />
                    </button>
                  ))}
                </div>
              ))
            ) : (
              <p className="quiet-row">진행 중인 작업이 없어요.</p>
            )}
          </Section>
          <section className="section">
            <div className="section-heading">
              <div className="heading-title">
                <h2>최근 활동</h2>
                <span
                  className="info-tip"
                  role="note"
                  aria-label="저장 안내"
                  title="비서 알림·프로젝트 이벤트·작업 완료는 이번 실행에만 표시됩니다. Codex 작업 사용량 기록은 별도의 로컬 저장 정책을 따릅니다."
                >
                  <Info size={13} />
                </span>
              </div>
              <details className="more-menu">
                <summary aria-label="활동 기록 관리">
                  <Ellipsis size={16} />
                </summary>
                <div className="menu">
                  <button
                    className="danger"
                    onClick={(event) => {
                      event.currentTarget
                        .closest("details")
                        ?.removeAttribute("open");
                      setConfirming({
                        title: "비서 알림 기록 지우기",
                        body: "이번 실행의 비서 알림 기록을 지웁니다. 작업·프로젝트 기록은 유지됩니다.",
                        label: "지우기",
                        run: () => call("activity.clear"),
                      });
                    }}
                  >
                    비서 알림 기록 지우기
                  </button>
                </div>
              </details>
            </div>
            <div className="card">
              {!!allEntries.length && (
                <div className="chip-row">
                  <Segmented
                    label="활동 종류"
                    options={[
                      ["", `전체 ${allEntries.length}`],
                      ...kinds.map(
                        (kind) =>
                          [
                            kind,
                            `${kind} ${
                              allEntries.filter((entry) => entry.kind === kind)
                                .length
                            }`,
                          ] as [string, string],
                      ),
                    ]}
                    value={filter}
                    select={(kind) => {
                      setFilter(kind);
                      setShown(ACTIVITY_PAGE);
                    }}
                  />
                </div>
              )}
              {!allEntries.length ? (
                <Empty>아직 기록된 활동이 없습니다.</Empty>
              ) : !entries.length ? (
                <Empty>이 종류의 활동이 없습니다.</Empty>
              ) : (
                entries.slice(0, shown).map((entry, index, list) => {
                  const day = dayLabel(entry.occurred_at);
                  const content = (
                    <>
                      <span className="record-time">
                        {clock(entry.occurred_at)}
                      </span>
                      <span className="pill">{entry.kind}</span>
                      {entry.source && <SourceTag name={entry.source} />}
                      <span className="record-summary">{entry.summary}</span>
                      <span className="record-result">{entry.result}</span>
                      {entry.action_token ? (
                        <ChevronRight size={14} />
                      ) : (
                        <span className="chevron-space" />
                      )}
                    </>
                  );
                  return (
                    <div key={index}>
                      {(index === 0 ||
                        dayLabel(list[index - 1].occurred_at) !== day) && (
                        <div className="day-label">{day}</div>
                      )}
                      {entry.action_token ? (
                        <button
                          className="record-row"
                          onClick={() =>
                            call("activity.open", {
                              token: entry.action_token,
                            })
                          }
                        >
                          {content}
                        </button>
                      ) : (
                        <div className="record-row static">{content}</div>
                      )}
                    </div>
                  );
                })
              )}
              {entries.length > shown && (
                <div className="section-footer">
                  <button
                    className="text-button"
                    onClick={() => setShown((count) => count + ACTIVITY_PAGE)}
                  >
                    {Math.min(ACTIVITY_PAGE, entries.length - shown)}건 더 보기
                  </button>
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
