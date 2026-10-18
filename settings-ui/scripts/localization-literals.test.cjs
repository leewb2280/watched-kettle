// Renderer and Electron text must come from the catalog, never fixed Korean or
// English literals. Exceptions share scripts/localization_literals.json with
// the Python guard.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

const repo = path.resolve(__dirname, "../..");
const root = path.join(repo, "settings-ui");
const HANGUL = /[가-힣]/;
const WORD = /[A-Za-z]{2,}/;
// Attributes that reach the screen or assistive technology as text.
const TEXT_ATTRIBUTES = new Set([
  "title",
  "placeholder",
  "aria-label",
  "alt",
  "label",
]);
const allowlist = JSON.parse(
  fs.readFileSync(
    path.join(repo, "scripts/localization_literals.json"),
    "utf8",
  ),
);

function files(folder, pattern) {
  return fs
    .readdirSync(folder, { withFileTypes: true, recursive: true })
    .filter((entry) => entry.isFile() && pattern.test(entry.name))
    .map((entry) => path.join(entry.parentPath, entry.name));
}

function parse(file, text) {
  const kind = file.endsWith("x") ? ts.ScriptKind.TSX : undefined;
  return ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
}

function lineOf(source, node) {
  return source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
}

function koreanLines(file, text) {
  const source = parse(file, text);
  const found = [];
  const visit = (node) => {
    const literal =
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node) ||
      ts.isJsxText(node);
    if (literal && HANGUL.test(node.text)) found.push(lineOf(source, node));
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

// JSX text and text attributes written directly in English show the same
// words in every language; only listed names, commands and units may.
function englishTexts(file, text) {
  const source = parse(file, text);
  const found = [];
  const visit = (node) => {
    let value = null;
    if (ts.isJsxText(node)) value = node.text.trim();
    if (
      ts.isJsxAttribute(node) &&
      TEXT_ATTRIBUTES.has(node.name.getText(source))
    ) {
      let initializer = node.initializer;
      if (initializer && ts.isJsxExpression(initializer)) {
        initializer = initializer.expression;
      }
      if (
        initializer &&
        (ts.isStringLiteral(initializer) ||
          ts.isNoSubstitutionTemplateLiteral(initializer))
      ) {
        value = initializer.text.trim();
      }
    }
    if (value && WORD.test(value)) {
      found.push({ line: lineOf(source, node), text: value });
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

function relative(file) {
  return path.relative(repo, file).replaceAll("\\", "/");
}

const sources = [
  ...files(path.join(root, "src"), /\.tsx?$/),
  ...files(path.join(root, "electron"), /\.cjs$/),
  path.join(root, "localization.cjs"),
];

test("settings UI and Electron sources have no unlisted Korean literals", () => {
  const korean = Object.fromEntries(
    Object.entries(allowlist.korean).filter(([file]) =>
      file.startsWith("settings-ui/"),
    ),
  );
  assert.ok(sources.length > 10);
  const found = {};
  for (const file of sources) {
    const lines = koreanLines(file, fs.readFileSync(file, "utf8"));
    if (lines.length) found[relative(file)] = lines;
  }
  const problems = [];
  for (const file of new Set([...Object.keys(found), ...Object.keys(korean)])) {
    const lines = found[file] || [];
    const expected = korean[file]?.count ?? 0;
    if (korean[file] && !String(korean[file].reason || "").trim()) {
      problems.push(file + ": allowlist entry needs a reason");
    }
    if (lines.length !== expected) {
      problems.push(
        `${file}: ${lines.length} Korean literal(s) at line ${lines.join(", ")}, ` +
          `${expected} allowed`,
      );
    }
  }
  assert.deepEqual(
    problems,
    [],
    "Move user-visible text to catalog.json and t(), or update the count and " +
      "reason in scripts/localization_literals.json",
  );
});

test("settings UI has no unlisted English JSX text", () => {
  const allowed = allowlist.untranslated;
  const used = new Set();
  const problems = [];
  for (const file of sources.filter((item) => item.endsWith(".tsx"))) {
    for (const item of englishTexts(file, fs.readFileSync(file, "utf8"))) {
      if (Object.hasOwn(allowed, item.text)) used.add(item.text);
      else problems.push(`${relative(file)}:${item.line}: ${item.text}`);
    }
  }
  for (const [text, reason] of Object.entries(allowed)) {
    if (!String(reason).trim()) problems.push(text + ": needs a reason");
    if (!used.has(text)) problems.push(text + ": no longer used; remove it");
  }
  assert.deepEqual(
    problems,
    [],
    "Move user-visible text to catalog.json and t(), or list a name, command " +
      "or unit under untranslated in scripts/localization_literals.json",
  );
});

test("the scanners see strings, templates and JSX text but not comments", () => {
  const sample = [
    "// 주석은 괜찮다",
    'const a = "한글";',
    "const b = `x ${a} 템플릿`;",
    "const c = <p>본문</p>;",
    'const d = <p title="Open file" data-id="raw">{n} tokens</p>;',
    "const e = <i aria-label={'Close'}>x</i>;",
  ].join("\n");
  const file = path.join(root, "sample.tsx");
  assert.deepEqual(koreanLines(file, sample), [2, 3, 4]);
  assert.deepEqual(englishTexts(file, sample), [
    { line: 5, text: "Open file" },
    { line: 5, text: "tokens" },
    { line: 6, text: "Close" },
  ]);
});
