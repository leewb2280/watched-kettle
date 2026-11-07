import { useCallback, useState } from "react";

// Tabs chosen in this app run. A hidden renderer is retired after a minute;
// Python keeps this map meanwhile and hands it to the next renderer, so
// reopening shows the same tab. Restarting the app starts over.
let remembered: Record<string, string> = {};

export function restoreTabs(tabs: Record<string, string> | undefined) {
  remembered = { ...(tabs || {}) };
}

export function rememberedTab<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  const saved = remembered[key] as T | undefined;
  return saved !== undefined && allowed.includes(saved) ? saved : fallback;
}

export function useRememberedTab<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): [T, (next: T) => void] {
  const [tab, setTab] = useState<T>(() =>
    rememberedTab(key, allowed, fallback),
  );
  const select = useCallback(
    (next: T) => {
      setTab(next);
      if (remembered[key] === next) return;
      remembered = { ...remembered, [key]: next };
      // View state only: losing it costs a tab, so a failure is not shown.
      window.settings
        ?.request("window.tabs", { tabs: remembered })
        .catch(() => {});
    },
    [key],
  );
  return [tab, select];
}
