// Try the hosted site on this computer: node dev.mjs  ->  http://localhost:8899/rathescar-grove
// Serves dist/ and runs the function for /api/*. Reads SANITY_TV_READ_TOKEN from the environment.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

globalThis.Netlify = { env: { get: (k) => process.env[k] } };
const { default: api } = await import("./netlify/functions/api.mts");
const here = dirname(fileURLToPath(import.meta.url)), dist = join(here, "dist");
const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".jpg": "image/jpeg",
  ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const redirects = (await readFile(join(dist, "_redirects"), "utf8")).split("\n").filter(Boolean).map((l) => l.trim().split(/\s+/));
const port = +(process.env.PORT || 8899);

createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost:" + port);
  try {
    if (url.pathname.startsWith("/api/")) {
      const chunks = [];
      for await (const c of req) chunks.push(c);
      const r = await api(new Request(url, { method: req.method, headers: req.headers, body: chunks.length ? Buffer.concat(chunks) : undefined }), {});
      res.writeHead(r.status, Object.fromEntries(r.headers));
      return res.end(Buffer.from(await r.arrayBuffer()));
    }
    const red = url.pathname === "/" ? ["/", "/tv/"] : redirects.find((x) => x[0] === url.pathname.replace(/\/$/, ""));
    if (red) { res.writeHead(302, { Location: red[1] }); return res.end(); }
    let p = normalize(url.pathname);
    if (p.endsWith("/")) p += "index.html";
    const body = await readFile(join(dist, p));
    res.writeHead(200, { "Content-Type": TYPES[extname(p)] || "application/octet-stream" });
    res.end(body);
  } catch (e) {
    res.writeHead(e.code === "ENOENT" ? 404 : 500); res.end(String(e.message || e));
  }
}).listen(port, () => console.log("guest-tv hosted, local: http://localhost:" + port + "/"));
