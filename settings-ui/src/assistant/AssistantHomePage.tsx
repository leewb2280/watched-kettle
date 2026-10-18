import { t } from "../../localization.cjs";
import { Check, ChevronRight } from "lucide-react";
import { Empty, Heading, Section } from "../components";
import { HomeLink, SourceTag, time } from "./presentation";

import { QuotaGroups } from "./QuotaGroups";
import type { AssistantSettingsState } from "./useAssistantSettings";
export function AssistantHomePage({
  usage,
  activity,
  integration,
  unconfirmed,
  call,
  shell,
  homeRows,
  connections,
}: Pick<
  AssistantSettingsState,
  | "usage"
  | "activity"
  | "integration"
  | "unconfirmed"
  | "call"
  | "shell"
  | "homeRows"
  | "connections"
>) {
  return (
    <div className="page">
      <Heading title={t("message.0590")} subtitle={t("message.0655")} />
      {!usage || !activity || !integration ? (
        <Empty>{t("message.0656")}</Empty>
      ) : (
        <div className="home-grid">
          <Section
            title={t("message.0657")}
            note={
              unconfirmed.length
                ? t("message.0617", { value0: unconfirmed.length })
                : ""
            }
          >
            {unconfirmed.length ? (
              unconfirmed.slice(0, 3).map((row) => (
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
                {t("message.0658")}
              </p>
            )}
            <HomeLink
              label={t("message.0659")}
              open={() => shell.navigate("activity")}
            />
          </Section>
          <Section
            title={t("message.0445")}
            note={
              homeRows.length
                ? t("message.0660", { value0: homeRows.length })
                : ""
            }
          >
            {homeRows.length ? (
              homeRows.slice(0, 4).map(({ project, row }, index) => (
                <button
                  className="thread-row"
                  key={`${project.key}-${index}`}
                  onClick={() =>
                    call("activity.open", { token: row.action_token })
                  }
                >
                  <span
                    className="record-summary"
                    title={`${project.label || t("message.0619")} · ${row.title || t("message.0620")}`}
                  >
                    {project.label ? (
                      <span data-user-text>{project.label}</span>
                    ) : (
                      t("message.0619")
                    )}{" "}
                    ·{" "}
                    {row.title ? (
                      <span data-user-text>{row.title}</span>
                    ) : (
                      t("message.0620")
                    )}
                  </span>
                  {project.source && <SourceTag name={project.source} />}
                  <span className="pill">{row.label || row.state}</span>
                  <ChevronRight size={14} />
                </button>
              ))
            ) : (
              <p className="quiet-row">{t("message.0661")}</p>
            )}
            <HomeLink
              label={t("message.0659")}
              open={() => shell.navigate("activity")}
            />
          </Section>
          <Section title={t("message.0662")}>
            <QuotaGroups usage={usage} compact />
            <HomeLink
              label={t("message.0663")}
              open={() => shell.navigate("usage")}
            />
          </Section>
          <Section title={t("message.0664")}>
            {!connections.length && (
              <p className="quiet-row">{t("message.0665")}</p>
            )}
            {connections.map(([name, state]) => (
              <button
                className={`home-connection tone-${state.tone}`}
                key={name}
                onClick={() => shell.navigate("integration")}
              >
                <span className="small-dot" />
                <strong>{name}</strong>
                <span className="record-summary">{state.title}</span>
                <ChevronRight size={14} />
              </button>
            ))}
          </Section>
        </div>
      )}
    </div>
  );
}
