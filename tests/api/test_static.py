from fastapi.testclient import TestClient

from backend.app.main import create_app


def _client(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>SPA-INDEX</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return TestClient(create_app(tmp_path))


def test_root_and_spa_routes_return_index(tmp_path):
    c = _client(tmp_path)
    for path in ("/", "/floor", "/work-orders/12", "/results/new"):
        r = c.get(path)
        assert r.status_code == 200 and "SPA-INDEX" in r.text, path
        assert r.headers["content-type"].startswith("text/html")


def test_assets_are_real_files(tmp_path):
    c = _client(tmp_path)
    r = c.get("/assets/app.js")
    assert r.status_code == 200 and r.text == "console.log(1)"
    assert c.get("/assets/missing.js").status_code == 404


def test_api_still_json(tmp_path):
    c = _client(tmp_path)
    assert c.get("/api/health").json() == {"status": "ok"}
    r = c.get("/api/does-not-exist")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    assert "SPA-INDEX" not in r.text


def test_path_traversal_does_not_leak(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>SPA-INDEX</html>", encoding="utf-8")
    c = TestClient(create_app(dist))
    assert "SECRET" not in c.get("/..%2Fsecret.txt").text
    assert "SECRET" not in c.get("/../secret.txt").text


def test_no_dist_means_api_only(tmp_path):
    c = TestClient(create_app(tmp_path / "nope"))
    assert c.get("/api/health").status_code == 200
    assert c.get("/").status_code == 404
