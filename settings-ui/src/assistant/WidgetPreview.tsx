import { useEffect, useRef, useState } from "react";
import { Section } from "../components";
import { errorText } from "../errors";
import type {
  UsageResponse,
  WidgetPreview as WidgetPreviewData,
} from "../types";

// The real Qt Quick widget drawn offscreen with the current settings, so the
// preview cannot drift from what appears next to the pet.
export function WidgetPreview({ usage }: { usage: UsageResponse }) {
  const [example, setExample] = useState(false);
  const [unfolded, setUnfolded] = useState(false);
  const [preview, setPreview] = useState<WidgetPreviewData | null>(null);
  const [failed, setFailed] = useState("");
  const sequence = useRef(0);
  const chips =
    (usage.controls || []).find((c) => c.key === "widget_shape")?.value ===
    "chips";
  const acrylic =
    (usage.controls || []).find((c) => c.key === "widget_material")?.value ===
    "acrylic";
  useEffect(() => {
    const id = ++sequence.current;
    // A change arrives as a few snapshots in a row; draw once they settle.
    const timer = window.setTimeout(() => {
      window
        .settings!.request("usage.widget_preview", {
          sample: example,
          expanded: chips && unfolded,
        })
        .then((value) => {
          if (id !== sequence.current) return;
          setPreview(value);
          setFailed("");
        })
        .catch((error: unknown) => {
          if (id === sequence.current) setFailed(errorText(error));
        });
    }, 150);
    return () => window.clearTimeout(timer);
  }, [usage, example, unfolded, chips]);
  return (
    <Section title="미리보기">
      <div className="widget-preview">
        <div className="widget-preview-stage">
          {preview ? (
            <img
              src={preview.image}
              width={preview.width}
              height={preview.height}
              alt="현재 설정의 사용량 위젯 미리보기"
            />
          ) : (
            <span className="quiet-row">
              {failed || "미리보기를 그리는 중입니다."}
            </span>
          )}
        </div>
        <div className="widget-preview-options">
          <span className="segmented" role="group" aria-label="미리보기 값">
            <button aria-pressed={!example} onClick={() => setExample(false)}>
              지금 값
            </button>
            <button aria-pressed={example} onClick={() => setExample(true)}>
              예시 값
            </button>
          </span>
          {chips && (
            <span className="segmented" role="group" aria-label="칩 모양">
              <button
                aria-pressed={!unfolded}
                onClick={() => setUnfolded(false)}
              >
                평소
              </button>
              <button aria-pressed={unfolded} onClick={() => setUnfolded(true)}>
                마우스를 올렸을 때
              </button>
            </span>
          )}
        </div>
        <p className="field-description">
          {failed && preview
            ? failed
            : preview?.sample && !example
              ? "아직 받은 한도가 없어 예시 값으로 보여 줍니다."
              : "펫 옆 위젯과 같은 방식으로 그린 모습입니다. 설정을 바꾸면 바로 반영됩니다."}
          {acrylic &&
            " 아크릴은 실제 위젯에서만 뒤를 흐리게 비추므로, 미리보기는 어두운 바탕 위의 색으로 보여 줍니다."}
        </p>
      </div>
    </Section>
  );
}
