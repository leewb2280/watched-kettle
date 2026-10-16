import { useEffect, useRef, useState } from "react";
import { errorText } from "./errors";
import type { PetBatchAction, PetBatchJob, Shell } from "./types";

export function usePetBatch(shell: Shell) {
  const latest = useRef(shell);
  latest.current = shell;
  const [job, setJob] = useState<PetBatchJob | null>(null);
  const [checking, setChecking] = useState(true);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const generation = useRef(0);
  const pollSequence = useRef(0);
  const connectionError = useRef(false);
  const startLock = useRef(false);
  const mounted = useRef(false);

  const poll = async (gen = generation.current) => {
    if (!mounted.current || gen !== generation.current) return;
    clearTimeout(timer.current);
    const seq = ++pollSequence.current;
    try {
      const value = await window.settings!.request("pet.trash.batch.status", {
        epoch: latest.current.snapshot.epoch,
      });
      if (
        !mounted.current ||
        gen !== generation.current ||
        seq !== pollSequence.current
      )
        return;
      if (value.job?.state !== "running") await latest.current.refresh();
      if (
        !mounted.current ||
        gen !== generation.current ||
        seq !== pollSequence.current
      )
        return;
      setJob(value.job);
      setChecking(false);
      if (connectionError.current) {
        setError("");
        connectionError.current = false;
      }
      if (value.job?.state === "running")
        timer.current = setTimeout(() => void poll(gen), 120);
    } catch (failure) {
      if (
        !mounted.current ||
        gen !== generation.current ||
        seq !== pollSequence.current
      )
        return;
      connectionError.current = true;
      setError(errorText(failure));
      setChecking(true);
      timer.current = setTimeout(() => void poll(gen), 1000);
    }
  };
  useEffect(() => {
    mounted.current = true;
    const gen = ++generation.current;
    setJob(null);
    setStarting(false);
    setCancelling(false);
    startLock.current = false;
    connectionError.current = false;
    setChecking(true);
    setError("");
    void poll(gen);
    return () => {
      mounted.current = false;
      ++generation.current;
      clearTimeout(timer.current);
    };
  }, [shell.snapshot.epoch]);

  const start = async (
    action: PetBatchAction,
    ids: string[],
    context: { petId: string; revision: number },
    replacementId = "",
  ) => {
    if (startLock.current || checking || job?.state === "running") return;
    startLock.current = true;
    setStarting(true);
    setError("");
    const gen = generation.current;
    try {
      const result = await latest.current.command(
        "pet.trash.batch.start",
        {
          ...context,
          action,
          ids,
          replacementId,
          operationKey: crypto.randomUUID(),
        },
        { inline: true },
      );
      if (mounted.current && gen === generation.current) setJob(result.job);
    } catch (failure) {
      if (mounted.current && gen === generation.current)
        setError(errorText(failure));
    } finally {
      // A lost start response is recovered by querying the active/last job;
      // never blindly resubmit a mutation with a fresh operation key.
      await poll(gen);
      startLock.current = false;
      if (mounted.current && gen === generation.current) setStarting(false);
    }
  };
  const cancel = async () => {
    if (!job || cancelling) return;
    setCancelling(true);
    const gen = generation.current;
    try {
      const result = await window.settings!.request("pet.trash.batch.cancel", {
        jobId: job.jobId,
        epoch: latest.current.snapshot.epoch,
      });
      if (mounted.current && gen === generation.current) setJob(result.job);
      await poll(gen);
    } catch (failure) {
      if (mounted.current && gen === generation.current)
        setError(errorText(failure));
    } finally {
      if (mounted.current && gen === generation.current) setCancelling(false);
    }
  };
  return {
    job,
    starting,
    cancelling,
    error,
    clearError: () => setError(""),
    refresh: () => poll(),
    start,
    cancel,
    busy: checking || starting || job?.state === "running",
  };
}
