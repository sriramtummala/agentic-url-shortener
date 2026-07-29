def test_health_check_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_check_reports_503_when_db_unavailable(app, client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(app.state.db, "code_exists", broken)
    resp = client.get("/health")
    assert resp.status_code == 503
