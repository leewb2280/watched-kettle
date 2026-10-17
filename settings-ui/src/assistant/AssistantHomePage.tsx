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
      <Heading
        title="홈"
        subtitle="확인할 알림, 진행 중인 작업, 남은 한도와 연결 상태를 모아 봅니다."
      />
      {!usage || !activity || !integration ? (
        <Empty>상태를 불러오는 중입니다.</Empty>
      ) : (
        <div className="home-grid">
          <Section
            title="확인할 알림"
            note={unconfirmed.length ? `${unconfirmed.length}건` : ""}
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
                확인할 알림이 없습니다.
              </p>
            )}
            <HomeLink
              label="활동 기록 열기"
              open={() => shell.navigate("activity")}
            />
          </Section>
          <Section
            title="진행 중"
            note={homeRows.length ? `${homeRows.length}개` : ""}
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
                    title={`${project.label || "프로젝트"} · ${row.title || "대화"}`}
                  >
                    {project.label || "프로젝트"} · {row.title || "대화"}
                  </span>
                  {project.source && <SourceTag name={project.source} />}
                  <span className="pill">{row.label || row.state}</span>
                  <ChevronRight size={14} />
                </button>
              ))
            ) : (
              <p className="quiet-row">진행 중인 작업이 없습니다.</p>
            )}
            <HomeLink
              label="활동 기록 열기"
              open={() => shell.navigate("activity")}
            />
          </Section>
          <Section title="남은 한도">
            <QuotaGroups usage={usage} compact />
            <HomeLink
              label="사용량 열기"
              open={() => shell.navigate("usage")}
            />
          </Section>
          <Section title="연결">
            {!connections.length && (
              <p className="quiet-row">
                사용 중인 도구가 없습니다. 연결·진단에서 Codex나 Claude Code를
                켤 수 있습니다.
              </p>
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
