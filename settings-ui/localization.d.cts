export type Message = {
  value: string | Record<string, string>;
  plural: string;
};
export type Bootstrap = {
  packId: string;
  locale: string;
  messages: Record<string, Message>;
};
export function setCatalog(value: Bootstrap): void;
export function locale(): string;
export function t(key: string, values?: Record<string, unknown>): string;

export function parts<T>(
  key: string,
  values: Record<string, T>,
): Array<string | T>;
