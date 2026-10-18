import { t } from "../../localization.cjs";
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
            t("message.0634")
          }
          close={() => setTasksOpen(false)}
          error={taskError || undefined}
        >
          <div className="filter-row">
            <label className="search">
              <Search size={15} />
              <input
                aria-label={t("message.0635")}
                placeholder={t("message.0636")}
                value={taskSearch}
                onChange={(event) => setTaskSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") queryTasks();
                }}
              />
            </label>
            <select
              aria-label={t("message.0637")}
              value={taskOrder}
              onChange={(event) => {
                setTaskOrder(event.target.value);
                queryTasks(PAGE_SIZE, event.target.value);
              }}
            >
              <option value="recent">{t("message.0638")}</option>
              <option value="top">{t("message.0639")}</option>
              <option value="time_asc">{t("message.0640")}</option>
              <option value="input">{t("message.0641")}</option>
              <option value="output">{t("message.0642")}</option>
            </select>
            <button className="button" onClick={() => queryTasks()}>
              {t("message.0643")}
            </button>
          </div>
          <div className="task-list">
            {!h.recent_tasks.length && (
              <Empty>
                {taskSearch ? t("message.0644") : t("message.0645")}
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
                      {t("message.1258", {
                        count: row.total_tokens,
                        value0: number(row.total_tokens),
                      })}
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
            label={t("message.0646")}
            offset={(h.task_history_limit || PAGE_SIZE) - PAGE_SIZE}
            hasMore={!!h.task_history_has_more}
            go={(offset) => queryTasks(offset + PAGE_SIZE)}
          />
        </Modal>
      )}
      {terminalHelp && <TerminalHelp close={() => setTerminalHelp(false)} />}
      {notice && (
        <Modal title={t("message.0647")} close={() => setNotice(null)}>
          <p className="notice-text">{notice.message}</p>
          {notice.category === "schedule" && (
            <p className="footnote">{t("message.0648")}</p>
          )}
        </Modal>
      )}
      {plan && (
        <Modal
          title={t("message.0649")}
          close={() => setPlan(null)}
          error={planError || undefined}
          footer={
            <>
              <button className="button" onClick={() => setPlan(null)}>
                {t("message.0650")}
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
                    notify(t("message.0651"));
                  } catch (e) {
                    setPlanError(errorText(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Check size={14} />
                {t("message.0652")}
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
            <p>{t("message.0653")}</p>
          )}
          {plan.warnings.map((warning: string) => (
            <p className="explanation" key={warning}>
              {warning}
            </p>
          ))}
          {!plan.canApply && (
            <p className="field-description">{t("message.0654")}</p>
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
