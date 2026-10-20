import { t } from "../../localization.cjs";
import { LocalizedText } from "../LocalizedText";
import {
  ArrowDown,
  ArrowUp,
  CircleCheck,
  CircleMinus,
  CircleX,
  TriangleAlert,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { InfoTip, Modal, Switch } from "../components";
import type {
  ClaudeIntegration,
  Diagnostics,
  InstallStatus,
  IntegrationResponse,
  ProviderDiagnostic,
  StatusLineLayout,
  StorageStatus,
} from "../types";
import {
  checkIcons,
  minuteOptions,
  SOURCE_CLASSES,
  TERMINAL_KEYBINDING,
  time,
  WAITING_MINUTES,
  WORK_MINUTES,
} from "./presentation";

export type CheckState = "ok" | "warn" | "off" | "error";

export type Check = { label: string; state: CheckState; value: string };

export function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="check-list">
      {checks.map((check) => (
        <li className={`check-${check.state}`} key={check.label}>
          {checkIcons[check.state]}
          <span>{check.label}</span>
          <strong>{check.value}</strong>
        </li>
      ))}
    </ul>
  );
}

// Translates the raw diagnostics into the few facts a user can act on.
// Both tools list the shared rows first, with the same names and order:
// 설치 감지 → 관리 hook → 최근 이벤트 수신, then their own rows.
export function integrationChecks(
  diagnostics: Diagnostics,
  install: InstallStatus,
): Check[] {
  const trust = diagnostics.global_hook_trust || {};
  const jsonl = diagnostics.jsonl_monitor || {};
  const installed = hooksConnected(install.state);
  const trustMissing =
    trust.valid && (trust.approved_count ?? 0) < (trust.expected_count ?? 0);
  return [
    {
      label: t("message.0737"),
      state: diagnostics.codex_environment?.detected ? "ok" : "warn",
      value: diagnostics.codex_environment?.detected
        ? t("message.0738")
        : t("message.0739"),
    },
    {
      label: t("message.0740"),
      state: installed
        ? "ok"
        : install.state === "not_installed"
          ? "off"
          : "warn",
      value: t("message.0741", {
        value0: install.installed_events ?? 0,
        value1: install.expected_events ?? 0,
      }),
    },
    {
      label: t("message.0742"),
      state: diagnostics.last_received_at ? "ok" : "off",
      value: diagnostics.last_received_at
        ? `${time(diagnostics.last_received_at)}${
            diagnostics.last_transport ? ` · ${diagnostics.last_transport}` : ""
          }`
        : t("message.0743"),
    },
    {
      label: t("message.0744"),
      state:
        !installed || !trust.valid
          ? "off"
          : trust.possibly_stale || trustMissing
            ? "warn"
            : "ok",
      value: !installed
        ? t("message.0745")
        : !trust.valid
          ? t("message.0746")
          : trust.possibly_stale
            ? t("message.0747")
            : trustMissing
              ? t("message.0748", {
                  value0: trust.approved_count,
                  value1: trust.expected_count,
                })
              : t("message.0749"),
    },
    {
      label: t("message.0750"),
      state: jsonl.active ? "ok" : "off",
      value: jsonl.active
        ? t("message.0751", { value0: jsonl.tracked_files ?? 0 })
        : t("message.0752"),
    },
  ];
}

// Rows about the app itself, not either tool.
export function appChecks(
  diagnostics: Diagnostics,
  storage: StorageStatus,
): Check[] {
  return [
    {
      label: t("message.0753"),
      state: diagnostics.last_error ? "error" : "ok",
      value: diagnostics.last_error || t("message.0754"),
    },
    {
      label: t("message.0755"),
      state: storage.available ? "ok" : "error",
      value:
        storage.message ||
        (storage.available ? t("message.0756") : t("message.0757")),
    },
    {
      label: t("message.0034"),
      state: "off",
      value: t("message.0758", {
        value0: diagnostics.schedule_event_count || 0,
      }),
    },
  ];
}

// Hooks another copy of this app wrote (installed build or source run) still
// deliver events here, since every copy spools to the same user folder.
const otherCopyHero = {
  tone: "ok",
  title: t("integration.other_copy_title"),
  body: t("integration.other_copy_body"),
  action: ["repair", t("integration.other_copy_action")] as [string, string],
};

