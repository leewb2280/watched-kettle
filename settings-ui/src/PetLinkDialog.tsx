import { t } from "../localization.cjs";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  ImagePlus,
  Link2,
  Play,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Modal } from "./components";
import { LocalizedText } from "./LocalizedText";
import { errorText } from "./errors";
import type {
  PetLinkPreview,
  PetLinkSource,
  PetLinkTransition,
  PetRegistration,
  Shell,
} from "./types";

type Step = "looks" | "transitions" | "confirm";
type Look = { petId: string; label: string };
type Registration = Pick<
  PetRegistration,
  "id" | "name" | "alreadyExists" | "restoreRequired" | "trashId"
>;
const pairKey = (from: string, to: string) => `${from}>${to}`;
// Same choices as the pet's automatic change interval.
const INTERVALS: [string, number, number][] = [
  ["10-30", 10, 30],
  ["60-180", 60, 180],
  ["180-600", 180, 600],
  ["600-1800", 600, 1800],
  ["1800-3600", 1800, 3600],
];
const rangeLabel = (low: number, high: number) =>
  low % 60 || high % 60
    ? t("pet.appearance.range.seconds", { min: low, max: high })
    : t("pet.appearance.range.minutes", { min: low / 60, max: high / 60 });

/** Plays a transition preview: start look, frames, end look, repeated. */
function TransitionPlayer({
  preview,
  reduceMotion,
}: {
  preview: PetLinkPreview;
  reduceMotion: boolean;
}) {
  const sequence = [preview.start, ...preview.frames, preview.end];
  const [index, setIndex] = useState(0);
  useEffect(() => {
    setIndex(0);
    if (reduceMotion) return;
    let current = 0;
    let timer: ReturnType<typeof setTimeout>;
    const next = () => {
      current = (current + 1) % sequence.length;
      setIndex(current);
      // Hold both looks a moment so the change reads clearly.
      const hold =
        current === 0 || current === sequence.length - 1
          ? 600
          : preview.intervalMs;
      timer = setTimeout(next, hold);
    };
    timer = setTimeout(next, 600);
    return () => clearTimeout(timer);
  }, [preview, reduceMotion]);
  return (
    <div className="link-player">
      <img src={sequence[index]} alt="" width={96} height={104} />
      <span className="link-player-kind">
        {preview.kind === "drawn"
          ? t("pet.link.kind.drawn", { count: preview.frames.length })
          : preview.kind === "reversed"
            ? t("pet.link.kind.reversed")
            : t("pet.link.kind.fade")}
      </span>
    </div>
  );
}

