import { build } from "esbuild";
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";

function run(command, args) {
  const result = spawnSync(command, args, { stdio: "inherit", shell: false });
  if (result.status !== 0) process.exit(result.status || 1);
}
run(process.execPath, ["node_modules/typescript/bin/tsc", "--noEmit"]);
await build({ entryPoints: ["web/neon-auth.ts"], bundle: true, platform: "browser", target: "es2022", format: "iife", minify: true, outfile: "apps/api/app/static/neon-auth.js" });
for (const file of readdirSync("apps/api/app/static").filter(f => f.endsWith(".js"))) run(process.execPath, ["--check", "apps/api/app/static/" + file]);
run(process.env.PYTHON || "python", ["-m", "compileall", "-q", "apps/api/app", "apps/api/migrations"]);
console.log("BUILD PASSED: Neon config/function types, auth browser bundle, JavaScript syntax and Python compilation.");