function hooksConnected(state?: string) {
  return state === "installed" || state === "other_copy";
}

export const heroes: Record<
  string,
  { tone: string; title: string; body?: string; action?: [string, string] }
> = {
  installed: {
    tone: "ok",
    title: t("message.0759"),
  },
  // Codex is in use but its hook is missing: logs still give some activity,
  // and the hero reconnects the hook.
  not_installed: {
    tone: "warn",
    title: t("message.0760"),
    body: t("message.0761"),
    action: ["repair", t("message.0762")],
  },
  partial: {
    tone: "warn",
    title: t("message.0763"),
    action: ["repair", t("message.0764")],
  },
  drifted: {
    tone: "warn",
    title: t("message.0763"),
    action: ["repair", t("message.0764")],
  },
  other_copy: otherCopyHero,
  disabled: {
    tone: "warn",
    title: t("message.0765"),
    body: t("message.0766"),
  },
  invalid: {
    tone: "error",
    title: t("message.0767"),
  },
};

// The trust row and the hero must agree, so approval gaps outrank "installed".
export function heroFor(integration: IntegrationResponse) {
  const install = integration.install || {};
  const trust = integration.diagnostics.global_hook_trust || {};
  if (
    hooksConnected(install.state) &&
    trust.valid &&
    (trust.possibly_stale ||
      (trust.approved_count ?? 0) < (trust.expected_count ?? 0))
  )
    return {
      tone: "warn",
      title: t("message.0768"),
      body: trust.possibly_stale
        ? t("message.0769")
        : t("message.0770", {
            value0: trust.approved_count,
            value1: trust.expected_count,
          }),
    };
  if (
    install.state === "not_installed" &&
    !integration.diagnostics.codex_environment?.detected
  )
    return {
      ...heroes.not_installed,
      body: t("message.0771"),
    };
  return heroes[install.state] || heroes.invalid;
}

export const claudeHeroes: Record<
  string,
  { tone: string; title: string; body?: string; action?: [string, string] }
> = {
  installed: {
    tone: "ok",
    title: t("message.0772"),
    body: t("message.0061"),
  },
  not_installed: {
    tone: "warn",
    title: t("message.0773"),
    body: t("message.0774"),
    action: ["repair", t("message.0762")],
  },
  partial: {
    tone: "warn",
    title: t("message.0775"),
    action: ["repair", t("message.0764")],
  },
  drifted: {
    tone: "warn",
    title: t("message.0775"),
    action: ["repair", t("message.0764")],
  },
  other_copy: otherCopyHero,
  disabled: {
    tone: "warn",
    title: t("message.0776"),
    body: t("message.0777"),
  },
  blocked_by_policy: {
    tone: "warn",
    title: t("message.0778"),
  },
  invalid: {
    tone: "error",
    title: t("message.0779"),
  },
};

export function claudeChecks(
  claude: ClaudeIntegration,
  diagnostics: ProviderDiagnostic,
): Check[] {
  const install = claude.install || {};
  const monitor = diagnostics.turn_end_monitor || {};
  const installed = hooksConnected(install.state);
  return [
    {
      label: t("message.0737"),
      state: install.detected ? "ok" : "warn",
      value: install.detected ? t("message.0738") : t("message.0739"),
    },
    {
      label: t("message.0740"),
      state: installed
        ? "ok"
        : install.state === "not_installed"
          ? "off"
          : "warn",
      value: t("message.0741", {
        value0: install.installed_events ?? 0,
        value1: install.expected_events ?? 0,
      }),
    },
    {
      label: t("message.0742"),
      state: diagnostics.last_hook_received_at ? "ok" : "off",
      value: diagnostics.last_hook_received_at
        ? time(diagnostics.last_hook_received_at)
        : t("message.0743"),
    },
    ...(claude.status_line
      ? [
          {
            label: t("message.0780"),
            state: (claude.status_line.observed_at
              ? "ok"
              : claude.status_line.state === "installed"
                ? "off"
                : "warn") as CheckState,
            value: claude.status_line.observed_at
              ? t("message.0781", {
                  value0: time(claude.status_line.observed_at),
                })
              : claude.status_line.state === "installed"
                ? t("message.0782")
                : t("message.0783"),
          },
        ]
      : []),
    {
      label: t("message.0784"),
      state: monitor.attached ? "ok" : "off",
      value: monitor.active_turns
        ? t("message.0785", { value0: monitor.active_turns })
        : t("message.0786", { value0: monitor.detected_count ?? 0 }),
    },
  ];
}

