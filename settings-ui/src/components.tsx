import { t } from "../localization.cjs";
import { Check, Info, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type {
  Control,
  HotkeyControl,
  NumberControl,
  OptionalControl,
  Scalar,
} from "./types";

export function Section({
  title,
  children,
  note,
  hideTitle,
}: {
  title: string;
  children: ReactNode;
  note?: string;
  hideTitle?: boolean;
}) {
  return (
    <section className="section" aria-label={hideTitle ? title : undefined}>
      {!hideTitle && (
        <div className="section-heading">
          <h2>{title}</h2>
          {note && <span>{note}</span>}
        </div>
      )}
      <div className="card">{children}</div>
    </section>
  );
}
export function Switch({
  label,
  value,
  change,
  disabled,
  id,
  describedBy,
}: {
  label: string;
  value: boolean;
  change: (v: boolean) => void;
  disabled?: boolean;
  id?: string;
  describedBy?: string;
}) {
  return (
    <button
      id={id}
      aria-describedby={describedBy}
      disabled={disabled}
      role="switch"
      aria-label={label}
      aria-checked={value}
      className="switch"
      onClick={() => change(!value)}
    >
      <span />
    </button>
  );
}
// A small "i" whose text shows on hover and on keyboard focus.
export function InfoTip({ label, text }: { label: string; text: string }) {
  const id = useId();
  return (
    <span
      className="info-tip"
      tabIndex={0}
      role="img"
      aria-label={label}
      aria-describedby={id}
    >
      <Info size={13} aria-hidden="true" />
      <span className="info-tip-text" role="tooltip" id={id}>
        {text}
      </span>
    </span>
  );
}
export function Modal({
  title,
  children,
  close,
  footer,
  error,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
  footer?: ReactNode;
  // Rendered inside the dialog: page banners and toasts sit under its backdrop.
  error?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current!;
    d.showModal();
    return () => d.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <button
          className="icon-button"
          aria-label={t("message.0970")}
          onClick={close}
        >
          <X size={18} />
        </button>
      </div>
      <div className="modal-content">
        {error && (
          <div className="error-banner modal-error" role="alert">
            <Info size={17} />
            {error}
          </div>
        )}
        {children}
      </div>
      {footer && <div className="modal-footer">{footer}</div>}
    </dialog>
  );
}
export function Range({
  field,
  change,
}: {
  field: NumberControl;
  change: (value: Scalar | undefined) => void;
}) {
  const [value, setValue] = useState(field.value ?? field.min ?? 0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const latest = useRef(value);
  const dirty = useRef(false);
  const callback = useRef(change);
  callback.current = change;
  useEffect(() => {
    if (!dirty.current) {
      setValue(field.value);
      latest.current = field.value;
    }
  }, [field.value]);
  useEffect(
    () => () => {
      clearTimeout(timer.current);
      if (dirty.current) {
        dirty.current = false;
        callback.current(latest.current);
      }
    },
    [],
  );
  const flush = () => {
    clearTimeout(timer.current);
    if (dirty.current) {
      dirty.current = false;
      change(latest.current);
    }
  };
  const displayValue = `${value}${field.unit ?? ""}`;
  return (
    <div className="range-control">
      <input
        id={`field-${field.key}`}
        type="range"
        aria-label={field.label}
        aria-valuetext={displayValue}
        min={field.min}
        max={field.max}
        step={field.step ?? 1}
        value={value}
        disabled={field.disabled}
        onChange={(event) => {
          const next = +event.target.value;
          setValue(next);
          latest.current = next;
          dirty.current = true;
          clearTimeout(timer.current);
          timer.current = setTimeout(flush, 180);
        }}
        onPointerUp={flush}
        onKeyUp={flush}
        onBlur={flush}
      />
      <output htmlFor={`field-${field.key}`}>{displayValue}</output>
    </div>
  );
}

export function PetSize({
  field,
  change,
}: {
  field: NumberControl;
  change: (value: number) => void;
}) {
  const [value, setValue] = useState<number>(field.value);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const latest = useRef(value);
  const dirty = useRef(false);
  const callback = useRef(change);
  callback.current = change;
  useEffect(() => {
    if (!dirty.current) {
      setValue(field.value);
      latest.current = field.value;
    }
  }, [field.value]);
  useEffect(
    () => () => {
      clearTimeout(timer.current);
      if (dirty.current) {
        dirty.current = false;
        callback.current(latest.current);
      }
    },
    [],
  );
  const flush = () => {
    clearTimeout(timer.current);
    if (dirty.current) {
      dirty.current = false;
      change(latest.current);
    }
  };
  const selectPreset = (next: number) => {
    clearTimeout(timer.current);
    dirty.current = false;
    latest.current = next;
    setValue(next);
    change(next);
  };
  const valueLabel =
    field.options?.find((option) => option.value === value)?.label ??
    `${value}px`;
  const sliderIndex = Math.max(
    0,
    field.options?.findIndex((option) => option.value === value) ?? 0,
  );
  return (
    <div className="pet-size-control">
      <output className="pet-size-value" aria-live="polite">
        {valueLabel}
      </output>
      <input
        id={`field-${field.key}`}
        type="range"
        aria-label={field.label}
        aria-valuetext={valueLabel}
        min={0}
        max={Math.max(0, (field.options?.length ?? 1) - 1)}
        step={1}
        value={sliderIndex}
        onChange={(event) => {
          const next = field.options?.[+event.target.value]?.value;
          if (typeof next !== "number") return;
          setValue(next);
          latest.current = next;
          dirty.current = true;
          clearTimeout(timer.current);
          timer.current = setTimeout(flush, 180);
        }}
        onPointerUp={flush}
        onKeyUp={flush}
        onBlur={flush}
      />
      {field.description && (
        <p className="pet-size-description">{field.description}</p>
      )}
      <div className="pet-size-presets" aria-label={t("message.0971")}>
        {field.presets?.map((preset) => (
          <button
            className="button compact"
            type="button"
            key={String(preset.value)}
            aria-pressed={value === preset.value}
            onClick={() => selectPreset(Number(preset.value))}
          >
            {preset.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function OptionalNumber({
  field,
  change,
}: {
  field: OptionalControl;
  change: (value: number | null) => void;
}) {
  const initial = field.value ?? field.effectiveValue ?? field.min ?? 0;
  const [value, setValue] = useState<number>(initial);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const latest = useRef(value);
  const dirty = useRef(false);
  const callback = useRef(change);
  callback.current = change;
  const enabled = field.value !== null;
  useEffect(() => {
    if (!dirty.current) {
      const next = field.value ?? field.effectiveValue ?? field.min ?? 0;
      setValue(next);
      latest.current = next;
    }
  }, [field.value, field.effectiveValue, field.min]);
  useEffect(
    () => () => {
      clearTimeout(timer.current);
      if (dirty.current) {
        dirty.current = false;
        callback.current(latest.current);
      }
    },
    [],
  );
  const flush = () => {
    clearTimeout(timer.current);
    if (dirty.current) {
      dirty.current = false;
      change(latest.current);
    }
  };
  const toggle = (nextEnabled: boolean) => {
    clearTimeout(timer.current);
    dirty.current = false;
    if (nextEnabled) {
      const next = field.effectiveValue ?? value;
      setValue(next);
      latest.current = next;
      change(next);
    } else {
      change(null);
    }
  };
  const displayValue = `${value}${field.unit ?? ""}`;
  const policyText = enabled
    ? t("message.0972", { value0: displayValue })
    : `${field.fallbackLabel ?? t("message.0973")} · ${
        field.effectiveValue ?? value
      }${field.unit ?? ""}`;
  return (
    <div className="optional-number-control">
      <div className="optional-number-heading">
        <span className="optional-number-policy">{policyText}</span>
        <span className="optional-number-toggle">
          <span>{t("message.0974")}</span>
          <Switch
            label={t("message.0975", { value0: field.label })}
            value={enabled}
            change={toggle}
            disabled={field.disabled}
          />
        </span>
      </div>
      <div className="range-control">
        <input
          id={`field-${field.key}`}
          type="range"
          aria-label={t("message.0976", { value0: field.label })}
          aria-valuetext={displayValue}
          min={field.min}
          max={field.max}
          step={field.step ?? 1}
          value={value}
          disabled={!enabled || field.disabled}
          onChange={(event) => {
            const next = +event.target.value;
            setValue(next);
            latest.current = next;
            dirty.current = true;
            clearTimeout(timer.current);
            timer.current = setTimeout(flush, 180);
          }}
          onPointerUp={flush}
          onKeyUp={flush}
          onBlur={flush}
        />
        <output htmlFor={`field-${field.key}`}>{displayValue}</output>
      </div>
    </div>
  );
}
// Commits only in-range numbers while typing; on blur an empty or out-of-range
// entry is restored or clamped, so the field always shows the value in use.
export function NumberInput({
  field,
  change,
}: {
  field: Control;
  change: (value: number) => void;
}) {
  const [text, setText] = useState(String(field.value ?? ""));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(String(field.value ?? ""));
  }, [field.value]);
  const min = field.min ?? -Infinity;
  const max = field.max ?? Infinity;
  const settle = () => {
    const parsed = Number(text);
    if (text.trim() === "" || !Number.isFinite(parsed)) {
      setText(String(field.value ?? ""));
      return;
    }
    const clamped = Math.min(Math.max(parsed, min), max);
    setText(String(clamped));
    if (clamped !== field.value) change(clamped);
  };
  const hasRange = field.min !== undefined && field.max !== undefined;
  return (
    <span className="number-input">
      <input
        id={`field-${field.key}`}
        type="number"
        inputMode="decimal"
        min={field.min}
        max={field.max}
        step={field.step}
        value={text}
        aria-describedby={hasRange ? `field-${field.key}-range` : undefined}
        onFocus={() => (focused.current = true)}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          const parsed = Number(next);
          if (
            next.trim() !== "" &&
            Number.isFinite(parsed) &&
            parsed >= min &&
            parsed <= max
          )
            change(parsed);
        }}
        onBlur={() => {
          focused.current = false;
          settle();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") settle();
        }}
      />
      {hasRange && (
        <small id={`field-${field.key}-range`} className="number-range">
          {field.min}–{field.max}
          {field.unit ?? ""}
        </small>
      )}
    </span>
  );
}
// The spelling Python's preferences.hotkeys accepts: Ctrl or Alt, then one key.
const HOTKEY_KEY = /^(?:[A-Z0-9]|F(?:[1-9]|1[0-9]|2[0-4]))$/;
const MODIFIER_KEYS = new Set(["Control", "Alt", "Shift", "Meta", "AltGraph"]);

export function hotkeyFromEvent(event: KeyboardEvent): string | null {
  const code = event.code;
  const key = code.startsWith("Key")
    ? code.slice(3)
    : code.startsWith("Digit")
      ? code.slice(5)
      : code;
  if (
    !HOTKEY_KEY.test(key) ||
    !(event.ctrlKey || event.altKey) ||
    event.metaKey
  )
    return null;
  return [
    event.ctrlKey && "Ctrl",
    event.altKey && "Alt",
    event.shiftKey && "Shift",
    key,
  ]
    .filter(Boolean)
    .join("+");
}

function HotkeyInput({
  field,
  change,
}: {
  field: HotkeyControl;
  change: (value: Scalar | undefined) => void;
}) {
  const [recording, setRecording] = useState(false);
  const [rejected, setRejected] = useState(false);
  useEffect(() => {
    if (!recording) return;
    // Capture on window so the app's own Alt+number shortcuts stay quiet.
    const record = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
      if (MODIFIER_KEYS.has(event.key)) return;
      if (
        event.key === "Escape" &&
        !event.ctrlKey &&
        !event.altKey &&
        !event.shiftKey
      ) {
        setRecording(false);
        return;
      }
      const text = hotkeyFromEvent(event);
      setRejected(text === null);
      if (text === null) return;
      setRecording(false);
      change(text);
    };
    const stop = () => setRecording(false);
    window.addEventListener("keydown", record, true);
    window.addEventListener("blur", stop);
    return () => {
      window.removeEventListener("keydown", record, true);
      window.removeEventListener("blur", stop);
    };
  }, [recording, change]);
  const status =
    rejected || field.status === "invalid"
      ? t("hotkey.invalid")
      : field.status === "in_use"
        ? t("hotkey.in_use")
        : field.status === "unavailable"
          ? t("hotkey.unavailable")
          : "";
  return (
    <span
      className="hotkey-input"
      role="group"
      aria-labelledby={`field-${field.key}-label`}
    >
      <span className="hotkey-row">
        <kbd
          id={`field-${field.key}`}
          className={
            recording ? "is-recording" : field.value ? undefined : "is-empty"
          }
          aria-live="polite"
        >
          {recording
            ? t("hotkey.recording")
            : field.value || t("hotkey.unassigned")}
        </kbd>
        <button
          className="button"
          disabled={field.disabled || recording}
          onClick={() => {
            setRejected(false);
            setRecording(true);
          }}
        >
          {field.value ? t("hotkey.change") : t("hotkey.assign")}
        </button>
        {field.value && !recording && (
          <button
            className="text-button"
            disabled={field.disabled}
            onClick={() => change("")}
          >
            {t("hotkey.clear")}
          </button>
        )}
      </span>
      {status && (
        <small className="hotkey-status" role="status">
          {status}
        </small>
      )}
    </span>
  );
}
export function Field({
  field,
  change,
  extra,
}: {
  field: Control;
  change: (value: Scalar | undefined) => void;
  extra?: ReactNode;
}) {
  const described =
    field.description && field.kind !== "pet_size"
      ? `field-${field.key}-description`
      : undefined;
  return (
    <div
      className={`setting-row ${
        field.kind === "pet_size" ? "pet-size-row" : ""
      } ${field.kind === "optional_number" ? "optional-number-row" : ""} ${
        field.disabled ? "is-disabled" : ""
      }`}
    >
      {field.description && field.kind !== "pet_size" ? (
        <div className="field-label">
          <label id={`field-${field.key}-label`} htmlFor={`field-${field.key}`}>
            {field.label}
          </label>
          <p
            id={`field-${field.key}-description`}
            className="field-description"
          >
            {field.description}
          </p>
        </div>
      ) : (
        <label id={`field-${field.key}-label`} htmlFor={`field-${field.key}`}>
          {field.label}
        </label>
      )}
      <div className="row-control">
        {field.kind === "bool" ? (
          <Switch
            id={`field-${field.key}`}
            describedBy={described}
            label={field.label}
            value={field.value}
            change={change}
            disabled={field.disabled}
          />
        ) : field.kind === "pet_size" ? (
          <PetSize field={field} change={change} />
        ) : field.kind === "range" ? (
          <Range field={field} change={change} />
        ) : field.kind === "select" ? (
          <select
            id={`field-${field.key}`}
            aria-label={field.label}
            aria-describedby={described}
            disabled={field.disabled}
            value={String(field.value ?? "")}
            onChange={(event) =>
              change(
                field.options?.find(
                  (option) => String(option.value) === event.target.value,
                )?.value,
              )
            }
          >
            {!field.options?.some((option) => option.value === field.value) && (
              <option value={String(field.value ?? "")}>
                {field.value || t("message.0977")}
              </option>
            )}
            {field.options?.map((option) => (
              <option
                key={String(option.value)}
                value={String(option.value)}
                disabled={option.disabled}
              >
                {option.label}
              </option>
            ))}
          </select>
        ) : field.kind === "color" ? (
          <input
            id={`field-${field.key}`}
            type="color"
            value={field.value}
            onChange={(event) => change(event.target.value)}
          />
        ) : field.kind === "optional_number" ? (
          <OptionalNumber field={field} change={change} />
        ) : field.kind === "hotkey" ? (
          <HotkeyInput field={field} change={change} />
        ) : (
          <NumberInput field={field} change={change} />
        )}
        {extra}
      </div>
    </div>
  );
}
// One tab strip for every screen: click or arrow keys, Home and End select
// and focus a tab. The panel is `${id}-panel`, labelled by `${id}-tab-${key}`.
export function TabList({
  id,
  label,
  tabs,
  value,
  select,
  className = "tabs",
  tabClassName,
  disabled,
}: {
  id: string;
  label: string;
  tabs: [string, string][];
  value: string;
  select: (key: string) => void;
  className?: string;
  tabClassName?: string;
  disabled?: boolean;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = tabs.findIndex(([key]) => key === value);
  return (
    <div
      className={className}
      role="tablist"
      aria-label={label}
      onKeyDown={(event) => {
        const target = {
          ArrowRight: index + 1,
          ArrowLeft: index - 1,
          Home: 0,
          End: tabs.length - 1,
        }[event.key];
        if (target === undefined || disabled) return;
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
          className={tabClassName}
          role="tab"
          aria-selected={value === key}
          aria-controls={`${id}-panel`}
          tabIndex={value === key ? 0 : -1}
          disabled={disabled}
          onClick={() => select(key)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}
export function Fields({
  controls,
  change,
  groupFooters,
  hideTitles,
  fieldExtras,
  groupRows,
}: {
  controls: Control[];
  change: (key: string, value: Scalar | undefined) => void;
  groupFooters?: Record<string, ReactNode>;
  hideTitles?: boolean;
  fieldExtras?: Record<string, ReactNode>;
  groupRows?: Record<string, ReactNode>;
}) {
  return (
    <>
      {[
        ...new Set(controls.map((control) => control.groupId || control.group)),
      ].map((group) => (
        <Section
          title={
            controls.find((c) => (c.groupId || c.group) === group)?.group ||
            group
          }
          key={group}
          hideTitle={hideTitles}
        >
          {controls
            .filter((control) => (control.groupId || control.group) === group)
            .map((field) => (
              <Field
                key={field.key}
                field={field}
                change={(value) => change(field.key, value)}
                extra={fieldExtras?.[field.key]}
              />
            ))}
          {groupRows?.[group]}
          {groupFooters?.[group] && (
            <div className="section-footer">{groupFooters[group]}</div>
          )}
        </Section>
      ))}
    </>
  );
}
export function Heading({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading compact">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {children}
    </div>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}
export function Confirm({
  title,
  children,
  confirm,
  close,
  label = t("message.0317"),
  danger,
}: {
  title: string;
  children: ReactNode;
  confirm: () => void;
  close: () => void;
  label?: string;
  danger?: boolean;
}) {
  return (
    <Modal
      title={title}
      close={close}
      footer={
        <>
          <button className="button" onClick={close}>
            {t("message.0650")}
          </button>
          <button
            className={`button primary ${danger ? "destructive" : ""}`}
            onClick={confirm}
          >
            <Check size={14} />
            {label}
          </button>
        </>
      }
    >
      {children}
    </Modal>
  );
}
