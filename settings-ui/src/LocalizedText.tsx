import { Fragment, type ReactNode } from "react";
import { parts } from "../localization.cjs";

// Translators reorder named slots; React retains escaping and app-owned markup.
export function LocalizedText({
  id,
  values,
}: {
  id: string;
  values: Record<string, ReactNode>;
}) {
  return (
    <>
      {parts(id, values).map((part, index) => (
        <Fragment key={index}>{part}</Fragment>
      ))}
    </>
  );
}
