// Builds the hosted site: the same TV and phone pages the house computer serves (../web), and the
// list of homes the function answers for (../data/homes, the ones that name a Sanity property).
import { cp, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const web = join(root, "web"), dist = join(here, "dist");
const readJson = async (p) => JSON.parse(await readFile(p, "utf8"));

const settings = await readJson(join(root, "data", "settings.json"));
const homes = {};
for (const id of (await readdir(join(root, "data", "homes"))).sort()) {
  const dir = join(root, "data", "homes", id);
  if (!existsSync(join(dir, "home.json"))) continue;
  const home = await readJson(join(dir, "home.json"));
  if (home.demo || !(home.sanity || {}).property) continue;   // the demo homes need the house computer's pretend devices
  homes[id] = { home, guide: existsSync(join(dir, "guide.json")) ? await readJson(join(dir, "guide.json")) : {} };
}
await writeFile(join(here, "lib", "homes.generated.mjs"),
  "// written by build.mjs from data/homes and data/settings.json\n" +
  "export const HOMES = " + JSON.stringify(homes, null, 2) + ";\n" +
  "export const SETTINGS = " + JSON.stringify({ brand: settings.brand || {}, sanity: settings.sanity || {}, weather: settings.weather || {},
    default_home: homes[settings.default_home] ? settings.default_home : Object.keys(homes)[0] }, null, 2) + ";\n");

await rm(dist, { recursive: true, force: true });
await mkdir(join(dist, "tv"), { recursive: true });
await mkdir(join(dist, "p"), { recursive: true });
for (const f of ["tv.css", "tv.js"]) await cp(join(web, f), join(dist, "tv", f));
await cp(join(web, "index.html"), join(dist, "tv", "index.html"));
await cp(join(web, "phone.html"), join(dist, "p", "index.html"));
for (const d of ["fonts", "brand"]) {
  await cp(join(web, d), join(dist, "tv", d), { recursive: true });
  await cp(join(web, d), join(dist, "p", d), { recursive: true });
}
// photos: only the homes that are served, and the shared SOS Stays backdrop
const wanted = new Set(["sos-hero"]);
for (const h of Object.values(homes)) for (const v of Object.values(h.home.photos || {})) wanted.add(v);
await mkdir(join(dist, "tv", "homes"), { recursive: true });
await mkdir(join(dist, "p", "homes"), { recursive: true });
for (const f of await readdir(join(web, "homes"))) {
  if ([...wanted].some((w) => f === w + ".jpg" || f.startsWith(w + "-"))) {
    await cp(join(web, "homes", f), join(dist, "tv", "homes", f));
    await cp(join(web, "homes", f), join(dist, "p", "homes", f));
  }
}
// /<home id> opens that home's TV screen
await writeFile(join(dist, "_redirects"), Object.keys(homes).map((id) => `/${id}  /tv/?home=${id}  302`).join("\n") + "\n");

// .deploy/: everything Netlify needs and nothing else (no data/private.json, no Python), ready to upload.
// Netlify installs the function's packages itself and has nothing to build.
const pack = join(here, ".deploy");
await rm(pack, { recursive: true, force: true });
await mkdir(pack, { recursive: true });
await cp(dist, join(pack, "site"), { recursive: true });
await cp(join(here, "netlify"), join(pack, "netlify"), { recursive: true });
await cp(join(here, "lib"), join(pack, "lib"), { recursive: true });
for (const f of ["package.json", "package-lock.json"]) if (existsSync(join(here, f))) await cp(join(here, f), join(pack, f));
await writeFile(join(pack, "netlify.toml"), `# written by hosted/build.mjs
[build]
  publish = "site"
[functions]
  directory = "netlify/functions"
[[redirects]]
  from = "/"
  to = "/tv/"
  status = 302
`);
console.log("Built", Object.keys(homes).join(", "), "-> dist/ and .deploy/");
