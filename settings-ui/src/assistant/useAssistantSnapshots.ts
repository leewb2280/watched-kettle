import { useEffect, useRef, useState } from "react";
import type {
  ActivityResponse,
  IntegrationResponse,
  Page,
  Shell,
  UsageResponse,
} from "../types";
export function useAssistantSnapshots(
  page: Page,
  visible: boolean,
  eventVersion: number,
  reportError: Shell["reportError"],
) {
  const shell = { visible, eventVersion };

  const [usage, setUsage] = useState<UsageResponse | null>(null);

  const [activity, setActivity] = useState<ActivityResponse | null>(null);

  const [integration, setIntegration] = useState<IntegrationResponse | null>(
    null,
  );

  const sequence = useRef(0);

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
    if (sources.includes("usage"))
      window
        .settings!.request("usage.snapshot")
        .then((value) => {
          if (id === sequence.current) setUsage(value);
        })
        .catch(reportError);
    if (sources.includes("activity"))
      window
        .settings!.request("activity.snapshot")
        .then((value) => {
          if (id === sequence.current) setActivity(value);
        })
        .catch(reportError);
    if (sources.includes("integration"))
      window
        .settings!.request("integration.snapshot")
        .then((value) => {
          if (id === sequence.current) setIntegration(value);
        })
        .catch(reportError);
    return () => {
      ++sequence.current;
    };
  }, [page, shell.eventVersion, shell.visible]);
  return {
    usage,
    setUsage,
    activity,
    setActivity,
    integration,
    setIntegration,
  };
}
