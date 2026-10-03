"""Read postcard history through MCP using isolated on-disk journey data."""

from copy import deepcopy
import json

from fastmcp import Client
import pytest


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("NOWHERE_HOME", str(tmp_path))
    from nowhere import server

    monkeypatch.setattr(server.state_mod, "_SAVE_DIR", tmp_path)
    monkeypatch.setattr(server, "_state", server.state_mod.WorldState())
    return server


def card(card_id, replies=None):
    return {
        "id": card_id,
        "stamp": {"place": "设得兰群岛", "local_time": "2026-08-11 12:00"},
        "text": f"第 {card_id} 张旅途问候。",
        "replies": replies or [],
        "front_img": f"/static/postcards/card_{card_id}.png",
    }


async def read_postcards(world):
    async with Client(world.mcp) as client:
        result = await client.call_tool("postcards", {})
    return result.data


@pytest.mark.asyncio
async def test_saved_history_survives_empty_journey_and_includes_replies(world, tmp_path):
    cards = [card(i) for i in range(1, 26)]
    cards[0]["replies"] = ["第一张的回信。", {"content": "第二句回信。"}]
    for item in cards:
        world.placememory.save_postcard(item)
    archive = tmp_path / "postcards.json"
    before = archive.read_bytes()

    result = await read_postcards(world)

    assert result["data"]["postcards"] == list(reversed(cards))
    assert "保存了 25 张明信片" in result["text"]
    assert "明信片 #1，来自设得兰群岛" in result["text"]
    assert "回信：第一张的回信。" in result["text"]
    assert "回信：第二句回信。" in result["text"]
    assert archive.read_bytes() == before
    assert world._state.postcards == []


@pytest.mark.asyncio
async def test_reads_fresh_replies_and_respects_deleted_cards(world):
    original = card(1)
    world.placememory.save_postcard(original)
    world.placememory.save_postcard(card(2))
    world._state.postcards = [deepcopy(original)]
    assert (await read_postcards(world))["data"]["postcards"][1]["replies"] == []

    assert world.placememory.add_postcard_reply(1, "刚刚寄回的回信。")
    result = await read_postcards(world)
    assert result["data"]["postcards"][1]["replies"] == ["刚刚寄回的回信。"]
    assert "回信：刚刚寄回的回信。" in result["text"]
    assert world._state.postcards[0]["replies"] == []

    assert world.placememory.delete_postcard(1)
    assert [c["id"] for c in (await read_postcards(world))["data"]["postcards"]] == [2]


@pytest.mark.asyncio
async def test_empty_history_does_not_create_journey_files(world, tmp_path):
    result = await read_postcards(world)
    assert result["data"]["postcards"] == []
    assert "还没有保存的明信片" in result["text"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_migrates_legacy_saved_cards_without_current_journey(world, tmp_path):
    legacy_card = card(7, ["旧明信片的回信。"])
    saved_state = tmp_path / "state.json"
    saved_state.write_text(json.dumps({"postcards": [legacy_card]}), encoding="utf-8")
    before = saved_state.read_bytes()

    result = await read_postcards(world)

    assert result["data"]["postcards"] == [legacy_card]
    assert "回信：旧明信片的回信。" in result["text"]
    assert json.loads((tmp_path / "postcards.json").read_text(encoding="utf-8"))["items"] == [legacy_card]
    assert saved_state.read_bytes() == before
    assert world._state.postcards == []
