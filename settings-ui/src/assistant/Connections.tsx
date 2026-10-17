import {
  ArrowDown,
  ArrowUp,
  CircleCheck,
  CircleMinus,
  CircleX,
  Info,
  TriangleAlert,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Modal, Switch } from "../components";
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
  const installed = install.state === "installed";
  const trustMissing =
    trust.valid && (trust.approved_count ?? 0) < (trust.expected_count ?? 0);
  return [
    {
      label: "설치 감지",
      state: diagnostics.codex_environment?.detected ? "ok" : "warn",
      value: diagnostics.codex_environment?.detected ? "감지됨" : "찾지 못함",
    },
    {
      label: "관리 hook",
      state: installed
        ? "ok"
        : install.state === "not_installed"
          ? "off"
          : "warn",
      value: `${install.installed_events ?? 0}/${install.expected_events ?? 0}개 이벤트`,
    },
    {
      label: "최근 이벤트 수신",
      state: diagnostics.last_received_at ? "ok" : "off",
      value: diagnostics.last_received_at
        ? `${time(diagnostics.last_received_at)}${
            diagnostics.last_transport ? ` · ${diagnostics.last_transport}` : ""
          }`
        : "이번 실행에서 아직 없음",
    },
    {
      label: "신뢰 승인",
      state:
        !installed || !trust.valid
          ? "off"
          : trust.possibly_stale || trustMissing
            ? "warn"
            : "ok",
      value: !installed
        ? "hook 설치 후 확인"
        : !trust.valid
          ? "확인할 수 없음"
          : trust.possibly_stale
            ? "승인 이후 hook이 바뀌었을 수 있음"
            : trustMissing
              ? `Codex에서 승인 필요 (${trust.approved_count}/${trust.expected_count})`
              : "승인됨",
    },
    {
      label: "작업 로그 감시",
      state: jsonl.active ? "ok" : "off",
      value: jsonl.active
        ? `감시 중 · 파일 ${jsonl.tracked_files ?? 0}개`
        : "꺼져 있음",
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
      label: "마지막 오류",
      state: diagnostics.last_error ? "error" : "ok",
      value: diagnostics.last_error || "없음",
    },
    {
      label: "로컬 기록 저장소",
      state: storage.available ? "ok" : "error",
      value: storage.message || (storage.available ? "사용 가능" : "사용 불가"),
    },
    {
      label: "일정 알림",
      state: "off",
      value: `이번 실행 ${diagnostics.schedule_event_count || 0}건 · 외부 일정 미연결`,
    },
  ];
}

export const heroes: Record<
  string,
  { tone: string; title: string; body?: string; action?: [string, string] }
> = {
  installed: {
    tone: "ok",
    title: "Codex 작업 상태를 받을 준비가 됐어요",
  },
  // Codex is in use but its hook is missing: logs still give some activity,
  // and the hero reconnects the hook.
  not_installed: {
    tone: "warn",
    title: "Codex hook이 연결되지 않았어요",
    body: "hook 없이도 Codex 로그로 작업 상태를 일부 받습니다. 연결하면 진행과 완료를 더 정확히 알려 줍니다.",
    action: ["repair", "hook 연결하기"],
  },
  partial: {
    tone: "warn",
    title: "연결 설정 일부가 바뀌었어요",
    action: ["repair", "연결 복구하기"],
  },
  drifted: {
    tone: "warn",
    title: "연결 설정 일부가 바뀌었어요",
    action: ["repair", "연결 복구하기"],
  },
  disabled: {
    tone: "warn",
    title: "Codex hook 기능이 꺼져 있어요",
    body: "Codex 설정에서 hook 기능을 켠 뒤 다시 확인해 주세요.",
  },
  invalid: {
    tone: "error",
    title: "Codex 설정을 읽을 수 없어요",
  },
};

