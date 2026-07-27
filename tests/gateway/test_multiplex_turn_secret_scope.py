"""Regression: multiplex primary turns scope pre-turn hygiene credential reads."""
from contextlib import contextmanager
from pathlib import Path

import pytest

from gateway.config import GatewayConfig
from gateway.platforms.base import MessageEvent
from gateway.run import GatewayRunner
from gateway.config import Platform
from gateway.session import SessionSource


@pytest.mark.asyncio
async def test_primary_multiplex_turn_enters_profile_scope(monkeypatch):
    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(multiplex_profiles=True)
    source = SessionSource(
        platform=Platform.TELEGRAM,
        user_id="u",
        chat_id="c",
        chat_type="dm",
        profile="default",
    )
    event = MessageEvent(text="hello", message_id="m1", source=source)
    entered = []

    @contextmanager
    def fake_scope(home):
        entered.append(Path(home))
        yield

    async def fake_inner(_event, _source, _key, _generation):
        assert entered == [Path("/fake/default")]
        return "ok"

    monkeypatch.setattr("gateway.run._profile_runtime_scope", fake_scope)
    monkeypatch.setattr(
        runner, "_resolve_profile_home_for_source", lambda _source: Path("/fake/default")
    )
    monkeypatch.setattr(runner, "_handle_message_with_agent", fake_inner)

    result = await runner._handle_profile_scoped_message_with_agent(event, source, "key", 1)
    assert result == "ok"
    assert entered == [Path("/fake/default")]
