import { t } from "../../localization.cjs";
import { Check, Download, RotateCcw } from "lucide-react";
import type { UpdateState } from "../types";

export function megabytes(bytes: number) {
  return (bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0);
}

// One row whose text and button follow UpdateService's state. Python owns the
// messages; this picks the action for each state.
export function UpdateRow({
  version,
  update,
  call,
}: {
  version: string;
  update: UpdateState;
  call: (
    method:
      | "update.download"
      | "update.apply"
      | "update.cancel"
      | "update.check"
      | "update.open",
  ) => unknown;
}) {
  const { state } = update;
  const percent =
    update.total > 0
      ? Math.min(100, Math.floor((update.received / update.total) * 100))
      : 0;
  const showPage =
    update.page_url !== "" &&
    (state === "available" ||
      state === "downloading" ||
      state === "staged" ||
      state === "error");
  let action = null;
  if (state === "available" && update.can_install) {
    action = (
      <button
        className="button primary"
        onClick={() => call("update.download")}
      >
        <Download size={14} />
        {t("message.1143")}
      </button>
    );
  } else if (state === "staged") {
    action = (
      <button className="button primary" onClick={() => call("update.apply")}>
        <RotateCcw size={14} />
        {t("update.restart_now")}
      </button>
    );
  } else if (state === "downloading") {
    action = (
      <button className="button" onClick={() => call("update.cancel")}>
        {t("message.0650")}
      </button>
    );
  } else if (state === "error") {
    action = (
      <button
        className="button"
        onClick={() =>
          call(update.retry === "download" ? "update.download" : "update.check")
        }
      >
        <RotateCcw size={14} />
        {t("message.0331")}
      </button>
    );
  } else if (state !== "installing" && state !== "preparing") {
    action = (
      <button
        className="button"
        disabled={state === "checking"}
        onClick={() => call("update.check")}
      >
        <RotateCcw size={14} />
        {t("message.0290")}
      </button>
    );
  }
  return (
    <div className="setting-row update-row">
      <div className="update-summary">
        <h3>Watched Kettle {version}</h3>
        <p aria-live="polite">
          {state === "current" && <Check size={12} className="update-ok" />}
          {update.message}
          {showPage && (
            <>
              {" · "}
              <button
                className="text-button inline"
                onClick={() => call("update.open")}
              >
                {t("message.1144")}
              </button>
            </>
          )}
        </p>
        {(state === "downloading" ||
          state === "preparing" ||
          state === "installing") && (
          <div className="update-progress">
            <div
              className="progress-track"
              role="progressbar"
              aria-label={t("message.1145")}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent}
            >
              <span style={{ width: `${percent}%` }} />
            </div>
            <output>
              {megabytes(update.received)} / {megabytes(update.total)}MB
            </output>
          </div>
        )}
      </div>
      {action}
    </div>
  );
}
