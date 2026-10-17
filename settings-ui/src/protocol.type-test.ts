// Compile-only contract checks; never imported by the renderer.
import type { CommandCall, Request } from "./types";
declare const request: Request;
declare const command: CommandCall;

request("pet.preview", { petId: "mori-bot" }).then((value) => {
  value.cropBounds.width.toFixed();
  // @ts-expect-error response fields are checked
  value.cropBounds.nonexistent;
});
// @ts-expect-error petId is required
request("pet.preview", {});
// @ts-expect-error arguments cannot be omitted for this command
request("pet.preview");
// @ts-expect-error native paths are not renderer commands
request("file.pet.prepare", { path: "secret" });
// @ts-expect-error native window state is main-only
request("window.state", { state: {} });
// @ts-expect-error setting key determines its value type
command("settings.set", { key: "opacity", value: false });
// @ts-expect-error query kind determines supported order
command("usage.query", { kind: "conversations", order: "custom" });
// @ts-expect-error query kind is required
command("usage.query", { search: "query" });

// @ts-expect-error empty requests do not accept arbitrary fields
request("settings.snapshot", { path: "secret" });
declare const chooseFile: import("./types").FileRequest;
// @ts-expect-error importing a decoration requires its kind
chooseFile("import");
// @ts-expect-error pet selection does not take a decoration kind
chooseFile("pet", "frame");

declare const assistant: ReturnType<
  typeof import("./assistant/commands").assistantCommands
>;
// @ts-expect-error helper calls retain the required argument contract
assistant.call("usage.query");
// @ts-expect-error quiet reads retain the required argument contract
assistant.read("usage.query");
declare const core: ReturnType<
  typeof import("./core/useCoreSettings").useCoreSettings
>;
// @ts-expect-error core helpers retain the required argument contract
core.call("pet.select");
