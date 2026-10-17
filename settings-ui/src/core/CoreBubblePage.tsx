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
      <Heading
        title="말풍선"
        subtitle="말풍선 디자인과 표시 방식, 표시 시간을 설정합니다."
      />
      <div className="bubble-intro-card card">
        <div className="bubble-intro">
          <span className="large-icon">
            <Palette size={30} />
          </span>
          <div className="bubble-intro-copy">
            <h2>말풍선 디자인</h2>
            <p>
              색, 모양, 장식부터 글자와 여백까지.
              <br />
              미리보기로 확인하고 마음에 들 때 적용하세요.
            </p>
          </div>
          <div className="bubble-intro-actions">
            <button
              className="button"
              onClick={() => call("pet.action", { action: "preview" })}
            >
              <Eye size={15} />
              펫에서 미리보기
            </button>
            <button className="button primary" onClick={openEditor}>
              <Sparkles size={15} />
              말풍선 꾸미기
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
                "표시 시간": (
                  <button
                    className="text-button"
                    disabled={!hasDurationOverrides}
                    onClick={() =>
                      call("pet.action", {
                        action: "duration_overrides_reset",
                      })
                    }
                  >
                    종류별 시간을 기본값으로
                  </button>
                ),
              }
            : undefined
        }
      />
      {snapshot.edition === "pet-assistant" && (
        <Section title="알림 잠시 쉬기">
          <div className="snooze-card">
            <div className="snooze-copy">
              {!snapshot.pet.bubbles_enabled ? (
                <>
                  <strong>말풍선 알림이 꺼져 있습니다</strong>
                  <p>알림을 켜면 잠시 쉬는 시간을 선택할 수 있어요.</p>
                </>
              ) : snapshot.pet.bubbles_snoozed ? (
                <>
                  <strong>알림 쉬는 중</strong>
                  <p>
                    약 {snapshot.pet.bubble_snooze_remaining_minutes}분 남음
                  </p>
                </>
              ) : (
                <>
                  <strong>필요할 때 잠시 조용하게</strong>
                  <p>
                    선택한 시간 동안 말풍선을 모두 숨깁니다. 그동안 온 일반·일정
                    알림은 나중에 다시 띄우지 않고, 아직 진행 중인 작업은 다시
                    나타나요.
                  </p>
                </>
              )}
            </div>
            <div className="snooze-actions">
              {snapshot.pet.bubbles_snoozed && snapshot.pet.bubbles_enabled ? (
                <button
                  className="button"
                  onClick={() => call("pet.action", { action: "resume" })}
                >
                  지금 다시 표시
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
                    {minutes}분
                  </button>
                ))
              )}
            </div>
          </div>
        </Section>
      )}
      {snapshot.edition === "pet-only" && (
        <p className="footnote">
          펫만 구성에서는 디자인과 미리보기를 제공합니다. 비서 알림은 생성하지
          않습니다.
        </p>
      )}
    </div>
  );
}
