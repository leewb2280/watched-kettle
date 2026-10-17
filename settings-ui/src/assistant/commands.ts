import type {
  Args,
  CommandCall,
  CommandOptions,
  RendererCommand,
  Result,
} from "../types";
/** Keeps the existing single-banner error behavior for assistant page commands. */
export function assistantCommands(command: CommandCall) {
  // App's command() already shows failures in the page banner; resolve null
  // instead of rejecting so callers never raise a second banner.
  const call = <M extends RendererCommand>(
    method: M,
    ...params: {} extends Args<M>
      ? [args?: Args<M>, options?: CommandOptions]
      : [args: Args<M>, options?: CommandOptions]
  ): Promise<Result<M> | true | null> => {
    const args = (params[0] ?? {}) as Args<M>;
    const options = params[1] ?? {};
    return command(method, args, options).then(
      (result) => result ?? true,
      () => null,
    );
  };

  const read = <M extends RendererCommand>(
    method: M,
    ...params: {} extends Args<M> ? [args?: Args<M>] : [args: Args<M>]
  ) =>
    command(method, (params[0] ?? {}) as Args<M>, { quiet: true }).then(
      (result): Result<M> | true => result ?? true,
      () => null,
    );
  return { call, read };
}
export type AssistantRead = ReturnType<typeof assistantCommands>["read"];
