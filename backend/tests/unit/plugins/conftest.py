from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    """A session on the `client` app's database."""
    from app.api import deps

    s = deps._factory()()
    yield s
    s.close()


@pytest.fixture
def board(client: TestClient) -> str:
    return client.post("/api/boards", json={"title": "Chairs"}).json()["id"]  # type: ignore[no-any-return]
