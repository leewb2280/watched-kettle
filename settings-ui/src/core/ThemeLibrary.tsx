import { t } from "../../localization.cjs";
import { Download, FolderOutput, Save, Trash2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Section } from "../components";
import { errorText } from "../errors";
import type { BubbleThemeEntry, SpeechBubbleTheme } from "../types";
import { themeLabels, ThemeValues } from "./bubbleTheme";
import type { useBubbleEditor } from "./useBubbleEditor";

/** Saved designs and theme files; applying one replaces the draft. */
export function ThemeLibrary({
  bubble,
}: {
  bubble: ReturnType<typeof useBubbleEditor>;
}) {
  const [themes, setThemes] = useState<BubbleThemeEntry[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    bubble.setEditorError("");
    try {
      await action();
    } catch (failure) {
      bubble.setEditorError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    window
      .settings!.request("bubble.theme.list")
      .then((value) => setThemes(value.themes))
      .catch(() => {});
  }, []);
  const apply = (theme: SpeechBubbleTheme, notice: string) => {
    bubble.changeDraft(theme as ThemeValues);
    bubble.setSelectedLayer(null);
    bubble.setEditorNotice(notice);
  };
  const draft = bubble.draft as SpeechBubbleTheme;
  return (
    <Section title={t("bubble.theme.title")}>
      <div className="card-body theme-library">
        {themes.length > 0 ? (
          <ul className="theme-gallery" aria-label={t("bubble.theme.saved")}>
            {themes.map((entry) => (
              <li key={entry.id}>
                <button
                  className="theme-chip"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      const loaded = await window.settings!.request(
                        "bubble.theme.load",
                        { id: entry.id },
                      );
                      apply(
                        loaded.theme,
                        t("bubble.theme.applied", { name: entry.name }),
                      );
                    })
                  }
                >
                  {entry.thumbnail && <img src={entry.thumbnail} alt="" />}
                  <span data-user-text>{entry.name}</span>
                </button>
                <button
                  className="icon-button"
                  aria-label={t("bubble.theme.delete", { name: entry.name })}
                  disabled={busy}
                  onClick={() =>
                    confirm(
                      t("bubble.theme.delete_confirm", { name: entry.name }),
                    ) &&
                    run(async () => {
                      const value = await window.settings!.request(
                        "bubble.theme.delete",
                        { id: entry.id },
                      );
                      setThemes(value.themes);
                    })
                  }
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="footnote">{t("bubble.theme.empty")}</p>
        )}
        <div className="theme-save">
          <input
            type="text"
            aria-label={t("bubble.theme.name")}
            placeholder={t("bubble.theme.name")}
            maxLength={60}
            value={name}
            data-user-text
            onChange={(event) => setName(event.target.value)}
          />
          <button
            className="button compact"
            disabled={busy || !name.trim()}
            onClick={() =>
              run(async () => {
                const value = await window.settings!.request(
                  "bubble.theme.save",
                  { name: name.trim(), theme: draft },
                );
                setThemes(value.themes);
                setName("");
                bubble.setEditorNotice(t("bubble.theme.saved_notice"));
              })
            }
          >
            <Save size={13} />
            {t("bubble.theme.save")}
          </button>
        </div>
        <div className="button-row">
          <button
            className="button compact"
            disabled={busy}
            onClick={() =>
              run(async () => {
                const result = await window.settings!.file("theme-export", {
                  name: name.trim() || t("bubble.theme.default_file"),
                  theme: draft,
                });
                if (!("cancelled" in result))
                  bubble.setEditorNotice(t("bubble.theme.exported"));
              })
            }
          >
            <Download size={13} />
            {t("bubble.theme.export")}
          </button>
          <button
            className="button compact"
            disabled={busy}
            onClick={() =>
              run(async () => {
                const result = await window.settings!.file("theme-import");
                if ("cancelled" in result) return;
                const updated = await window.settings!.request("bubble.editor");
                bubble.setEditor((value) =>
                  value
                    ? {
                        ...value,
                        elements: updated.elements,
                        revision: updated.revision,
                      }
                    : null,
                );
                apply(
                  result.theme,
                  t("bubble.theme.imported", {
                    name: result.name || t("bubble.theme.default_file"),
                  }),
                );
              })
            }
          >
            <Upload size={13} />
            {t("bubble.theme.import")}
          </button>
          <button
            className="button compact"
            disabled={busy}
            title={t("bubble.theme.package_hint")}
            onClick={() =>
              run(async () => {
                const result = await window.settings!.file("theme-package", {
                  theme: draft,
                });
                if ("cancelled" in result) return;
                bubble.setEditorNotice(
                  result.omitted.length
                    ? t("bubble.theme.packaged_omitted", {
                        fields: result.omitted
                          .map((key) => themeLabels[key] || key)
                          .join(", "),
                      })
                    : t("bubble.theme.packaged"),
                );
              })
            }
          >
            <FolderOutput size={13} />
            {t("bubble.theme.package")}
          </button>
        </div>
      </div>
    </Section>
  );
}
