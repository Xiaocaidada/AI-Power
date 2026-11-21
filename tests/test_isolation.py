async def test_user_sees_only_own_knowledge_bases(client, api):
    alice = await api.headers("alice@example.com")
    bob = await api.headers("bob@example.com")
    await client.post("/knowledge-bases", json={"name": "Alice KB"}, headers=alice)
    await client.post("/knowledge-bases", json={"name": "Bob KB"}, headers=bob)

    alice_list = await client.get("/knowledge-bases", headers=alice)
    bob_list = await client.get("/knowledge-bases", headers=bob)

    assert [kb["name"] for kb in alice_list.json()] == ["Alice KB"]
    assert [kb["name"] for kb in bob_list.json()] == ["Bob KB"]


async def test_get_other_users_knowledge_base_returns_404(client, api):
    alice = await api.headers("alice2@example.com")
    bob = await api.headers("bob2@example.com")
    created = await client.post("/knowledge-bases", json={"name": "Private"}, headers=alice)
    kb_id = created.json()["id"]

    response = await client.get(f"/knowledge-bases/{kb_id}", headers=bob)

    assert response.status_code == 404


async def test_delete_other_users_knowledge_base_returns_404_and_keeps_it(client, api):
    alice = await api.headers("alice3@example.com")
    bob = await api.headers("bob3@example.com")
    created = await client.post("/knowledge-bases", json={"name": "Keep me"}, headers=alice)
    kb_id = created.json()["id"]

    response = await client.delete(f"/knowledge-bases/{kb_id}", headers=bob)
    still_there = await client.get(f"/knowledge-bases/{kb_id}", headers=alice)

    assert response.status_code == 404
    assert still_there.status_code == 200


async def test_knowledge_base_endpoints_require_auth(client):
    response = await client.get("/knowledge-bases")

    assert response.status_code == 401


async def test_knowledge_base_name_must_not_be_blank(client, api):
    headers = await api.headers("blank@example.com")

    response = await client.post("/knowledge-bases", json={"name": "   "}, headers=headers)

    assert response.status_code == 422


async def test_owner_can_delete_own_knowledge_base(client, api):
    headers = await api.headers("owner@example.com")
    created = await client.post("/knowledge-bases", json={"name": "Temp"}, headers=headers)
    kb_id = created.json()["id"]

    deleted = await client.delete(f"/knowledge-bases/{kb_id}", headers=headers)
    fetched = await client.get(f"/knowledge-bases/{kb_id}", headers=headers)

    assert deleted.status_code == 204
    assert fetched.status_code == 404
