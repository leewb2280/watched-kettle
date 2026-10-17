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
      <Heading
        title="위젯"
        subtitle="펫 옆 사용량 위젯의 모양과 표시 항목, 색과 크기를 설정합니다."
      />
      {!usage ? (
        <Empty>위젯 설정을 불러오는 중입니다.</Empty>
      ) : (
        <>
          <WidgetPreview usage={usage} />
          <Fields
            controls={usage!.controls.filter((control: Control) =>
              ["위젯", "위젯 외관"].includes(control.group),
            )}
            change={(key, value) =>
              call("usage.set", { key, value } as UsageSetting)
            }
            groupFooters={{
              위젯: (
                <span className="footer-actions">
                  <button
                    className="text-button"
                    disabled={!widgetVisible}
                    onClick={() =>
                      call("usage.action", { action: "reset_widget" })
                    }
                  >
                    기본 구성으로
                  </button>
                  <button
                    className="text-button"
                    disabled={!widgetVisible}
                    onClick={() =>
                      call("usage.action", { action: "reset_position" })
                    }
                  >
                    펫 옆으로 위치 복원
                  </button>
                </span>
              ),
              "위젯 외관": (
                <span className="footer-actions">
                  <button
                    className="text-button"
                    disabled={!widgetVisible}
                    onClick={() =>
                      call("usage.action", { action: "reset_style" })
                    }
                  >
                    기본 스타일로
                  </button>
                  <button
                    className="text-button"
                    disabled={!widgetVisible}
                    onClick={() =>
                      call("usage.action", { action: "reset_scale" })
                    }
                  >
                    기본 크기로
                  </button>
                </span>
              ),
            }}
          />
          <Section title="오늘 흐름 시간대">
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
                전체 24시간으로
              </button>
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
