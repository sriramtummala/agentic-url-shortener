def test_create_url_rejects_denylisted_destination(client):
    resp = client.post("/api/urls", json={"destination_url": "https://malware-example.test/payload"})
    assert resp.status_code == 422


def test_create_url_allows_non_denylisted_destination(client):
    resp = client.post("/api/urls", json={"destination_url": "https://example.com/page"})
    assert resp.status_code == 201


def test_report_below_threshold_does_not_flag(client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/page"}).json()
    code = created["code"]

    resp = client.post(f"/api/urls/{code}/report")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_count"] == 1
    assert body["flagged"] is False

    redirect = client.get(f"/{code}", follow_redirects=False)
    assert redirect.status_code == 302


def test_report_threshold_flags_and_blocks_redirect(client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/page"}).json()
    code = created["code"]

    last = None
    for _ in range(3):  # default REPORT_THRESHOLD
        last = client.post(f"/api/urls/{code}/report")
    assert last.json()["flagged"] is True

    redirect = client.get(f"/{code}", follow_redirects=False)
    assert redirect.status_code == 403

    meta = client.get(f"/api/urls/{code}")
    assert meta.status_code == 200
    assert meta.json()["flagged"] is True
    assert meta.json()["report_count"] == 3


def test_flagging_invalidates_a_warm_cache_entry(client):
    created = client.post("/api/urls", json={"destination_url": "https://example.com/page"}).json()
    code = created["code"]

    client.get(f"/{code}", follow_redirects=False)  # warm the cache

    for _ in range(3):
        client.post(f"/api/urls/{code}/report")

    redirect = client.get(f"/{code}", follow_redirects=False)
    assert redirect.status_code == 403


def test_report_unknown_code_is_404(client):
    resp = client.post("/api/urls/doesnotexist/report")
    assert resp.status_code == 404
