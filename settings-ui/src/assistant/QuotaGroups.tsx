import type { UsageResponse } from "../types";
import { isStale, number, quotaTone, time } from "./presentation";

export function QuotaGroups({
  usage,
  compact = false,
}: {
  usage: UsageResponse;
  compact?: boolean;
}) {
  return (
    <div className="quota-groups">
      {!(usage.limit_groups || []).length && (
        <p className="quiet-row">두 도구의 사용량이 꺼져 있습니다.</p>
      )}
      {(usage.limit_groups || []).map((group) => (
        <section
          className="quota-provider"
          data-provider={group.key}
          key={group.key}
        >
          <h3>{group.label}</h3>
          {group.limits.length ? (
            <div className={compact ? "" : "quota-grid"}>
              {group.limits.map((limit) => {
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
