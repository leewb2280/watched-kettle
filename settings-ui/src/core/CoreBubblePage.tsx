import { t } from "../../localization.cjs";
import { Eye, Palette, Sparkles } from "lucide-react";
import { Field, Fields, Heading, Section } from "../components";

import type { CoreSettingsState } from "./useCoreSettings";
export function CoreBubblePage({
  call,
  openEditor,
  themeControl,
  snapshot,
  change,
  hasDurationOverrides,
}: Pick<
  CoreSettingsState,
  | "call"
  | "openEditor"
  | "themeControl"
  | "snapshot"
  | "change"
  | "hasDurationOverrides"
>) {
  return (
    <div className="page">
      <Heading title={t("message.0592")} subtitle={t("message.1095")} />
      <div className="bubble-intro-card card">
        <div className="bubble-intro">
          <span className="large-icon">
            <Palette size={30} />
          </span>
          <div className="bubble-intro-copy">
            <h2>{t("message.1096")}</h2>
            <p>
              {t("message.1097")}
              <br />
              {t("message.1098")}
            </p>
          </div>
          <div className="bubble-intro-actions">
            <button
              className="button"
              onClick={() => call("pet.action", { action: "preview" })}
            >
              <Eye size={15} />
              {t("message.1099")}
            </button>
            <button className="button primary" onClick={openEditor}>
              <Sparkles size={15} />
              {t("message.1100")}
            </button>
          </div>
        </div>
        {themeControl && (
          <Field
            key={snapshot.pet.pet_id}
            field={themeControl}
            change={(value) => change(themeControl.key, value)}
          />
        )}
      </div>
      <Fields
        key={snapshot.pet.pet_id}
        controls={snapshot.bubbleControls.filter(
          (control) => control !== themeControl,
        )}
        change={change}
        groupFooters={
          snapshot.edition === "pet-assistant"
            ? {
                bubble_timing: (
                  <button
                    className="text-button"
                    disabled={!hasDurationOverrides}
                    onClick={() =>
                      call("pet.action", {
                        action: "duration_overrides_reset",
                      })
                    }
                  >
                    {t("message.1101")}
                  </button>
                ),
              }
            : undefined
        }
      />
      {snapshot.edition === "pet-assistant" && (
        <Section title={t("message.0222")}>
          <div className="snooze-card">
            <div className="snooze-copy">
              {!snapshot.pet.bubbles_enabled ? (
                <>
                  <strong>{t("message.1102")}</strong>
                  <p>{t("message.1103")}</p>
                </>
              ) : snapshot.pet.bubbles_snoozed ? (
                <>
                  <strong>{t("message.1104")}</strong>
                  <p>
                    {t("bubble.snooze_remaining", {
                      count: snapshot.pet.bubble_snooze_remaining_minutes,
                    })}
                  </p>
                </>
              ) : (
                <>
                  <strong>{t("message.1107")}</strong>
                  <p>{t("message.1108")}</p>
                </>
              )}
            </div>
            <div className="snooze-actions">
              {snapshot.pet.bubbles_snoozed && snapshot.pet.bubbles_enabled ? (
                <button
                  className="button"
                  onClick={() => call("pet.action", { action: "resume" })}
                >
                  {t("message.1109")}
                </button>
              ) : (
                ([15, 30, 60] as const).map((minutes) => (
                  <button
                    className="button"
                    key={minutes}
                    disabled={!snapshot.pet.bubbles_enabled}
                    onClick={() =>
                      call("pet.action", { action: "snooze", minutes })
                    }
                  >
                    {minutes}
                    {t("message.0831")}
                  </button>
                ))
              )}
            </div>
          </div>
        </Section>
      )}
      {snapshot.edition === "pet-only" && (
        <p className="footnote">{t("message.1110")}</p>
      )}
    </div>
  );
}
