import { Check, ChevronDown, Search } from "lucide-react";
import { Confirm, Empty, Modal } from "../components";
import { errorText } from "../errors";
import { TerminalHelp } from "./Connections";
import {
  Details,
  PAGE_SIZE,
  Pager,
  number,
  outcomeLabels,
  qualityLabels,
  time,
} from "./presentation";
import type { AssistantSettingsState } from "./useAssistantSettings";
export function AssistantDialogs({
  integration,
  h,
  setConfirming,
  search,
  filter,
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
}: Pick<
  AssistantSettingsState,
  | "integration"
  | "h"
  | "setConfirming"
  | "search"
  | "filter"
  | "setTerminalHelp"
  | "busy"
  | "setBusy"
  | "notify"
  | "tasksOpen"
  | "setTasksOpen"
  | "taskError"
  | "taskSearch"
  | "setTaskSearch"
  | "queryTasks"
  | "taskOrder"
  | "setTaskOrder"
  | "expandedTask"
  | "setExpandedTask"
  | "terminalHelp"
  | "notice"
  | "setNotice"
  | "plan"
  | "setPlan"
  | "planError"
  | "command"
  | "setPlanError"
  | "confirming"
>) {
  return (
    <>
      {tasksOpen && h?.selected_thread_hash && (
        <Modal
          title={
            h.selected_conversation?.title ||
            h.conversations?.find(
              (row) => row.thread_hash === h.selected_thread_hash,
            )?.title ||
            "선택한 대화의 작업"
          }
          close={() => setTasksOpen(false)}
          error={taskError || undefined}
        >
          <div className="filter-row">
            <label className="search">
              <Search size={15} />
              <input
                aria-label="작업 기록 검색"
                placeholder="모델·결과·측정 품질 검색"
                value={taskSearch}
                onChange={(event) => setTaskSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") queryTasks();
                }}
              />
            </label>
            <select
              aria-label="작업 표시 순서"
              value={taskOrder}
              onChange={(event) => {
                setTaskOrder(event.target.value);
                queryTasks(PAGE_SIZE, event.target.value);
              }}
            >
              <option value="recent">최근 작업</option>
              <option value="top">측정 사용량 상위</option>
              <option value="time_asc">오래된 작업</option>
              <option value="input">입력 토큰 상위</option>
              <option value="output">출력 토큰 상위</option>
            </select>
            <button className="button" onClick={() => queryTasks()}>
              검색
            </button>
          </div>
          <div className="task-list">
            {!h.recent_tasks.length && (
              <Empty>
                {taskSearch
                  ? "검색 결과가 없습니다."
                  : "표시할 작업이 없습니다."}
              </Empty>
            )}
            {h.recent_tasks.map((row, index: number) => {
              const key = row.turn_hash || String(index);
              const open = expandedTask === key;
              return (
                <div key={key}>
                  <button
                    className="record-row"
                    aria-expanded={open}
                    onClick={() => setExpandedTask(open ? null : key)}
                  >
                    <span className="record-time">
                      {time(row.completed_at)}
                    </span>
                    <strong>{outcomeLabels[row.outcome] || row.outcome}</strong>
                    <span className="record-summary">
                      {[
                        qualityLabels[
                          "data_quality" in row ? row.data_quality : ""
                        ],
                        row.model,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    <span className="record-tokens">
                      {number(row.total_tokens)} tokens
                    </span>
                    <ChevronDown
                      size={14}
                      className={open ? "rotated" : undefined}
                    />
                  </button>
                  {open && (
                    <div className="task-details">
                      <Details value={row} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <Pager
            label="작업"
            offset={(h.task_history_limit || PAGE_SIZE) - PAGE_SIZE}
            hasMore={!!h.task_history_has_more}
            go={(offset) => queryTasks(offset + PAGE_SIZE)}
          />
        </Modal>
      )}
      {terminalHelp && <TerminalHelp close={() => setTerminalHelp(false)} />}
      {notice && (
        <Modal title="알림 내용" close={() => setNotice(null)}>
          <p className="notice-text">{notice.message}</p>
          {notice.category === "schedule" && (
            <p className="footnote">
              외부 일정 시스템은 아직 연결되지 않았습니다.
            </p>
          )}
        </Modal>
      )}
      {plan && (
        <Modal
          title="연결 변경 검토"
          close={() => setPlan(null)}
          error={planError || undefined}
          footer={
            <>
              <button className="button" onClick={() => setPlan(null)}>
                취소
              </button>
              <button
                className="button primary"
                disabled={!plan.canApply || busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await command(
                      "integration.apply",
                      { token: plan.token },
                      { inline: true },
                    );
                    setPlan(null);
                    notify("연결 설정을 적용했습니다.");
                  } catch (e) {
                    setPlanError(errorText(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Check size={14} />
                변경 적용
              </button>
            </>
          }
        >
          {plan.changes.length ? (
            <ul className="plan-changes">
              {plan.changes.map((change: string) => (
                <li key={change}>{change}</li>
              ))}
            </ul>
          ) : (
            <p>변경할 내용이 없습니다.</p>
          )}
          {plan.warnings.map((warning: string) => (
            <p className="explanation" key={warning}>
              {warning}
            </p>
          ))}
          {!plan.canApply && (
            <p className="field-description">
              지금은 적용할 수 없습니다. 위 안내를 확인해 주세요.
            </p>
          )}
        </Modal>
      )}
      {confirming && (
        <Confirm
          title={confirming.title}
          label={confirming.label}
          danger
          close={() => setConfirming(null)}
          confirm={() => {
            confirming.run();
            setConfirming(null);
          }}
        >
          <p>{confirming.body}</p>
        </Confirm>
      )}
    </>
  );
}
