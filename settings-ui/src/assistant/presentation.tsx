import { CircleCheck, CircleMinus, CircleX, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { DiagnosticValues } from "../types";
import type { CheckState } from "./Connections";

export const PAGE_SIZE = 100;

// Agent sources get the same colored dot as the bubbles, widget and caption.
export const SOURCE_CLASSES: Record<string, string> = {
  Codex: "source-codex",
  "Claude Code": "source-claude-code",
};

export function SourceTag({ name }: { name: string }) {
  const kind = SOURCE_CLASSES[name];
  return (
    <span className={kind ? `source-tag ${kind}` : "source-tag"}>{name}</span>
  );
}

export const ACTIVITY_PAGE = 50;

// Remaining-quota tones; the card color carries meaning instead of order.
export const QUOTA_LOW = 30;

export const QUOTA_CRITICAL = 10;

export const number = (value: unknown) =>
  typeof value === "number"
    ? new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(value)
    : "확인 불가";

export const time = (value: string | number | null | undefined) =>
  value
    ? new Date(value).toLocaleString("ko-KR", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "확인 불가";

export const clock = (value: string | number | null | undefined) =>
  new Date(value!).toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
  });

// start_date is a calendar date; parse it without a UTC shift.
export const shortDate = (value: string) => {
  const [, month, day] = String(value).split("-").map(Number);
  return month && day ? `${month}/${day}` : String(value);
};

export const dayLabel = (value: string | number | null | undefined) => {
  const date = new Date(value!);
  const startOf = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(new Date()) - startOf(date)) / 86400000);
  if (days === 0) return "오늘";
  if (days === 1) return "어제";
  return date.toLocaleDateString("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
  });
};

// Same as the widget (usage/widget_state.py STALE_MINUTES).
export const STALE_MS = 15 * 60 * 1000;

export const isStale = (value: string | number | null | undefined) =>
  !!value && Date.now() - new Date(value!).getTime() > STALE_MS;

export const quotaTone = (remaining: unknown): [string, string] =>
  typeof remaining !== "number"
    ? ["unknown", "확인 불가"]
    : remaining >= QUOTA_LOW
      ? ["ok", "여유"]
      : remaining >= QUOTA_CRITICAL
        ? ["low", "주의"]
        : ["critical", "부족"];

export const outcomeLabels: Record<string, string> = {
  done: "완료",
  completed: "완료",
  failed: "실패",
  aborted: "중단",
  cancelled: "중단",
  running: "진행 중",
};

export const qualityLabels: Record<string, string> = {
  estimated: "측정됨",
  measured: "측정됨",
  partial: "부분 측정",
  unavailable: "측정 불가",
};

export const detailLabels: Record<string, string> = {
  completed_at: "완료 시각",
  outcome: "결과",
  input_tokens: "입력 토큰",
  net_new_input_tokens: "새 입력 토큰",
  cached_input_tokens: "캐시 입력 토큰",
  output_tokens: "출력 토큰",
  total_tokens: "전체 토큰",
  estimated_credits_micros: "예상 크레딧",
  estimated_usd_micros: "예상 비용",
  model: "모델",
  reasoning_effort: "추론 수준",
  speed: "속도",
  data_quality: "관측 품질",
  quality_reason: "품질 설명",
  account_plan: "계정 플랜",
  limit_name: "한도 이름",
  plan_type: "플랜",
  reached_type: "도달한 한도",
  individual_limit: "개별 한도",
  individual_used: "개별 사용량",
  individual_remaining_percent: "개별 남은 비율",
  individual_resets_at: "개별 초기화 시각",
  lifetime_tokens: "계정 누적 토큰",
  peak_daily_tokens: "최대 일일 토큰",
  longest_running_turn_sec: "최장 작업 시간",
  current_streak_days: "현재 연속 활동일",
  longest_streak_days: "최장 연속 활동일",
  credit_balance: "크레딧 잔액",
  unlimited_credits: "무제한 크레딧",
  has_credits: "크레딧 사용",
  spend_control_reached: "지출 한도 도달",
};

export const precise = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 4,
});

export function formatDetail(key: string, value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? "예" : "아니요";
  if (key === "estimated_credits_micros")
    return `${precise.format(Number(value) / 1e6)} 크레딧`;
  if (key === "estimated_usd_micros")
    return `$${precise.format(Number(value) / 1e6)}`;
  if (key.endsWith("_at")) return time(value as string | number);
  if (key === "outcome") return outcomeLabels[String(value)] || String(value);
  if (key === "data_quality")
    return qualityLabels[String(value)] || String(value);
  if (key.endsWith("_percent")) return `${number(value)}%`;
  if (key.endsWith("_sec")) return `${number(value)}초`;
  if (key.endsWith("_days")) return `${number(value)}일`;
  return typeof value === "number" ? number(value) : String(value);
}

// Only labelled, known values are shown; raw keys and hashes stay hidden.
export function Details({ value }: { value: DiagnosticValues }) {
  const rows = Object.entries(value)
    .filter(([key]) => detailLabels[key])
    .map(([key, v]) => [key, formatDetail(key, v)] as const)
    .filter(([, text]) => text !== null);
  if (!rows.length) return <p className="footnote">표시할 정보가 없습니다.</p>;
  return (
    <dl className="detail-list">
      {rows.map(([key, text]) => (
        <div key={key}>
          <dt>{detailLabels[key]}</dt>
          <dd>{text}</dd>
        </div>
      ))}
    </dl>
  );
}

