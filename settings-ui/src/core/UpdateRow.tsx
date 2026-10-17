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
    (state === "available" || state === "downloading" || state === "error");
  let action = null;
  if (state === "available" && update.can_install) {
    action = (
      <button
        className="button primary"
        onClick={() => call("update.download")}
      >
        <Download size={14} />
        업데이트
      </button>
    );
  } else if (state === "downloading") {
    action = (
      <button className="button" onClick={() => call("update.cancel")}>
        취소
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
        다시 시도
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
        업데이트 확인
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
                변경 사항 보기
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
              aria-label="업데이트 내려받기"
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
