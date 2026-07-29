import pytest
from fastapi.testclient import TestClient

from service.app.main import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(db_path=tmp_path / "test.db")


@pytest.fixture
def client(app):
    return TestClient(app)
