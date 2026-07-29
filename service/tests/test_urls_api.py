from datetime import datetime, timedelta, timezone


def test_create_url_returns_code_and_owner_token(client):
    resp = client.post("/api/urls", json={"destination_url": "https://example.com/very/long/path"})
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["code"]) == 7
    assert body["destination_url"] == "https://example.com/very/long/path"
    assert len(body["owner_token"]) > 10


def test_create_url_rejects_invalid_url(client):
    resp = client.post("/api/urls", json={"destination_url": "not-a-url"})
    assert resp.status_code == 422


def test_create_url_rejects_past_expiry(client):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    resp = client.post("/api/urls", json={"destination_url": "https://example.com", "expires_at": past})
    assert resp.status_code == 422


def test_create_url_accepts_future_expiry(client):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = client.post("/api/urls", json={"destination_url": "https://example.com", "expires_at": future})
    assert resp.status_code == 201
    assert resp.json()["expires_at"] is not None


def test_get_metadata_for_existing_code(client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/page"}).json()
    resp = client.get(f"/api/urls/{created['code']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["destination_url"] == "https://example.com/page"
    assert "owner_token" not in body


def test_get_metadata_for_unknown_code_is_404(client):
    resp = client.get("/api/urls/doesnotexist")
    assert resp.status_code == 404


def test_delete_requires_matching_owner_token(client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/page"}).json()
    code = created["code"]

    resp = client.delete(f"/api/urls/{code}", headers={"X-Owner-Token": "wrong-token"})
    assert resp.status_code == 403

    resp = client.delete(f"/api/urls/{code}", headers={"X-Owner-Token": created["owner_token"]})
    assert resp.status_code == 204

    resp = client.get(f"/api/urls/{code}")
    assert resp.status_code == 404


def test_delete_unknown_code_is_404(client):
    resp = client.delete("/api/urls/doesnotexist", headers={"X-Owner-Token": "x"})
    assert resp.status_code == 404


def test_two_creates_never_collide_in_code(client):
    codes = set()
    for _ in range(20):
        resp = client.post("/api/urls", json={"destination_url": "https://example.com/page"})
        codes.add(resp.json()["code"])
    assert len(codes) == 20
