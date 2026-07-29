import pytest

from orchestrator.state_store import StateStore


@pytest.fixture(autouse=True)
def _close_state_stores_after_test(monkeypatch):
    """StateStore holds a persistent sqlite3 connection for its lifetime.
    Most tests construct one directly (not via a fixture) and don't always
    call .close(), which leaks the connection until garbage collection and
    shows up as ResourceWarnings in the suite. Track every instance created
    during a test and close it automatically afterward -- calling .close()
    twice on a StateStore that already closed itself is a safe no-op, so
    this is safe to layer on top of tests that already clean up explicitly.
    """
    instances = []
    original_init = StateStore.__init__

    def tracked_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        instances.append(self)

    monkeypatch.setattr(StateStore, "__init__", tracked_init)
    yield
    for store in instances:
        store.close()
