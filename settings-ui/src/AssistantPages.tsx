import { AssistantActivityPage } from "./assistant/AssistantActivityPage";
import { AssistantDialogs } from "./assistant/AssistantDialogs";
import { AssistantHomePage } from "./assistant/AssistantHomePage";
import { AssistantIntegrationPage } from "./assistant/AssistantIntegrationPage";
import { AssistantUsagePage } from "./assistant/AssistantUsagePage";
import { AssistantWidgetPage } from "./assistant/AssistantWidgetPage";
import { useAssistantSettings } from "./assistant/useAssistantSettings";
import type { Page, Shell } from "./types";

export function AssistantPages({ shell, page }: { shell: Shell; page: Page }) {
  const state = useAssistantSettings(shell, page);
  return (
    <>
      {page === "home" && <AssistantHomePage {...state} />}
      {page === "usage" && <AssistantUsagePage {...state} />}
      {page === "widget" && <AssistantWidgetPage {...state} />}
      {page === "activity" && <AssistantActivityPage {...state} />}
      {page === "integration" && <AssistantIntegrationPage {...state} />}
      <AssistantDialogs {...state} />
    </>
  );
}
