/** File purpose: Describe and hash the complete built UI for runtime readiness checks. */
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const directory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../web/dist");
const root = path.resolve(directory, "../..");
const manifest = "coach-ui-manifest.json";

/**
 * Inputs: Bytes or canonical text.
 * Outputs: A lowercase SHA-256 digest.
 * Logic: Hash build content without recording machine-specific paths.
 * Dependencies: Node crypto.
 */
function digest(value) { return createHash("sha256").update(value).digest("hex"); }

/**
 * Inputs: One built asset directory.
 * Outputs: Relative file names in that tree.
 * Logic: Enumerate regular public files and reject symbolic links.
 * Dependencies: Node filesystem and path utilities.
 */
function inventory(current) {
  const files = [];
  for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
    const target = path.join(current, entry.name);
    if (entry.isSymbolicLink()) throw new Error("UI assets must not use symbolic links.");
    if (entry.isDirectory()) files.push(...inventory(target));
    else if (entry.isFile() && target !== path.join(directory, manifest)) files.push(path.relative(directory, target).split(path.sep).join("/"));
  }
  return files;
}

if (!fs.existsSync(path.join(directory, "index.html"))) throw new Error("Build the UI before writing its manifest.");
const notices = fs.readFileSync(path.join(root, "THIRD_PARTY_NOTICES.md"), "utf8");
for (const name of ["react", "react-dom", "scheduler"]) {
  const upstream = fs.readFileSync(path.join(root, "web/node_modules", name, "LICENSE"), "utf8").trim();
  if (!notices.includes(upstream)) throw new Error(`Update the third-party notice for ${name} before packaging.`);
}
fs.copyFileSync(path.join(root, "THIRD_PARTY_NOTICES.md"), path.join(directory, "THIRD_PARTY_NOTICES.md"));
fs.copyFileSync(path.join(root, "LICENSE"), path.join(directory, "LICENSE.txt"));
const files = {};
for (const name of inventory(directory).sort()) files[name] = digest(fs.readFileSync(path.join(directory, name)));
const buildId = digest(JSON.stringify(files));
fs.writeFileSync(path.join(directory, manifest), JSON.stringify({
  _comment: "Describe verified public UI assets and their content identity.",
  format_version: 1, api_version: "1", build_id: buildId, files,
}, null, 2) + "\n");
process.stdout.write(`UI asset manifest written: ${buildId}\n`);
