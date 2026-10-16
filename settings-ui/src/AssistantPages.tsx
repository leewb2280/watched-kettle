import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleMinus,
  CircleX,
  Download,
  Ellipsis,
  Info,
  RotateCcw,
  Search,
  TriangleAlert,
} from "lucide-react";
import type { CommandOptions, Page, Shell, Values } from "./types";
import {
  Confirm,
  Empty,
  Fields,
  Heading,
  Modal,
  Section,
  Switch,
} from "./components";
import { errorText } from "./errors";
import { BarLineChart, RemainingChart, tokens, type Bar } from "./TrendChart";

const PAGE_SIZE = 100;
// Agent sources get the same colored dot as the bubbles, widget and caption.
const SOURCE_CLASSES: Record<string, string> = {
  Codex: "source-codex",
  "Claude Code": "source-claude-code",
};

function SourceTag({ name }: { name: string }) {
  const kind = SOURCE_CLASSES[name];
  return (
    <span className={kind ? `source-tag ${kind}` : "source-tag"}>{name}</span>
  );
}
const ACTIVITY_PAGE = 50;
// Remaining-quota tones; the card color carries meaning instead of order.
const QUOTA_LOW = 30;
const QUOTA_CRITICAL = 10;

const number = (value: any) =>
  typeof value === "number"
    ? new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(value)
    : "확인 불가";
const time = (value: any) =>
  value
    ? new Date(value).toLocaleString("ko-KR", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "확인 불가";
const clock = (value: any) =>
  new Date(value).toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
  });
// start_date is a calendar date; parse it without a UTC shift.
const shortDate = (value: string) => {
  const [, month, day] = String(value).split("-").map(Number);
  return month && day ? `${month}/${day}` : String(value);
};
const dayLabel = (value: any) => {
  const date = new Date(value);
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
const STALE_MS = 15 * 60 * 1000;
const isStale = (value: any) =>
  !!value && Date.now() - new Date(value).getTime() > STALE_MS;
const quotaTone = (remaining: any): [string, string] =>
  typeof remaining !== "number"
    ? ["unknown", "확인 불가"]
    : remaining >= QUOTA_LOW
      ? ["ok", "여유"]
      : remaining >= QUOTA_CRITICAL
        ? ["low", "주의"]
        : ["critical", "부족"];

const outcomeLabels: Record<string, string> = {
  done: "완료",
  completed: "완료",
  failed: "실패",
  aborted: "중단",
  cancelled: "중단",
  running: "진행 중",
};
const qualityLabels: Record<string, string> = {
  estimated: "측정됨",
  measured: "측정됨",
  partial: "부분 측정",
  unavailable: "측정 불가",
};
const detailLabels: Record<string, string> = {
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
const precise = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 4 });
function formatDetail(key: string, value: any): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? "예" : "아니요";
  if (key === "estimated_credits_micros")
    return `${precise.format(value / 1e6)} 크레딧`;
  if (key === "estimated_usd_micros") return `$${precise.format(value / 1e6)}`;
  if (key.endsWith("_at")) return time(value);
  if (key === "outcome") return outcomeLabels[value] || String(value);
  if (key === "data_quality") return qualityLabels[value] || String(value);
  if (key.endsWith("_percent")) return `${number(value)}%`;
  if (key.endsWith("_sec")) return `${number(value)}초`;
  if (key.endsWith("_days")) return `${number(value)}일`;
  return typeof value === "number" ? number(value) : String(value);
}
// Only labelled, known values are shown; raw keys and hashes stay hidden.
function Details({ value }: { value: Values }) {
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
const TREND_SOURCES: [string, string][] = [
  ["codex", "Codex"],
  ["claude_code", "Claude Code"],
];
const TREND_COLORS: Record<string, string> = {
  codex: "var(--chart-codex)",
  claude_code: "var(--chart-claude-code)",
};
const versus = (value: number | null | undefined) =>
  value == null
    ? "—"
    : value === 0
      ? "평소와 같음"
      : `평소보다 ${Math.abs(value)}% ${value > 0 ? "많음" : "적음"}`;
const percent = (value: number | null | undefined, unit = "%") =>
  value == null ? "—" : `${number(value)}${unit}`;
// Calendar dates (YYYY-MM-DD) without a UTC shift.
const calendar = (value: string) => {
  const [year, month, day] = String(value).split("-").map(Number);
  return new Date(year, month - 1, day);
};
const longDate = (value: string) =>
  calendar(value).toLocaleDateString("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
  });
