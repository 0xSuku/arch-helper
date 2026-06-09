"""Servidor HTTP del panel de control (stdlib only)."""
from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..daily_checks import DailyChecks
from ..device import Device, ROOT
from ..failsafes import STOP_FILE, clear_stop_file
from ..emulator import EmulatorConsole
from ..log import get_logger
from ..paths.daily import EXTRA_CLAIMS, MAIN_LOOP_ORDER
from .jobs import RUNNER, JobBusyError, dispatch

log = get_logger("panel")

STATIC_DIR = Path(__file__).resolve().parent / "static"
LOG_FILE = ROOT / "logs" / "bot.log"


class PanelHandler(BaseHTTPRequestHandler):
    server_version = "ArcheroPanel/1.0"

    def log_message(self, fmt: str, *args) -> None:
        log.debug("HTTP %s", fmt % args)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _serve_static(self, rel: str) -> None:
        path = (STATIC_DIR / rel).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if path.startswith("/static/"):
            return self._serve_static(path.removeprefix("/static/"))

        if path == "/api/status":
            device = Device()
            device.connect()
            console = EmulatorConsole()
            screen_id = "unknown"
            if device.is_connected():
                from ..screens import identify

                screen_id = identify(device.screenshot()).value
            return self._json(
                200,
                {
                    "job": RUNNER.snapshot(),
                    "screen": screen_id,
                    "emulator": {
                        "name": console.display_name,
                        "backend": console.backend,
                        "running": console.is_running(),
                        "index": console.index,
                        "tool_exists": console.tool.exists(),
                    },
                    "ldplayer": {
                        "running": console.is_running(),
                        "index": console.index,
                        "ldconsole_exists": console.tool.exists(),
                    },
                    "adb": {
                        "serial": device.serial,
                        "connected": device.is_connected(),
                    },
                    "stop_requested": STOP_FILE.exists(),
                },
            )

        if path == "/api/claims":
            from ..task_tiers import grouped_panel_items

            return self._json(200, grouped_panel_items())

        if path == "/api/daily-status":
            lines = DailyChecks(force=False).status_lines()
            return self._json(200, {"lines": lines})

        if path == "/api/logs":
            qs = parse_qs(parsed.query)
            lines = int(qs.get("lines", ["120"])[0])
            lines = max(10, min(lines, 500))
            return self._json(200, {"lines": _tail_log(lines)})

        if path == "/api/skills":
            from ..skill_scores import (
                category_labels,
                group_labels,
                list_skill_rows,
                valid_categories,
                valid_groups,
            )

            return self._json(200, {
                "skills": list_skill_rows(),
                "categories": valid_categories(),
                "groups": valid_groups(),
                "category_labels": category_labels(),
                "group_labels": group_labels(),
            })

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/run":
            try:
                body = self._read_json()
                job = str(body.get("job", "")).strip()
                params = body.get("params") or {}
                if not job:
                    return self._json(400, {"ok": False, "error": "Falta job"})
                dispatch(job, params)
                return self._json(200, {"ok": True, "job": job})
            except JobBusyError as exc:
                return self._json(409, {"ok": False, "error": str(exc)})
            except ValueError as exc:
                return self._json(400, {"ok": False, "error": str(exc)})

        if path == "/api/stop":
            STOP_FILE.write_text("", encoding="utf-8")
            log.info("Panel: STOP solicitado")
            return self._json(200, {"ok": True})

        if path == "/api/clear-stop":
            clear_stop_file()
            return self._json(200, {"ok": True})

        if path == "/api/skills/set":
            try:
                from ..skill_scores import resolve_skill_id, set_score

                body = self._read_json()
                skill_id = resolve_skill_id(str(body.get("skill_id", "")))
                score = int(body.get("score", 0))
                set_score(skill_id, score)
                return self._json(200, {"ok": True, "id": skill_id, "score": score})
            except (ValueError, TypeError) as exc:
                return self._json(400, {"ok": False, "error": str(exc)})

        if path == "/api/skills/bump":
            try:
                from ..skill_scores import bump_score, resolve_skill_id

                body = self._read_json()
                skill_id = resolve_skill_id(str(body.get("skill_id", "")))
                delta = int(body.get("delta", 1))
                new_score = bump_score(skill_id, delta)
                return self._json(200, {"ok": True, "id": skill_id, "score": new_score})
            except (ValueError, TypeError) as exc:
                return self._json(400, {"ok": False, "error": str(exc)})

        if path == "/api/skills/update":
            try:
                from ..skill_scores import update_skill_meta

                body = self._read_json()
                result = update_skill_meta(
                    skill_id=str(body.get("skill_id", "")),
                    name=str(body.get("name", "")),
                    category=str(body.get("category", "")),
                    group=str(body.get("group", "")),
                    score=int(body["score"]) if body.get("score") is not None else None,
                    catalog_fp=body.get("catalog_fp") or None,
                )
                return self._json(200, {"ok": True, **result})
            except (ValueError, TypeError) as exc:
                return self._json(400, {"ok": False, "error": str(exc)})

        self.send_error(404)


def _tail_log(max_lines: int) -> list[str]:
    if not LOG_FILE.exists():
        return []
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-max_lines:]


def run_panel(host: str = "127.0.0.1", port: int = 8765) -> None:
    if not STATIC_DIR.exists():
        raise FileNotFoundError(f"Falta carpeta static del panel: {STATIC_DIR}")

    server = ThreadingHTTPServer((host, port), PanelHandler)
    url = f"http://{host}:{port}/"
    log.info("Panel web en %s (Ctrl+C para cerrar)", url)
    print(f"\n  Archero v2 Panel -> {url}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Panel cerrado")
    finally:
        server.server_close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Panel web del bot Archero v2")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run_panel(args.host, args.port)


if __name__ == "__main__":
    main()
