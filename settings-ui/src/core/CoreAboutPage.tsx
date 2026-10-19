import { t } from "../../localization.cjs";
import { FolderOpen } from "lucide-react";
import { Heading, Section } from "../components";

import type { CoreSettingsState } from "./useCoreSettings";

// target="_blank" reaches the main process's window-open handler, which hands
// only repository links to the default browser (electron/external.cjs).
function ExternalLink({ href, children }: { href: string; children: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

export function CoreAboutPage({
  snapshot,
  call,
}: Pick<CoreSettingsState, "snapshot" | "call">) {
  const about = snapshot.about;
  const links: [string, string][] = [
    [t("about.repository"), about.links.repository],
    [t("about.issues"), about.links.issues],
    [t("about.license"), about.links.license],
  ];
  return (
    <div className="page">
      <Heading title={t("about.nav")} subtitle={t("about.subtitle")} />
      <Section title={t("about.app_section")}>
        <div className="setting-row">
          <div>
            <h3>Watched Kettle {about.version}</h3>
            <p>
              {about.edition === "pet-assistant"
                ? t("message.0604")
                : t("message.0605")}
              {" · "}
              {t("about.copyright")}
            </p>
          </div>
        </div>
        <p className="footnote about-note">{t("about.unofficial")}</p>
      </Section>
      <Section title={t("about.whats_new", { version: about.whatsNewVersion })}>
        <ul className="about-list">
          {about.whatsNew.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="footnote about-links">
          <ExternalLink href={about.links.releaseNotes}>
            {t("about.release_notes")}
          </ExternalLink>
          <ExternalLink href={about.links.changelog}>
            {t("about.changelog")}
          </ExternalLink>
        </p>
      </Section>
      <Section title={t("about.links_section")}>
        {links.map(([label, url]) => (
          <div className="setting-row" key={url}>
            <div>
              <h3>{label}</h3>
              <p>
                <ExternalLink href={url}>{url}</ExternalLink>
              </p>
            </div>
          </div>
        ))}
      </Section>
      <Section title={t("about.third_party_section")}>
        <ul className="about-list about-notices">
          {about.thirdParty.map((notice) => (
            <li key={notice.name}>
              <span>{notice.name}</span>
              <span>{notice.license}</span>
            </li>
          ))}
        </ul>
        <div className="setting-row">
          <div>
            <p>
              {about.licensesAvailable
                ? t("about.third_party_note")
                : t("about.licenses_source_run")}
            </p>
          </div>
          <button
            className="button"
            disabled={!about.licensesAvailable}
            onClick={() => call("about.open_licenses")}
          >
            <FolderOpen size={14} />
            {t("about.open_licenses")}
          </button>
        </div>
      </Section>
    </div>
  );
}
