import { t } from "../../localization.cjs";
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
      <Heading title={t("message.0593")} subtitle={t("message.0614")} />
      {!activity ? (
        <Empty>{t("message.0615")}</Empty>
      ) : (
        <>
          <Section
            title={t("message.0616")}
            note={
              unconfirmed.length
                ? t("message.0617", { value0: unconfirmed.length })
                : ""
            }
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
                {t("message.0618")}
              </p>
            )}
          </Section>
          <Section title={t("message.0445")}>
            {activity.projects.length ? (
              activity.projects.map((project) => (
                <div className="project-activity" key={project.key}>
                  <div className="project-activity-heading">
                    <h3>
                      {project.label ? (
                        <span data-user-text>{project.label}</span>
                      ) : (
                        t("message.0619")
                      )}
                    </h3>
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
                        {row.title ? (
                          <span data-user-text>{row.title}</span>
                        ) : (
                          t("message.0620")
                        )}
                      </span>
                      <span className="pill">{row.label || row.state}</span>
                      <ChevronRight size={14} />
                    </button>
                  ))}
                </div>
              ))
            ) : (
              <p className="quiet-row">{t("message.0621")}</p>
            )}
          </Section>
          <section className="section">
            <div className="section-heading">
              <div className="heading-title">
                <h2>{t("message.0622")}</h2>
                <span
                  className="info-tip"
                  role="note"
                  aria-label={t("message.0623")}
                  title={t("message.0624")}
                >
                  <Info size={13} />
                </span>
              </div>
              <details className="more-menu">
                <summary aria-label={t("message.0625")}>
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
                        title: t("message.0626"),
                        body: t("message.0627"),
                        label: t("message.0628"),
                        run: () => call("activity.clear"),
                      });
                    }}
                  >
                    {t("message.0626")}
                  </button>
                </div>
              </details>
            </div>
            <div className="card">
              {!!allEntries.length && (
                <div className="chip-row">
                  <Segmented
                    label={t("message.0629")}
                    options={[
                      ["", t("message.0630", { value0: allEntries.length })],
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
                <Empty>{t("message.0631")}</Empty>
              ) : !entries.length ? (
                <Empty>{t("message.0632")}</Empty>
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
                    {t("activity.more", {
                      count: Math.min(ACTIVITY_PAGE, entries.length - shown),
                    })}
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
