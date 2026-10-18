import { t } from "../../localization.cjs";
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
    <Section title={t("message.0323")}>
      <div className="widget-preview">
        <div className="widget-preview-stage">
          {preview ? (
            <img
              src={preview.image}
              width={preview.width}
              height={preview.height}
              alt={t("message.0960")}
            />
          ) : (
            <span className="quiet-row">{failed || t("message.0961")}</span>
          )}
        </div>
        <div className="widget-preview-options">
          <span
            className="segmented"
            role="group"
            aria-label={t("message.0962")}
          >
            <button aria-pressed={!example} onClick={() => setExample(false)}>
              {t("message.0963")}
            </button>
            <button aria-pressed={example} onClick={() => setExample(true)}>
              {t("message.0422")}
            </button>
          </span>
          {chips && (
            <span
              className="segmented"
              role="group"
              aria-label={t("message.0964")}
            >
              <button
                aria-pressed={!unfolded}
                onClick={() => setUnfolded(false)}
              >
                {t("message.0965")}
              </button>
              <button aria-pressed={unfolded} onClick={() => setUnfolded(true)}>
                {t("message.0966")}
              </button>
            </span>
          )}
        </div>
        <p className="field-description">
          {failed && preview
            ? failed
            : preview?.sample && !example
              ? t("message.0967")
              : t("message.0968")}
          {acrylic && t("message.0969")}
        </p>
      </div>
    </Section>
  );
}
