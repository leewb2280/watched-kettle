import { CoreAppPage } from "./core/CoreAppPage";
import { CoreBubblePage } from "./core/CoreBubblePage";
import { CoreDialogs } from "./core/CoreDialogs";
import { CorePetPage } from "./core/CorePetPage";
import { useCoreSettings } from "./core/useCoreSettings";
import type { Page, Shell } from "./types";

export function CorePages({ shell, page }: { shell: Shell; page: Page }) {
  const state = useCoreSettings(shell, page);
  return (
    <>
      {page === "pet" && <CorePetPage {...state} />}
      {page === "bubble" && <CoreBubblePage {...state} />}
      {page === "app" && <CoreAppPage {...state} />}
      <CoreDialogs {...state} />
    </>
  );
}
