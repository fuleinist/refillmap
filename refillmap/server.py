"""HTTP server for refillmap. Python standard library only."""

from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .engine import Engine

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


class BadRequest(Exception):
    pass


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/json; charset=utf-8"


def json_response(payload: object, status: int = 200) -> Response:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return Response(status=status, body=body, content_type="application/json; charset=utf-8")


def _first(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[0]


def _float(query: dict[str, list[str]], key: str, default: float) -> float:
    raw = _first(query, key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise BadRequest(f"Bad number for {key}") from exc


def _bool(query: dict[str, list[str]], key: str, default: bool) -> bool:
    raw = _first(query, key)
    if raw is None or raw == "":
        return default
    return raw.lower() not in ("0", "false", "no", "off")


class App:
    """Route table for the refillmap API and static files."""

    def __init__(self, data_dir: str | None = None, cache_dir: str | None = None, allow_live: bool = True):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_dir = data_dir or os.path.join(root, "data")
        self.cache_dir = cache_dir or os.path.join(root, "cache")
        self.web_dir = WEB_DIR
        self.engine = Engine(self.data_dir, self.cache_dir, allow_live=allow_live)

    def route(self, path: str, query: dict[str, list[str]]) -> Response:
        try:
            if path == "/api/health":
                return json_response({"ok": True, "areas": len(self.engine.list_areas())})
            if path == "/api/areas":
                return json_response({"areas": self.engine.list_areas()})
            if path.startswith("/api/area/"):
                return self._area_detail(path[len("/api/area/"):])
            if path == "/api/plan":
                return self._plan(query)
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            return json_response({"detail": "Not found"}, 404)
        except BadRequest as exc:
            return json_response({"detail": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001 - a server must answer
            return json_response({"detail": f"Internal error: {exc}"}, 500)

    def _area_detail(self, area_id: str) -> Response:
        try:
            area = self.engine.area(area_id)
        except KeyError:
            return json_response({"detail": f"Unknown area: {area_id}"}, 404)
        prepared = self.engine.prepared(area)
        return json_response(
            {
                "id": area.id,
                "name": area.name,
                "source": area.source,
                "fetchedAt": area.fetched_at,
                "map": prepared.map_payload,
            }
        )

    def _plan(self, query: dict[str, list[str]]) -> Response:
        area_id = _first(query, "area", "newtown") or "newtown"
        shade = _float(query, "shade", 1.5)
        shade = max(0.0, min(4.0, shade))
        lat = _first(query, "lat")
        lon = _first(query, "lon")
        weather = _bool(query, "weather", True)
        when = self._parse_time(_first(query, "at"))

        origin: tuple[float, float] | None = None
        if lat not in (None, "") and lon not in (None, ""):
            try:
                origin = (float(lat), float(lon))
            except ValueError as exc:
                raise BadRequest("Bad lat or lon") from exc
            if not (-90.0 <= origin[0] <= 90.0 and -180.0 <= origin[1] <= 180.0):
                raise BadRequest("lat or lon out of range")

        try:
            area = self.engine.area(area_id)
        except KeyError:
            if area_id not in ("custom", "here"):
                return json_response({"detail": f"Unknown area: {area_id}"}, 404)
            if origin is None:
                raise BadRequest("A custom area needs a lat and lon pair.")
            try:
                area = self.engine.live_area_for(origin[0], origin[1])
            except RuntimeError as exc:
                return json_response({"detail": str(exc)}, 503)

        try:
            plan = self.engine.plan(area, when, shade_weight=shade, origin=origin, include_weather=weather)
        except RuntimeError as exc:
            return json_response({"detail": str(exc)}, 422)
        return json_response(plan)

    @staticmethod
    def _parse_time(value: str | None) -> datetime:
        if not value:
            return datetime.now().astimezone()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise BadRequest("Bad time value. Use ISO 8601, for example 2026-11-19T14:00.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed

    def _static(self, relative: str) -> Response:
        root = os.path.abspath(self.web_dir)
        target = os.path.abspath(os.path.join(root, relative.lstrip("/\\")))
        if not target.startswith(root + os.sep) and target != root:
            return json_response({"detail": "Not found"}, 404)
        if not os.path.isfile(target):
            return json_response({"detail": "Not found"}, 404)
        content_type, _ = mimetypes.guess_type(target)
        content_type = content_type or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        with open(target, "rb") as handle:
            body = handle.read()
        return Response(status=200, body=body, content_type=content_type)


class RefillmapHandler(BaseHTTPRequestHandler):
    server_version = "refillmap/0.1"
    app: App

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self._respond()

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib naming
        self._respond()

    def _respond(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        response = self.app.route(parsed.path, query)
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def log_message(self, fmt: str, *args) -> None:
        return


class RefillmapServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: App):
        self.app = app
        handler = type("BoundRefillmapHandler", (RefillmapHandler,), {"app": app})
        super().__init__(address, handler)


def serve(host: str = "127.0.0.1", port: int = 8099, app: App | None = None) -> RefillmapServer:
    server = RefillmapServer((host, port), app or App())
    print(f"refillmap on http://{host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return server