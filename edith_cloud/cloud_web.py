from __future__ import annotations

import json
import logging
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger("edith.cloud_web")


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EDITH Cloud Command Center</title>
  <style>
    :root {
      --bg: #071018;
      --panel: #0d1b2a;
      --panel2: #12263a;
      --line: #21435f;
      --txt: #e9f3ff;
      --muted: #9fb8cc;
      --acc: #20d4ff;
      --ok: #22c55e;
      --warn: #f59e0b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; color: var(--txt); background:
      radial-gradient(1200px 700px at 10% -20%, #11314d 0%, transparent 50%),
      radial-gradient(900px 500px at 100% 0%, #0d2f3f 0%, transparent 45%),
      var(--bg);
      font-family: "Segoe UI", system-ui, sans-serif;
      min-height: 100vh;
      animation: fade .35s ease;
    }
    @keyframes fade { from {opacity: .6; transform: translateY(5px)} to {opacity:1; transform:none} }
    .wrap { max-width: 1280px; margin: 0 auto; padding: 20px; }
    .head {
      display: flex; gap: 12px; align-items: center; justify-content: space-between;
      background: linear-gradient(180deg, #13293f, #102336);
      border: 1px solid var(--line); border-radius: 16px; padding: 16px 20px;
      box-shadow: 0 20px 50px rgba(0,0,0,.3);
    }
    .title { font-weight: 700; letter-spacing: .2px; }
    .sub { color: var(--muted); font-size: 13px; margin-top: 3px; }
    .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; margin-top: 14px; }
    .card { background: linear-gradient(180deg, var(--panel2), var(--panel)); border: 1px solid var(--line); border-radius: 14px; padding: 14px; }
    .log { height: 58vh; overflow: auto; white-space: pre-wrap; line-height: 1.45; font-family: Consolas, monospace; font-size: 14px; }
    .row { display: flex; gap: 10px; margin-top: 10px; }
    input, button, select {
      border-radius: 10px; border: 1px solid var(--line); background: #0f2234; color: var(--txt);
      padding: 11px 12px; font-size: 14px;
    }
    input { flex: 1; }
    button { cursor: pointer; transition: transform .12s ease, border-color .12s ease, background .12s ease; }
    button:hover { transform: translateY(-1px); border-color: var(--acc); background: #12324b; }
    button:disabled { opacity: .5; cursor: default; transform: none; }
    .chips { display: grid; gap: 8px; }
    .chip { border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; font-size: 13px; color: var(--muted); }
    .ok { color: var(--ok); } .warn { color: var(--warn); }
    .pulse { animation: pulse 1s infinite ease-in-out; }
    @keyframes pulse { 0%{opacity:.5}50%{opacity:1}100%{opacity:.5} }
    @media (max-width: 980px) {
      .grid { grid-template-columns: 1fr; }
      .log { height: 45vh; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="head">
      <div>
        <div class="title">EDITH Cloud Command Center</div>
        <div class="sub">Realtime, voice-enabled, categorized, cloud-only interface</div>
      </div>
      <div id="health" class="sub">Checking services...</div>
    </div>
    <div class="grid">
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b>Conversation</b>
          <span id="state" class="sub">Idle</span>
        </div>
        <div id="log" class="log"></div>
        <div class="row">
          <input id="prompt" placeholder="Type command..." />
          <button id="send">Send</button>
          <button id="mic">Voice</button>
        </div>
      </div>
      <div class="card">
        <b>Classification</b>
        <div class="chips" style="margin-top:8px">
          <div id="intent" class="chip">Intent: -</div>
          <div id="route" class="chip">Route: -</div>
          <div id="latency" class="chip">Latency: -</div>
          <div class="chip">Accessibility:
            <span class="ok">Browser TTS</span>,
            <span class="ok">Browser Voice Input</span>
          </div>
        </div>
      </div>
    </div>
  </div>
<script>
const log = document.getElementById("log");
const promptEl = document.getElementById("prompt");
const sendBtn = document.getElementById("send");
const micBtn = document.getElementById("mic");
const stateEl = document.getElementById("state");
const healthEl = document.getElementById("health");
const intentEl = document.getElementById("intent");
const routeEl = document.getElementById("route");
const latencyEl = document.getElementById("latency");

function appendLine(who, text) {
  const t = new Date().toLocaleTimeString();
  log.textContent += `[${t}] ${who}: ${text}\\n`;
  log.scrollTop = log.scrollHeight;
}
function classify(text) {
  const s = text.toLowerCase();
  if (s.includes("image") || s.includes("generate")) return ["creative", "cloud_image_gen"];
  if (s.includes("search") || s.includes("web")) return ["research", "cloud_search"];
  if (s.includes("plan")) return ["planning", "cloud_llm_heavy"];
  if (s.includes("message") || s.includes("whatsapp")) return ["communication", "cloud_router_whatsapp"];
  return ["general", "cloud_llm_fast"];
}
async function refreshStatus() {
  try {
    const r = await fetch("/api/status");
    const d = await r.json();
    const p = d.preflight || {};
    const parts = Object.entries(p).map(([k,v]) => `${k}:${v ? "OK":"OFF"}`);
    healthEl.textContent = parts.join(" | ");
  } catch {
    healthEl.textContent = "Status unavailable";
  }
}
async function sendCommand(text) {
  if (!text.trim()) return;
  const [intent, route] = classify(text);
  intentEl.textContent = `Intent: ${intent}`;
  routeEl.textContent = `Route: ${route}`;
  appendLine("YOU", text);
  stateEl.textContent = "Processing...";
  stateEl.classList.add("pulse");
  sendBtn.disabled = true;
  const t0 = performance.now();
  try {
    const r = await fetch("/api/command", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text})
    });
    const d = await r.json();
    appendLine("EDITH", d.reply || "(no reply)");
    const dt = Math.round(performance.now() - t0);
    latencyEl.textContent = `Latency: ${dt} ms`;
    if ("speechSynthesis" in window && d.reply) {
      const u = new SpeechSynthesisUtterance(d.reply);
      u.rate = 1.03;
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(u);
    }
  } catch (e) {
    appendLine("SYSTEM", "Request failed.");
  } finally {
    stateEl.textContent = "Idle";
    stateEl.classList.remove("pulse");
    sendBtn.disabled = false;
  }
}
sendBtn.onclick = () => { const t = promptEl.value; promptEl.value = ""; sendCommand(t); };
promptEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { const t = promptEl.value; promptEl.value = ""; sendCommand(t); }
});
micBtn.onclick = () => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { appendLine("SYSTEM", "Browser speech recognition not available."); return; }
  const rec = new SR();
  rec.lang = "en-US"; rec.interimResults = false; rec.maxAlternatives = 1;
  stateEl.textContent = "Listening...";
  rec.onresult = (e) => {
    const heard = e.results[0][0].transcript || "";
    sendCommand(heard);
  };
  rec.onend = () => { stateEl.textContent = "Idle"; };
  rec.onerror = () => { stateEl.textContent = "Idle"; };
  rec.start();
};
refreshStatus();
setInterval(refreshStatus, 2000);
</script>
</body>
</html>
"""


def serve_cloud_web(assistant: Any, host: str = "127.0.0.1", port: int = 8765, auto_open: bool = True) -> None:
    """
    Start the cloud web UI server and block forever.
    """
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "EDITHCloudWeb/1.0"

        def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/" or self.path.startswith("/?"):
                body = HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path == "/api/status":
                preflight = getattr(assistant, "cloud_preflight", {})
                self._write_json({"ok": True, "preflight": preflight})
                return

            self._write_json({"ok": False, "error": "Not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/command":
                self._write_json({"ok": False, "error": "Not found"}, status=404)
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                text = str(payload.get("text", "")).strip()
                if not text:
                    self._write_json({"ok": False, "error": "Empty command"}, status=400)
                    return

                with lock:
                    started = time.perf_counter()
                    result = assistant.handle(text)
                    ms = int((time.perf_counter() - started) * 1000)
                self._write_json(
                    {
                        "ok": True,
                        "reply": result.reply,
                        "action": result.action,
                        "metadata": result.metadata,
                        "latency_ms": ms,
                    }
                )
            except Exception as exc:
                logger.exception("Web command failed")
                self._write_json({"ok": False, "error": str(exc)}, status=500)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            logger.debug("%s - %s", self.address_string(), format % args)

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    logger.info("Cloud web UI available at %s", url)
    print(f"EDITH Cloud Web UI: {url}")
    if auto_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    server.serve_forever()

