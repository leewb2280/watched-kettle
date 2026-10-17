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
      title="펫 가져오기"
      close={() => {
        if (!busy) close();
      }}
      error={error || undefined}
      footer={
        <>
          <button className="button" disabled={busy} onClick={close}>
            {registered ? "닫기" : "취소"}
          </button>
          {registered ? (
            <button
              className="button primary"
              disabled={busy}
              onClick={registered.restoreRequired ? restore : use}
            >
              {registered.restoreRequired ? "휴지통에서 복원" : "이 펫 사용"}
            </button>
          ) : (
            <button
              className="button primary"
              disabled={busy || !prepared || !name.trim()}
              onClick={add}
            >
              <Plus size={15} />
              추가
            </button>
          )}
        </>
      }
    >
      <p className="footnote">
        웹 펫 설정에서 다운로드한 PNG 또는 WebP 스프라이트를 선택하세요. 최대
        20MiB이며, V1·V2 규격을 지원합니다.
      </p>
      {!registered && (
        <button className="button" disabled={busy} onClick={choose}>
          <Folder size={15} />
          {prepared ? "다른 파일 선택" : "파일 선택"}
        </button>
      )}
      {prepared && (
        <div className="pet-import-preview">
          <img src={prepared.thumbnail} alt="가져올 펫 기본 자세" />
          {registered ? (
            <p role="status">
              <strong>{registered.name}</strong>
              {registered.restoreRequired
                ? "은(는) 휴지통에 있어요. 이전 이름과 설정을 그대로 복원할 수 있어요."
                : registered.alreadyExists
                  ? "은(는) 이미 등록되어 있습니다. 기존 이름과 설정을 유지합니다."
                  : "을(를) 펫 목록에 추가했습니다."}
            </p>
          ) : (
            <label className="pet-import-name">
              펫 이름
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
            V{prepared.spriteVersion} · 등록 후 원본 파일을 지워도 사용할 수
            있습니다.
          </small>
        </div>
      )}
      {busy && <p role="status">처리 중…</p>}
    </Modal>
  );
}
