import { t } from "../../localization.cjs";
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
      <Heading title={t("message.0594")} subtitle={t("message.0666")}>
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
          {t("message.0667")}
        </button>
      </Heading>
      {!integration || !hero ? (
        <Empty>{t("message.0668")}</Empty>
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
          <Section title={t("message.0669")}>
            <CheckList
              checks={appChecks(
                integration.diagnostics,
                integration.storage || {},
              )}
            />
          </Section>
          <details className="advanced card">
            <summary>{t("message.0670")}</summary>
            {(
              [
                ...(codexActive ? [["Codex", "codex"]] : []),
                ...(claudeActive ? [["Claude Code", "claude_code"]] : []),
              ] as [string, string][]
            ).map(([name, provider]) => (
              <div className="setting-row" key={provider}>
                <div className="field-label">
                  <label>{t("connection.repair_title", { name })}</label>
                  <p className="field-description">
                    {t("connection.repair_note", { name })}
                  </p>
                </div>
                <button
                  className="button"
                  aria-label={t("message.0674", { value0: name })}
                  onClick={() => preview("repair", provider)}
                >
                  {t("message.0675")}
                </button>
              </div>
            ))}
            <div className="setting-row">
              <div className="field-label">
                <label>{t("message.0676")}</label>
                <p className="field-description">{t("message.0677")}</p>
              </div>
              <button
                className="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const result = await window.settings!.file("export");
                    if (!("cancelled" in result)) notify(t("message.0678"));
                  } catch (e) {
                    reportError(e);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Download size={14} />
                {t("message.0676")}
              </button>
            </div>
            <details className="diagnostics">
              <summary>{t("message.0679")}</summary>
              <pre>{JSON.stringify(integration.diagnostics, null, 2)}</pre>
            </details>
          </details>
        </>
      )}
    </div>
  );
}
