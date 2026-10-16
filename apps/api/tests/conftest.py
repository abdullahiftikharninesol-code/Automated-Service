from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.main import app


@pytest.fixture(autouse=True)
def disable_limiter_by_default() -> Generator[None, None, None]:
    limiter.enabled = False
    limiter.reset()
    try:
        yield
    finally:
        limiter.reset()
        limiter.enabled = False


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    def override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register(client: TestClient, suffix: str = "one") -> dict[str, object]:
    response = client.post(
        "/auth/register",
        json={
            "organization_name": f"Comfort {suffix}",
            "name": "Owner",
            "email": f"owner-{suffix}@example.com",
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def account(client: TestClient) -> dict[str, object]:
    return register(client)


@pytest.fixture
def auth_headers(account: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {account['access_token']}"}
