import pytest
from fastapi.testclient import TestClient

from service.app.main import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(db_path=tmp_path / "test.db")


@pytest.fixture
def client(app):
    # Used as a context manager so FastAPI's lifespan startup/shutdown
    # actually runs (plain TestClient(app) skips it), which is what was
    # leaving background resources for pytest to warn about at GC time.
    with TestClient(app) as test_client:
        yield test_client
