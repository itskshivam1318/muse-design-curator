import pytest

from tests.unit.providers.fake_http import FakeApi


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()
