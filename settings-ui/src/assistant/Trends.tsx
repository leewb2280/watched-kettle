import { t, locale } from "../../localization.cjs";
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
      ? t("message.0910")
      : t("message.0911", {
          value0: Math.abs(value),
          value1: t(value > 0 ? "comparison.more" : "comparison.less"),
        });

export const percent = (value: number | null | undefined, unit = "%") =>
  value == null ? "—" : `${number(value)}${unit}`;

// Calendar dates (YYYY-MM-DD) without a UTC shift.
export const calendar = (value: string) => {
  const [year, month, day] = String(value).split("-").map(Number);
  return new Date(year, month - 1, day);
};

export const longDate = (value: string) =>
  calendar(value).toLocaleDateString(locale(), {
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
          ? t("message.0912")
          : t("message.0913", { value0: name })}
      </Empty>
    );
  } else if (chart === "tokens") {
    const hours: HourTrend | null = data.hours;
    const average: (number | null)[] | null = hours?.average ?? null;
    if (!hours || (hours.total == null && !average)) {
      body = <Empty>{t("message.0914")}</Empty>;
    } else {
      stats = [
        [t("message.0915"), tokens(hours.total)],
        [t("message.0916"), versus(hours.versus_average)],
        [
          t("message.0917"),
          hours.peak_hour == null
            ? "—"
            : t("message.0918", { value0: hours.peak_hour }),
        ],
      ];
      const bars: Bar[] = (hours.hours as (number | null)[]).map(
        (value, hour) => ({
          label: t("message.0918", { value0: hour }),
          title: t("message.0919", {
            value0: hour,
            value1: hour === nowHour ? t("comparison.now") : "",
          }),
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
          referenceName={t("message.0920", { value0: hours.average_days })}
          label={t("message.0921", {
            value0: name,
            value1: tokens(hours.total),
            value2: versus(hours.versus_average),
          })}
          describe={(bar) => [
            bar.title,
            bar.value == null ? t("message.0922") : tokens(bar.value),
            ...(bar.line == null
              ? []
              : [t("message.0923", { value0: tokens(bar.line) })]),
          ]}
        />
      );
      notes.push(
        (average
          ? t("message.0924", { value0: hours.average_days })
          : t("message.0925", { value0: hours.average_days })) +
          (source === "codex" ? t("message.0926") : t("message.0927")),
      );
    }
  } else if (chart === "quota") {
    const series: QuotaTrend | undefined = data.quota?.[span];
    const spanName =
      span === "five_hour" ? t("message.0333") : t("message.0334");
    const day = new Date();
    day.setHours(0, 0, 0, 0);
    // A line computed before midnight belongs to yesterday until the next refresh.
    const points: [string, number][] = (series?.points || []).filter(
      ([at]: [string, number]) => new Date(at).getTime() >= day.getTime(),
    );
    if (!points.length) {
      body = (
        <Empty>
          {t("usage.quota_missing", { window: name + " " + spanName })}
        </Empty>
      );
    } else {
      stats = [
        [t("message.0930"), percent(series!.now_remaining)],
        [t("message.0931"), percent(series!.spent, "%p")],
        [
          t("message.0932"),
          t("message.0933", { value0: series!.resets.length }),
        ],
      ];
      body = (
        <RemainingChart
          points={points}
          resets={series!.resets}
          day={day}
          now={new Date()}
          color={color}
          label={t("message.0934", {
            value0: name,
            value1: spanName,
            value2: percent(series!.now_remaining),
            value3: percent(series!.spent, "%p"),
          })}
        />
      );
    }
    notes.push(t("message.0935"));
    notes.push(source === "codex" ? t("message.0936") : t("message.0937"));
  } else {
    const daily: DailyTrend = data.daily;
    const days: DailyPoint[] = daily.days || [];
    if (!days.length || daily.total == null) {
      body = <Empty>{t("message.0938")}</Empty>;
    } else {
      stats = [
        [t("message.0939", { value0: days.length }), tokens(daily.total)],
        [t("message.0940"), tokens(daily.average)],
        [t("message.0941"), daily.peak_date ? shortDate(daily.peak_date) : "—"],
      ];
      const today = localToday();
      const step = Math.ceil(days.length / 6);
      const bars: Bar[] = days.map((row, index) => ({
        label: shortDate(row.date),
        title: `${longDate(row.date)}${row.date === today ? t("message.0942") : ""}`,
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
          referenceName={t("message.0943")}
          label={t("message.0944", {
            value0: name,
            value1: days.length,
            value2: tokens(daily.total),
            value3: tokens(daily.average),
          })}
          describe={(bar) => [
            bar.title,
            bar.value == null ? t("message.0945") : tokens(bar.value),
            ...(bar.line == null
              ? []
              : [t("message.0946", { value0: tokens(bar.line) })]),
          ]}
        />
      );
    }
    notes.push(
      (source === "codex" ? t("message.0947") : t("message.0948")) +
        t("message.0949"),
    );
  }
  return (
    <section className="section">
      <div className="section-heading">
        <h2>{t("message.0950")}</h2>
        {sources.length > 1 && (
          <Segmented
            label={t("message.0951")}
            options={sources}
            value={source}
            select={setProvider}
          />
        )}
      </div>
      <div className="card trend-card">
        <div className="trend-toolbar">
          <Segmented
            label={t("message.0952")}
            options={[
              ["tokens", t("message.0953")],
              ["quota", t("message.0954")],
              ["daily", t("message.0955")],
            ]}
            value={chart}
            select={setChart}
          />
          {chart === "quota" && (
            <Segmented
              label={t("message.0956")}
              options={[
                ["five_hour", t("message.0333")],
                ["seven_day", t("message.0334")],
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
                  {t("usage.recent_span", { span: option.label })}
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
