const emergency = {
  "message.1262": "설정 연결이 끊겼습니다. / The settings connection closed.",
  "message.1263": "진행 중인 요청이 너무 많습니다. / Too many requests.",
  "message.1264": "요청이 너무 큽니다. / Request too large.",
  "message.1265":
    "응답이 지연되고 있습니다. / The response is taking too long.",
  "message.1266": "허용되지 않은 화면입니다. / Unauthorized screen.",
  "message.1267": "허용되지 않은 명령입니다. / Command not allowed.",
  "message.1272":
    "허용되지 않은 파일 작업입니다. / File operation not allowed.",
  "message.1274":
    "펫 앱의 트레이에서 설정을 열어주세요. / Open settings from the pet app tray.",
  "message.1275":
    "런타임 연결이 종료되었습니다. / The runtime connection closed.",
  "message.0598":
    "펫 앱의 트레이에서 설정을 열어주세요. / Open settings from the pet app tray.",
};

// Data-only formatting. React markup is supplied by the app, never by a pack.
let catalog = { packId: "official.ko", locale: "ko", messages: {} };
function setCatalog(value) {
  if (!value || !value.messages || typeof value.locale !== "string") return;
  catalog = value;
}
function locale() {
  return catalog.locale;
}
function template(key, values) {
  const entry = catalog.messages[key];
  if (!entry) return emergency[key] || key;
  let text = entry.value;
  if (typeof text === "object" && text) {
    const count = values[entry.plural];
    const category =
      typeof count === "number" && Number.isFinite(count)
        ? new Intl.PluralRules(catalog.locale, {
            maximumFractionDigits: 20,
          }).select(count)
        : "other";
    text = text[category] ?? text.other;
  }
  return String(text);
}
function parts(key, values = {}) {
  const text = template(key, values);
  const pattern = /{{|}}|{([A-Za-z_][A-Za-z_0-9]*)}/g;
  const result = [];
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    result.push(text.slice(offset, match.index));
    result.push(
      match[0] === "{{"
        ? "{"
        : match[0] === "}}"
          ? "}"
          : Object.prototype.hasOwnProperty.call(values, match[1])
            ? values[match[1]]
            : match[0],
    );
    offset = match.index + match[0].length;
  }
  result.push(text.slice(offset));
  return result;
}
function t(key, values = {}) {
  return parts(key, values).map(String).join("");
}
module.exports = { setCatalog, t, locale, parts };
