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
        "omniroute": ("OmniRoute", "configomniroute.yaml"),
        "9router": ("9router", "config9router.yaml"),
        "freellmapi": ("FreeLLMAPI", "configfreellmapi.yaml"),
    }
    monkeypatch.setenv("HOME", str(tmp_path))
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    adapter.config.extra["router_config_dir"] = str(hermes_home)
    for key, (_label, filename) in adapter._ROUTER_CONFIGS.items():
        src = hermes_home / filename
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
    assert captured_keyboard["args"][0] == [["Switch mode", "Provider", "Model"]]


@pytest.mark.asyncio
async def test_menu_reply_keyboard_button_opens_integrated_menu(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path, monkeypatch)
    msg = SimpleNamespace(
        text="Menu",
        chat=SimpleNamespace(id=123, type="private"),
        from_user=SimpleNamespace(id=1, first_name="ViPi"),
    )
    update = SimpleNamespace(message=msg, update_id=9)
    adapter._send_integrated_menu = AsyncMock(return_value=True)
    adapter._ensure_forum_commands = AsyncMock()
    monkeypatch.setattr(adapter, "_is_user_authorized_from_message", lambda _msg: True)
    monkeypatch.setattr(adapter, "_should_process_message", lambda *_args, **_kwargs: True)

    await adapter._handle_text_message(update, None)

    adapter._send_integrated_menu.assert_awaited_once_with(msg)