// Items the built-in Claude Code status line can show, with a sample.
export const STATUS_LINE_ITEMS: [string, string, string][] = [
  ["pet", t("message.0787"), t("statusline.pet_off")],
  ["ide", "IDE", "VS Code"],
  ["model", t("message.0788"), "Opus 5.5 high"],
  ["context", t("message.0789"), t("message.0790")],
  ["five_hour", t("message.0791"), t("message.0792")],
  ["seven_day", t("message.0793"), t("message.0794")],
];

export function StatusLineEditor({
  layout,
  save,
}: {
  layout: StatusLineLayout;
  save: (layout: StatusLineLayout) => void;
}) {
  const lines: string[][] = layout.lines || [];
  const shown = lines.flat();
  // One ordered list: shown items line by line, then the hidden ones.
  const order = [
    ...shown,
    ...STATUS_LINE_ITEMS.map(([key]) => key).filter(
      (key) => !shown.includes(key),
    ),
  ];
  const lineOf: Record<string, number> = Object.fromEntries(
    order.map((key) => [key, lines.findIndex((line) => line.includes(key))]),
  );
  const commit = (
    nextOrder: string[],
    nextLines: Record<string, number>,
    flags: Partial<StatusLineLayout> = {},
  ) =>
    save({
      lines: [0, 1].map((line) =>
        nextOrder.filter((key) => nextLines[key] === line),
      ),
      color: layout.color,
      reset_times: layout.reset_times,
      ...flags,
    });
  const move = (index: number, delta: number) => {
    const next = [...order];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    commit(next, lineOf);
  };
  const label = (key: string) =>
    STATUS_LINE_ITEMS.find(([item]) => item === key)?.[1] || key;
  const sample = (key: string) => {
    const text = STATUS_LINE_ITEMS.find(([item]) => item === key)?.[2] || "";
    return key === "five_hour" && layout.reset_times ? `${text} (14:30)` : text;
  };
  return (
    <div className="status-line-editor">
      {order.map((key, index) => (
        <div className="setting-row status-line-item" key={key}>
          <label htmlFor={`status-line-${key}`}>{label(key)}</label>
          <select
            id={`status-line-${key}`}
            value={lineOf[key]}
            onChange={(event) =>
              commit(order, { ...lineOf, [key]: Number(event.target.value) })
            }
          >
            <option value={-1}>{t("message.0795")}</option>
            <option value={0}>{t("message.0796")}</option>
            <option value={1}>{t("message.0797")}</option>
          </select>
          <button
            className="icon-button"
            aria-label={t("message.0712", { value0: label(key) })}
            disabled={index === 0}
            onClick={() => move(index, -1)}
          >
            <ArrowUp size={14} />
          </button>
          <button
            className="icon-button"
            aria-label={t("message.0713", { value0: label(key) })}
            disabled={index === order.length - 1}
            onClick={() => move(index, 1)}
          >
            <ArrowDown size={14} />
          </button>
        </div>
      ))}
      <div className="setting-row">
        <label>{t("message.0798")}</label>
        <Switch
          label={t("message.0799")}
          value={!!layout.color}
          change={(value) => commit(order, lineOf, { color: value })}
        />
      </div>
      <div className="setting-row">
        <label>{t("message.0800")}</label>
        <Switch
          label={t("message.0801")}
          value={!!layout.reset_times}
          change={(value) => commit(order, lineOf, { reset_times: value })}
        />
      </div>
      <div className="status-line-preview" aria-label={t("message.0802")}>
        {lines.some((line) => line.length) ? (
          lines
            .filter((line) => line.length)
            .map((line, index) => (
              <div key={index}>{line.map(sample).join(" · ")}</div>
            ))
        ) : (
          <div>{t("message.0803")}</div>
        )}
      </div>
    </div>
  );
}

