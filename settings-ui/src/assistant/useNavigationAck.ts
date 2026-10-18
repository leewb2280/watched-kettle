import { t } from "../../localization.cjs";
import { useEffect, useRef } from "react";
import type {
  ActivityResponse,
  IntegrationResponse,
  NoticeRecord,
  Page,
  Shell,
  UsageResponse,
} from "../types";
export function useNavigationAck(
  shell: Pick<Shell, "route" | "visible">,
  page: Page,
  usage: UsageResponse | null,
  activity: ActivityResponse | null,
  integration: IntegrationResponse | null,
  notice: NoticeRecord | null,
  setNotice: (notice: NoticeRecord) => void,
  tab: string,
  setTab: (tab: string) => void,
  setFilter: (filter: string) => void,
  reportError: Shell["reportError"],
) {
  const acknowledged = useRef("");

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
        (row) => row.record_id === route.notice?.record_id,
      );
      if (!found) {
        reportError(new Error(t("message.0959")));
        return;
      }
      if (notice?.record_id !== found.record_id) {
        setNotice(found);
        return;
      }
    }
    if (route.filter)
      setFilter(
        (
          {
            usage: t("message.0204"),
            schedule: t("message.0205"),
            system: t("message.0202"),
          } as Record<string, string>
        )[route.filter] || "",
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
}