// The trust row and the hero must agree, so approval gaps outrank "installed".
export function heroFor(integration: IntegrationResponse) {
  const install = integration.install || {};
  const trust = integration.diagnostics.global_hook_trust || {};
  if (
    install.state === "installed" &&
    trust.valid &&
    (trust.possibly_stale ||
      (trust.approved_count ?? 0) < (trust.expected_count ?? 0))
  )
    return {
      tone: "warn",
      title: "Codex에서 hook 승인을 확인해 주세요",
      body: trust.possibly_stale
        ? "승인한 뒤 hook이 바뀌었을 수 있습니다. Codex에서 승인 상태를 다시 확인해 주세요."
        : `승인되지 않은 hook이 있습니다 (${trust.approved_count}/${trust.expected_count}). Codex에서 승인 상태를 확인해 주세요.`,
    };
  if (
    install.state === "not_installed" &&
    !integration.diagnostics.codex_environment?.detected
  )
    return {
      ...heroes.not_installed,
      body: "Codex를 찾지 못했습니다. Codex를 설치한 뒤 새로고침하거나, hook을 미리 연결해 둘 수 있습니다.",
    };
  return heroes[install.state] || heroes.invalid;
}

export const claudeHeroes: Record<
  string,
  { tone: string; title: string; body?: string; action?: [string, string] }
> = {
  installed: {
    tone: "ok",
    title: "Claude Code 작업 상태를 받을 준비가 됐어요",
    body: "이미 열려 있는 Claude Code 세션은 다시 시작해야 적용됩니다.",
  },
  not_installed: {
    tone: "warn",
    title: "Claude Code hook이 연결되지 않았어요",
    body: "hook을 연결해야 CLI와 VS Code의 Claude Code 작업을 펫이 알려 줍니다.",
    action: ["repair", "hook 연결하기"],
  },
  partial: {
    tone: "warn",
    title: "Claude Code 연결 설정 일부가 바뀌었어요",
    action: ["repair", "연결 복구하기"],
  },
  drifted: {
    tone: "warn",
    title: "Claude Code 연결 설정 일부가 바뀌었어요",
    action: ["repair", "연결 복구하기"],
  },
  disabled: {
    tone: "warn",
    title: "Claude Code에서 hook이 모두 꺼져 있어요",
    body: "Claude Code 설정의 disableAllHooks를 끈 뒤 다시 확인해 주세요.",
  },
  blocked_by_policy: {
    tone: "warn",
    title: "관리자 정책이 사용자 hook을 막고 있어요",
  },
  invalid: {
    tone: "error",
    title: "Claude Code 설정을 읽을 수 없어요",
  },
};

export function claudeChecks(
  claude: ClaudeIntegration,
  diagnostics: ProviderDiagnostic,
): Check[] {
  const install = claude.install || {};
  const monitor = diagnostics.turn_end_monitor || {};
  const installed = install.state === "installed";
  return [
    {
      label: "설치 감지",
      state: install.detected ? "ok" : "warn",
      value: install.detected ? "감지됨" : "찾지 못함",
    },
    {
      label: "관리 hook",
      state: installed
        ? "ok"
        : install.state === "not_installed"
          ? "off"
          : "warn",
      value: `${install.installed_events ?? 0}/${install.expected_events ?? 0}개 이벤트`,
    },
    {
      label: "최근 이벤트 수신",
      state: diagnostics.last_hook_received_at ? "ok" : "off",
      value: diagnostics.last_hook_received_at
        ? time(diagnostics.last_hook_received_at)
        : "이번 실행에서 아직 없음",
    },
    ...(claude.status_line
      ? [
          {
            label: "한도 수신",
            state: (claude.status_line.observed_at
              ? "ok"
              : claude.status_line.state === "installed"
                ? "off"
                : "warn") as CheckState,
            value: claude.status_line.observed_at
              ? `${time(claude.status_line.observed_at)} 관측`
              : claude.status_line.state === "installed"
                ? "터미널 Claude Code 응답 후 표시"
                : "연결 안 됨",
          },
        ]
      : []),
    {
      label: "거절·중단 감지",
      state: monitor.attached ? "ok" : "off",
      value: monitor.active_turns
        ? `작업 중 세션 ${monitor.active_turns}개 확인 중`
        : `대기 중 · 이번 실행 ${monitor.detected_count ?? 0}건 감지`,
    },
  ];
}

