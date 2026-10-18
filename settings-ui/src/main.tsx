import React from "react";
import { createRoot } from "react-dom/client";
import { setCatalog, t } from "../localization.cjs";
import "./tokens.css";
import "./styles.css";

async function start() {
  try {
    const ready = await window.settings?.ready();
    if (ready?.localization) {
      setCatalog(ready.localization);
      document.documentElement.lang = ready.localization.locale;
      document.title = t("message.1273");
    }
    if (!ready?.localization) {
      document.getElementById("root")!.textContent = t("message.0598");
      return;
    }
  } catch (error) {
    document.getElementById("root")!.textContent = t("message.1262");
    return;
  }
  const { App } = await import("./App");
  createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
void start();
