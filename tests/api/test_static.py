from pathlib import Path

import pytest
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


@pytest.mark.parametrize("path", [
    "/%5C%5Cevil-host%5Cshare%5Cx",        # \\evil-host\share\x : UNC -> SMB 접속 시도 금지
    "/%5C%5C%3F%5CC%3A%5Csecret.txt",      # \\?\C:\...
    "///evil-host/share/x",                # path 가 //evil-host/... -> dist / path 가 UNC 가 됨
    "/..%5Csecret.txt", "/sub%5C..%5C..%5Csecret.txt",
    "/C:%5Csecret.txt", "/C:/secret.txt", "/x%00y", "/%00",
])
def test_suspicious_paths_return_index_without_touching_filesystem(tmp_path, monkeypatch, path):
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>SPA-INDEX</html>", encoding="utf-8")
    c = TestClient(create_app(dist))
    inside = str(dist.resolve()) + "\\"
    touched = []
    real_resolve, real_is_file = Path.resolve, Path.is_file

    def spy_resolve(self, *a, **k):
        touched.append(str(self))
        return real_resolve(self, *a, **k)

    def spy_is_file(self, *a, **k):
        touched.append(str(self))
        return real_is_file(self, *a, **k)

    monkeypatch.setattr(Path, "resolve", spy_resolve)
    monkeypatch.setattr(Path, "is_file", spy_is_file)
    r = c.get(path)
    assert r.status_code == 200, (path, r.status_code)
    assert "SPA-INDEX" in r.text and "SECRET" not in r.text
    # 파일시스템 접근은 dist 내부의 평범한 경로뿐이어야 한다 (UNC·드라이브·상위 디렉터리·NUL 금지)
    assert all(t.startswith(inside) and "\x00" not in t and "secret" not in t.lower() for t in touched), touched


def test_filesystem_errors_fall_back_to_index(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>SPA-INDEX</html>", encoding="utf-8")
    c = TestClient(create_app(dist), raise_server_exceptions=False)

    def boom(self, *a, **k):
        raise OSError("device not ready")

    monkeypatch.setattr(Path, "is_file", boom)
    r = c.get("/some/page")
    assert r.status_code == 200 and "SPA-INDEX" in r.text
