// Podgląd TasteCode bez backendu w Pythonie: te same adresy co FastAPI (backend/app/main.py), czyli "/" z {{NAME}}
// i /static/ z katalogu frontend/. Bez zależności; port z PORT (ustawia TasteCode), potem --port, potem 4173.
// shortcut: bez API, /auth, /files, sw.js i manifestu (503), więc zakładki z danymi pokazują swój komunikat błędu;
// podgląd z danymi tylko z prawdziwym backendem (uvicorn), gdy TasteCode pozwoli uruchomić Pythona
// Sprawdzenie bez uruchamiania serwera: node .taste/preview/server.mjs --check
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = fileURLToPath(new URL("../../frontend", import.meta.url));
const NAME = "PolIDS";   // domyślne settings.name (backend/app/config.py)
const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon" };

// adres → plik we frontend/ albo null (inne adresy i wszystko, co wychodzi poza frontend/)
function route(pathname) {
  if (pathname === "/") return join(FRONTEND, "index.html");
  if (!pathname.startsWith("/static/")) return null;
  const file = resolve(FRONTEND, "." + decodeURIComponent(pathname.slice("/static".length)));
  return file.startsWith(FRONTEND + sep) ? file : null;
}

if (process.argv.includes("--check")) {
  assert.equal(route("/"), join(FRONTEND, "index.html"));
  assert.equal(route("/static/css/style.css"), join(FRONTEND, "css", "style.css"));
  assert.equal(route("/static/..%2fbackend%2fapp%2fmain.py"), null);
  assert.equal(route("/static/..%5c.env"), null);
  assert.equal(route("/api/config"), null);
  console.log("preview server check ok");
} else {
  const server = createServer(async (req, res) => {
    let file = null, body = null;
    try {
      file = route(new URL(req.url, "http://127.0.0.1").pathname);
      if (file) body = await readFile(file);
    } catch { /* zły %-kod w adresie, brak pliku albo katalog */ }
    if (!body) {
      // JSON z detail jak w FastAPI: api() pokazuje go w zakładce zamiast danych
      res.writeHead(file ? 404 : 503, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ detail: file ? "Not Found" : "no PolIDS server in this preview" }));
    }
    if (file.endsWith(".html")) body = body.toString("utf8").replaceAll("{{NAME}}", NAME);
    res.writeHead(200, { "Content-Type": TYPES[extname(file)] || "application/octet-stream", "Cache-Control": "no-cache" });
    res.end(body);
  });
  const arg = process.argv.indexOf("--port");
  const port = Number(process.env.PORT || (arg > 0 && process.argv[arg + 1]) || 4173);
  server.listen(port, "127.0.0.1", () => console.log(`PolIDS preview on http://127.0.0.1:${port}/`));
}
