async def test_metrics_endpoint_counts_requests(client):
    await client.get("/users/me")  # 401, but it is still a request

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
    assert 'handler="/users/me"' in response.text


async def test_metrics_endpoint_is_hidden_from_the_api_docs(client):
    paths = (await client.get("/openapi.json")).json()["paths"]

    assert "/metrics" not in paths


async def test_health_checks_are_not_counted(client):
    await client.get("/health")

    assert 'handler="/health"' not in (await client.get("/metrics")).text
