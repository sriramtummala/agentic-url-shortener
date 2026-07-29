def test_openapi_schema_generates_and_covers_expected_paths(app):
    schema = app.openapi()
    assert schema["info"]["title"] == "URL Shortener Service"

    paths = schema["paths"]
    assert "post" in paths["/api/urls"]
    assert "get" in paths["/api/urls/{code}"]
    assert "delete" in paths["/api/urls/{code}"]
    assert "get" in paths["/api/urls/{code}/analytics"]
    assert "get" in paths["/health"]
    assert "get" in paths["/{code}"]
