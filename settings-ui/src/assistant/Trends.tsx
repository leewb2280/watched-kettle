import { type ReactNode } from "react";
import { Empty } from "../components";
import { BarLineChart, RemainingChart, tokens, type Bar } from "../TrendChart";
import type {
  Control,
  DailyPoint,
  DailyTrend,
  HourTrend,
  QuotaTrend,
  UsageResponse,
} from "../types";
import { number, Segmented, shortDate } from "./presentation";

export const TREND_SOURCES: [string, string][] = [
  ["codex", "Codex"],
  ["claude_code", "Claude Code"],
];

export const TREND_COLORS: Record<string, string> = {
  codex: "var(--chart-codex)",
  claude_code: "var(--chart-claude-code)",
};

export const versus = (value: number | null | undefined) =>
  value == null
    ? "—"
    : value === 0
      ? "평소와 같음"
      : `평소보다 ${Math.abs(value)}% ${value > 0 ? "많음" : "적음"}`;

export const percent = (value: number | null | undefined, unit = "%") =>
  value == null ? "—" : `${number(value)}${unit}`;

// Calendar dates (YYYY-MM-DD) without a UTC shift.
export const calendar = (value: string) => {
  const [year, month, day] = String(value).split("-").map(Number);
  return new Date(year, month - 1, day);
};

export const longDate = (value: string) =>
  calendar(value).toLocaleDateString("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
  });

export const localToday = () => {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

export function TrendStats({ items }: { items: [string, string][] }) {
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

export function Trends({
  usage,
  chart,
  setChart,
  provider,
  setProvider,
  span,
  setSpan,
  setDays,
}: {
  usage: UsageResponse;
  chart: string;
  setChart: (value: string) => void;
  provider: string;
  setProvider: (value: string) => void;
  span: string;
  setSpan: (value: string) => void;
  setDays: (value: number) => void;
}) {
  const trends = usage.trends;
  const chartDays = usage.controls.find(
    (control: Control) => control.key === "chart_days",
  );
  // A switched-off tool is left out; with both off the page says so.
  const sources = TREND_SOURCES.filter(([key]) =>
    key === "codex" ? usage.enabled : usage.claude_code_enabled,
  );
  if (!sources.length) return null;
  // Start on a tool with data; the choice stays separate from the history tab.
  const source = sources.some(([key]) => key === provider)
    ? provider
    : (sources.find(
        ([key]) => trends[key as "codex" | "claude_code"]?.enabled,
      ) || sources[0])[0];
  const name = source === "codex" ? "Codex" : "Claude Code";
  const color = TREND_COLORS[source];
  const data = trends[source as "codex" | "claude_code"];
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
    const hours: HourTrend | null = data.hours;
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
    const series: QuotaTrend | undefined = data.quota?.[span];
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
    const daily: DailyTrend = data.daily;
    const days: DailyPoint[] = daily.days || [];
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
              {chartDays.options?.map((option) => (
                <option key={String(option.value)} value={String(option.value)}>
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