export function TerminalHelp({ close }: { close: () => void }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(TERMINAL_KEYBINDING, null, 4);
  return (
    <Modal title={t("message.0804")} close={close}>
      <p>
        <LocalizedText
          id="integration.terminal_help"
          values={{ command: <code>claude</code> }}
        />
      </p>
      <h3>{t("message.0807")}</h3>
      <p>
        <LocalizedText
          id="integration.keybinding_help"
          values={{
            file: <code>%APPDATA%\Code\User\keybindings.json</code>,
            shortcut: <code>Ctrl+Shift+&apos;</code>,
          }}
        />
      </p>
      <pre className="code-block">{text}</pre>
      <button
        className="button compact"
        onClick={() =>
          navigator.clipboard.writeText(text).then(() => setCopied(true))
        }
      >
        {copied ? t("message.0810") : t("message.0811")}
      </button>
      <ul className="help-notes">
        <li>{t("message.0812")}</li>
        <li>
          <LocalizedText
            id="integration.venv_note"
            values={{ command: <code>claude</code> }}
          />
        </li>
        <li>{t("message.0815")}</li>
      </ul>
      <h3>{t("message.0816")}</h3>
      <ul className="help-notes">
        <li>
          <code>/context</code> {t("message.0817")}
          <code>/usage</code> {t("message.0818")}
        </li>
        <li>
          <code>/clear</code> {t("message.0819")}
          <code>/compact</code> {t("message.0820")} <code>/resume</code>{" "}
          {t("message.0821")}
        </li>
        <li>
          <code>/rename</code> {t("message.0822")}
        </li>
      </ul>
    </Modal>
  );
}

export type Hero = {
  tone: string;
  title: string;
  body?: string;
  action?: [string, string];
};

export function StatusHero({
  hero,
  message,
  act,
}: {
  hero: Hero;
  message?: string;
  act: (operation: string) => void;
}) {
  return (
    <div className={`status-hero card tone-${hero.tone}`}>
      <span className="status-icon">
        {hero.tone === "ok" ? (
          <CircleCheck size={22} />
        ) : hero.tone === "error" ? (
          <CircleX size={22} />
        ) : hero.tone === "off" ? (
          <CircleMinus size={22} />
        ) : (
          <TriangleAlert size={22} />
        )}
      </span>
      <div className="status-copy">
        <h3>{hero.title}</h3>
        <p>{hero.body || message}</p>
      </div>
      {hero.action && (
        <button className="button primary" onClick={() => act(hero.action![0])}>
          {hero.action[1]}
        </button>
      )}
    </div>
  );
}

// One tool's block: heading with its source dot, state, settings, checks.
export function ProviderBlock({
  name,
  hero,
  message,
  act,
  checks,
  children,
}: {
  name: string;
  hero: Hero;
  message?: string;
  act: (operation: string) => void;
  checks: Check[];
  children: ReactNode;
}) {
  return (
    <section className="section provider-block" aria-label={name}>
      <div className="section-heading">
        <h2 className={`provider-title ${SOURCE_CLASSES[name] || ""}`}>
          {name}
        </h2>
      </div>
      <div className="provider-stack">
        <StatusHero hero={hero} message={message} act={act} />
        <div className="card">{children}</div>
        <div className="card">
          <h4 className="check-heading">{t("message.0823")}</h4>
          <CheckList checks={checks} />
        </div>
      </div>
    </section>
  );
}

// One switch per tool: on connects its hooks and usage, off removes them,
// stops reading its files and hides it everywhere but this page.
export function ToolSwitchRow({
  name,
  value,
  preview,
}: {
  name: string;
  value: boolean;
  preview: (operation: string) => void;
}) {
  return (
    <div className="setting-row">
      <div className="field-label">
        <label>{t("integration.tool_label", { name })}</label>
        <p className="field-description">
          {value
            ? t("message.0825", { value0: name })
            : t("message.0826", { value0: name })}{" "}
          {t("message.0827")}
        </p>
      </div>
      <Switch
        label={t("message.0828", { value0: name })}
        value={value}
        change={(next) => preview(next ? "enable" : "disable")}
      />
    </div>
  );
}

