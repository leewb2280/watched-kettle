import { t, locale } from "../../localization.cjs";
import { LocalizedText } from "../LocalizedText";
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

// Notice center filters, in chip order; Python sends the same stable IDs.
export const ACTIVITY_GROUPS: Record<string, string> = {
  notice: "activity.group.notice",
  attention: "activity.group.attention",
  progress: "activity.group.progress",
  completion: "activity.group.completion",
};

// Remaining-quota tones; the card color carries meaning instead of order.
export const QUOTA_LOW = 30;

export const QUOTA_CRITICAL = 10;

export const number = (value: unknown) =>
  typeof value === "number"
    ? new Intl.NumberFormat(locale(), { maximumFractionDigits: 1 }).format(
        value,
      )
    : t("message.0336");

export const time = (value: string | number | null | undefined) =>
  value
    ? new Date(value).toLocaleString(locale(), {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : t("message.0336");

export const clock = (value: string | number | null | undefined) =>
  new Date(value!).toLocaleTimeString(locale(), {
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
  if (days === 0) return t("message.0846");
  if (days === 1) return t("message.0847");
  return date.toLocaleDateString(locale(), {
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
    ? ["unknown", t("message.0336")]
    : remaining >= QUOTA_LOW
      ? ["ok", t("message.0848")]
      : remaining >= QUOTA_CRITICAL
        ? ["low", t("message.0849")]
        : ["critical", t("message.0850")];

export const outcomeLabels: Record<string, string> = {
  done: t("message.0319"),
  completed: t("message.0319"),
  failed: t("message.0284"),
  aborted: t("message.0320"),
  cancelled: t("message.0320"),
  running: t("message.0445"),
};

export const qualityLabels: Record<string, string> = {
  estimated: t("message.0357"),
  measured: t("message.0357"),
  partial: t("message.0356"),
  unavailable: t("message.0359"),
};

export const detailLabels: Record<string, string> = {
  completed_at: t("message.0851"),
  outcome: t("message.0852"),
  input_tokens: t("message.0853"),
  net_new_input_tokens: t("message.0854"),
  cached_input_tokens: t("message.0855"),
  output_tokens: t("message.0856"),
  total_tokens: t("message.0857"),
  estimated_credits_micros: t("message.0858"),
  estimated_usd_micros: t("message.0859"),
  model: t("message.0860"),
  reasoning_effort: t("message.0861"),
  speed: t("message.0862"),
  data_quality: t("message.0863"),
  quality_reason: t("message.0864"),
  account_plan: t("message.0865"),
  limit_name: t("message.0866"),
  plan_type: t("message.0867"),
  reached_type: t("message.0868"),
  individual_limit: t("message.0869"),
  individual_used: t("message.0870"),
  individual_remaining_percent: t("message.0871"),
  individual_resets_at: t("message.0872"),
  lifetime_tokens: t("message.0873"),
  peak_daily_tokens: t("message.0874"),
  longest_running_turn_sec: t("message.0875"),
  current_streak_days: t("message.0876"),
  longest_streak_days: t("message.0877"),
  credit_balance: t("message.0878"),
  unlimited_credits: t("message.0879"),
  has_credits: t("message.0880"),
  spend_control_reached: t("message.0881"),
};

export const precise = new Intl.NumberFormat(locale(), {
  maximumFractionDigits: 4,
});

export function formatDetail(key: string, value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean")
    return value ? t("message.0882") : t("message.0883");
  if (key === "estimated_credits_micros")
    return t("message.0884", {
      count: Number(value) / 1e6,
      value0: precise.format(Number(value) / 1e6),
    });
  if (key === "estimated_usd_micros")
    return `$${precise.format(Number(value) / 1e6)}`;
  if (key.endsWith("_at")) return time(value as string | number);
  if (key === "outcome") return outcomeLabels[String(value)] || String(value);
  if (key === "data_quality")
    return qualityLabels[String(value)] || String(value);
  if (key.endsWith("_percent")) return `${number(value)}%`;
  if (key.endsWith("_sec")) return t("message.0885", { value0: number(value) });
  if (key.endsWith("_days"))
    return t("message.0425", { value0: number(value) });
  return typeof value === "number" ? number(value) : String(value);
}

// Only labelled, known values are shown; raw keys and hashes stay hidden.
export function Details({ value }: { value: DiagnosticValues }) {
  const rows = Object.entries(value)
    .filter(([key]) => detailLabels[key])
    .map(([key, v]) => [key, formatDetail(key, v)] as const)
    .filter(([, text]) => text !== null);
  if (!rows.length) return <p className="footnote">{t("message.0886")}</p>;
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
    <div
      className="pagination"
      role="group"
      aria-label={t("message.0887", { value0: label })}
    >
      <span>{t("usage.from", { count: offset + 1 })}</span>
      <button
        className="button compact"
        disabled={!offset}
        onClick={() => go(Math.max(0, offset - PAGE_SIZE))}
      >
        {t("usage.previous_page", { count: PAGE_SIZE })}
      </button>
      <button
        className="button compact"
        disabled={!hasMore}
        onClick={() => go(offset + PAGE_SIZE)}
      >
        {t("usage.next_page", { count: PAGE_SIZE })}
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
      setMessage(t("message.0891"));
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
        <label>{t("message.0892")}</label>
        {message ? (
          <p className="field-description danger" role="alert">
            {message}
          </p>
        ) : (
          <p className="field-description">{t("message.0893")}</p>
        )}
      </div>
      <div
        className="hour-inputs"
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node))
            commit();
        }}
      >
        <LocalizedText
          id="usage.hour_range"
          values={{
            start: input(0, t("message.0894"), 0, 23),
            end: input(1, t("message.0896"), 1, 24),
          }}
        />
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