const localToday = () => {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

function TrendStats({ items }: { items: [string, string][] }) {
  return (
    <dl className="trend-stats">
      {items.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Trends({
  usage,
  chart,
  setChart,
  provider,
  setProvider,
  span,
  setSpan,
  setDays,
}: {
  usage: Values;
  chart: string;
  setChart: (value: string) => void;
  provider: string;
  setProvider: (value: string) => void;
  span: string;
  setSpan: (value: string) => void;
  setDays: (value: number) => void;
}) {
  const trends: Values = usage.trends || {};
  const chartDays = usage.controls.find(
    (control: Values) => control.key === "chart_days",
  );
  // A switched-off tool is left out; with both off the page says so.
  const sources = TREND_SOURCES.filter(([key]) =>
    key === "codex" ? usage.enabled : usage.claude_code_enabled,
  );
  if (!sources.length) return null;
  // Start on a tool with data; the choice stays separate from the history tab.
  const source = sources.some(([key]) => key === provider)
    ? provider
    : (sources.find(([key]) => trends[key]?.enabled) || sources[0])[0];
  const name = source === "codex" ? "Codex" : "Claude Code";
  const color = TREND_COLORS[source];
  const data: Values = trends[source] || {};
  const nowHour = Number(trends.now_hour ?? new Date().getHours());
  let stats: [string, string][] = [];
  const notes: string[] = [];
  let body: ReactNode = null;
  if (!data.enabled) {
    body = (
      <Empty>
        {source === "claude_code" && usage.claude_code_enabled
          ? "Claude Code 기록을 아직 읽지 못했습니다."
          : `${name} 사용량이 꺼져 있습니다. 위의 스위치로 켤 수 있습니다.`}
      </Empty>
    );
  } else if (chart === "tokens") {
    const hours: Values | null = data.hours;
    const average: (number | null)[] | null = hours?.average ?? null;
    if (!hours || (hours.total == null && !average)) {
      body = <Empty>오늘 관측한 토큰이 아직 없습니다.</Empty>;
    } else {
      stats = [
        ["오늘 합계", tokens(hours.total)],
        ["평소 대비", versus(hours.versus_average)],
        [
          "가장 많이 쓴 시간",
          hours.peak_hour == null ? "—" : `${hours.peak_hour}시`,
        ],
      ];
      const bars: Bar[] = (hours.hours as (number | null)[]).map(
        (value, hour) => ({
          label: `${hour}시`,
          title: `${hour}시${hour === nowHour ? "(지금)" : ""}`,
          value,
          line: average?.[hour] ?? null,
          current: hour === nowHour,
          future: hour > nowHour,
          tick: hour % 6 === 0,
        }),
      );
      body = (
        <BarLineChart
          bars={bars}
          color={color}
          reference="area"
          referenceName={`평소(${hours.average_days}일 평균)`}
          label={`${name} 오늘 시간대별 토큰. 합계 ${tokens(hours.total)}, ${versus(hours.versus_average)}.`}
          describe={(bar) => [
            bar.title,
            bar.value == null ? "관측 없음" : tokens(bar.value),
            ...(bar.line == null ? [] : [`평소 ${tokens(bar.line)}`]),
          ]}
        />
      );
      notes.push(
        (average
          ? `회색 면은 지난 7일 중 기록이 있는 ${hours.average_days}일의 같은 시간 평균이고, 평소 대비는 지금 시간까지 비교합니다. `
          : `평균을 낼 기록이 ${hours.average_days}일뿐입니다. 3일이 쌓이면 평소 모양을 그립니다. `) +
          (source === "codex"
            ? "이 PC의 Codex 로그 기준이며, 관측하지 못한 시간은 바닥에 옅게 표시합니다."
            : "이 PC의 Claude Code 대화 기록 기준이며, 끝난 턴의 토큰을 끝난 시간에 셉니다."),
      );
    }
  } else if (chart === "quota") {
    const series: Values | undefined = data.quota?.[span];
    const spanName = span === "five_hour" ? "5시간" : "7일";
    const day = new Date();
    day.setHours(0, 0, 0, 0);
    // A line computed before midnight belongs to yesterday until the next refresh.
    const points: [string, number][] = (series?.points || []).filter(
      ([at]: [string, number]) => new Date(at).getTime() >= day.getTime(),
    );
    if (!points.length) {
      body = (
        <Empty>
          오늘 관측한 {name} {spanName} 한도 값이 없습니다.
        </Empty>
      );
    } else {
      stats = [
        ["지금 남은 한도", percent(series!.now_remaining)],
        ["오늘 줄어든 한도", percent(series!.spent, "%p")],
        ["초기화", `${series!.resets.length}회`],
      ];
      body = (
        <RemainingChart
          points={points}
          resets={series!.resets}
          day={day}
          now={new Date()}
          color={color}
          label={`${name} ${spanName} 한도의 오늘 남은 비율. 지금 ${percent(series!.now_remaining)}, 오늘 ${percent(series!.spent, "%p")} 줄어듦.`}
        />
      );
    }
    notes.push(
      "세로 점선은 한도 초기화 시점이고, 옅은 선은 마지막 관측 뒤 지금까지입니다.",
    );
    notes.push(
      source === "codex"
        ? "Codex 기본 한도의 남은 비율입니다. 위젯에서 크게 보여 줄 한도와는 따로 고릅니다."
        : "터미널에서 Claude Code를 쓸 때만 관측해 빈 시간이 있을 수 있습니다.",
    );
  } else {
    const daily: Values = data.daily || {};
    const days: Values[] = daily.days || [];
    if (!days.length || daily.total == null) {
      body = <Empty>일별 기록이 아직 없습니다.</Empty>;
    } else {
      stats = [
        [`최근 ${days.length}일 합계`, tokens(daily.total)],
        ["하루 평균", tokens(daily.average)],
        ["가장 많이 쓴 날", daily.peak_date ? shortDate(daily.peak_date) : "—"],
      ];
      const today = localToday();
      const step = Math.ceil(days.length / 6);
      const bars: Bar[] = days.map((row, index) => ({
        label: shortDate(row.date),
        title: `${longDate(row.date)}${row.date === today ? "(오늘)" : ""}`,
        value: row.tokens,
        line: row.average,
        current: row.date === today,
        tick: (days.length - 1 - index) % step === 0,
      }));
      body = (
        <BarLineChart
          bars={bars}
          color={color}
          reference="line"
          referenceName="7일 이동 평균"
          label={`${name} 최근 ${days.length}일 일별 토큰. 합계 ${tokens(daily.total)}, 하루 평균 ${tokens(daily.average)}.`}
          describe={(bar) => [
            bar.title,
            bar.value == null ? "기록 없음" : tokens(bar.value),
            ...(bar.line == null ? [] : [`7일 평균 ${tokens(bar.line)}`]),
          ]}
        />
      );
    }
    notes.push(
      (source === "codex"
        ? "서버가 제공한 계정 전체(다른 PC 포함)의 일별 토큰입니다. "
        : "이 PC의 Claude Code 대화 기록 기준이며, 다른 PC의 사용량은 들어가지 않습니다. ") +
        "선은 7일 이동 평균입니다(7일 중 4일 이상 기록이 있을 때).",
    );
  }
  return (
    <section className="section">
      <div className="section-heading">
        <h2>추이</h2>
        {sources.length > 1 && (
          <Segmented
            label="추이 도구"
            options={sources}
            value={source}
            select={setProvider}
          />
        )}
      </div>
      <div className="card trend-card">
        <div className="trend-toolbar">
          <Segmented
            label="추이 그래프 종류"
            options={[
              ["tokens", "오늘 토큰"],
              ["quota", "오늘 한도"],
              ["daily", "일별 토큰"],
            ]}
            value={chart}
            select={setChart}
          />
          {chart === "quota" && (
            <Segmented
              label="한도 기간"
              options={[
                ["five_hour", "5시간"],
                ["seven_day", "7일"],
              ]}
              value={span}
              select={setSpan}
            />
          )}
          {chart === "daily" && chartDays && (
            <select
              aria-label={chartDays.label}
              value={String(chartDays.value)}
              onChange={(event) => setDays(Number(event.target.value))}
            >
              {chartDays.options.map((option: Values) => (
                <option key={option.value} value={String(option.value)}>
                  최근 {option.label}
                </option>
              ))}
            </select>
          )}
        </div>
        {data.enabled && stats.length > 0 && <TrendStats items={stats} />}
        {body}
        {data.enabled &&
          notes.map((note) => (
            <p className="footnote" key={note}>
              {note}
            </p>
          ))}
      </div>
    </section>
  );
}
function TabList({
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
function Segmented({
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
function Pager({
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
function HourRange({
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
type CheckState = "ok" | "warn" | "off" | "error";
const checkIcons: Record<CheckState, ReactNode> = {
  ok: <CircleCheck size={16} />,
  warn: <TriangleAlert size={16} />,
  off: <CircleMinus size={16} />,
  error: <CircleX size={16} />,
};
type Check = { label: string; state: CheckState; value: string };
function CheckList({ checks }: { checks: Check[] }) {
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
function integrationChecks(diagnostics: Values, install: Values): Check[] {
  const trust = diagnostics.global_hook_trust || {};
  const jsonl = diagnostics.jsonl_monitor || {};
  const installed = install.state === "installed";
  const trustMissing =
    trust.valid && trust.approved_count < trust.expected_count;
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
function appChecks(diagnostics: Values, storage: Values): Check[] {
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
const heroes: Record<
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
function heroFor(integration: Values) {
  const install = integration.install || {};
  const trust = integration.diagnostics.global_hook_trust || {};
  if (
    install.state === "installed" &&
    trust.valid &&
    (trust.possibly_stale || trust.approved_count < trust.expected_count)
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
const claudeHeroes: Record<
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
const WORK_MINUTES = [3, 5, 10, 15, 20, 30, 60, 120];
const WAITING_MINUTES = [10, 15, 30, 60, 120, 240];
const minuteOptions = (choices: number[], current: number) =>
  [...new Set([...choices, current])].sort((a, b) => a - b);
function claudeChecks(claude: Values, diagnostics: Values): Check[] {
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
const STATUS_LINE_ITEMS: [string, string, string][] = [
  ["pet", "펫 연결(끊겼을 때만)", "펫 꺼짐"],
  ["ide", "IDE", "VS Code"],
  ["model", "모델·추론 강도", "Opus 5.5 high"],
  ["context", "컨텍스트", "컨텍스트 12% (24k/200k)"],
  ["five_hour", "5시간 한도", "5시간 41%"],
  ["seven_day", "7일 한도", "7일 55%"],
];
function StatusLineEditor({
  layout,
  save,
}: {
  layout: Values;
  save: (layout: Values) => void;
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
    flags: Values = {},
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
const TERMINAL_KEYBINDING = {
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
function TerminalHelp({ close }: { close: () => void }) {
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
type Hero = {
  tone: string;
  title: string;
  body?: string;
  action?: [string, string];
};
function StatusHero({
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
function ProviderBlock({
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
function ToolSwitchRow({
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
function ToolOffSection({
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
function CodexSection({
  integration,
  hero,
  preview,
}: {
  integration: Values;
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
function ClaudeCodeSection({
  claude,
  diagnostics,
  preview,
  previewStatusLine,
  setMinutes,
  saveLayout,
  openHelp,
}: {
  claude: Values;
  diagnostics: Values;
  preview: (operation: string) => void;
  previewStatusLine: (operation: string) => void;
  setMinutes: (key: string, value: number) => void;
  saveLayout: (layout: Values) => void;
  openHelp: () => void;
}) {
  const statusLine = claude.status_line;
  const statusLineOn = ["installed", "drifted"].includes(statusLine?.state);
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
          "이 시간 동안 Claude Code 신호가 없으면 작업 중 표시를 풉니다.",
        )}
        {minutes(
          "claude_code_waiting_minutes",
          "확인 대기 표시 유지",
          WAITING_MINUTES,
          claude.waiting_minutes,
          "이 시간 동안 신호가 없으면 확인 대기 표시를 풉니다. 거절·중단은 바로 감지합니다.",
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
type Confirmation = {
  title: string;
  body: string;
  label: string;
  run: () => void;
};

function QuotaGroups({
  usage,
  compact = false,
}: {
  usage: Values;
  compact?: boolean;
}) {
  return (
    <div className="quota-groups">
      {!(usage.limit_groups || []).length && (
        <p className="quiet-row">두 도구의 사용량이 꺼져 있습니다.</p>
      )}
      {(usage.limit_groups || []).map((group: Values) => (
        <section
          className="quota-provider"
          data-provider={group.key}
          key={group.key}
        >
          <h3>{group.label}</h3>
          {group.limits.length ? (
            <div className={compact ? "" : "quota-grid"}>
              {group.limits.map((limit: Values) => {
                const remaining = limit.window.remaining_percent;
                const [tone, quotaLabel] = quotaTone(remaining);
                // Past its reset with no new sample (claude_code_limits.bucket).
                const estimated = !!limit.window.estimated;
                const toneLabel = estimated ? "추정" : quotaLabel;
                return (
                  <article
                    className={
                      compact
                        ? `home-limit tone-${tone}`
                        : `quota-card card tone-${tone}`
                    }
                    key={limit.key}
                  >
                    {compact ? (
                      <>
                        <span>{limit.label}</span>
                        <strong>
                          {number(remaining)}
                          {typeof remaining === "number" && "%"}
                        </strong>
                        <span className="pill">{toneLabel}</span>
                      </>
                    ) : (
                      <>
                        <div className="quota-heading">
                          <span>{limit.label}</span>
                          <span className="pill">{toneLabel}</span>
                        </div>
                        <div className="quota-value">
                          {number(remaining)}
                          {typeof remaining === "number" && <span>%</span>}
                          <small>남음</small>
                        </div>
                      </>
                    )}
                    <div className="meter">
                      <i
                        style={{
                          width: `${Math.max(0, Math.min(100, remaining || 0))}%`,
                        }}
                      />
                    </div>
                    {!compact && (
                      <>
                        <p>
                          {limit.window.resets_at
                            ? `${time(limit.window.resets_at)} 초기화${estimated ? " (추정)" : ""}`
                            : estimated
                              ? "다음에 사용할 때 새로 시작"
                              : "초기화 시각 확인 불가"}
                        </p>
                        {group.key === "claude_code" &&
                          usage.claude_code?.data?.limits_observed_at && (
                            <p className="quota-source">
                              {time(usage.claude_code.data.limits_observed_at)}{" "}
                              관측
                              {isStale(
                                usage.claude_code.data.limits_observed_at,
                              )
                                ? " · 오래된 값"
                                : ""}
                            </p>
                          )}
                      </>
                    )}
                  </article>
                );
              })}
              {group.key === "claude_code" && !compact && (
                <p className="quota-note">
                  Claude Code 한도는 터미널에서 Claude Code를 쓸 때만
                  갱신됩니다. 한동안 쓰지 않았거나 웹·데스크톱 앱에서 쓴 양은
                  반영되지 않으며, 초기화 시각이 지나면 다시 쓸 때까지 100%로
                  추정합니다.
                </p>
              )}
            </div>
          ) : (
            <p className="quiet-row">
              {group.key === "claude_code"
                ? usage.claude_code?.status_line === "installed"
                  ? "터미널에서 Claude Code를 사용하면 한도가 표시됩니다."
                  : "연결·진단에서 Claude Code 한도 가져오기를 켜 주세요."
                : "현재 확인 가능한 Codex 한도가 없습니다."}
            </p>
          )}
        </section>
      ))}
    </div>
  );
}

// The real Qt Quick widget drawn offscreen with the current settings, so the
// preview cannot drift from what appears next to the pet.
function WidgetPreview({ usage }: { usage: Values }) {
  const [example, setExample] = useState(false);
  const [unfolded, setUnfolded] = useState(false);
  const [preview, setPreview] = useState<Values | null>(null);
  const [failed, setFailed] = useState("");
  const sequence = useRef(0);
  const chips =
    (usage.controls || []).find((c: Values) => c.key === "widget_shape")
      ?.value === "chips";
  const acrylic =
    (usage.controls || []).find((c: Values) => c.key === "widget_material")
      ?.value === "acrylic";
  useEffect(() => {
    const id = ++sequence.current;
    // A change arrives as a few snapshots in a row; draw once they settle.
    const timer = window.setTimeout(() => {
      window
        .settings!.request("usage.widget_preview", {
          sample: example,
          expanded: chips && unfolded,
        })
        .then((value: Values) => {
          if (id !== sequence.current) return;
          setPreview(value);
          setFailed("");
        })
        .catch((error: unknown) => {
          if (id === sequence.current) setFailed(errorText(error));
        });
    }, 150);
    return () => window.clearTimeout(timer);
  }, [usage, example, unfolded, chips]);
  return (
    <Section title="미리보기">
      <div className="widget-preview">
        <div className="widget-preview-stage">
          {preview ? (
            <img
              src={preview.image}
              width={preview.width}
              height={preview.height}
              alt="현재 설정의 사용량 위젯 미리보기"
            />
          ) : (
            <span className="quiet-row">
              {failed || "미리보기를 그리는 중입니다."}
            </span>
          )}
        </div>
        <div className="widget-preview-options">
          <span className="segmented" role="group" aria-label="미리보기 값">
            <button aria-pressed={!example} onClick={() => setExample(false)}>
              지금 값
            </button>
            <button aria-pressed={example} onClick={() => setExample(true)}>
              예시 값
            </button>
          </span>
          {chips && (
            <span className="segmented" role="group" aria-label="칩 모양">
              <button
                aria-pressed={!unfolded}
                onClick={() => setUnfolded(false)}
              >
                평소
              </button>
              <button aria-pressed={unfolded} onClick={() => setUnfolded(true)}>
                마우스를 올렸을 때
              </button>
            </span>
          )}
        </div>
        <p className="field-description">
          {failed && preview
            ? failed
            : preview?.sample && !example
              ? "아직 받은 한도가 없어 예시 값으로 보여 줍니다."
              : "펫 옆 위젯과 같은 방식으로 그린 모습입니다. 설정을 바꾸면 바로 반영됩니다."}
          {acrylic &&
            " 아크릴은 실제 위젯에서만 뒤를 흐리게 비추므로, 미리보기는 어두운 바탕 위의 색으로 보여 줍니다."}
        </p>
      </div>
    </Section>
  );
}

function HomeLink({ label, open }: { label: string; open: () => void }) {
  return (
    <div className="section-footer">
      <button className="text-button" onClick={open}>
        {label}
      </button>
    </div>
  );
}
export function AssistantPages({ shell, page }: { shell: Shell; page: Page }) {
  const { command, notify, reportError } = shell;
  const [usage, setUsage] = useState<Values | null>(null);
  const [activity, setActivity] = useState<Values | null>(null);
  const [integration, setIntegration] = useState<Values | null>(null);
  const [tab, setTab] = useState("overview");
  const [chart, setChart] = useState("tokens");
  const [trendProvider, setTrendProvider] = useState("");
  const [trendSpan, setTrendSpan] = useState("five_hour");
  const [search, setSearch] = useState("");
  const [projectOrder, setProjectOrder] = useState("recent");
  const [conversationOrder, setConversationOrder] = useState("recent");
  const [taskSearch, setTaskSearch] = useState("");
  const [taskOrder, setTaskOrder] = useState("recent");
  const [tasksOpen, setTasksOpen] = useState(false);
  const [provider, setProvider] = useState("codex");
  const [expandedTask, setExpandedTask] = useState<string | null>(null);
  const [taskError, setTaskError] = useState("");
  const [notice, setNotice] = useState<Values | null>(null);
  const [plan, setPlan] = useState<Values | null>(null);
  const [planError, setPlanError] = useState("");
  const [filter, setFilter] = useState("");
  const [shown, setShown] = useState(ACTIVITY_PAGE);
  const [confirming, setConfirming] = useState<Confirmation | null>(null);
  const [terminalHelp, setTerminalHelp] = useState(false);
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  const acknowledged = useRef("");
  // App's command() already shows failures in the page banner; resolve null
  // instead of rejecting so callers never raise a second banner.
  const call = (
    method: string,
    args: Values = {},
    options: CommandOptions = {},
  ): Promise<any> =>
    command(method, args, options).then(
      (result) => result ?? true,
      () => null,
    );
  const read = (method: string, args: Values = {}) =>
    call(method, args, { quiet: true });
  useEffect(() => {
    // Home combines the three assistant snapshots; the widget page reads usage.
    const sources = (
      {
        home: ["usage", "activity", "integration"],
        usage: ["usage"],
        widget: ["usage"],
        activity: ["activity"],
        integration: ["integration"],
      } as Record<string, string[]>
    )[page];
    if (!shell.visible || !sources) return;
    const id = ++sequence.current;
    const setters: Values = {
      usage: setUsage,
      activity: setActivity,
      integration: setIntegration,
    };
    for (const source of sources)
      window
        .settings!.request(source + ".snapshot")
        .then((value) => {
          if (id === sequence.current) setters[source](value);
        })
        .catch((e) => {
          if (id === sequence.current) reportError(e);
        });
    return () => {
      ++sequence.current;
    };
  }, [page, shell.eventVersion, shell.visible]);
  useEffect(() => {
    const route = shell.route;
    if (
      !route?.navigationId ||
      !shell.visible ||
      acknowledged.current === route.navigationId ||
      route.page !== page
    )
      return;
    if (!route.notice && document.querySelector("dialog[open]")) return;
    if (page === "usage" && tab !== "overview") {
      setTab("overview");
      return;
    }
    if (
      (page === "usage" && !usage) ||
      (page === "activity" && !activity) ||
      (page === "integration" && !integration)
    )
      return;
    if (route.notice) {
      const found = activity?.notices.find(
        (row: Values) => row.record_id === route.notice?.record_id,
      );
      if (!found) {
        reportError(new Error("알림이 만료되었습니다."));
        return;
      }
      if (notice?.record_id !== found.record_id) {
        setNotice(found);
        return;
      }
    }
    if (route.filter)
      setFilter(
        ({ usage: "사용량", schedule: "일정", system: "시스템" } as Values)[
          route.filter
        ] || "",
      );
    const id = route.navigationId;
    let timer = requestAnimationFrame(() => {
      timer = requestAnimationFrame(() => {
        window
          .settings!.request("navigation.ack", { navigationId: id })
          .then((result) => {
            if (result.confirmed) acknowledged.current = id;
          })
          .catch(reportError);
      });
    });
    return () => cancelAnimationFrame(timer);
  }, [
    shell.route,
    page,
    usage,
    activity,
    integration,
    notice,
    shell.visible,
    tab,
  ]);
  const u = usage?.data;
  // Claude Code history reuses the history tab with its own source data.
  const claudeHistory = usage?.claude_code?.data;
  // A tool whose usage switch is off is not offered as a history source.
  const historySources: string[] = [
    ...(usage?.enabled ? ["codex"] : []),
    ...(usage?.claude_code_enabled && claudeHistory ? ["claude_code"] : []),
  ];
  const source = historySources.includes(provider)
    ? provider
    : historySources[0] || "codex";
  const h = source === "claude_code" ? claudeHistory : u;
  useEffect(() => {
    if (!h) return;
    setSearch(h.project_search ?? "");
    setProjectOrder(h.project_order || "recent");
    setConversationOrder(h.conversation_order || "recent");
  }, [source, h?.project_search, h?.project_order, h?.conversation_order]);
  const queryProjects = (
    offset = 0,
    order = projectOrder,
    from: string = source,
  ) =>
    read("usage.query", {
      kind: "projects",
      search,
      order,
      offset,
      provider: from,
    });
  const queryConversations = (offset = 0, order = conversationOrder) =>
    read("usage.query", {
      kind: "conversations",
      search,
      order,
      offset,
      provider: source,
    });
  // Runs inside the task dialog, whose backdrop would hide the page banner.
  const queryTasks = (limit = PAGE_SIZE, order = taskOrder) =>
    command(
      "usage.query",
      { kind: "tasks", search: taskSearch, order, limit, provider: source },
      { inline: true, quiet: true },
    ).then(
      () => setTaskError(""),
      (e) => setTaskError(errorText(e)),
    );
  const selectTab = (next: string) => {
    if (next === "history" && tab !== "history")
      queryProjects(h?.project_offset || 0);
    setTab(next);
  };
  const selectProvider = (next: string) => {
    setProvider(next);
    setTasksOpen(false);
    queryProjects(0, "recent", next);
  };
  const openConversation = async (key: string) => {
    if (
      !(await read("usage.select", {
        kind: "conversation",
        key,
        provider: source,
      }))
    )
      return;
    setTaskSearch("");
    setTaskOrder("recent");
    setExpandedTask(null);
    setTaskError("");
    setTasksOpen(true);
  };
  const preview = async (operation: string, provider = "codex") => {
    const result = await read("integration.preview", { operation, provider });
    if (result) {
      setPlanError("");
      setPlan(result);
    }
  };
  const widgetVisible = !!usage?.controls.find(
    (control: Values) => control.key === "widget_visible",
  )?.value;
  const selectedProject = h?.projects?.find(
    (row: Values) => row.project_key === h.selected_project_key,
  );
  const allEntries: Values[] = activity?.entries || [];
  const kinds = [...new Set<string>(allEntries.map((entry) => entry.kind))];
  if (filter && !kinds.includes(filter)) kinds.push(filter);
  const entries = allEntries.filter(
    (entry) => !filter || entry.kind === filter,
  );
  const unconfirmed: Values[] = (activity?.notices || [])
    .filter((row: Values) => !row.confirmed)
    .reverse();
  const hero = integration ? heroFor(integration) : null;
  // Home lists each running conversation with the project it belongs to.
  const homeRows: { project: Values; row: Values }[] = (
    activity?.projects || []
  ).flatMap((project: Values) =>
    (project.rows || []).map((row: Values) => ({ project, row })),
  );
  // Only tools in use; a switched-off one lives on the connections page.
  const codexActive = integration?.codex_active !== false;
  const claudeActive = !!integration?.claude_code?.active;
  const connections: [string, Values][] = integration
    ? [
        ...(codexActive
          ? ([["Codex", heroFor(integration)]] as [string, Values][])
          : []),
        ...(claudeActive
          ? ([
              [
                "Claude Code",
                claudeHeroes[integration.claude_code.install?.state] ||
                  claudeHeroes.invalid,
              ],
            ] as [string, Values][])
          : []),
      ]
    : [];
  return (
    <>
      {page === "home" && (
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
                  unconfirmed.slice(0, 3).map((row: Values) => (
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
                    사용 중인 도구가 없습니다. 연결·진단에서 Codex나 Claude
                    Code를 켤 수 있습니다.
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
      )}
      {page === "usage" && (
        <div className="page">
          <Heading
            title="사용량"
            subtitle="남은 한도와 이 기기에서 관측한 작업을 확인합니다."
          >
            <div className="heading-actions">
              <button
                className="button compact"
                disabled={!usage?.any_enabled}
                onClick={() => call("usage.action", { action: "refresh" })}
              >
                <RotateCcw size={14} />
                새로고침
              </button>
            </div>
          </Heading>
          <TabList
            id="usage"
            label="사용량 영역"
            tabs={[
              ["overview", "현황"],
              ["history", "기록"],
              ["settings", "설정"],
            ]}
            value={tab}
            select={selectTab}
          />
          {!u ? (
            <Empty>사용량을 불러오는 중입니다.</Empty>
          ) : (
            <div
              role="tabpanel"
              id="usage-panel"
              aria-labelledby={`usage-tab-${tab}`}
            >
              <div className="availability">
                {usage!.enabled && (
                  <span
                    className="availability-item"
                    data-state={u.availability.state}
                  >
                    <span className="small-dot" />
                    <strong>Codex</strong>
                    {[
                      u.account_email,
                      u.account_plan,
                      // A working account needs no sentence; anything else
                      // (checking, offline, no account) says what is wrong.
                      u.availability.state === "available" && u.account_hash
                        ? ""
                        : u.availability.message,
                    ]
                      .filter(Boolean)
                      .map((part: string) => (
                        <span key={part}>{part}</span>
                      ))}
                  </span>
                )}
                {usage!.claude_code_enabled && usage!.claude_code && (
                  <span
                    className="availability-item"
                    data-state={
                      usage!.claude_code.data?.limits_observed_at
                        ? "available"
                        : "checking"
                    }
                  >
                    <span className="small-dot" />
                    <strong>Claude Code</strong>
                    <span>
                      {usage!.claude_code.data?.limits_observed_at
                        ? `마지막 관측 ${time(usage!.claude_code.data.limits_observed_at)}`
                        : "아직 관측 전"}
                    </span>
                  </span>
                )}
              </div>
              {u.storage_error && (
                <div className="error-banner">
                  <Info size={16} />
                  <span>{u.storage_error}</span>
                </div>
              )}
              {u.refresh?.state === "refreshing" && (
                <p className="footnote" role="status">
                  {u.refresh.message || "최신 사용량 확인 중…"}
                </p>
              )}
              {!usage!.any_enabled && tab !== "settings" && (
                <p className="paused-note">
                  사용 중인 도구가 없어 한도를 확인하지 않습니다.{" "}
                  <button
                    className="text-button inline"
                    onClick={() => shell.navigate("integration")}
                  >
                    연결·진단
                  </button>
                  에서 Codex나 Claude Code를 켤 수 있습니다.
                </p>
              )}
              {tab === "overview" && (
                <div>
                  <div className="section-heading">
                    <h2>남은 한도</h2>
                    <span>
                      {u.last_updated_at
                        ? `${time(u.last_updated_at)} 확인`
                        : ""}
                    </span>
                  </div>
                  <QuotaGroups usage={usage!} />
                  {usage!.enabled && (
                    <Section
                      title="오늘의 기기 활동"
                      note={
                        u.last_sample_at
                          ? `마지막 관측 ${time(u.last_sample_at)}`
                          : "아직 관측 전"
                      }
                    >
                      {[
                        u.observed_today_tokens,
                        u.unclassified_today_tokens,
                        u.observed_today_percent_points,
                      ].every((value) => typeof value !== "number") ? (
                        <p className="paused-note">
                          오늘 이 기기에서 관측한 Codex 작업이 아직 없습니다.
                          작업을 하면 토큰과 한도 감소가 여기에 표시됩니다.
                        </p>
                      ) : (
                        <div className="activity-summary">
                          {(
                            [
                              ["관측한 토큰", u.observed_today_tokens, ""],
                              ["미분류 토큰", u.unclassified_today_tokens, ""],
                              [
                                "관측한 한도 감소",
                                u.observed_today_percent_points,
                                "%p",
                              ],
                            ] as [string, any, string][]
                          ).map(([label, value, unit]) => (
                            <div key={label}>
                              <span>{label}</span>
                              <strong>
                                {number(value)}
                                {typeof value === "number" && unit && (
                                  <small>{unit}</small>
                                )}
                              </strong>
                            </div>
                          ))}
                        </div>
                      )}
                    </Section>
                  )}
                  <Trends
                    usage={usage!}
                    chart={chart}
                    setChart={setChart}
                    provider={trendProvider}
                    setProvider={setTrendProvider}
                    span={trendSpan}
                    setSpan={setTrendSpan}
                    setDays={(value) =>
                      call("usage.set", { key: "chart_days", value })
                    }
                  />
                  {usage!.enabled && (
                    <details className="explanation">
                      <summary>한도 상세와 계정 통계</summary>
                      {u.buckets.map((bucket: Values) => (
                        <div className="detail-group" key={bucket.limit_id}>
                          <h3>{bucket.limit_name || bucket.limit_id}</h3>
                          <Details value={bucket} />
                        </div>
                      ))}
                      <div className="detail-group">
                        <h3>계정 통계</h3>
                        <Details value={u.summary} />
                      </div>
                    </details>
                  )}
                  {usage!.enabled && u.device_history_message && (
                    <p className="footnote">{u.device_history_message}</p>
                  )}
                </div>
              )}
              {tab === "history" && (
                <div
                  className={
                    (
                      source === "claude_code"
                        ? usage!.claude_code_enabled
                        : usage!.enabled
                    )
                      ? ""
                      : "is-paused"
                  }
                >
                  {(historySources.length > 1 || source === "claude_code") && (
                    <div className="chip-row provider-row">
                      {historySources.length > 1 && (
                        <Segmented
                          label="기록 출처"
                          options={[
                            ["codex", "Codex"],
                            ["claude_code", "Claude Code"],
                          ]}
                          value={source}
                          select={selectProvider}
                        />
                      )}
                      {source === "claude_code" && (
                        <>
                          <span className="footnote">
                            {h.availability?.message}
                            {h.import_remaining
                              ? ` · 남은 파일 ${h.import_remaining}개`
                              : ""}
                          </span>
                          <button
                            className="text-button danger"
                            onClick={() =>
                              setConfirming({
                                title: "Claude Code 작업 기록 지우기",
                                body: "이 기기에 저장한 Claude Code 작업 기록을 지웁니다. Claude Code의 대화 기록 파일은 지우지 않으며, 이후 작업부터 다시 기록합니다.",
                                label: "지우기",
                                run: () =>
                                  call("usage.action", {
                                    action: "clear",
                                    provider: "claude_code",
                                  }),
                              })
                            }
                          >
                            기록 지우기
                          </button>
                        </>
                      )}
                    </div>
                  )}
                  <div className="filter-row">
                    <label className="search">
                      <Search size={15} />
                      <input
                        aria-label="사용량 기록 검색"
                        value={search}
                        placeholder="프로젝트·대화 검색"
                        onChange={(event) => setSearch(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") queryProjects();
                        }}
                      />
                    </label>
                    <button className="button" onClick={() => queryProjects()}>
                      검색
                    </button>
                  </div>
                  <div className="history-columns">
                    <section className="section">
                      <div className="section-heading">
                        <h2>프로젝트 · {h.project_count ?? 0}개</h2>
                        <select
                          aria-label="프로젝트 정렬"
                          value={projectOrder}
                          onChange={(event) => {
                            setProjectOrder(event.target.value);
                            queryProjects(0, event.target.value);
                          }}
                        >
                          <option value="recent">최근순</option>
                          <option value="name">이름순</option>
                          {source === "codex" && (
                            <option value="custom">직접 정렬</option>
                          )}
                        </select>
                      </div>
                      <div className="card">
                        {!h.projects?.length && (
                          <Empty>
                            {search
                              ? "검색 결과가 없습니다."
                              : "아직 기록된 프로젝트가 없습니다."}
                          </Empty>
                        )}
                        {(h.projects || []).map((row: Values) => {
                          const selected =
                            row.project_key === h.selected_project_key;
                          return (
                            <div
                              className={`project-row ${selected ? "selected" : ""}`}
                              key={row.project_key}
                            >
                              <button
                                className="project-main"
                                aria-current={selected ? "true" : undefined}
                                onClick={() =>
                                  read("usage.select", {
                                    kind: "project",
                                    key: row.project_key,
                                    provider: source,
                                  })
                                }
                              >
                                <span className="project-avatar">
                                  {(row.name || "?")[0]}
                                </span>
                                <span className="project-name">
                                  <strong title={row.name}>{row.name}</strong>
                                  <small>
                                    {row.conversation_count ?? 0}개 대화 ·{" "}
                                    {time(row.completed_at)}
                                  </small>
                                </span>
                              </button>
                              {h.project_order === "custom" && !search && (
                                <>
                                  <button
                                    className="icon-button"
                                    aria-label={`${row.name} 위로`}
                                    onClick={() =>
                                      call("usage.move", {
                                        key: row.project_key,
                                        direction: -1,
                                      })
                                    }
                                  >
                                    <ArrowUp size={14} />
                                  </button>
                                  <button
                                    className="icon-button"
                                    aria-label={`${row.name} 아래로`}
                                    onClick={() =>
                                      call("usage.move", {
                                        key: row.project_key,
                                        direction: 1,
                                      })
                                    }
                                  >
                                    <ArrowDown size={14} />
                                  </button>
                                </>
                              )}
                            </div>
                          );
                        })}
                        <Pager
                          label="프로젝트"
                          offset={h.project_offset || 0}
                          hasMore={!!h.projects_has_more}
                          go={(offset) => queryProjects(offset)}
                        />
                      </div>
                    </section>
                    <section className="section">
                      <div className="section-heading">
                        <h2 title={selectedProject?.name}>
                          {selectedProject?.name
                            ? `${selectedProject.name}의 대화`
                            : "대화"}
                        </h2>
                        <select
                          aria-label="대화 정렬"
                          value={conversationOrder}
                          onChange={(event) => {
                            setConversationOrder(event.target.value);
                            queryConversations(0, event.target.value);
                          }}
                        >
                          <option value="recent">최근순</option>
                          <option value="top">측정 사용량 상위</option>
                        </select>
                      </div>
                      <div className="card">
                        {!h.conversations?.length && (
                          <Empty>
                            {h.projects?.length
                              ? "이 프로젝트에 표시할 대화가 없습니다."
                              : "프로젝트를 고르면 대화가 표시됩니다."}
                          </Empty>
                        )}
                        {(h.conversations || []).map((row: Values) => {
                          const selected =
                            row.thread_hash === h.selected_thread_hash;
                          return (
                            <div
                              className={`project-row ${selected ? "selected" : ""}`}
                              key={row.thread_hash}
                            >
                              <button
                                className="project-main"
                                aria-current={selected ? "true" : undefined}
                                onClick={() =>
                                  openConversation(row.thread_hash)
                                }
                              >
                                <span className="project-name">
                                  <strong title={row.title}>{row.title}</strong>
                                  <small>{time(row.completed_at)}</small>
                                </span>
                                <span className="record-tokens">
                                  {number(row.total_tokens)} tokens
                                </span>
                                <ChevronRight size={15} />
                              </button>
                            </div>
                          );
                        })}
                        <Pager
                          label="대화"
                          offset={h.conversation_offset || 0}
                          hasMore={!!h.conversations_has_more}
                          go={(offset) => queryConversations(offset)}
                        />
                      </div>
                      {h.conversation_status && (
                        <p className="footnote">{h.conversation_status}</p>
                      )}
                    </section>
                  </div>
                  {!!h.legacy_tasks?.length && (
                    <details className="explanation">
                      <summary>
                        이전 형식의 기록 · {h.legacy_tasks.length}건
                      </summary>
                      {h.legacy_tasks.map((row: Values, index: number) => (
                        <div className="detail-group" key={index}>
                          <h3>
                            {time(row.completed_at)} ·{" "}
                            {number(row.total_tokens)} tokens
                          </h3>
                          <Details value={row} />
                        </div>
                      ))}
                    </details>
                  )}
                  {h.history_message && (
                    <p className="footnote">{h.history_message}</p>
                  )}
                </div>
              )}
              {tab === "settings" && (
                <>
                  <Fields
                    controls={usage!.controls.filter(
                      (control: Values) => control.group === "사용량 알림",
                    )}
                    change={(key, value) => call("usage.set", { key, value })}
                  />
                  {usage!.enabled && (
                    <Section title="데이터 관리">
                      <div className="setting-row">
                        <div className="field-label">
                          <label>Codex 기기 관측 기록</label>
                          <p className="field-description">
                            이 Windows 사용자의 Codex 로그에서 관측한 토큰·한도
                            변화입니다.
                          </p>
                        </div>
                        <button
                          className="button danger"
                          onClick={() =>
                            setConfirming({
                              title: "기기 관측 기록 지우기",
                              body: "이 기기의 관측 기록을 지웁니다. 되돌릴 수 없습니다.",
                              label: "지우기",
                              run: () =>
                                call("usage.action", {
                                  action: "clear_device",
                                }),
                            })
                          }
                        >
                          지우기
                        </button>
                      </div>
                      <div className="setting-row">
                        <div className="field-label">
                          <label>Codex 현재 계정 작업 기록</label>
                          <p className="field-description">
                            현재 Codex 계정의 프로젝트·대화·작업 사용량입니다.
                            Claude Code 작업 기록은 기록 탭에서 지웁니다.
                          </p>
                        </div>
                        <button
                          className="button danger"
                          disabled={u.clearing_history || u.account_checking}
                          onClick={() =>
                            setConfirming({
                              title: "현재 계정 기록 지우기",
                              body: "현재 계정의 사용량 기록을 지웁니다. 되돌릴 수 없습니다.",
                              label: "지우기",
                              run: () =>
                                call("usage.action", { action: "clear" }),
                            })
                          }
                        >
                          지우기
                        </button>
                      </div>
                    </Section>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}
      {page === "widget" && (
        <div className="page">
          <Heading
            title="위젯"
            subtitle="펫 옆 사용량 위젯의 모양과 표시 항목, 색과 크기를 설정합니다."
          />
          {!usage ? (
            <Empty>위젯 설정을 불러오는 중입니다.</Empty>
          ) : (
            <>
              <WidgetPreview usage={usage} />
              <Fields
                controls={usage!.controls.filter((control: Values) =>
                  ["위젯", "위젯 외관"].includes(control.group),
                )}
                change={(key, value) => call("usage.set", { key, value })}
                groupFooters={{
                  위젯: (
                    <span className="footer-actions">
                      <button
                        className="text-button"
                        disabled={!widgetVisible}
                        onClick={() =>
                          call("usage.action", { action: "reset_widget" })
                        }
                      >
                        기본 구성으로
                      </button>
                      <button
                        className="text-button"
                        disabled={!widgetVisible}
                        onClick={() =>
                          call("usage.action", { action: "reset_position" })
                        }
                      >
                        펫 옆으로 위치 복원
                      </button>
                    </span>
                  ),
                  "위젯 외관": (
                    <span className="footer-actions">
                      <button
                        className="text-button"
                        disabled={!widgetVisible}
                        onClick={() =>
                          call("usage.action", { action: "reset_style" })
                        }
                      >
                        기본 스타일로
                      </button>
                      <button
                        className="text-button"
                        disabled={!widgetVisible}
                        onClick={() =>
                          call("usage.action", { action: "reset_scale" })
                        }
                      >
                        기본 크기로
                      </button>
                    </span>
                  ),
                }}
              />
              <Section title="오늘 흐름 시간대">
                <HourRange
                  hours={usage!.hours}
                  disabled={!widgetVisible}
                  save={(value) =>
                    call("usage.set", { key: "widget_hours", value })
                  }
                />
                <div className="section-footer">
                  <button
                    className="text-button"
                    disabled={!widgetVisible}
                    onClick={() =>
                      call("usage.action", { action: "reset_hours" })
                    }
                  >
                    전체 24시간으로
                  </button>
                </div>
              </Section>
            </>
          )}
        </div>
      )}
      {page === "activity" && (
        <div className="page">
          <Heading
            title="활동 기록"
            subtitle="확인할 알림과 진행 중인 작업, 최근 활동을 모아 봅니다."
          />
          {!activity ? (
            <Empty>활동을 불러오는 중입니다.</Empty>
          ) : (
            <>
              <Section
                title="확인하지 않은 알림"
                note={unconfirmed.length ? `${unconfirmed.length}건` : ""}
              >
                {unconfirmed.length ? (
                  unconfirmed.slice(0, 5).map((row: Values) => (
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
                    확인할 알림이 없어요.
                  </p>
                )}
              </Section>
              <Section title="진행 중">
                {activity.projects.length ? (
                  activity.projects.map((project: Values) => (
                    <div className="project-activity" key={project.key}>
                      <div className="project-activity-heading">
                        <h3>{project.label || "프로젝트"}</h3>
                        {project.source && <SourceTag name={project.source} />}
                        {project.summary && <span>{project.summary}</span>}
                      </div>
                      {(project.rows || []).map((row: Values, j: number) => (
                        <button
                          className="thread-row"
                          key={j}
                          onClick={() =>
                            call("activity.open", { token: row.action_token })
                          }
                        >
                          <span className="record-summary">
                            {row.title || "대화"}
                          </span>
                          <span className="pill">{row.label || row.state}</span>
                          <ChevronRight size={14} />
                        </button>
                      ))}
                    </div>
                  ))
                ) : (
                  <p className="quiet-row">진행 중인 작업이 없어요.</p>
                )}
              </Section>
              <section className="section">
                <div className="section-heading">
                  <div className="heading-title">
                    <h2>최근 활동</h2>
                    <span
                      className="info-tip"
                      role="note"
                      aria-label="저장 안내"
                      title="비서 알림·프로젝트 이벤트·작업 완료는 이번 실행에만 표시됩니다. Codex 작업 사용량 기록은 별도의 로컬 저장 정책을 따릅니다."
                    >
                      <Info size={13} />
                    </span>
                  </div>
                  <details className="more-menu">
                    <summary aria-label="활동 기록 관리">
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
                            title: "비서 알림 기록 지우기",
                            body: "이번 실행의 비서 알림 기록을 지웁니다. 작업·프로젝트 기록은 유지됩니다.",
                            label: "지우기",
                            run: () => call("activity.clear"),
                          });
                        }}
                      >
                        비서 알림 기록 지우기
                      </button>
                    </div>
                  </details>
                </div>
                <div className="card">
                  {!!allEntries.length && (
                    <div className="chip-row">
                      <Segmented
                        label="활동 종류"
                        options={[
                          ["", `전체 ${allEntries.length}`],
                          ...kinds.map(
                            (kind) =>
                              [
                                kind,
                                `${kind} ${
                                  allEntries.filter(
                                    (entry) => entry.kind === kind,
                                  ).length
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
                    <Empty>아직 기록된 활동이 없습니다.</Empty>
                  ) : !entries.length ? (
                    <Empty>이 종류의 활동이 없습니다.</Empty>
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
                          <span className="record-summary">
                            {entry.summary}
                          </span>
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
                        onClick={() =>
                          setShown((count) => count + ACTIVITY_PAGE)
                        }
                      >
                        {Math.min(ACTIVITY_PAGE, entries.length - shown)}건 더
                        보기
                      </button>
                    </div>
                  )}
                </div>
              </section>
            </>
          )}
        </div>
      )}
      {page === "integration" && (
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
                  detected={!!integration.claude_code.install?.detected}
                  preview={(operation) => preview(operation, "claude_code")}
                />
              )}
              {claudeActive && (
                <ClaudeCodeSection
                  claude={integration.claude_code}
                  diagnostics={integration.diagnostics.claude_code || {}}
                  preview={(operation) => preview(operation, "claude_code")}
                  previewStatusLine={(operation) =>
                    preview(operation, "claude_code_status_line")
                  }
                  setMinutes={(key, value) =>
                    call("integration.set", { key, value })
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
                        if (!result.cancelled)
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
      )}
      {tasksOpen && h?.selected_thread_hash && (
        <Modal
          title={
            h.selected_conversation?.title ||
            h.conversations?.find(
              (row: Values) => row.thread_hash === h.selected_thread_hash,
            )?.title ||
            "선택한 대화의 작업"
          }
          close={() => setTasksOpen(false)}
          error={taskError || undefined}
        >
          <div className="filter-row">
            <label className="search">
              <Search size={15} />
              <input
                aria-label="작업 기록 검색"
                placeholder="모델·결과·측정 품질 검색"
                value={taskSearch}
                onChange={(event) => setTaskSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") queryTasks();
                }}
              />
            </label>
            <select
              aria-label="작업 표시 순서"
              value={taskOrder}
              onChange={(event) => {
                setTaskOrder(event.target.value);
                queryTasks(PAGE_SIZE, event.target.value);
              }}
            >
              <option value="recent">최근 작업</option>
              <option value="top">측정 사용량 상위</option>
              <option value="time_asc">오래된 작업</option>
              <option value="input">입력 토큰 상위</option>
              <option value="output">출력 토큰 상위</option>
            </select>
            <button className="button" onClick={() => queryTasks()}>
              검색
            </button>
          </div>
          <div className="task-list">
            {!h.recent_tasks.length && (
              <Empty>
                {taskSearch
                  ? "검색 결과가 없습니다."
                  : "표시할 작업이 없습니다."}
              </Empty>
            )}
            {h.recent_tasks.map((row: Values, index: number) => {
              const key = row.turn_hash || String(index);
              const open = expandedTask === key;
              return (
                <div key={key}>
                  <button
                    className="record-row"
                    aria-expanded={open}
                    onClick={() => setExpandedTask(open ? null : key)}
                  >
                    <span className="record-time">
                      {time(row.completed_at)}
                    </span>
                    <strong>{outcomeLabels[row.outcome] || row.outcome}</strong>
                    <span className="record-summary">
                      {[qualityLabels[row.data_quality], row.model]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    <span className="record-tokens">
                      {number(row.total_tokens)} tokens
                    </span>
                    <ChevronDown
                      size={14}
                      className={open ? "rotated" : undefined}
                    />
                  </button>
                  {open && (
                    <div className="task-details">
                      <Details value={row} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <Pager
            label="작업"
            offset={(h.task_history_limit || PAGE_SIZE) - PAGE_SIZE}
            hasMore={!!h.task_history_has_more}
            go={(offset) => queryTasks(offset + PAGE_SIZE)}
          />
        </Modal>
      )}
      {terminalHelp && <TerminalHelp close={() => setTerminalHelp(false)} />}
      {notice && (
        <Modal title="알림 내용" close={() => setNotice(null)}>
          <p className="notice-text">{notice.message}</p>
          {notice.category === "schedule" && (
            <p className="footnote">
              외부 일정 시스템은 아직 연결되지 않았습니다.
            </p>
          )}
        </Modal>
      )}
      {plan && (
        <Modal
          title="연결 변경 검토"
          close={() => setPlan(null)}
          error={planError || undefined}
          footer={
            <>
              <button className="button" onClick={() => setPlan(null)}>
                취소
              </button>
              <button
                className="button primary"
                disabled={!plan.canApply || busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await command(
                      "integration.apply",
                      { token: plan.token },
                      { inline: true },
                    );
                    setPlan(null);
                    notify("연결 설정을 적용했습니다.");
                  } catch (e) {
                    setPlanError(errorText(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Check size={14} />
                변경 적용
              </button>
            </>
          }
        >
          {plan.changes.length ? (
            <ul className="plan-changes">
              {plan.changes.map((change: string) => (
                <li key={change}>{change}</li>
              ))}
            </ul>
          ) : (
            <p>변경할 내용이 없습니다.</p>
          )}
          {plan.warnings.map((warning: string) => (
            <p className="explanation" key={warning}>
              {warning}
            </p>
          ))}
          {!plan.canApply && (
            <p className="field-description">
              지금은 적용할 수 없습니다. 위 안내를 확인해 주세요.
            </p>
          )}
        </Modal>
      )}
      {confirming && (
        <Confirm
          title={confirming.title}
          label={confirming.label}
          danger
          close={() => setConfirming(null)}
          confirm={() => {
            confirming.run();
            setConfirming(null);
          }}
        >
          <p>{confirming.body}</p>
        </Confirm>
      )}
    </>
  );
}
