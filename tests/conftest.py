import pytest
from strive.demo import make_demo_index
from strive.config import Settings
from strive.features import DSPExtractor
from strive.api import create_app
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def index():
    return make_demo_index()


@pytest.fixture
def client(index):
    app = create_app(Settings(audit_path=":memory:"), DSPExtractor(), index)
    with TestClient(app) as c:
        yield c
