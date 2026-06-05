import pytest

@pytest.mark.asyncio
async def test_register(client):
    response = await client.post('/auth/register', json={
        'email': 'newuser@example.com',
        'password': 'password123'
    })

    assert response.status_code == 201
    data = response.json()
    assert data['email'] == 'newuser@example.com'
    assert data['is_active'] == True
    assert 'id' in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    await client.post('/auth/register', json={
        'email': 'newuser@example.com',
        'password': 'testpassword123'
    })
    response = await client.post('/auth/register', json={
        'email': 'newuser@example.com',
        'password': 'testpassword456'
    })
    assert response.status_code == 400



@pytest.mark.asyncio
async def test_login(client):
    await client.post('/auth/register', json={
        'email': 'newuser@example.com', 
        'password': 'testpassword123'
    })
    response = await client.post('/auth/login', json={
        'email': 'newuser@example.com',
        'password': 'testpassword123'
    })
    assert response.status_code == 200
    data = response.json()
    assert 'access_token' in data
    assert data['token_type'] == 'bearer'


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post('/auth/register', json={
        'email': 'newuser@example.com',
        'password': 'testpassword123'
    })
    response = await client.post('/auth/login', json={
        'email': 'newuser@example.com',
        'password': 'wrongpassword'
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client):
    await client.post('/auth/register', json={
        'email': 'newuser@example.com',
        'password': 'testpassword123'
    })
    login = await client.post('/auth/login', json={
        'email': 'newuser@example.com',
        'password': 'testpassword123'
    })
    token = login.json()['access_token']



    response = await client.get('/users/me', headers={
        'Authorization': f'Bearer {token}'
    })
    assert response.status_code == 200
    assert response.json()['email'] == 'newuser@example.com'