from types import SimpleNamespace

from routes import model_routes
from src import agent_loop, llm_core
from src.tool_schemas import FUNCTION_TOOL_SCHEMAS
from src.model_profiles import (
    GENERIC_TOOL_SCHEMA_PROFILE,
    ODYSSEUS_COMPACT_TOOL_SCHEMA_PROFILE,
    tool_schema_profile,
)


def test_model_tool_modes_filters_to_supported_values():
    ep = SimpleNamespace(
        model_tool_modes='{"small": "compact", "legacy": "none", "big": "full", "bad": "verbose"}'
    )

    assert model_routes._model_tool_modes(ep) == {
        "small": "compact",
        "legacy": "none",
        "big": "full",
    }


def test_agent_model_tool_modes_parser_matches_route_parser():
    raw = {"small": "compact", "legacy": "none", "big": "full", "bad": "verbose"}

    assert agent_loop._parse_model_tool_modes(raw) == {
        "small": "compact",
        "legacy": "none",
        "big": "full",
    }


def test_apply_compact_tool_surface_strips_schema_descriptions():
    schema = {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from disk",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
            },
        },
    }

    compact = agent_loop._apply_tool_surface_to_schemas([schema], "compact")

    assert compact[0]["function"]["name"] == "read_file"
    assert "description" not in compact[0]["function"]
    assert "description" not in compact[0]["function"]["parameters"]["properties"]["path"]


def test_apply_none_tool_surface_removes_schemas():
    assert agent_loop._apply_tool_surface_to_schemas([{"type": "function"}], "none") == []


def test_qwen35_policy_route_honors_explicit_thinking_control(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_QWEN_ROUTE_THINKING", "off")

    assert agent_loop._thinking_mode_for_route(
        model="qwen35-9b-policy-run",
        tool_surface="",
        domains={"files"},
    ) == "off"
    assert agent_loop._thinking_mode_for_route(
        model="llama-3.1-8b",
        tool_surface="",
        domains={"files"},
    ) is None


def test_preheretic_tools_model_forces_thinking_off():
    assert agent_loop._thinking_mode_for_route(
        model="odysseus-qwen3.5-tools-pre-heretic",
        tool_surface="compact",
        domains={"web"},
    ) == "off"


def test_ajax_c375_defaults_to_compact_and_forces_thinking_off(monkeypatch):
    class BrokenSession:
        def __init__(self):
            raise RuntimeError("endpoint metadata unavailable")

    import core.database

    monkeypatch.setattr(core.database, "SessionLocal", BrokenSession)
    assert agent_loop._configured_model_tool_surface(
        "http://100.67.207.85:19187/v1", "ajax_c375"
    ) == "compact"
    assert agent_loop._thinking_mode_for_route(
        model="ajax_c375",
        tool_surface="compact",
        domains=set(),
    ) == "off"

    payload = {}
    monkeypatch.setattr(llm_core, "is_local_endpoint", lambda _url: True)
    llm_core._apply_local_qwen_thinking_mode(
        payload,
        "http://ajax.invalid/v1",
        "ajax_c375",
        "off",
    )
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_ollama_openai_compat_thinking_off_uses_reasoning_effort_for_any_model():
    url = "http://127.0.0.1:11434/v1/chat/completions"
    # bonsai-2 is not in _THINKING_MODEL_PATTERNS; Ollama still needs the switch.
    payload = {}
    llm_core._apply_local_qwen_thinking_mode(payload, url, "bonsai-2:27b", "off")
    assert payload == {"reasoning_effort": "none"}

    payload = {}
    llm_core._apply_local_qwen_thinking_mode(payload, url, "bonsai-2:27b", "on")
    assert payload == {}


def test_ollama_reasoning_levels_follow_thinking_capability(monkeypatch):
    from src.chatgpt_subscription import validate_reasoning_effort

    calls = []

    class FakeResponse:
        def __init__(self, caps):
            self._caps = caps

        def raise_for_status(self):
            pass

        def json(self):
            return {"capabilities": self._caps}

    def fake_post(url, json, timeout):
        calls.append((url, json["model"]))
        if json["model"] == "down:1b":
            raise OSError("ollama restarting")
        return FakeResponse(["completion", "thinking"] if json["model"] == "think:9b" else ["completion"])

    monkeypatch.setattr(llm_core, "_ollama_thinking_models", {})
    monkeypatch.setattr(llm_core.httpx, "post", fake_post)
    url = "http://127.0.0.1:11434/v1/chat/completions"

    assert llm_core.ollama_reasoning_metadata(url, "think:9b") == llm_core.OLLAMA_REASONING_METADATA
    assert llm_core.ollama_reasoning_metadata(url, "think:9b") == llm_core.OLLAMA_REASONING_METADATA
    assert calls == [("http://127.0.0.1:11434/api/show", "think:9b")]  # cached after first probe
    assert llm_core.ollama_reasoning_metadata(url, "plain:3b") is None
    assert llm_core.ollama_reasoning_metadata(url, "down:1b") is None
    assert "down:1b" not in llm_core._ollama_thinking_models  # failures are retried later
    assert llm_core.ollama_reasoning_metadata("https://api.openai.com/v1", "think:9b") is None

    assert validate_reasoning_effort("think:9b", "high") == "high"
    assert validate_reasoning_effort("think:9b", "ultra") is None
    assert validate_reasoning_effort("plain:3b", "high") is None


def test_named_schema_profile_aliases_are_accepted_by_settings_api():
    assert model_routes._normalize_model_tool_mode("regular") == "full"
    assert model_routes._normalize_model_tool_mode("odysseus_compact") == "compact"


def test_odysseus_ajax_names_force_native_tool_transport():
    assert agent_loop._agent_route_tool_mode(
        "http://model.invalid/v1", "Odysseus-experiment"
    ) == (True, False, False)
    assert agent_loop._agent_route_tool_mode(
        "http://model.invalid/v1", "provider/Ajax_trial_99"
    ) == (True, False, False)


def test_builtin_function_schemas_are_accepted_by_openai_top_level_contract():
    forbidden = {"oneOf", "anyOf", "allOf", "enum", "const", "not"}
    for schema in FUNCTION_TOOL_SCHEMAS:
        parameters = schema.get("function", {}).get("parameters", {})
        assert parameters.get("type") == "object"
        assert forbidden.isdisjoint(parameters)


def test_models_select_one_of_two_tool_schema_profiles():
    assert tool_schema_profile("gpt-5.5") == GENERIC_TOOL_SCHEMA_PROFILE
    assert tool_schema_profile("claude-sonnet-5") == GENERIC_TOOL_SCHEMA_PROFILE
    assert (
        tool_schema_profile("lab/Odysseus-trial55")
        == ODYSSEUS_COMPACT_TOOL_SCHEMA_PROFILE
    )
    assert (
        tool_schema_profile("provider/Ajax_c375")
        == ODYSSEUS_COMPACT_TOOL_SCHEMA_PROFILE
    )
