const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { setCatalog, t, locale, parts } = require("../localization.cjs");
const root = path.resolve(
  __dirname,
  "../../watched_kettle/localization/resources",
);
const source = JSON.parse(
  fs.readFileSync(path.join(root, "catalog.json"), "utf8"),
).messages;
const english = JSON.parse(
  fs.readFileSync(path.join(root, "en/messages.json"), "utf8"),
);
const messages = Object.fromEntries(
  Object.entries(source).map(([key, entry]) => [
    key,
    { value: english[key]?.value ?? entry.value, plural: entry.plural ?? "" },
  ]),
);

test("official English formats dynamic values and language-specific plurals", () => {
  setCatalog({ locale: "en-US", packId: "official.en", messages });
  assert.equal(locale(), "en-US");
  assert.equal(t("bubble.more_projects", { count: 1 }), "1 more project");
  assert.equal(t("bubble.more_projects", { count: 2 }), "2 more projects");
  assert.equal(
    t("language.coverage", { done: 2, total: 3, review: 1 }),
    "Translated 2/3 · Review needed: 1",
  );
});
test("messages are plain text; values and dollar signs are not executable templates", () => {
  setCatalog({
    locale: "en-US",
    packId: "test",
    messages: {
      plain: { value: "{name}", plural: "" },
    },
  });
  assert.equal(
    t("plain", { name: "<script>$&</script>" }),
    "<script>$&</script>",
  );
});
test("shared CLDR categories cover a language with more than two plural forms", () => {
  setCatalog({
    locale: "pl",
    packId: "test",
    messages: {
      count: {
        value: {
          one: "{n} one",
          few: "{n} few",
          many: "{n} many",
          other: "{n} other",
        },
        plural: "n",
      },
    },
  });
  assert.equal(t("count", { n: 1 }), "1 one");
  assert.equal(t("count", { n: 2 }), "2 few");
  assert.equal(t("count", { n: 5 }), "5 many");
});

test("named UI slots can be reordered without turning user values into HTML", () => {
  const name = { controlledMarkup: "strong" };
  setCatalog({
    locale: "en-US",
    packId: "test",
    messages: {
      reordered: { value: "Delete {name} permanently.", plural: "" },
    },
  });
  assert.deepEqual(parts("reordered", { name }), [
    "Delete ",
    name,
    " permanently.",
  ]);
});

test("declared pack locales work in Intl without a host-language fallback", () => {
  const supported = JSON.parse(
    fs.readFileSync(path.join(root, "locales.json"), "utf8"),
  );
  const electron = path.resolve(
    __dirname,
    "../node_modules/electron/dist/electron.exe",
  );
  const check = [
    'const fs = require("node:fs"), assert = require("node:assert/strict");',
    'const data = JSON.parse(fs.readFileSync(0, "utf8"));',
    "for (const tag of data.locales)",
    "  for (const api of [Intl.PluralRules, Intl.NumberFormat, Intl.DateTimeFormat])",
    "    assert.equal(api.supportedLocalesOf(tag).length, 1, tag);",
    "console.log(JSON.stringify({electron: process.versions.electron, checked: data.locales.length}));",
  ].join("\n");
  const output = execFileSync(electron, ["-e", check], {
    input: JSON.stringify(supported),
    encoding: "utf8",
    windowsHide: true,
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
  });
  assert.deepEqual(JSON.parse(output), {
    electron: supported.electron,
    checked: supported.locales.length,
  });
});

test("literal braces use the same escape convention as Python", () => {
  setCatalog({
    locale: "en-US",
    packId: "test",
    messages: {
      braces: { value: "Language {{pack}}", plural: "" },
    },
  });
  assert.equal(t("braces"), "Language {pack}");
});

test("raw counts select plurals independently of localized display strings", () => {
  for (const [lang, counts] of [
    [
      "fr-FR",
      [
        [1234, "other"],
        [1, "one"],
        [0, "one"],
      ],
    ],
    [
      "ru",
      [
        [1, "one"],
        [2, "few"],
        [5, "many"],
        [1234, "few"],
        [1.0001, "other"],
        [0.000001, "other"],
        [1.5, "other"],
      ],
    ],
  ]) {
    setCatalog({
      locale: lang,
      packId: "test",
      messages: {
        number: {
          value: {
            one: "{value0} one",
            few: "{value0} few",
            many: "{value0} many",
            other: "{value0} other",
          },
          plural: "count",
        },
      },
    });
    for (const [count, category] of counts) {
      const display = new Intl.NumberFormat(lang, {
        maximumFractionDigits: 6,
      }).format(count);
      assert.equal(
        t("number", { count, value0: display }),
        display + " " + category,
      );
    }
    for (const count of [
      "1,234",
      "1",
      true,
      false,
      undefined,
      null,
      NaN,
      Infinity,
    ]) {
      assert.equal(t("number", { count, value0: "shown" }), "shown other");
    }
  }
});

test("official English counts and startup newlines are complete", () => {
  setCatalog({ locale: "en-US", packId: "official.en", messages });
  for (const count of [0, 1, 2]) {
    assert.equal(
      t("message.1258", { count, value0: String(count) }),
      count + (count === 1 ? " token" : " tokens"),
    );
    const startup = t("message.0031", { value0: count, value1: "details" });
    assert.equal(
      startup,
      "Could not load " +
        count +
        (count === 1 ? " pet." : " pets.") +
        "\nLast error: details",
    );
    assert.equal(
      t("message.0933", { value0: count }),
      count + (count === 1 ? " time" : " times"),
    );
  }
});