@pytest.mark.asyncio
async def test_router_callback_uses_profile_router_directory(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path, monkeypatch)
    profile_home = tmp_path / "profile-sula"
    profile_home.mkdir()
    adapter.config.extra["router_config_dir"] = str(profile_home)
    for key, (_label, filename) in adapter._ROUTER_CONFIGS.items():
        (profile_home / filename).write_text(
            yaml.safe_dump({"model": {"provider": key, "default": f"{key}-model"}}),
            encoding="utf-8",
        )
    (profile_home / "config.yaml").write_text(
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

    cfg = yaml.safe_load((profile_home / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["model"]["provider"] == "9router"


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
async def test_provider_reply_keyboard_button_opens_omniroute_picker(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path, monkeypatch)
    msg = SimpleNamespace(
        text="Provider",
        chat=SimpleNamespace(id=123, type="private"),
        from_user=SimpleNamespace(id=1, first_name="ViPi"),
    )
    update = SimpleNamespace(message=msg, update_id=8)
    adapter._send_omniroute_provider_picker = AsyncMock()
    adapter._ensure_forum_commands = AsyncMock()
    monkeypatch.setattr(adapter, "_is_user_authorized_from_message", lambda _msg: True)
    monkeypatch.setattr(adapter, "_should_process_message", lambda *_args, **_kwargs: True)

    await adapter._handle_text_message(update, None)

    adapter._send_omniroute_provider_picker.assert_awaited_once_with(msg)


@pytest.mark.asyncio
async def test_provider_command_refreshes_persistent_keyboard_before_picker(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path, monkeypatch)
    msg = SimpleNamespace(
        chat=SimpleNamespace(id=123, type="private"),
        from_user=SimpleNamespace(id=1, first_name="ViPi"),
    )
    update = SimpleNamespace(effective_message=msg, message=msg, update_id=10)
    adapter._send_main_menu = AsyncMock()
    adapter._send_omniroute_provider_picker = AsyncMock()
    monkeypatch.setattr(adapter, "_effective_update_message", lambda _update: msg)
    monkeypatch.setattr(adapter, "_is_user_authorized_from_message", lambda _msg: True)

    await adapter._handle_provider_command(update, None)

    adapter._send_main_menu.assert_awaited_once_with(update, None)
    adapter._send_omniroute_provider_picker.assert_awaited_once_with(msg)


def test_omniroute_provider_catalog_groups_fixed_models_and_excludes_auto(tmp_path, monkeypatch):
    adapter = _make_adapter(tmp_path, monkeypatch)
    payload = b'{"data":[{"id":"codex/gpt-5.5"},{"id":"codex/gpt-5.4"},{"id":"openai/gpt-4o"},{"id":"auto/bestfree"}]}'

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return payload

    monkeypatch.setattr(adapter, "_read_omniroute_client_config", lambda: ("http://127.0.0.1:20129/v1/models", "secret-not-logged"))
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())

    assert adapter._fetch_omniroute_provider_catalog() == [
        {"provider": "codex", "models": ["codex/gpt-5.5", "codex/gpt-5.4"]},
        {"provider": "openai", "models": ["openai/gpt-4o"]},
    ]


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
    source = (Path(__file__).parents[2] / "gateway" / "slash_commands_model.py").read_text(encoding="utf-8")
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
    assert (tmp_path / ".hermes" / "config9router.yaml").exists()
    assert "Đã chuyển router sang" in query.edit_message_text.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_omniroute_router_uses_configomniroute_file_name(tmp_path, monkeypatch):
    """OmniRoute switch mode must copy configomniroute.yaml (renamed standard), not old names."""
    adapter = _make_adapter(tmp_path, monkeypatch)
    hermes_home = tmp_path / ".hermes"
    stale = hermes_home / "configomnirote.yaml"
    correct = hermes_home / "configomniroute.yaml"
    stale.write_text(
        yaml.safe_dump({"model": {"provider": "wrong-omni", "default": "wrong-model"}}),
        encoding="utf-8",
    )
    correct.write_text(
        yaml.safe_dump({"model": {"provider": "omniroute", "default": "right-model"}}),
        encoding="utf-8",
    )
    dest = hermes_home / "config.yaml"
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

    await adapter._handle_router_callback(query, "rt:omniroute")

    cfg = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert cfg["model"]["provider"] == "omniroute"
    assert cfg["model"]["default"] == "right-model"
    assert "configomniroute.yaml" in query.edit_message_text.await_args.kwargs["text"]


def test_router_client_config_follows_active_router(tmp_path, monkeypatch):
    """Provider picker reads the active router's own provider entry from config.yaml."""
    adapter = _make_adapter(tmp_path, monkeypatch)
    hermes_home = tmp_path / ".hermes"
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {"provider": "9router", "default": "smart-route"},
                "providers": {
                    "omniroute": {"base_url": "http://localhost:20129/v1", "api_key": "omni-key"},
                    "9router": {"base_url": "http://localhost:20128/v1", "api_key": "nr-key"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("NR_KEY", raising=False)

    url, key = adapter._read_router_client_config("9router")
    assert url == "http://localhost:20128/v1/models"
    assert key == "nr-key"

    url, key = adapter._read_router_client_config("omniroute")
    assert url == "http://localhost:20129/v1/models"
    assert key == "omni-key"


def test_provider_catalog_groups_prefixed_and_flat_models(tmp_path, monkeypatch):
    """Prefixed ids group by provider; bare ids land in the all-models entry."""
    adapter = _make_adapter(tmp_path, monkeypatch)
    payload = (
        b'{"data":[{"id":"b.ai/glm-5.3-flash","owned_by":"b.ai"},'
        b'{"id":"gh/gpt-4.1","owned_by":"gh"},{"id":"smart-route","owned_by":"combo"}]}'
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return payload

    monkeypatch.setattr(
        adapter,
        "_read_router_client_config",
        lambda router_key: ("http://127.0.0.1:20128/v1/models", "secret-not-logged"),
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())

    entries = adapter._fetch_omniroute_provider_catalog("9router")
    assert entries == [
        {"provider": "all-models", "models": ["smart-route"]},
        {"provider": "b.ai", "models": ["b.ai/glm-5.3-flash"]},
        {"provider": "gh", "models": ["gh/gpt-4.1"]},
    ]


def test_flat_catalog_groups_single_all_models_entry(tmp_path, monkeypatch):
    """FreeLLMAPI-style flat catalogs collapse into one all-models entry."""
    adapter = _make_adapter(tmp_path, monkeypatch)
    payload = b'{"data":[{"id":"auto"},{"id":"fusion"},{"id":"qwen3.6-27b"}]}'

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return payload

    monkeypatch.setattr(
        adapter,
        "_read_router_client_config",
        lambda router_key: ("http://127.0.0.1:3001/v1/models", "secret-not-logged"),
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())

    entries = adapter._fetch_omniroute_provider_catalog("freellmapi")
    assert entries == [
        {"provider": "all-models", "models": ["auto", "fusion", "qwen3.6-27b"]},
    ]
