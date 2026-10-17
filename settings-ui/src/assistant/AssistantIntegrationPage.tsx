import { Download, RotateCcw } from "lucide-react";
import { Empty, Heading, Section } from "../components";
import type { IntegrationSetting } from "../types";
import {
  CheckList,
  ClaudeCodeSection,
  CodexSection,
  ToolOffSection,
  appChecks,
} from "./Connections";
import type { AssistantSettingsState } from "./useAssistantSettings";
export function AssistantIntegrationPage({
  setIntegration,
  reportError,
  integration,
  hero,
  codexActive,
  preview,
  claudeActive,
  call,
  setTerminalHelp,
  busy,
  setBusy,
  notify,
}: Pick<
  AssistantSettingsState,
  | "setIntegration"
  | "reportError"
  | "integration"
  | "hero"
  | "codexActive"
  | "preview"
  | "claudeActive"
  | "call"
  | "setTerminalHelp"
  | "busy"
  | "setBusy"
  | "notify"
>) {
  return (
    <div className="page">
      <Heading
        title="연결·진단"
        subtitle="Codex·Claude Code 작업 상태를 받는 연결을 확인합니다."
      >
        <button
          className="button compact"
          onClick={() =>
            window
              .settings!.request("integration.snapshot")
              .then(setIntegration)
              .catch(reportError)
          }
        >
          <RotateCcw size={14} />
          새로고침
        </button>
      </Heading>
      {!integration || !hero ? (
        <Empty>연결 상태를 확인하는 중입니다.</Empty>
      ) : (
        <>
          {codexActive ? (
            <CodexSection
              integration={integration}
              hero={hero}
              preview={(operation) => preview(operation, "codex")}
            />
          ) : (
            <ToolOffSection
              name="Codex"
              detected={!!integration.codex_detected}
              preview={(operation) => preview(operation, "codex")}
            />
          )}
          {integration.claude_code && !claudeActive && (
            <ToolOffSection
              name="Claude Code"
              detected={!!integration.claude_code!.install?.detected}
              preview={(operation) => preview(operation, "claude_code")}
            />
          )}
          {claudeActive && (
            <ClaudeCodeSection
              claude={integration.claude_code!}
              diagnostics={integration.diagnostics.claude_code || {}}
              preview={(operation) => preview(operation, "claude_code")}
              previewStatusLine={(operation) =>
                preview(operation, "claude_code_status_line")
              }
              setMinutes={(key, value) =>
                call("integration.set", { key, value } as IntegrationSetting)
              }
              saveLayout={(layout) =>
                call("integration.set", {
                  key: "status_line_layout",
                  value: layout,
                })
              }
              openHelp={() => setTerminalHelp(true)}
            />
          )}
          <Section title="앱 상태">
            <CheckList
              checks={appChecks(
                integration.diagnostics,
                integration.storage || {},
              )}
            />
          </Section>
          <details className="advanced card">
            <summary>고급 도구</summary>
            {(
              [
                ...(codexActive ? [["Codex", "codex"]] : []),
                ...(claudeActive ? [["Claude Code", "claude_code"]] : []),
              ] as [string, string][]
            ).map(([name, provider]) => (
              <div className="setting-row" key={provider}>
                <div className="field-label">
                  <label>{name} 연결 복구</label>
                  <p className="field-description">
                    이 앱의 hook을 다시 맞춥니다. 끄려면 위의 {name} 사용
                    스위치를 씁니다.
                  </p>
                </div>
                <button
                  className="button"
                  aria-label={`${name} 복구 검토`}
                  onClick={() => preview("repair", provider)}
                >
                  복구 검토
                </button>
              </div>
            ))}
            <div className="setting-row">
              <div className="field-label">
                <label>진단 내보내기</label>
                <p className="field-description">
                  문제를 알릴 때 첨부할 수 있는 ZIP 파일입니다.
                </p>
              </div>
              <button
                className="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const result = await window.settings!.file("export");
                    if (!("cancelled" in result))
                      notify("진단 ZIP을 저장했습니다.");
                  } catch (e) {
                    reportError(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Download size={14} />
                진단 내보내기
              </button>
            </div>
            <details className="diagnostics">
              <summary>원본 상태 보기</summary>
              <pre>{JSON.stringify(integration.diagnostics, null, 2)}</pre>
            </details>
          </details>
        </>
      )}
    </div>
  );
}
