import { t } from "../../localization.cjs";
import { Empty, Fields, Heading, Section } from "../components";
import type { Control, UsageSetting } from "../types";
import { HourRange } from "./presentation";
import type { AssistantSettingsState } from "./useAssistantSettings";
import { WidgetPreview } from "./WidgetPreview";
export function AssistantWidgetPage({
  usage,
  call,
  widgetVisible,
}: Pick<AssistantSettingsState, "usage" | "call" | "widgetVisible">) {
  return (
    <div className="page">
      <Heading title={t("message.0494")} subtitle={t("message.0729")} />
      {!usage ? (
        <Empty>{t("message.0730")}</Empty>
      ) : (
        <>
          <WidgetPreview usage={usage} />
          <Fields
            controls={usage!.controls.filter((control: Control) =>
              ["widget", "widget_appearance"].includes(control.groupId || ""),
            )}
            change={(key, value) =>
              call("usage.set", { key, value } as UsageSetting)
            }
            groupFooters={{
              widget: (
                <span className="footer-actions">
                  <button
                    className="text-button"
                    disabled={!widgetVisible}
                    onClick={() =>
                      call("usage.action", { action: "reset_widget" })
                    }
                  >
                    {t("message.0731")}
                  </button>
                  <button
                    className="text-button"
                    disabled={!widgetVisible}
                    onClick={() =>
                      call("usage.action", { action: "reset_position" })
                    }
                  >
                    {t("message.0732")}
                  </button>
                </span>
              ),
              widget_appearance: (
                <span className="footer-actions">
                  <button
                    className="text-button"
                    disabled={!widgetVisible}
                    onClick={() =>
                      call("usage.action", { action: "reset_style" })
                    }
                  >
                    {t("message.0733")}
                  </button>
                  <button
                    className="text-button"
                    disabled={!widgetVisible}
                    onClick={() =>
                      call("usage.action", { action: "reset_scale" })
                    }
                  >
                    {t("message.0734")}
                  </button>
                </span>
              ),
            }}
          />
          <Section title={t("message.0735")}>
            <HourRange
              hours={[usage!.hours[0], usage!.hours[1]]}
              disabled={!widgetVisible}
              save={(value) =>
                call("usage.set", { key: "widget_hours", value })
              }
            />
            <div className="section-footer">
              <button
                className="text-button"
                disabled={!widgetVisible}
                onClick={() => call("usage.action", { action: "reset_hours" })}
              >
                {t("message.0736")}
              </button>
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
