#!/usr/bin/env node
/**
 * Load the exporter's SQL files into D1, in filename order.
 *
 *   node scripts/seed-local.mjs            # local Miniflare database
 *   node scripts/seed-local.mjs --remote   # the real D1 database
 *
 * Run `wrangler d1 migrations apply` first: this script only writes data.
 */
import { execFileSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const dataDir = resolve(root, "..", "dist", "d1");
const remote = process.argv.includes("--remote");
const wrangler = join(root, "node_modules", ".bin", "wrangler");

let files;
try {
  files = readdirSync(dataDir)
    .filter((name) => name.startsWith("data-") && name.endsWith(".sql"))
    .sort();
} catch {
  console.error(`No exported data in ${dataDir}. Run: python python/export_cloudflare.py`);
  process.exit(1);
}

if (files.length === 0) {
  console.error(`No SQL files in ${dataDir}.`);
  process.exit(1);
}

for (const [index, file] of files.entries()) {
  const path = join(dataDir, file);
  console.log(`[${index + 1}/${files.length}] ${file}`);
  const args = ["d1", "execute", "phonetariffs", "--file", path, remote ? "--remote" : "--local", "--yes"];
  execFileSync(wrangler, args, { cwd: root, stdio: "inherit" });
}

console.log(`Loaded ${files.length} files into ${remote ? "remote" : "local"} D1.`);
