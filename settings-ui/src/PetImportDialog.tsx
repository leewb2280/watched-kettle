import { LocalizedText } from "./LocalizedText";
import { t } from "../localization.cjs";
import { Folder, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Modal } from "./components";
import { errorText } from "./errors";
import type { Shell } from "./types";

import type { PetRegistration, PetPreparation as Preparation } from "./types";

type Registration = Pick<
  PetRegistration,
  "id" | "name" | "alreadyExists" | "restoreRequired" | "trashId"
>;

export function PetImportDialog({
  shell,
  close,
}: {
  shell: Shell;
  close: () => void;
}) {
  const [prepared, setPrepared] = useState<Preparation | null>(null);
  const [registered, setRegistered] = useState<Registration | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const token = useRef("");
  const mounted = useRef(false);
  const cancel = (value: string) => {
    if (value)
      window
        .settings!.request("pet.import.cancel", { token: value })
        .catch(() => {});
  };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      cancel(token.current);
    };
  }, []);

  const choose = async () => {
    setBusy(true);
    setError("");
    setPrepared(null);
    setRegistered(null);
    cancel(token.current);
    token.current = "";
    try {
      const result = await window.settings!.file("pet");
      if (!mounted.current) {
        if ("token" in result) cancel(result.token);
        return;
      }
      if (!("cancelled" in result)) {
        token.current = result.token;
        setPrepared(result);
        setName(result.name);
      }
    } catch (failure) {
      if (mounted.current) setError(errorText(failure));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  const add = async () => {
    if (!prepared) return;
    setBusy(true);
    setError("");
    try {
      const result = await shell.command(
        "pet.import.commit",
        { token: prepared.token, name: name.trim() },
        { inline: true },
      );
      setRegistered(result);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };
  const restore = async () => {
    if (!registered?.trashId) return;
    setBusy(true);
    setError("");
    try {
      const result = await shell.command(
        "pet.trash.restore",
        { trashId: registered.trashId! },
        { inline: true },
      );
      setRegistered({ id: result.id, name: result.name, alreadyExists: false });
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };
  const use = async () => {
    if (!registered) return;
    setBusy(true);
    setError("");
    try {
      // A duplicate may be hidden. Reveal it only when the user chooses use.
      const catalog = await window.settings!.request("pet.catalog");
      if (catalog.hidden.includes(registered.id))
        await shell.command(
          "pet.catalog.save",
          {
            sort: catalog.sort,
            order: catalog.order,
            hidden: catalog.hidden.filter((id: string) => id !== registered.id),
          },
          { inline: true },
        );
      await shell.command(
        "pet.select",
        { id: registered.id },
        { inline: true },
      );
      close();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={t("message.1126")}
      close={() => {
        if (!busy) close();
      }}
      error={error || undefined}
      footer={
        <>
          <button className="button" disabled={busy} onClick={close}>
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
          ) : (
            <button
              className="button primary"
              disabled={busy || !prepared || !name.trim()}
              onClick={add}
            >
              <Plus size={15} />
              {t("message.1154")}
            </button>
          )}
        </>
      }
    >
      <p className="footnote">{t("message.1155")}</p>
      {!registered && (
        <button className="button" disabled={busy} onClick={choose}>
          <Folder size={15} />
          {prepared ? t("message.1156") : t("message.1157")}
        </button>
      )}
      {prepared && (
        <div className="pet-import-preview">
          <img src={prepared.thumbnail} alt={t("message.1158")} />
          {registered ? (
            <p role="status">
              <LocalizedText
                id={
                  registered.restoreRequired
                    ? "pet.import.trashed"
                    : registered.alreadyExists
                      ? "pet.import.exists"
                      : "pet.import.added"
                }
                values={{ name: <strong>{registered.name}</strong> }}
              />
            </p>
          ) : (
            <label className="pet-import-name">
              {t("message.1162")}
              <input
                type="text"
                value={name}
                maxLength={100}
                disabled={busy}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
          )}
          <small>
            V{prepared.spriteVersion} {t("message.1163")}
          </small>
        </div>
      )}
      {busy && <p role="status">{t("status.processing")}</p>}
    </Modal>
  );
}
