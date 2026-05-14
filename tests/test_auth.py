"""Tests for the JWT authentication flow and watchlist endpoints."""

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_success(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"username": "alice", "password": "securepass1"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "alice"
    assert data["is_admin"] is False
    assert "hashed_password" not in data
    assert "id" in data


def test_register_duplicate_username(client: TestClient) -> None:
    payload = {"username": "bob", "password": "securepass1"}
    client.post("/auth/register", json=payload)
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]


def test_register_password_too_short(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"username": "charlie", "password": "short"},
    )
    # Pydantic min_length=8 on password → 422 Unprocessable Entity
    assert response.status_code == 422


def test_register_username_too_short(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"username": "ab", "password": "validpass1"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_success(client: TestClient) -> None:
    client.post("/auth/register", json={"username": "dana", "password": "pass12345"})
    response = client.post(
        "/auth/login",
        data={"username": "dana", "password": "pass12345"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    # JWT has three dot-separated segments
    assert data["access_token"].count(".") == 2


def test_login_wrong_password(client: TestClient) -> None:
    client.post("/auth/register", json={"username": "eve", "password": "correct12"})
    response = client.post(
        "/auth/login",
        data={"username": "eve", "password": "wrongpass"},
    )
    assert response.status_code == 401


def test_login_nonexistent_user(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        data={"username": "ghost", "password": "anypass12"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Protected endpoints — authentication enforcement
# ---------------------------------------------------------------------------


def test_watchlist_requires_auth(client: TestClient) -> None:
    response = client.get("/auth/me/watchlist")
    assert response.status_code == 401


def test_watchlist_add_requires_auth(client: TestClient) -> None:
    response = client.post("/auth/me/watchlist/Canada")
    assert response.status_code == 401


def test_invalid_token_rejected(client: TestClient) -> None:
    response = client.get(
        "/auth/me/watchlist",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Watchlist CRUD (requires an existing Country row)
# ---------------------------------------------------------------------------


def _register_and_login(client: TestClient, username: str) -> dict:
    """Helper: register a user and return auth headers."""
    client.post(
        "/auth/register",
        json={"username": username, "password": "pass12345"},
    )
    token = client.post(
        "/auth/login",
        data={"username": username, "password": "pass12345"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _insert_country(test_engine, name: str = "Canada", region: str = "Americas") -> None:
    """Insert a Country row directly without going through HTTP."""
    from sqlalchemy.orm import sessionmaker
    from app.models import Country

    Session = sessionmaker(bind=test_engine)
    db = Session()
    try:
        db.add(Country(name=name, region=region))
        db.commit()
    finally:
        db.close()


def test_watchlist_empty_for_new_user(client: TestClient) -> None:
    headers = _register_and_login(client, "frank")
    response = client.get("/auth/me/watchlist", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_watchlist_add_and_retrieve(client: TestClient, test_engine) -> None:
    _insert_country(test_engine, "Canada", "Americas")
    headers = _register_and_login(client, "grace")

    add_resp = client.post("/auth/me/watchlist/Canada", headers=headers)
    assert add_resp.status_code == 200
    assert add_resp.json()["name"] == "Canada"

    list_resp = client.get("/auth/me/watchlist", headers=headers)
    assert list_resp.status_code == 200
    watchlist = list_resp.json()
    assert len(watchlist) == 1
    assert watchlist[0]["name"] == "Canada"


def test_watchlist_add_nonexistent_country(client: TestClient) -> None:
    headers = _register_and_login(client, "henry")
    response = client.post("/auth/me/watchlist/Nonexistent", headers=headers)
    assert response.status_code == 404


def test_watchlist_add_duplicate(client: TestClient, test_engine) -> None:
    _insert_country(test_engine, "Germany", "Europe")
    headers = _register_and_login(client, "ingrid")

    client.post("/auth/me/watchlist/Germany", headers=headers)
    response = client.post("/auth/me/watchlist/Germany", headers=headers)
    assert response.status_code == 409


def test_watchlist_remove(client: TestClient, test_engine) -> None:
    _insert_country(test_engine, "Japan", "Asia-Pacific")
    headers = _register_and_login(client, "jun")

    client.post("/auth/me/watchlist/Japan", headers=headers)
    del_resp = client.delete("/auth/me/watchlist/Japan", headers=headers)
    assert del_resp.status_code == 204

    list_resp = client.get("/auth/me/watchlist", headers=headers)
    assert list_resp.json() == []


def test_watchlist_remove_nonexistent(client: TestClient) -> None:
    headers = _register_and_login(client, "karen")
    response = client.delete("/auth/me/watchlist/NotInWatchlist", headers=headers)
    assert response.status_code == 404