export function TabList({
  id,
  label,
  tabs,
  value,
  select,
}: {
  id: string;
  label: string;
  tabs: [string, string][];
  value: string;
  select: (key: string) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = tabs.findIndex(([key]) => key === value);
  return (
    <div
      className="tabs"
      role="tablist"
      aria-label={label}
      onKeyDown={(event) => {
        const target = {
          ArrowRight: index + 1,
          ArrowLeft: index - 1,
          Home: 0,
          End: tabs.length - 1,
        }[event.key];
        if (target === undefined) return;
        event.preventDefault();
        const next = (target + tabs.length) % tabs.length;
        select(tabs[next][0]);
        refs.current[next]?.focus();
      }}
    >
      {tabs.map(([key, text], i) => (
        <button
          key={key}
          ref={(element) => {
            refs.current[i] = element;
          }}
          id={`${id}-tab-${key}`}
          role="tab"
          aria-selected={value === key}
          aria-controls={`${id}-panel`}
          tabIndex={value === key ? 0 : -1}
          onClick={() => select(key)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function Segmented({
  label,
  options,
  value,
  select,
}: {
  label: string;
  options: [string, string][];
  value: string;
  select: (key: string) => void;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([key, text]) => (
        <button
          key={key}
          aria-pressed={value === key}
          onClick={() => select(key)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function Pager({
  offset,
  hasMore,
  go,
  label,
}: {
  offset: number;
  hasMore: boolean;
  go: (offset: number) => void;
  label: string;
}) {
  if (!offset && !hasMore) return null;
  return (
    <div className="pagination" role="group" aria-label={`${label} 페이지`}>
      <span>{offset + 1}번째부터</span>
      <button
        className="button compact"
        disabled={!offset}
        onClick={() => go(Math.max(0, offset - PAGE_SIZE))}
      >
        이전 {PAGE_SIZE}건
      </button>
      <button
        className="button compact"
        disabled={!hasMore}
        onClick={() => go(offset + PAGE_SIZE)}
      >
        다음 {PAGE_SIZE}건
      </button>
    </div>
  );
}

// Saves only once focus leaves both fields, so typing "15" never sends "1"
// and moving between the two inputs never validates a half-edited range.
export function HourRange({
  hours,
  disabled,
  save,
}: {
  hours: [number, number];
  disabled?: boolean;
  save: (value: [number, number]) => void;
}) {
  const [draft, setDraft] = useState([String(hours[0]), String(hours[1])]);
  const [message, setMessage] = useState("");
  const editing = useRef(false);
  useEffect(() => {
    if (!editing.current) setDraft([String(hours[0]), String(hours[1])]);
  }, [hours[0], hours[1]]);
  const commit = () => {
    editing.current = false;
    const [start, end] = draft.map(Number);
    const valid =
      draft.every((text) => /^\d+$/.test(text.trim())) &&
      start >= 0 &&
      start <= 23 &&
      end >= 1 &&
      end <= 24 &&
      start < end;
    if (!valid) {
      setMessage(
        "시작은 0~23시, 종료는 1~24시이며 시작이 종료보다 빨라야 합니다.",
      );
      setDraft([String(hours[0]), String(hours[1])]);
      return;
    }
    setMessage("");
    if (start !== hours[0] || end !== hours[1]) save([start, end]);
  };
  const input = (index: number, label: string, min: number, max: number) => (
    <input
      aria-label={label}
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      disabled={disabled}
      value={draft[index]}
      onFocus={() => (editing.current = true)}
      onChange={(event) =>
        setDraft((value) =>
          value.map((item, i) => (i === index ? event.target.value : item)),
        )
      }
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
    />
  );
  return (
    <div className={`setting-row hour-range ${disabled ? "is-disabled" : ""}`}>
      <div className="field-label">
        <label>표시할 시간대</label>
        {message ? (
          <p className="field-description danger" role="alert">
            {message}
          </p>
        ) : (
          <p className="field-description">
            오늘 흐름 그래프에 표시할 하루 중 시간대입니다.
          </p>
        )}
      </div>
      <div
        className="hour-inputs"
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node))
            commit();
        }}
      >
        {input(0, "위젯 시작 시각", 0, 23)}
        <span>시부터</span>
        {input(1, "위젯 종료 시각", 1, 24)}
        <span>시까지</span>
      </div>
    </div>
  );
}

export const checkIcons: Record<CheckState, ReactNode> = {
  ok: <CircleCheck size={16} />,
  warn: <TriangleAlert size={16} />,
  off: <CircleMinus size={16} />,
  error: <CircleX size={16} />,
};

export const WORK_MINUTES = [3, 5, 10, 15, 20, 30, 60, 120];

export const WAITING_MINUTES = [10, 15, 30, 60, 120, 240];

export const minuteOptions = (choices: number[], current: number) =>
  [...new Set([...choices, current])].sort((a, b) => a - b);

export const TERMINAL_KEYBINDING = {
  key: "ctrl+shift+'",
  command: "runCommands",
  args: {
    commands: [
      "workbench.action.focusSecondEditorGroup",
      "workbench.action.unlockEditorGroup",
      {
        command: "workbench.action.terminal.new",
        args: {
          config: {
            executable: "powershell.exe",
            args: [
              "-NoLogo",
              "-Command",
              "if ($env:VSCODE_PYTHON_PWSH_ACTIVATE) { Invoke-Expression $env:VSCODE_PYTHON_PWSH_ACTIVATE }; claude",
            ],
            name: "Claude Code",
          },
          location: { viewColumn: -1 },
        },
      },
      "workbench.action.lockEditorGroup",
    ],
  },
};

export type Confirmation = {
  title: string;
  body: string;
  label: string;
  run: () => void;
};

export function HomeLink({ label, open }: { label: string; open: () => void }) {
  return (
    <div className="section-footer">
      <button className="text-button" onClick={open}>
        {label}
      </button>
    </div>
  );
}
