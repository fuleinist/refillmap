import json
import os
import threading
from urllib.request import urlopen

import pytest

from refillmap.server import App, RefillmapServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    cache = tmp_path_factory.mktemp("cache")
    return App(data_dir=DATA, cache_dir=str(cache), allow_live=False)


def call(app, path, **params):
    query = {key: [str(value)] for key, value in params.items()}
    response = app.route(path, query)
    payload = json.loads(response.body.decode("utf-8")) if response.body else None
    return response.status, payload


def test_health(app):
    status, payload = call(app, "/api/health")
    assert status == 200
    assert payload["ok"] is True


def test_area_list(app):
    status, payload = call(app, "/api/areas")
    assert status == 200
    ids = [area["id"] for area in payload["areas"]]
    assert "newtown" in ids
    assert "parramatta" in ids


def test_plan_returns_three_targets(app):
    status, plan = call(app, "/api/plan", area="newtown", at="2026-11-19T14:00", weather="false")
    assert status == 200
    assert plan["sun"]["isDay"] is True
    assert plan["grid"]["cellM"] == 7.0
    for kind in ("water", "seat", "cool"):
        assert plan["targets"][kind] is not None, kind
        route = plan["targets"][kind]["route"]
        assert len(route["points"]) >= 2
        assert route["lengthM"] > 0
        assert 0 <= route["shadePct"] <= 100


def test_route_starts_near_the_origin(app):
    _, plan = call(app, "/api/plan", area="newtown", at="2026-11-19T13:00", weather="false")
    origin = plan["origin"]
    first = plan["targets"]["water"]["route"]["points"][0]
    assert abs(first[0] - origin["lat"]) + abs(first[1] - origin["lon"]) < 0.002


def test_start_point_changes_the_plan(app):
    _, plan_a = call(
        app, "/api/plan", area="newtown", at="2026-11-19T14:00", weather="false", lat="-33.9060", lon="151.1740"
    )
    _, plan_b = call(
        app, "/api/plan", area="newtown", at="2026-11-19T14:00", weather="false", lat="-33.9100", lon="151.1820"
    )
    spot_a = plan_a["targets"]["water"]["spot"]
    spot_b = plan_b["targets"]["water"]["spot"]
    assert (spot_a["lat"], spot_a["lon"]) != (spot_b["lat"], spot_b["lon"])


def test_unknown_area_is_404(app):
    status, payload = call(app, "/api/plan", area="atlantis")
    assert status == 404
    assert "Unknown area" in payload["detail"]


def test_bad_time_is_400(app):
    status, payload = call(app, "/api/plan", area="newtown", at="yesterday")
    assert status == 400
    assert "ISO 8601" in payload["detail"]


def test_custom_area_needs_coordinates(app):
    status, _ = call(app, "/api/plan", area="here")
    assert status == 400


def test_shade_bitmap_matches_grid(app):
    _, plan = call(app, "/api/plan", area="parramatta", at="2026-11-19T15:00", weather="false")
    bitmap = plan["shade"]["bitmap"]
    assert bitmap["width"] > 0 and bitmap["height"] > 0
    assert len(bitmap["bits"]) > 0
    assert plan["shade"]["buildings"] > 0
    assert plan["shade"]["trees"] > 0


def test_index_page_serves_html(app):
    response = app.route("/", {})
    assert response.status == 200
    assert "refillmap" in response.body.decode("utf-8")
    assert response.content_type.startswith("text/html")


def test_static_path_traversal_is_blocked(app):
    response = app.route("/static/../refillmap/engine.py", {})
    assert response.status == 404


def test_server_answers_over_http(app):
    server = RefillmapServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["ok"] is True
    finally:
        server.shutdown()
        server.server_close()