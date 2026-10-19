import { t } from "../../localization.cjs";
import { useState } from "react";
import { Check, ChevronRight, Ellipsis } from "lucide-react";
import { Empty, Heading, InfoTip } from "../components";
import {
  ACTIVITY_GROUPS,
  ACTIVITY_PAGE,
  clock,
  dayLabel,
  Segmented,
  SourceTag,
  time,
} from "./presentation";

import type { AssistantSettingsState } from "./useAssistantSettings";

const UNCONFIRMED_PREVIEW = 5;

export function AssistantActivityPage({
  activity,
  unconfirmed,
  call,
  setConfirming,
  allEntries,
  groups,
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
  | "groups"
  | "filter"
  | "setFilter"
  | "setShown"
  | "entries"
  | "shown"
>) {
  const [expanded, setExpanded] = useState(false);
  const hidden = unconfirmed.length - UNCONFIRMED_PREVIEW;
  return (
    <div className="page">
      <Heading title={t("message.0593")} subtitle={t("message.0614")} />
      {!activity ? (
        <Empty>{t("message.0615")}</Empty>
      ) : (
        <>
          <section className="section">
            <div className="section-heading">
              <div className="heading-title">
                <h2>{t("message.0616")}</h2>
                {!!unconfirmed.length && (
                  <span className="heading-note">
                    {t("message.0617", { value0: unconfirmed.length })}
                  </span>
                )}
              </div>
              {!!unconfirmed.length && (
                <button
                  className="text-button"
                  onClick={() => call("activity.confirm_all")}
                >
                  {t("activity.mark_all_read")}
                </button>
              )}
            </div>
            <div className="card">
              {unconfirmed.length ? (
                unconfirmed
                  .slice(0, expanded ? undefined : UNCONFIRMED_PREVIEW)
                  .map((row) => (
                    <button
                      className="record-row"
                      key={row.record_id}
                      onClick={() =>
                        call("activity.open", { token: row.action_token })
                      }
                    >
                      <span className="record-time">
                        {time(row.recorded_at)}
                      </span>
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
              {hidden > 0 && (
                <div className="section-footer">
                  <button
                    className="text-button"
                    onClick={() => setExpanded((value) => !value)}
                  >
                    {expanded
                      ? t("activity.collapse")
                      : t("activity.more", { count: hidden })}
                  </button>
                </div>
              )}
            </div>
          </section>
          <section className="section">
            <div className="section-heading">
              <div className="heading-title">
                <h2>{t("message.0622")}</h2>
                <InfoTip label={t("message.0623")} text={t("message.0624")} />
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
                      ...groups.map(
                        (group) =>
                          [
                            group,
                            `${t(ACTIVITY_GROUPS[group])} ${
                              allEntries.filter(
                                (entry) => entry.group === group,
                              ).length
                            }`,
                          ] as [string, string],
                      ),
                    ]}
                    value={filter}
                    select={(group) => {
                      setFilter(group);
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
                    <div
                      key={`${entry.group}-${entry.occurred_at}-${
                        entry.action_token || index
                      }`}
                    >
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
