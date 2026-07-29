"""End-to-end user-journey test: exercises the full API surface in one
flow, as a real caller would, rather than one endpoint at a time."""

from datetime import datetime, timedelta, timezone


def test_full_url_lifecycle(client):
    create_resp = client.post("/api/urls", json={
        "destination_url": "https://example.com/product/123",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
    })
    assert create_resp.status_code == 201
    created = create_resp.json()
    code = created["code"]
    owner_token = created["owner_token"]

    meta_resp = client.get(f"/api/urls/{code}")
    assert meta_resp.status_code == 200
    assert meta_resp.json()["destination_url"] == "https://example.com/product/123"

    for _ in range(5):
        redirect_resp = client.get(f"/{code}", follow_redirects=False)
        assert redirect_resp.status_code == 302
        assert redirect_resp.headers["location"] == "https://example.com/product/123"

    analytics_resp = client.get(f"/api/urls/{code}/analytics")
    assert analytics_resp.status_code == 200
    assert analytics_resp.json()["click_count"] == 5

    delete_resp = client.delete(f"/api/urls/{code}", headers={"X-Owner-Token": owner_token})
    assert delete_resp.status_code == 204

    assert client.get(f"/api/urls/{code}").status_code == 404
    assert client.get(f"/{code}", follow_redirects=False).status_code == 404
    assert client.get(f"/api/urls/{code}/analytics").status_code == 404
    assert client.delete(f"/api/urls/{code}", headers={"X-Owner-Token": owner_token}).status_code == 404
