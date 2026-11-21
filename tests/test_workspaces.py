async def _personal_workspace(client, headers):
    response = await client.get("/workspaces", headers=headers)
    assert response.status_code == 200
    return response.json()[0]


async def _create_workspace(client, headers, name="Team"):
    response = await client.post("/workspaces", json={"name": name}, headers=headers)
    assert response.status_code == 201
    return response.json()


async def test_registration_creates_personal_workspace(client, api):
    headers = await api.headers("tenant-personal@example.com")

    response = await client.get("/workspaces", headers=headers)

    assert response.status_code == 200
    workspaces = response.json()
    assert len(workspaces) == 1
    assert workspaces[0]["is_personal"] is True
    assert workspaces[0]["role"] == "owner"
    assert workspaces[0]["plan"] == "free"


async def test_shared_workspace_resources_are_visible_to_members(client, api):
    owner = await api.headers("tenant-owner@example.com")
    member = await api.headers("tenant-member@example.com")
    workspace = await _create_workspace(client, owner)

    invite = await client.post(
        f"/workspaces/{workspace['id']}/members",
        json={"email": "tenant-member@example.com"},
        headers=owner,
    )
    assert invite.status_code == 201

    owner_headers = {**owner, "X-Workspace-Id": workspace["id"]}
    member_headers = {**member, "X-Workspace-Id": workspace["id"]}
    created = await client.post(
        "/knowledge-bases", json={"name": "Shared KB"}, headers=owner_headers
    )
    assert created.status_code == 201

    listed = await client.get("/knowledge-bases", headers=member_headers)

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [created.json()["id"]]


async def test_cross_workspace_access_returns_404(client, api):
    alice = await api.headers("tenant-alice@example.com")
    bob = await api.headers("tenant-bob@example.com")
    created = await client.post("/knowledge-bases", json={"name": "Private"}, headers=alice)
    assert created.status_code == 201

    response = await client.get(f"/knowledge-bases/{created.json()['id']}", headers=bob)

    assert response.status_code == 404


async def test_non_member_cannot_select_workspace(client, api):
    alice = await api.headers("tenant-owner2@example.com")
    bob = await api.headers("tenant-outsider@example.com")
    workspace = await _create_workspace(client, alice)

    response = await client.get(
        "/knowledge-bases", headers={**bob, "X-Workspace-Id": workspace["id"]}
    )

    assert response.status_code == 404


async def test_removed_member_loses_workspace_access(client, api):
    owner = await api.headers("tenant-owner3@example.com")
    member = await api.headers("tenant-member3@example.com")
    workspace = await _create_workspace(client, owner)
    member_id = (await client.get("/auth/me", headers=member)).json()["id"]
    await client.post(
        f"/workspaces/{workspace['id']}/members",
        json={"email": "tenant-member3@example.com"},
        headers=owner,
    )

    removed = await client.delete(
        f"/workspaces/{workspace['id']}/members/{member_id}", headers=owner
    )
    response = await client.get(
        "/knowledge-bases", headers={**member, "X-Workspace-Id": workspace["id"]}
    )

    assert removed.status_code == 204
    assert response.status_code == 404


async def test_api_key_is_bound_to_its_workspace(client, api):
    owner = await api.headers("tenant-key@example.com")
    workspace = await _create_workspace(client, owner)
    team_headers = {**owner, "X-Workspace-Id": workspace["id"]}
    created = await client.post("/api-keys", json={"name": "team key"}, headers=team_headers)
    assert created.status_code == 201
    key = created.json()["key"]

    listed = await client.get("/knowledge-bases", headers={"X-API-Key": key})
    personal = await _personal_workspace(client, owner)
    conflict = await client.get(
        "/knowledge-bases",
        headers={"X-API-Key": key, "X-Workspace-Id": personal["id"]},
    )

    assert listed.status_code == 200
    assert conflict.status_code == 404


async def test_usage_is_scoped_to_workspace(client, api):
    owner = await api.headers("tenant-usage@example.com")
    workspace = await _create_workspace(client, owner)
    team_headers = {**owner, "X-Workspace-Id": workspace["id"]}

    personal = await client.get("/usage/summary", headers=owner)
    team = await client.get("/usage/summary", headers=team_headers)

    assert personal.status_code == 200
    assert team.status_code == 200
    assert personal.json()["buckets"] == []
    assert team.json()["buckets"] == []