export function PetLinkDialog({
  shell,
  close: closeDialog,
}: {
  shell: Shell;
  close: () => void;
}) {
  const [step, setStep] = useState<Step>("looks");
  const [sources, setSources] = useState<PetLinkSource[]>([]);
  const [maxLooks, setMaxLooks] = useState(6);
  const [looks, setLooks] = useState<Look[]>([]);
  const [defaultPet, setDefaultPet] = useState("");
  const [transitions, setTransitions] = useState<PetLinkTransition[]>([]);
  const [intervals, setIntervals] = useState<Record<string, number>>({});
  const [preview, setPreview] = useState<{
    key: string;
    data: PetLinkPreview;
  } | null>(null);
  const [name, setName] = useState("");
  // A joined pet being edited; saving replaces it.
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(
    null,
  );
  const [bubblePet, setBubblePet] = useState("");
  const [autoInterval, setAutoInterval] = useState("60-180");
  const [order, setOrder] = useState<"random" | "sequence">("random");
  const [registered, setRegistered] = useState<Registration | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const previewSequence = useRef(0);

  useEffect(() => {
    window
      .settings!.request("pet.link.sources")
      .then((value) => {
        setSources(value.entries);
        setMaxLooks(value.maxLooks);
        setTransitions(value.transitions);
      })
      .catch((failure) => setError(errorText(failure)));
  }, []);

  const close = () => {
    window.settings!.request("pet.link.reset").catch(() => {});
    closeDialog();
  };
  const source = (id: string) => sources.find((row) => row.id === id);
  const lookOf = (id: string) => looks.find((look) => look.petId === id);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };

  const addLook = (id: string) => {
    const row = source(id);
    if (!row || looks.length >= maxLooks) return;
    const next = [...looks, { petId: id, label: row.name.slice(0, 100) }];
    setLooks(next);
    if (!defaultPet) setDefaultPet(id);
    if (!name) setName(row.name.slice(0, 100));
    if (!bubblePet && row.hasBubble) setBubblePet(id);
  };
  const edit = (id: string) =>
    run(async () => {
      if (!id) {
        await window.settings!.request("pet.link.reset");
        setEditing(null);
        setLooks([]);
        setDefaultPet("");
        setTransitions([]);
        setPreview(null);
        return;
      }
      const draft = await window.settings!.request("pet.link.load", {
        petId: id,
      });
      setSources((rows) => [
        ...rows.filter((row) => !row.id.includes("#")),
        ...draft.sources,
      ]);
      setLooks(draft.looks);
      setDefaultPet(draft.defaultPetId);
      setName(draft.name);
      setBubblePet(draft.bubblePetId);
      setTransitions(draft.transitions);
      setIntervals({});
      setPreview(null);
      setOrder(draft.auto.order);
      setAutoInterval(
        INTERVALS.find(
          ([, low, high]) =>
            low === draft.auto.minSeconds && high === draft.auto.maxSeconds,
        )?.[0] ?? "60-180",
      );
      setEditing({ id, name: source(id)?.name ?? draft.name });
    });
  const moveLook = (index: number, offset: number) => {
    const next = [...looks];
    [next[index], next[index + offset]] = [next[index + offset], next[index]];
    setLooks(next);
  };
  const removeLook = (id: string) => {
    const next = looks.filter((look) => look.petId !== id);
    setLooks(next);
    if (defaultPet === id) setDefaultPet(next[0]?.petId ?? "");
    if (bubblePet === id) setBubblePet("");
    if (preview?.key.split(">").includes(id)) setPreview(null);
  };
  const pairs = looks.flatMap((from) =>
    looks
      .filter((to) => to.petId !== from.petId)
      .map((to) => [from, to] as [Look, Look]),
  );
  const drawn = (from: string, to: string) =>
    transitions.find((row) => row.fromPetId === from && row.toPetId === to);
  const showPreview = async (from: string, to: string) => {
    const sequence = ++previewSequence.current;
    await run(async () => {
      const data = await window.settings!.request("pet.link.preview", {
        fromPetId: from,
        toPetId: to,
      });
      if (sequence === previewSequence.current)
        setPreview({ key: pairKey(from, to), data });
    });
  };
  const importTransition = (from: string, to: string) =>
    run(async () => {
      const result = await window.settings!.file("link-transition", {
        fromPetId: from,
        toPetId: to,
      });
      if ("cancelled" in result) return;
      setTransitions((rows) => [
        ...rows.filter((row) => row.fromPetId !== from || row.toPetId !== to),
        result,
      ]);
      await showPreview(from, to);
    });
  const clearTransition = (from: string, to: string) =>
    run(async () => {
      const result = await window.settings!.request(
        "pet.link.transition.clear",
        { fromPetId: from, toPetId: to },
      );
      setTransitions(result.transitions);
      if (preview?.key === pairKey(from, to)) await showPreview(from, to);
    });
  const create = () =>
    run(async () => {
      const [, low, high] =
        INTERVALS.find(([key]) => key === autoInterval) ?? INTERVALS[1];
      const ids = new Set(looks.map((look) => look.petId));
      const result = await shell.command(
        "pet.link.create",
        {
          looks,
          defaultPetId: defaultPet,
          name: name.trim(),
          bubblePetId: bubblePet,
          intervals: transitions
            .filter((row) => ids.has(row.fromPetId) && ids.has(row.toPetId))
            .map((row) => ({
              fromPetId: row.fromPetId,
              toPetId: row.toPetId,
              intervalMs:
                intervals[pairKey(row.fromPetId, row.toPetId)] ??
                row.intervalMs,
            })),
          auto: { minSeconds: low, maxSeconds: high, order },
          ...(editing ? { replacePetId: editing.id } : {}),
        },
        { inline: true },
      );
      setRegistered(result);
    });
  const restore = () =>
    run(async () => {
      const result = await shell.command(
        "pet.trash.restore",
        { trashId: registered!.trashId! },
        { inline: true },
      );
      setRegistered({ id: result.id, name: result.name, alreadyExists: false });
    });
  const use = () =>
    run(async () => {
      await shell.command(
        "pet.select",
        { id: registered!.id },
        { inline: true },
      );
      close();
    });

  const labelsReady =
    looks.length >= 2 && looks.every((look) => look.label.trim());
  const steps: [Step, string][] = [
    ["looks", t("pet.link.step.looks")],
    ["transitions", t("pet.link.step.transitions")],
    ["confirm", t("pet.link.step.confirm")],
  ];
  const stepIndex = steps.findIndex(([key]) => key === step);
  return (
    <Modal
      title={t("pet.link.title")}
      className="pet-import-modal pet-link-modal"
      close={close}
      error={error || undefined}
      footer={
        <>
          {!registered && stepIndex > 0 && (
            <button
              className="button import-back"
              disabled={busy}
              onClick={() => setStep(steps[stepIndex - 1][0])}
            >
              <ArrowLeft size={15} aria-hidden="true" />
              {t("pet.link.back")}
            </button>
          )}
          <div className="import-footer-actions">
            <button className="button" onClick={close}>
              {registered ? t("message.0970") : t("message.0650")}
            </button>
            {registered ? (
              <button
                className="button primary"
                disabled={busy}
                onClick={registered.restoreRequired ? restore : use}
              >
                {registered.restoreRequired
                  ? t("message.1152")
                  : t("message.1153")}
              </button>
            ) : step === "confirm" ? (
              <button
                className="button primary"
                disabled={busy || !labelsReady || !name.trim()}
                onClick={create}
              >
                <Link2 size={15} aria-hidden="true" />
                {editing ? t("pet.link.replace") : t("pet.link.create")}
              </button>
            ) : (
              <button
                className="button primary"
                disabled={busy || !labelsReady}
                onClick={() => setStep(steps[stepIndex + 1][0])}
              >
                {t("pet.link.next")}
                <ArrowRight size={15} aria-hidden="true" />
              </button>
            )}
          </div>
        </>
      }
    >
      <div className="pet-link-body" aria-busy={busy}>
        {!registered && (
          <ol className="link-steps">
            {steps.map(([key, label], index) => (
              <li
                key={key}
                aria-current={key === step ? "step" : undefined}
                className={index < stepIndex ? "is-done" : undefined}
              >
                {label}
              </li>
            ))}
          </ol>
        )}
        {!registered && step === "looks" && (
          <div className="link-looks">
            <p className="import-intro">
              {t("pet.link.looks_intro", { max: maxLooks })}
            </p>
            {sources.some((row) => row.joined) && (
              <label className="link-add">
                {t("pet.link.edit_title")}
                <select
                  aria-label={t("pet.link.edit_title")}
                  value={editing?.id ?? ""}
                  disabled={busy}
                  onChange={(event) => edit(event.target.value)}
                >
                  <option value="">{t("pet.link.edit_choose")}</option>
                  {sources
                    .filter((row) => row.joined)
                    .map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.name}
                      </option>
                    ))}
                </select>
              </label>
            )}
            <ul className="link-look-list">
              {looks.map((look, index) => (
                <li key={look.petId} className="link-look-row">
                  <img src={source(look.petId)?.thumbnail} alt="" />
                  <div className="link-look-fields">
                    <label>
                      {t("pet.link.look_name")}
                      <input
                        type="text"
                        data-user-text
                        maxLength={100}
                        value={look.label}
                        onChange={(event) =>
                          setLooks(
                            looks.map((item) =>
                              item.petId === look.petId
                                ? { ...item, label: event.target.value }
                                : item,
                            ),
                          )
                        }
                      />
                    </label>
                    <small data-user-text>{source(look.petId)?.name}</small>
                  </div>
                  <label className="link-default">
                    <input
                      type="radio"
                      name="link-default"
                      checked={defaultPet === look.petId}
                      onChange={() => setDefaultPet(look.petId)}
                    />
                    {t("pet.link.default_look")}
                  </label>
                  <span className="link-row-actions">
                    <button
                      className="icon-button"
                      aria-label={t("pet.link.move_up", { name: look.label })}
                      disabled={index === 0}
                      onClick={() => moveLook(index, -1)}
                    >
                      <ArrowUp size={14} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label={t("pet.link.move_down", { name: look.label })}
                      disabled={index === looks.length - 1}
                      onClick={() => moveLook(index, 1)}
                    >
                      <ArrowDown size={14} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label={t("pet.link.remove", { name: look.label })}
                      onClick={() => removeLook(look.petId)}
                    >
                      <X size={14} />
                    </button>
                  </span>
                </li>
              ))}
            </ul>
            <label className="link-add">
              {t("pet.link.add_look")}
              <select
                aria-label={t("pet.link.add_look")}
                value=""
                disabled={looks.length >= maxLooks}
                onChange={(event) => addLook(event.target.value)}
              >
                <option value="">{t("pet.link.choose_pet")}</option>
                {sources
                  .filter(
                    (row) =>
                      !lookOf(row.id) &&
                      !row.id.includes("#") &&
                      row.id !== editing?.id,
                  )
                  .map((row) => (
                    <option
                      key={row.id}
                      value={row.id}
                      disabled={!!row.problem}
                    >
                      {row.problem ? `${row.name} — ${row.problem}` : row.name}
                    </option>
                  ))}
              </select>
            </label>
          </div>
        )}
        {!registered && step === "transitions" && (
          <div className="link-transitions">
            <p className="import-intro">{t("pet.link.transitions_intro")}</p>
            {preview && (
              <TransitionPlayer
                preview={preview.data}
                reduceMotion={shell.snapshot.appearance.reduceMotion}
              />
            )}
            <ul className="link-pair-list">
              {pairs.map(([from, to]) => {
                const key = pairKey(from.petId, to.petId);
                const row = drawn(from.petId, to.petId);
                const reverse = drawn(to.petId, from.petId);
                return (
                  <li
                    key={key}
                    className={`link-pair${preview?.key === key ? " is-previewed" : ""}`}
                  >
                    <span className="link-pair-names">
                      <span data-user-text>{from.label}</span>
                      <ArrowRight size={13} aria-hidden="true" />
                      <span data-user-text>{to.label}</span>
                    </span>
                    <span className="link-pair-kind">
                      {row
                        ? t("pet.link.kind.drawn", { count: row.frames })
                        : reverse
                          ? t("pet.link.kind.reversed")
                          : t("pet.link.kind.fade")}
                      {row?.resized && (
                        <small className="import-warning">
                          {t("pet.link.resized")}
                        </small>
                      )}
                    </span>
                    {row && (
                      <label className="link-pair-interval">
                        {t("pet.link.frame_interval")}
                        <input
                          type="number"
                          min={16}
                          max={1000}
                          value={intervals[key] ?? row.intervalMs}
                          onChange={(event) =>
                            setIntervals({
                              ...intervals,
                              [key]: Math.min(
                                1000,
                                Math.max(16, Number(event.target.value) || 16),
                              ),
                            })
                          }
                        />
                      </label>
                    )}
                    <span className="link-row-actions">
                      <button
                        className="icon-button"
                        aria-label={t("pet.link.play", {
                          from: from.label,
                          to: to.label,
                        })}
                        disabled={busy}
                        onClick={() => showPreview(from.petId, to.petId)}
                      >
                        <Play size={14} />
                      </button>
                      <button
                        className="icon-button"
                        aria-label={t("pet.link.import_transition", {
                          from: from.label,
                          to: to.label,
                        })}
                        disabled={busy}
                        onClick={() => importTransition(from.petId, to.petId)}
                      >
                        <ImagePlus size={14} />
                      </button>
                      {row && (
                        <button
                          className="icon-button"
                          aria-label={t("pet.link.clear_transition", {
                            from: from.label,
                            to: to.label,
                          })}
                          disabled={busy}
                          onClick={() => clearTransition(from.petId, to.petId)}
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
            <p className="import-help">{t("pet.link.transition_help")}</p>
          </div>
        )}
        {!registered && step === "confirm" && (
          <div className="link-confirm">
            <label className="pet-import-name">
              {t("message.1162")}
              <input
                type="text"
                data-user-text
                maxLength={100}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              {t("pet.link.bubble")}
              <select
                aria-label={t("pet.link.bubble")}
                value={bubblePet}
                onChange={(event) => setBubblePet(event.target.value)}
              >
                <option value="">{t("pet.link.bubble_none")}</option>
                {looks
                  .filter((look) => source(look.petId)?.hasBubble)
                  .map((look) => (
                    <option key={look.petId} value={look.petId}>
                      {look.label}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              {t("pet.appearance.interval")}
              <select
                aria-label={t("pet.appearance.interval")}
                value={autoInterval}
                onChange={(event) => setAutoInterval(event.target.value)}
              >
                {INTERVALS.map(([key, low, high]) => (
                  <option key={key} value={key}>
                    {rangeLabel(low, high)}
                  </option>
                ))}
              </select>
            </label>
            {looks.length > 2 && (
              <label>
                {t("pet.appearance.order")}
                <select
                  aria-label={t("pet.appearance.order")}
                  value={order}
                  onChange={(event) =>
                    setOrder(event.target.value as "random" | "sequence")
                  }
                >
                  <option value="random">
                    {t("pet.appearance.order.random")}
                  </option>
                  <option value="sequence">
                    {t("pet.appearance.order.sequence")}
                  </option>
                </select>
              </label>
            )}
            {editing && (
              <p role="status" className="import-warning">
                <LocalizedText
                  id="pet.link.edit_note"
                  values={{
                    name: <strong data-user-text>{editing.name}</strong>,
                  }}
                />
              </p>
            )}
            <p className="import-help">
              {t("pet.link.summary", {
                looks: looks.length,
                drawn: transitions.filter(
                  (row) => lookOf(row.fromPetId) && lookOf(row.toPetId),
                ).length,
              })}
            </p>
          </div>
        )}
        {registered && (
          <div className="import-result">
            <img
              src={source(defaultPet)?.thumbnail}
              alt=""
              width={144}
              height={156}
            />
            <div className="import-result-copy">
              <h3>
                <Check size={20} aria-hidden="true" />
                {registered.restoreRequired
                  ? t("pet.import.restore_title")
                  : registered.alreadyExists
                    ? t("pet.import.exists_title")
                    : editing
                      ? t("pet.link.replaced_title")
                      : t("pet.link.created_title")}
              </h3>
              <p role="status">
                <LocalizedText
                  id={
                    registered.restoreRequired
                      ? "pet.import.trashed"
                      : registered.alreadyExists
                        ? "pet.import.exists"
                        : "pet.import.added"
                  }
                  values={{
                    name: <strong data-user-text>{registered.name}</strong>,
                  }}
                />
              </p>
            </div>
          </div>
        )}
        {busy && (
          <div className="import-progress" role="status">
            <span>{t("status.processing")}</span>
          </div>
        )}
      </div>
    </Modal>
  );
}