// Items the built-in Claude Code status line can show, with a sample.
export const STATUS_LINE_ITEMS: [string, string, string][] = [
  ["pet", "펫 연결(끊겼을 때만)", "펫 꺼짐"],
  ["ide", "IDE", "VS Code"],
  ["model", "모델·추론 강도", "Opus 5.5 high"],
  ["context", "컨텍스트", "컨텍스트 12% (24k/200k)"],
  ["five_hour", "5시간 한도", "5시간 41%"],
  ["seven_day", "7일 한도", "7일 55%"],
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
            <option value={-1}>숨김</option>
            <option value={0}>1줄</option>
            <option value={1}>2줄</option>
          </select>
          <button
            className="icon-button"
            aria-label={`${label(key)} 위로`}
            disabled={index === 0}
            onClick={() => move(index, -1)}
          >
            <ArrowUp size={14} />
          </button>
          <button
            className="icon-button"
            aria-label={`${label(key)} 아래로`}
            disabled={index === order.length - 1}
            onClick={() => move(index, 1)}
          >
            <ArrowDown size={14} />
          </button>
        </div>
      ))}
      <div className="setting-row">
        <label>색으로 강조</label>
        <Switch
          label="상태줄 색으로 강조"
          value={!!layout.color}
          change={(value) => commit(order, lineOf, { color: value })}
        />
      </div>
      <div className="setting-row">
        <label>5시간 한도 초기화 시각</label>
        <Switch
          label="5시간 한도 초기화 시각 표시"
          value={!!layout.reset_times}
          change={(value) => commit(order, lineOf, { reset_times: value })}
        />
      </div>
      <div className="status-line-preview" aria-label="상태줄 미리보기">
        {lines.some((line) => line.length) ? (
          lines
            .filter((line) => line.length)
            .map((line, index) => (
              <div key={index}>{line.map(sample).join(" · ")}</div>
            ))
        ) : (
          <div>표시할 항목이 없습니다.</div>
        )}
      </div>
    </div>
  );
}

