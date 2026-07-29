"""Regression tests for Telegram persistent router menu."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml


def _ensure_telegram_mock():
    if "telegram" in sys.modules and hasattr(sys.modules["telegram"], "__file__"):
        return
    mod = MagicMock()
    mod.ext.ContextTypes.DEFAULT_TYPE = type(None)
    mod.constants.ParseMode.MARKDOWN = "Markdown"
    mod.constants.ParseMode.MARKDOWN_V2 = "MarkdownV2"
    mod.constants.ParseMode.HTML = "HTML"
    mod.constants.ChatType.PRIVATE = "private"
    mod.constants.ChatType.GROUP = "group"
    mod.constants.ChatType.SUPERGROUP = "supergroup"
    mod.constants.ChatType.CHANNEL = "channel"
    mod.error.NetworkError = type("NetworkError", (OSError,), {})
    mod.error.TimedOut = type("TimedOut", (OSError,), {})
    mod.error.BadRequest = type("BadRequest", (Exception,), {})
    for name in ("telegram", "telegram.ext", "telegram.constants", "telegram.request"):
        sys.modules.setdefault(name, mod)
    sys.modules.setdefault("telegram.error", mod.error)


_ensure_telegram_mock()

from gateway.config import PlatformConfig
from plugins.platforms.telegram import adapter as telegram_adapter
from plugins.platforms.telegram.adapter import TelegramAdapter


def _make_adapter(tmp_path, monkeypatch):
    adapter = TelegramAdapter(PlatformConfig(enabled=True, token="test-token"))
    adapter._bot = AsyncMock()
    adapter._app = MagicMock()
    adapter._ROUTER_CONFIGS = {
        "omniroute": ("OmniRoute", str(tmp_path / "configominiroute.yaml")),
        "9router": ("9router", str(tmp_path / "config9router.yaml")),
        "freellmapi": ("FreeLLMAPI", str(tmp_path / "configfreellmapi.yaml")),
    }
    monkeypatch.setenv("HOME", str(tmp_path))
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    for key, (_label, path) in adapter._ROUTER_CONFIGS.items():
        src = tmp_path / path.split("/")[-1]
        src.write_text(
            yaml.safe_dump({"model": {"provider": key, "default": f"{key}-model"}}),
            encoding="utf-8",
        )
    return adapter


@pytest.mark.asyncio
async def test_main_menu_uses_switch_mode_and_model_buttons(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path, monkeypatch)
    (tmp_path / ".hermes" / "config.yaml").write_text(
        yaml.safe_dump({"model": {"provider": "omniroute", "default": "auto/codex"}}),
        encoding="utf-8",
    )
    msg = SimpleNamespace(
        reply_text=AsyncMock(),
        from_user=SimpleNamespace(id=1, first_name="ViPi"),
        chat=SimpleNamespace(id=123, type="private"),
    )
    captured_keyboard = {}

    def fake_reply_keyboard_markup(*args, **kwargs):
        captured_keyboard["args"] = args
        captured_keyboard["kwargs"] = kwargs
        return SimpleNamespace(kind="reply-keyboard", args=args, kwargs=kwargs)

    monkeypatch.setattr(adapter, "_is_user_authorized_from_message", lambda _msg: True)
    monkeypatch.setattr(telegram_adapter, "ReplyKeyboardMarkup", fake_reply_keyboard_markup)

    await adapter._send_main_menu(SimpleNamespace(effective_message=msg), None)

    args = msg.reply_text.await_args.args
    assert "Router hiện tại" in args[0]
    assert captured_keyboard["args"][0] == [["Switch mode", "Model"]]


@pytest.mark.asyncio
async def test_model_reply_keyboard_button_dispatches_model_picker(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path, monkeypatch)
    msg = SimpleNamespace(
        text="Model",
        chat=SimpleNamespace(id=123, type="private"),
        from_user=SimpleNamespace(id=1, first_name="ViPi"),
    )
    update = SimpleNamespace(message=msg, update_id=7)
    event = SimpleNamespace(text="")
    adapter._build_message_event = MagicMock(return_value=event)
    adapter.handle_message = AsyncMock()
    adapter._ensure_forum_commands = AsyncMock()
    monkeypatch.setattr(adapter, "_is_user_authorized_from_message", lambda _msg: True)
    monkeypatch.setattr(adapter, "_should_process_message", lambda *_args, **_kwargs: True)

    await adapter._handle_text_message(update, None)

    assert event.text == "/model"
    adapter.handle_message.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_group_live_search_query_bypasses_mention_gate_only_for_initiator(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path, monkeypatch)
    msg = SimpleNamespace(
        text="gpt-5",
        chat=SimpleNamespace(id=123, type="group"),
        from_user=SimpleNamespace(id=1, first_name="ViPi"),
    )
    update = SimpleNamespace(message=msg, update_id=8)
    adapter._model_picker_state["123"] = {"mode": "search", "search_user_id": "1"}
    adapter._search_model_picker = AsyncMock()
    monkeypatch.setattr(adapter, "_is_user_authorized_from_message", lambda _msg: True)
    monkeypatch.setattr(adapter, "_should_process_message", lambda *_args, **_kwargs: False)

    await adapter._handle_text_message(update, None)

    adapter._search_model_picker.assert_awaited_once_with(update, "123", "gpt-5")


def test_gateway_model_picker_loads_full_catalog_for_live_search():
    """The gateway passes no initial model cap: pagination protects the UI,
    while live search needs the complete callable catalog."""
    source = (Path(__file__).parents[2] / "gateway" / "slash_commands.py").read_text(encoding="utf-8")
    assert "max_models=None" in source


@pytest.mark.asyncio
async def test_router_callback_copies_source_to_config_yaml_without_deleting_source(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path, monkeypatch)
    dest = tmp_path / ".hermes" / "config.yaml"
    dest.write_text(
        yaml.safe_dump({"model": {"provider": "old", "default": "old-model"}}),
        encoding="utf-8",
    )
    query = SimpleNamespace(
        from_user=SimpleNamespace(id=1, first_name="ViPi"),
        message=SimpleNamespace(chat_id=123, chat=SimpleNamespace(type="private"), message_thread_id=None),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    monkeypatch.setattr(adapter, "_is_callback_user_authorized", lambda *a, **k: True)

    await adapter._handle_router_callback(query, "rt:9router")

    cfg = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert cfg["model"]["provider"] == "9router"
    assert (tmp_path / "config9router.yaml").exists()
    assert "Đã chuyển router sang" in query.edit_message_text.await_args.kwargs["text"]
