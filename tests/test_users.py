import pytest


async def test_update_settings(client, alice):
    response = await client.patch(
        "/users/me/settings",
        json={"digest_time": "07:30:00", "timezone": "Europe/Warsaw"},
        headers=alice,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["digest_time"] == "07:30:00"
    assert data["timezone"] == "Europe/Warsaw"


async def test_update_settings_persists(client, alice):
    await client.patch(
        "/users/me/settings", json={"timezone": "Asia/Tokyo"}, headers=alice
    )

    me = await client.get("/users/me", headers=alice)

    assert me.json()["timezone"] == "Asia/Tokyo"


async def test_partial_update_keeps_other_fields(client, alice):
    await client.patch(
        "/users/me/settings", json={"digest_time": "10:00:00"}, headers=alice
    )

    response = await client.patch(
        "/users/me/settings", json={"timezone": "Europe/Paris"}, headers=alice
    )

    assert response.json()["digest_time"] == "10:00:00"
    assert response.json()["timezone"] == "Europe/Paris"


async def test_unknown_timezone_is_rejected(client, alice):
    response = await client.patch(
        "/users/me/settings", json={"timezone": "Mars/Olympus"}, headers=alice
    )

    assert response.status_code == 422


@pytest.mark.parametrize("method", ["get", "patch"])
async def test_user_endpoints_require_authentication(client, method):
    url = "/users/me" if method == "get" else "/users/me/settings"

    response = await getattr(client, method)(url)

    assert response.status_code == 401