export function TerminalHelp({ close }: { close: () => void }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(TERMINAL_KEYBINDING, null, 4);
  return (
    <Modal title="터미널에서 Claude Code 쓰기" close={close}>
      <p>
        Claude Code 한도와 상태줄은 터미널에서 실행한 Claude Code에서만
        갱신됩니다. VS Code 확장의 그래픽 패널은 상태줄을 실행하지 않으므로, VS
        Code에서는 내장 터미널에서 <code>claude</code>를 실행해 주세요.
      </p>
      <h3>VS Code 단축키로 열기</h3>
      <p>
        <code>%APPDATA%\Code\User\keybindings.json</code>에 아래 항목을 추가하면{" "}
        <code>Ctrl+Shift+&apos;</code>로 오른쪽 편집 그룹의 새 탭에 Claude
        Code가 열립니다. 앱은 VS Code 설정을 바꾸지 않습니다.
      </p>
      <pre className="code-block">{text}</pre>
      <button
        className="button compact"
        onClick={() =>
          navigator.clipboard.writeText(text).then(() => setCopied(true))
        }
      >
        {copied ? "복사했습니다" : "단축키 설정 복사"}
      </button>
      <ul className="help-notes">
        <li>
          터미널을 연 편집 그룹은 VS Code가 자동으로 잠그므로, 단축키가 잠금을
          풀고 새 탭을 연 뒤 다시 잠급니다.
        </li>
        <li>
          명령 앞부분은 Python 프로젝트의 가상 환경(venv)을 켭니다. Python
          프로젝트가 아니면 <code>claude</code>만 남겨도 됩니다.
        </li>
        <li>편집 그룹이 셋 이상이면 두 번째 그룹에 열립니다.</li>
      </ul>
      <h3>자주 쓰는 Claude Code 명령</h3>
      <ul className="help-notes">
        <li>
          <code>/context</code> 컨텍스트 사용량, <code>/usage</code> 한도
        </li>
        <li>
          <code>/clear</code> 새 대화, <code>/compact</code> 요약 후 계속,{" "}
          <code>/resume</code> 이전 대화
        </li>
        <li>
          <code>/rename</code> 세션 이름(입력창 위 가로줄에 보입니다)
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
          <h4 className="check-heading">연결 점검</h4>
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
        <label>{name} 사용</label>
        <p className="field-description">
          {value
            ? `끄면 이 앱의 hook을 지우고 ${name} 파일을 더 읽지 않으며, 홈·사용량·기록·트레이·위젯에서 숨깁니다. 저장된 기록은 남습니다.`
            : `켜면 ${name} 사용자 설정에 이 앱의 hook만 추가하고 작업 상태와 사용량을 보여 줍니다.`}{" "}
          적용 전에 바뀌는 내용을 먼저 보여 줍니다.
        </p>
      </div>
      <Switch
        label={`${name} 사용`}
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
              이 PC에서 {name}을(를) 찾지 못했습니다. 설치한 뒤 켜도 되고, 미리
              켜 둘 수도 있습니다.
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
            {value}분
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
              <label>Claude Code 한도 가져오기</label>
              <span
                className="info-tip"
                role="note"
                aria-label="한도 가져오기 안내"
                title={[
                  "터미널(CLI·VS Code 터미널 모드)에서만 갱신되고, VS Code 그래픽 패널에서는 갱신되지 않습니다.",
                  "쓰던 status line은 그대로 보여 주고, 없으면 짧은 한도 문구를 보여 줍니다.",
                  'Claude Code를 쓰는 동안에만 값이 들어와, 15분 넘게 새 값이 없으면 위젯에 회색과 "n분 전"으로 표시합니다. Codex는 5분마다 다시 확인해 회색이 되지 않습니다.',
                ].join("\n")}
              >
                <Info size={13} />
              </span>
            </div>
            <p className="field-description">
              Claude Code 하단 status line으로 5시간·7일 한도를 받습니다. (
              <button className="text-button inline" onClick={openHelp}>
                터미널에서 쓰는 방법
              </button>
              )
            </p>
          </div>
          <Switch
            label="Claude Code 한도 가져오기"
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
        <summary>세부 설정</summary>
        {minutes(
          "claude_code_work_minutes",
          "작업 중 표시 유지",
          WORK_MINUTES,
          claude.work_minutes,
          "이 시간 동안 Claude Code 신호가 없으면 작업 중 표시를 풉니다. 도구 실행 중에는 확인 대기 시간을 씁니다.",
        )}
        {minutes(
          "claude_code_waiting_minutes",
          "확인 대기 표시 유지",
          WAITING_MINUTES,
          claude.waiting_minutes,
          "이 시간 동안 신호가 없으면 권한 요청·백그라운드 대기·도구 실행 중 표시를 풉니다. 거절·중단은 바로 감지합니다.",
        )}
        {statusLine && statusLineOn && statusLine.layout && (
          <div className="status-line-block">
            <h4 className="check-heading">상태줄 항목</h4>
            {statusLine.has_original && (
              <p className="footnote">
                쓰던 status line이 있어 그 출력을 그대로 보여 줍니다. 아래
                항목은 쓰던 status line이 없을 때 표시하는 기본 상태줄에
                적용됩니다.
              </p>
            )}
            <StatusLineEditor layout={statusLine.layout} save={saveLayout} />
          </div>
        )}
      </details>
    </ProviderBlock>
  );
}
