import { t, locale } from "../localization.cjs";
// Usage overview trend charts (stage 14): bars with an optional reference
// line, and a remaining-percent line with reset marks. One axis per chart;
// series wear the provider's chart color, text stays in ink tokens.
import { useEffect, useRef, useState, type CSSProperties } from "react";

const HEIGHT = 150;
const PAD = { top: 10, right: 10, bottom: 22, left: 44 };
const MAX_BAR = 24;
const GAP = 2;
const RADIUS = 4;
const DAY_MS = 86400000;

const compact = new Intl.NumberFormat(locale(), {
  notation: "compact",
  maximumFractionDigits: 1,
});
const full = new Intl.NumberFormat(locale(), { maximumFractionDigits: 0 });
export const tokens = (value: number | null | undefined) =>
  value == null
    ? t("message.0945")
    : t("message.1258", { count: value, value0: full.format(value) });
export const shortTokens = (value: number | null | undefined) =>
  value == null ? "—" : compact.format(value);

export type Bar = {
  label: string; // axis label (shown on some ticks)
  title: string; // tooltip heading
  value: number | null; // null: not observed
  line?: number | null; // reference line value at this slot
  current?: boolean;
  future?: boolean; // nothing to draw yet
  tick?: boolean;
};

function useWidth() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(560);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setWidth(Math.max(240, element.clientWidth));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

// 1, 2, 2.5, 5 x 10^n at or above the value, so grid labels stay round.
function niceMax(value: number) {
  if (!(value > 0)) return 1;
  const unit = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 2.5, 5, 10].map((f) => f * unit).find((v) => v >= value)!;
}

// Rounded top, square base anchored to the baseline.
function barPath(x: number, y: number, width: number, base: number) {
  const r = Math.min(RADIUS, width / 2, base - y);
  return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${base}Z`;
}

// Monotone cubic (Fritsch-Carlson): smooth, but never above or below the
// values it passes through, so a smoothed peak is still the real peak.
function smoothPath(points: [number, number][]) {
  const n = points.length;
  const at = ([x, y]: [number, number]) => `${x.toFixed(1)},${y.toFixed(1)}`;
  if (n < 3) return `M${points.map(at).join("L")}`;
  const dx: number[] = [];
  const slope: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(points[i + 1][0] - points[i][0]);
    slope.push((points[i + 1][1] - points[i][1]) / dx[i]);
  }
  const t = points.map((_, i) =>
    i === 0
      ? slope[0]
      : i === n - 1
        ? slope[n - 2]
        : slope[i - 1] * slope[i] <= 0
          ? 0
          : (slope[i - 1] + slope[i]) / 2,
  );
  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) {
      t[i] = t[i + 1] = 0;
      continue;
    }
    const a = t[i] / slope[i];
    const b = t[i + 1] / slope[i];
    const sum = a * a + b * b;
    if (sum > 9) {
      const k = 3 / Math.sqrt(sum);
      t[i] = k * a * slope[i];
      t[i + 1] = k * b * slope[i];
    }
  }
  let path = `M${at(points[0])}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    const step = dx[i] / 3;
    path += `C${at([x0 + step, y0 + t[i] * step])} ${at([x1 - step, y1 - t[i + 1] * step])} ${at([x1, y1])}`;
  }
  return path;
}

// Consecutive known values; a missing one ends a run instead of being drawn
// through (an unobserved hour is not zero).
function runs(values: (number | null | undefined)[]) {
  const result: { start: number; values: number[] }[] = [];
  values.forEach((value, index) => {
    if (value == null) return;
    const last = result.at(-1);
    if (last && last.start + last.values.length === index)
      last.values.push(value);
    else result.push({ start: index, values: [value] });
  });
  return result;
}

// Breaks the path at missing values instead of drawing through them.
function linePath(points: ([number, number] | null)[]) {
  let path = "";
  let open = false;
  for (const point of points) {
    if (!point) {
      open = false;
      continue;
    }
    path += `${open ? "L" : "M"}${point[0].toFixed(1)},${point[1].toFixed(1)}`;
    open = true;
  }
  return path;
}