export function ToolOffSection({
  name,
  detected,
  preview,
}: {
  name: string;
  detected: boolean;
  preview: (operation: string) => void;
}) {
  return (
    <section className="section provider-block" aria-label={name}>
      <div className="section-heading">
        <h2 className={`provider-title ${SOURCE_CLASSES[name] || ""}`}>
          {name}
        </h2>
      </div>
      <div className="provider-stack">
        <div className="card">
          <ToolSwitchRow name={name} value={false} preview={preview} />
          {!detected && (
            <p className="footnote">
              {t("integration.not_installed", { name })}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

export function CodexSection({
  integration,
  hero,
  preview,
}: {
  integration: IntegrationResponse;
  hero: Hero;
  preview: (operation: string) => void;
}) {
  return (
    <ProviderBlock
      name="Codex"
      hero={hero}
      message={integration.install?.message}
      act={preview}
      checks={integrationChecks(
        integration.diagnostics,
        integration.install || {},
      )}
    >
      <ToolSwitchRow name="Codex" value preview={preview} />
    </ProviderBlock>
  );
}

export function ClaudeCodeSection({
  claude,
  diagnostics,
  preview,
  previewStatusLine,
  setMinutes,
  saveLayout,
  openHelp,
}: {
  claude: ClaudeIntegration;
  diagnostics: ProviderDiagnostic;
  preview: (operation: string) => void;
  previewStatusLine: (operation: string) => void;
  setMinutes: (key: string, value: number) => void;
  saveLayout: (layout: StatusLineLayout) => void;
  openHelp: () => void;
}) {
  const statusLine = claude.status_line;
  const statusLineOn = ["installed", "drifted"].includes(
    statusLine?.state ?? "",
  );
  const state = claude.install?.state || "invalid";
  const hero = claudeHeroes[state] || claudeHeroes.invalid;
  const minutes = (
    key: string,
    label: string,
    choices: number[],
    current: number,
    description: string,
  ) => (
    <div className="setting-row">
      <div className="field-label">
        <label>{label}</label>
        <p className="field-description">{description}</p>
      </div>
      <select
        aria-label={label}
        value={String(current)}
        onChange={(event) => setMinutes(key, Number(event.target.value))}
      >
        {minuteOptions(choices, current).map((value) => (
          <option key={value} value={String(value)}>
            {value}
            {t("message.0831")}
          </option>
        ))}
      </select>
    </div>
  );
  return (
    <ProviderBlock
      name="Claude Code"
      hero={hero}
      message={claude.install?.message}
      act={preview}
      checks={claudeChecks(claude, diagnostics)}
    >
      <ToolSwitchRow name="Claude Code" value preview={preview} />
      {statusLine && (
        <div className="setting-row">
          <div className="field-label">
            <div className="heading-title">
              <label>{t("message.0832")}</label>
              <InfoTip
                label={t("message.0833")}
                text={[
                  t("message.0834"),
                  t("message.0835"),
                  t("message.0836"),
                ].join("\n")}
              />
            </div>
            <p className="field-description">
              {t("message.0837")}
              <button className="text-button inline" onClick={openHelp}>
                {t("message.0838")}
              </button>
              )
            </p>
          </div>
          <Switch
            label={t("message.0832")}
            value={statusLineOn}
            disabled={statusLine.state === "invalid"}
            change={(value) =>
              previewStatusLine(
                value
                  ? statusLine.state === "drifted"
                    ? "repair"
                    : "install"
                  : "remove",
              )
            }
          />
        </div>
      )}
      <details className="status-line-details">
        <summary>{t("message.0839")}</summary>
        {minutes(
          "claude_code_work_minutes",
          t("message.0840"),
          WORK_MINUTES,
          claude.work_minutes,
          t("message.0841"),
        )}
        {minutes(
          "claude_code_waiting_minutes",
          t("message.0842"),
          WAITING_MINUTES,
          claude.waiting_minutes,
          t("message.0843"),
        )}
        {statusLine && statusLineOn && statusLine.layout && (
          <div className="status-line-block">
            <h4 className="check-heading">{t("message.0844")}</h4>
            {statusLine.has_original && (
              <p className="footnote">{t("message.0845")}</p>
            )}
            <StatusLineEditor layout={statusLine.layout} save={saveLayout} />
          </div>
        )}
      </details>
    </ProviderBlock>
  );
}
