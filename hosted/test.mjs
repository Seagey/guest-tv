// Checks the JavaScript mapping against the Python one (sanity_sync.to_home) on real documents.
//   node test.mjs <parity.json>   where parity.json is {home: {doc, mapped}} written from Python
import { readFile } from "node:fs/promises";
import { isDeepStrictEqual } from "node:util";
import { toHome } from "./lib/sanity-map.mjs";
const data = JSON.parse(await readFile(process.argv[2], "utf8"));
let bad = 0;
for (const [id, { doc, mapped }] of Object.entries(data)) {
  const mine = JSON.parse(JSON.stringify(toHome(doc, "SOS Stays")));
  const same = isDeepStrictEqual(mine, mapped);
  console.log(same ? "PASS" : "FAIL", id);
  if (!same) {
    bad++;
    for (const part of ["home", "guide"]) for (const k of new Set([...Object.keys(mine[part]), ...Object.keys(mapped[part])])) {
      if (!isDeepStrictEqual(mine[part][k], mapped[part][k])) console.log("  differs:", part + "." + k);
    }
  }
}
process.exit(bad ? 1 : 0);