function Tooltip({
  x,
  width,
  lines,
}: {
  x: number;
  width: number;
  lines: string[];
}) {
  // Beside the hovered mark, inside the plot, so it never covers the summary.
  const flip = x > width * 0.6;
  return (
    <div
      className={flip ? "trend-tooltip is-left" : "trend-tooltip"}
      style={{ left: flip ? x - 12 : x + 12, top: PAD.top }}
      role="presentation"
    >
      <strong>{lines[0]}</strong>
      {lines.slice(1).map((line) => (
        <span key={line}>{line}</span>
      ))}
    </div>
  );
}

function YGrid({
  max,
  width,
  format,
}: {
  max: number;
  width: number;
  format: (value: number) => string;
}) {
  const plot = HEIGHT - PAD.top - PAD.bottom;
  return (
    <g className="trend-grid">
      {[0, 0.5, 1].map((share) => {
        const y = PAD.top + plot * (1 - share);
        return (
          <g key={share}>
            <line x1={PAD.left} x2={width - PAD.right} y1={y} y2={y} />
            <text x={PAD.left - 6} y={y + 3} textAnchor="end">
              {format(max * share)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

export function BarLineChart({
  bars,
  label,
  color,
  reference,
  referenceName,
  describe,
}: {
  bars: Bar[];
  label: string;
  color: string;
  // area: a soft "usual day" shape behind the bars; line: a thin smooth line.
  reference: "area" | "line";
  referenceName: string;
  describe: (bar: Bar) => string[];
}) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const plot = HEIGHT - PAD.top - PAD.bottom;
  const base = PAD.top + plot;
  const max = niceMax(
    Math.max(0, ...bars.flatMap((bar) => [bar.value ?? 0, bar.line ?? 0])),
  );
  const slot = (width - PAD.left - PAD.right) / Math.max(1, bars.length);
  const barWidth = Math.max(2, Math.min(MAX_BAR, slot - GAP));
  const center = (index: number) => PAD.left + slot * (index + 0.5);
  const y = (value: number) => base - (value / max) * plot;
  const segments = runs(bars.map((bar) => bar.line));
  const hasLine = segments.length > 0;
  // Each run spans its slots edge to edge, so a lone hour is still a shape.
  const areas = segments.map(({ start, values }) => {
    const left = PAD.left + slot * start;
    const right = left + slot * values.length;
    const top = smoothPath([
      [left, y(values[0])],
      ...values.map((value, i): [number, number] => [
        center(start + i),
        y(value),
      ]),
      [right, y(values.at(-1)!)],
    ]);
    return { top, fill: `${top}L${right},${base}L${left},${base}Z` };
  });
  const lines = segments.map(({ start, values }) =>
    smoothPath(
      values.map((value, i): [number, number] => [center(start + i), y(value)]),
    ),
  );
  return (
    <div
      className="trend-chart"
      ref={ref}
      style={{ "--series": color } as CSSProperties}
      onMouseLeave={() => setHover(null)}
    >
      <svg width={width} height={HEIGHT} role="img" aria-label={label}>
        <YGrid max={max} width={width} format={shortTokens} />
        {reference === "area" &&
          areas.map((area, index) => (
            <g key={index}>
              <path className="trend-reference" d={area.fill} />
              <path className="trend-reference-edge" d={area.top} />
            </g>
          ))}
        {bars.map((bar, index) => {
          if (bar.future) return null;
          const x = center(index) - barWidth / 2;
          if (bar.value == null)
            return (
              <rect
                key={index}
                className="trend-unknown"
                x={x}
                y={base - 3}
                width={barWidth}
                height={3}
              />
            );
          const top = Math.min(base - 1, y(bar.value));
          return (
            <path
              key={index}
              className={
                bar.current || hover === index
                  ? "trend-bar is-current"
                  : "trend-bar"
              }
              d={barPath(x, top, barWidth, base)}
            />
          );
        })}
        {reference === "line" &&
          lines.map((line, index) => (
            <g key={index}>
              <path className="trend-line-halo" d={line} />
              <path className="trend-line is-reference" d={line} />
            </g>
          ))}
        {bars.map((bar, index) =>
          bar.tick ? (
            <text
              key={index}
              className="trend-axis"
              x={center(index)}
              y={HEIGHT - 6}
              textAnchor="middle"
            >
              {bar.label}
            </text>
          ) : null,
        )}
        {bars.map((_, index) => (
          <rect
            key={index}
            className="trend-hit"
            x={PAD.left + slot * index}
            y={PAD.top}
            width={slot}
            height={plot}
            onMouseEnter={() => setHover(index)}
          />
        ))}
      </svg>
      {hover != null && !bars[hover].future && (
        <Tooltip
          x={center(hover)}
          width={width}
          lines={describe(bars[hover])}
        />
      )}
      {hasLine && (
        <div className="trend-legend" aria-hidden="true">
          <span>
            <i className="swatch-bar" />
            {t("message.1259")}
          </span>
          <span>
            <i className={`swatch-${reference}`} />
            {referenceName}
          </span>
        </div>
      )}
    </div>
  );
}

export function RemainingChart({
  points,
  resets,
  day,
  now,
  label,
  color,
}: {
  points: [string, number][];
  resets: string[];
  day: Date; // local midnight of the shown day
  now: Date;
  label: string;
  color: string;
}) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const plot = HEIGHT - PAD.top - PAD.bottom;
  const base = PAD.top + plot;
  const start = day.getTime();
  const span = DAY_MS;
  const right = width - PAD.right;
  const x = (time: number) =>
    PAD.left + ((time - start) / span) * (right - PAD.left);
  const y = (value: number) => base - (value / 100) * plot;
  const values = points.map(
    ([at, value]) => [new Date(at).getTime(), value] as [number, number],
  );
  const nowTime = Math.min(now.getTime(), start + span);
  // The last known value holds until now; drawn fainter, as it is not observed.
  const last = values.at(-1);
  const held =
    last && last[0] < nowTime
      ? `M${x(last[0])},${y(last[1])}H${x(nowTime)}`
      : "";
  const line = linePath(values.map(([t, v]) => [x(t), y(v)]));
  const area = values.length
    ? `${line}L${x(values.at(-1)![0])},${base}L${x(values[0][0])},${base}Z`
    : "";
  const ticks = [0, 6, 12, 18, 24];
  const pick = (clientX: number, box: DOMRect) => {
    if (!values.length) return null;
    const time =
      start + ((clientX - box.left - PAD.left) / (right - PAD.left)) * span;
    let best = 0;
    values.forEach(([t], index) => {
      if (Math.abs(t - time) < Math.abs(values[best][0] - time)) best = index;
    });
    return best;
  };
  const hovered = hover == null ? null : values[hover];
  return (
    <div
      className="trend-chart"
      ref={ref}
      style={{ "--series": color } as CSSProperties}
      onMouseLeave={() => setHover(null)}
    >
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        aria-label={label}
        onMouseMove={(event) =>
          setHover(
            pick(event.clientX, event.currentTarget.getBoundingClientRect()),
          )
        }
      >
        <YGrid max={100} width={width} format={(v) => `${v}%`} />
        {resets.map((at) => {
          const rx = x(new Date(at).getTime());
          return (
            <line
              key={at}
              className="trend-reset"
              x1={rx}
              x2={rx}
              y1={PAD.top}
              y2={base}
            />
          );
        })}
        {area && <path className="trend-area" d={area} />}
        {held && <path className="trend-line is-held" d={held} />}
        {line && <path className="trend-line" d={line} />}
        {last && !hovered && (
          <circle
            className="trend-dot"
            cx={x(last[0])}
            cy={y(last[1])}
            r={3.5}
          />
        )}
        <line
          className="trend-now"
          x1={x(nowTime)}
          x2={x(nowTime)}
          y1={PAD.top}
          y2={base}
        />
        {ticks.map((hour) => (
          <text
            key={hour}
            className="trend-axis"
            x={x(start + hour * 3600000)}
            y={HEIGHT - 6}
            textAnchor={hour === 0 ? "start" : hour === 24 ? "end" : "middle"}
          >
            {hour}
            {t("message.1260")}
          </text>
        ))}
        {hovered && (
          <>
            <line
              className="trend-crosshair"
              x1={x(hovered[0])}
              x2={x(hovered[0])}
              y1={PAD.top}
              y2={base}
            />
            <circle
              className="trend-dot"
              cx={x(hovered[0])}
              cy={y(hovered[1])}
              r={4}
            />
          </>
        )}
      </svg>
      {hovered && (
        <Tooltip
          x={x(hovered[0])}
          width={width}
          lines={[
            new Date(hovered[0]).toLocaleTimeString(locale(), {
              hour: "2-digit",
              minute: "2-digit",
            }),
            t("message.1261", { value0: hovered[1] }),
          ]}
        />
      )}
    </div>
  );
}
