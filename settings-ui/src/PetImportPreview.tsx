import { useEffect, useRef, useState } from "react";
import { t } from "../localization.cjs";
import type { ImportPreview, PetPreparation } from "./types";

const animations = [
  ["idle", "pet.import.idle"],
  ["running-right", "pet.import.running_right"],
  ["running-left", "pet.import.running_left"],
  ["waving", "pet.import.waving"],
  ["jumping", "pet.import.jumping"],
  ["failed", "pet.import.failed"],
  ["waiting", "pet.import.waiting"],
  ["running", "pet.import.running"],
  ["review", "pet.import.review"],
] as const;

export function PetImportPreview({
  prepared,
  reduceMotion,
}: {
  prepared: PetPreparation;
  reduceMotion: boolean;
}) {
  const [state, setState] = useState("idle");
  const [strip, setStrip] = useState<ImportPreview | null>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(!reduceMotion);
  const [direction, setDirection] = useState(0);
  const cache = useRef(new Map<string, ImportPreview>());
  const looking = state === "look";
  const row = looking ? `look-${Math.floor(direction / 8)}` : state;
  useEffect(() => {
    let active = true;
    setStrip(null);
    setFrame(0);
    const key = `${prepared.token}:${row}`;
    const old = cache.current.get(key);
    if (old) setStrip(old);
    else
      window
        .settings!.request("pet.import.preview", {
          token: prepared.token,
          state: row,
        })
        .then((value) => {
          if (!active) return;
          if (cache.current.size >= 11) cache.current.clear();
          cache.current.set(key, value);
          setStrip(value);
        })
        .catch(() => {
          if (active) setStrip(null);
        });
    return () => {
      active = false;
    };
  }, [prepared.token, row]);
  useEffect(() => {
    if (reduceMotion) setPlaying(false);
  }, [reduceMotion]);
  useEffect(() => {
    if (!strip || !playing || looking) return;
    const timer = window.setInterval(
      () => setFrame((value) => (value + 1) % strip.frames),
      strip.interval,
    );
    return () => window.clearInterval(timer);
  }, [strip, playing, looking]);
  return (
    <div className="import-animation">
      <div className="import-animation-stage">
        {strip ? (
          <img
            src={strip.image}
            alt={t("message.1158")}
            style={{
              width: strip.frames * 192,
              maxWidth: "none",
              transform: `translateX(-${(looking ? direction % 8 : frame) * 192}px)`,
            }}
          />
        ) : (
          <img src={prepared.thumbnail} alt={t("message.1158")} />
        )}
      </div>
      <div className="import-animation-controls">
        <label>
          {t("pet.import.animation")}
          <select
            aria-label={t("pet.import.animation")}
            value={state}
            onChange={(event) => setState(event.target.value)}
          >
            {animations.map(([value, key]) => (
              <option key={value} value={value}>
                {t(key)}
              </option>
            ))}
            {prepared.spriteVersion === 2 && (
              <option value="look">{t("pet.import.look")}</option>
            )}
          </select>
        </label>
        {looking ? (
          <label>
            {t("pet.import.direction")}
            <input
              aria-label={t("pet.import.direction")}
              type="range"
              min={0}
              max={15}
              step={1}
              value={direction}
              onChange={(event) => setDirection(Number(event.target.value))}
            />
          </label>
        ) : (
          <button className="button" onClick={() => setPlaying(!playing)}>
            {playing ? t("pet.import.pause") : t("pet.import.play")}
          </button>
        )}
      </div>
    </div>
  );
}
