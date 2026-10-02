from fastapi.testclient import TestClient

from tests.conftest import register


def test_register_login_and_me(client: TestClient) -> None:
    registered = register(client, "auth")
    response = client.post(
        "/auth/login",
        json={"email": "owner-auth@example.com", "password": "StrongPassword123!"},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["organization_id"] == registered["user"]["organization_id"]
    assert "password_hash" not in me.json()


def test_login_rejects_bad_password(client: TestClient) -> None:
    register(client, "wrong")
    response = client.post(
        "/auth/login",
        json={"email": "owner-wrong@example.com", "password": "not-the-password"},
    )
    assert response.status_code == 401
