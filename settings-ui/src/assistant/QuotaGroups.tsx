import { t } from "../../localization.cjs";
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
        <p className="quiet-row">{t("message.0898")}</p>
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
                const toneLabel = estimated ? t("message.0899") : quotaLabel;
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
                          <small>{t("message.0900")}</small>
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
                            ? t("message.0901", {
                                value0: time(limit.window.resets_at),
                                value1: estimated
                                  ? " " + t("widget.estimated")
                                  : "",
                              })
                            : estimated
                              ? t("message.0902")
                              : t("message.0903")}
                        </p>
                        {group.key === "claude_code" &&
                          usage.claude_code?.data?.limits_observed_at && (
                            <p className="quota-source">
                              {time(usage.claude_code.data.limits_observed_at)}{" "}
                              {t("message.0904")}
                              {isStale(
                                usage.claude_code.data.limits_observed_at,
                              )
                                ? t("message.0905")
                                : ""}
                            </p>
                          )}
                      </>
                    )}
                  </article>
                );
              })}
              {group.key === "claude_code" && !compact && (
                <p className="quota-note">{t("message.0906")}</p>
              )}
            </div>
          ) : (
            <p className="quiet-row">
              {group.key === "claude_code"
                ? usage.claude_code?.status_line === "installed"
                  ? t("message.0907")
                  : t("message.0908")
                : t("message.0909")}
            </p>
          )}
        </section>
      ))}
    </div>
  );
}
