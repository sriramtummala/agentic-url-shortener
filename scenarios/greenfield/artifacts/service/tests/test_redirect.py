from datetime import datetime, timedelta, timezone


def test_redirect_to_destination(client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/target"}).json()
    resp = client.get(f"/{created['code']}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com/target"


def test_redirect_unknown_code_is_404(client):
    resp = client.get("/doesnotexist", follow_redirects=False)
    assert resp.status_code == 404


def test_redirect_expired_code_is_410(app, client):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    app.state.db.insert_url(
        code="expired", destination_url="https://example.com/old",
        owner_token="t", created_at=datetime.now(timezone.utc).isoformat(), expires_at=past,
    )
    resp = client.get("/expired", follow_redirects=False)
    assert resp.status_code == 410


def test_metadata_expired_code_is_410(app, client):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    app.state.db.insert_url(
        code="expired2", destination_url="https://example.com/old",
        owner_token="t", created_at=datetime.now(timezone.utc).isoformat(), expires_at=past,
    )
    resp = client.get("/api/urls/expired2")
    assert resp.status_code == 410
