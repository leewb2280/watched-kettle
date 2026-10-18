// Wire types are generated from the Qt-independent Python protocol.
export * from "./protocol.generated";
import type {
  Args,
  Page,
  Ready,
  RendererCommand,
  Result,
  Route,
  SettingsEvent,
  SettingsSnapshot,
} from "./protocol.generated";

// Arbitrary diagnostic data must be narrowed before use.
export type DiagnosticValues = Record<string, unknown>;
export type CommandOptions = { inline?: boolean; quiet?: boolean };
export type CommandCall = <M extends RendererCommand>(
  method: M,
  ...args: {} extends Args<M>
    ? [args?: Args<M>, options?: CommandOptions]
    : [args: Args<M>, options?: CommandOptions]
) => Promise<Result<M>>;
export type Shell = {
  snapshot: SettingsSnapshot;
  command: CommandCall;
  refresh: () => Promise<void>;
  navigate: (page: Page) => void;
  notify: (text: string) => void;
  reportError: (error: unknown) => void;
  visible: boolean;
  eventVersion: number;
  busy: boolean;
  route: Route | null;
};
declare global {
  const __ASSISTANT__: boolean;
  interface Window {
    settings?: {
      request: import("./protocol.generated").Request;
      file: import("./protocol.generated").FileRequest;
      onEvent: (listener: (value: SettingsEvent) => void) => () => void;
      ready: () => Promise<Ready>;
      openLanguagePackFolder: () => Promise<{ opened: boolean }>;
    };
  }
}
