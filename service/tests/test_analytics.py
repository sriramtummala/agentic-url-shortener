from datetime import datetime, timezone


def test_analytics_counts_clicks_and_builds_daily_series(client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/page"}).json()
    code = created["code"]

    for _ in range(3):
        client.get(f"/{code}", follow_redirects=False)

    resp = client.get(f"/api/urls/{code}/analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["click_count"] == 3
    assert body["last_accessed_at"] is not None
    assert len(body["daily_clicks"]) == 1
    today = datetime.now(timezone.utc).date().isoformat()
    assert body["daily_clicks"][0] == {"day": today, "count": 3}


def test_analytics_for_never_visited_url_is_zero(client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/page"}).json()
    resp = client.get(f"/api/urls/{created['code']}/analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["click_count"] == 0
    assert body["last_accessed_at"] is None
    assert body["daily_clicks"] == []


def test_analytics_for_unknown_code_is_404(client):
    resp = client.get("/api/urls/doesnotexist/analytics")
    assert resp.status_code == 404


def test_delete_cascades_click_rows(app, client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/page"}).json()
    code = created["code"]
    client.get(f"/{code}", follow_redirects=False)

    client.delete(f"/api/urls/{code}", headers={"X-Owner-Token": created["owner_token"]})

    assert app.state.db.get_click_series(code) == []
