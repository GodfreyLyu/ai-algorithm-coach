/** File purpose: Check frontend file descriptions and executable function contracts. */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const requireWeb = createRequire(path.join(root, "web", "package.json"));
const ts = requireWeb("typescript");
const labels = ["Inputs:", "Outputs:", "Logic:", "Dependencies:"];

/**
 * Inputs: A directory inside the maintained frontend.
 * Outputs: Source file paths without dependency or build output.
 * Logic: Walk only owned source folders and skip generated artifacts.
 * Dependencies: Node filesystem and path utilities.
 */
function sourceFiles(directory) {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (["node_modules", "dist", "test-results", "playwright-report"].includes(entry.name)) continue;
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...sourceFiles(target));
    else if (entry.isFile() && /\.(tsx?|mjs|css|html|jsonc?|md)$/.test(entry.name)) files.push(target);
  }
  return files;
}

/**
 * Inputs: A function node and its parsed source file.
 * Outputs: Whether a nearby JSDoc contract describes all four required parts.
 * Logic: Inspect the function and its declaration container for leading comments.
 * Dependencies: TypeScript syntax nodes and comment ranges.
 */
function hasContract(node, source) {
  let candidate = node;
  for (let depth = 0; depth < 4 && candidate; depth += 1) {
    const ranges = ts.getLeadingCommentRanges(source.text, candidate.pos) ?? [];
    for (const range of ranges) {
      const comment = source.text.slice(range.pos, range.end);
      let complete = comment.startsWith("/**");
      for (const label of labels) complete = complete && comment.includes(label);
      if (complete) return true;
    }
    if (ts.isBlock(candidate) || ts.isSourceFile(candidate)) break;
    candidate = candidate.parent;
  }
  return false;
}

/**
 * Inputs: A frontend path and its UTF-8 contents.
 * Outputs: Documentation failures for that file.
 * Logic: Verify format-safe file descriptions and executable function contracts.
 * Dependencies: TypeScript parsing, hasContract, and the project labels.
 */
function inspect(file, text) {
  const name = path.relative(root, file);
  const failures = [];
  const extension = path.extname(file);
  if (path.basename(file) === "package-lock.json") return failures;
  if (extension === ".json" && path.basename(file) !== "tsconfig.json") {
    if (!JSON.parse(text)._comment) failures.push(`${name}: missing legal purpose metadata`);
  } else {
    const prefix = extension === ".html" || extension === ".md" ? "<!--" : extension === ".css" ? "/*" : extension === ".jsonc" || extension === ".json" ? "//" : "/**";
    if (!text.trimStart().startsWith(prefix)) failures.push(`${name}: missing file purpose comment`);
  }
  if (![".ts", ".tsx", ".mjs"].includes(extension)) return failures;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true,
    extension === ".tsx" ? ts.ScriptKind.TSX : extension === ".mjs" ? ts.ScriptKind.JS : ts.ScriptKind.TS);
  /**
   * Inputs: One node in the source syntax tree.
   * Outputs: Updated failure collection.
   * Logic: Check executable functions and recursively visit children.
   * Dependencies: TypeScript syntax predicates and hasContract.
   */
  function visit(node) {
    if ((ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node) ||
         ts.isMethodDeclaration(node) || ts.isConstructorDeclaration(node) ||
         ts.isGetAccessorDeclaration(node) || ts.isSetAccessorDeclaration(node)) && !hasContract(node, source)) {
      const location = source.getLineAndCharacterOfPosition(node.getStart(source));
      failures.push(`${name}:${location.line + 1}: missing Inputs, Outputs, Logic, or Dependencies contract`);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return failures;
}

const files = sourceFiles(path.join(root, "web"));
for (const file of fs.readdirSync(path.join(root, "scripts"))) {
  if (file.endsWith(".mjs")) files.push(path.join(root, "scripts", file));
}
const failures = [];
for (const file of files) failures.push(...inspect(file, fs.readFileSync(file, "utf8")));
for (const failure of failures) process.stderr.write(`${failure}\n`);
if (!failures.length) process.stdout.write("Frontend purpose comments and function contracts passed.\n");
process.exitCode = failures.length ? 1 : 0;
