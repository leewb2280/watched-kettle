// The Electron main process rejects with "code: message"; ipcRenderer.invoke
// then prepends its own "Error invoking remote method '…': Error: " wrapper.
const remotePrefix = /^(?:Error: )?Error invoking remote method '[^']*': /;
const codePrefix = /^([a-z][a-z0-9_]*): /;

export type DescribedError = { code?: string; message: string };

export function describeError(error: unknown): DescribedError {
  let text = String(
    error instanceof Error ? error.message : (error ?? ""),
  ).replace(remotePrefix, "");
  text = text.replace(/^Error: /, "");
  const match = codePrefix.exec(text);
  if (!match) return { message: text || "알 수 없는 오류가 발생했습니다." };
  return { code: match[1], message: text.slice(match[0].length) };
}

export function errorText(error: unknown) {
  return describeError(error).message;
}

export function isStaleError(error: unknown) {
  const { code } = describeError(error);
  return code === "conflict" || code === "stale_context";
}
