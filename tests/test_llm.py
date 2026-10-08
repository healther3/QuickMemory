"""LiteLLM 适配器单元测试：SDK 与传输层均使用模拟对象。"""

import asyncio
import builtins
import os
from types import SimpleNamespace

import pytest

from backend.schemas import SettingsData
from backend.services import llm


SECRET = "sk-not-a-real-key-DO-NOT-LEAK"
MESSAGES = [{"role": "system", "content": "只返回 JSON"}, {"role": "user", "content": "测试内容"}]


class UpstreamError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class FakeSDK:
    def __init__(self, *responses):
        self.responses = list(responses or ['{"ok": true}'])
        self.calls = []

    async def acompletion(self, **kwargs):
        self.calls.append(dict(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response))])


def settings(**overrides):
    return SettingsData(api_key=SECRET, **overrides)


def install_sdk(monkeypatch, *responses):
    sdk = FakeSDK(*responses)
    monkeypatch.setattr(llm, "load_litellm", lambda: sdk)
    return sdk


@pytest.mark.parametrize("mode", ["auto", "on", "off"])
async def test_configured_endpoint_and_model_are_forwarded_without_streaming_or_retries(monkeypatch, mode):
    sdk = install_sdk(monkeypatch)
    config = settings(provider="custom", base_url="http://127.0.0.1:8123/custom/v1/", model="organization/model-name", json_mode=mode, request_timeout=37)

    result = await llm.LiteLLMClient().complete(MESSAGES, config, 0.37)

    assert result == '{"ok": true}'
    assert len(sdk.calls) == 1
    call = sdk.calls[0]
    assert call["model"] == "openai/organization/model-name"
    assert call["api_base"] == "http://127.0.0.1:8123/custom/v1"
    assert call["api_key"] == SECRET
    assert call["messages"] == MESSAGES
    assert call["temperature"] == 0.37
    assert call["timeout"] == 37
    assert call["stream"] is False
    assert call["num_retries"] == 0
    assert call["caching"] is False
    assert call["mock_response"] is None
    if mode == "off":
        assert "response_format" not in call
    else:
        assert call["response_format"] == {"type": "json_object"}


async def test_openai_model_prefix_is_not_duplicated(monkeypatch):
    sdk = install_sdk(monkeypatch)
    await llm.LiteLLMClient().complete(MESSAGES, settings(model="openai/my-model"), 0.7)
    assert sdk.calls[0]["model"] == "openai/my-model"


@pytest.mark.parametrize("status,detail", [
    (400, "response_format is unsupported"),
    (422, "json_object is not allowed for this model"),
])
async def test_auto_mode_retries_only_explicit_unsupported_json_without_format(monkeypatch, status, detail):
    sdk = install_sdk(monkeypatch, UpstreamError(status, detail), '{"ok": true}')
    result = await llm.LiteLLMClient().complete(MESSAGES, settings(json_mode="auto"), 0.2)
    assert result == '{"ok": true}'
    assert len(sdk.calls) == 2
    assert sdk.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in sdk.calls[1]
    assert {key: value for key, value in sdk.calls[0].items() if key != "response_format"} == sdk.calls[1]


@pytest.mark.parametrize("mode,status,detail", [
    ("on", 400, "response_format unsupported"),
    ("off", 400, "response_format unsupported"),
    ("auto", 401, "response_format unsupported"),
    ("auto", 403, "json_object not allowed"),
    ("auto", 429, "response_format unsupported"),
    ("auto", 500, "response_format unsupported"),
    ("auto", 400, "temperature unsupported"),
    ("auto", 400, "invalid JSON syntax in response_format"),
    ("auto", 422, "invalid model name"),
])
async def test_auth_rate_limits_other_parameters_and_forced_modes_do_not_trigger_json_fallback(monkeypatch, mode, status, detail):
    sdk = install_sdk(monkeypatch, UpstreamError(status, detail + " " + SECRET))
    with pytest.raises(llm.LLMError) as error:
        await llm.LiteLLMClient().complete(MESSAGES, settings(json_mode=mode), 0.2)
    assert len(sdk.calls) == 1
    assert SECRET not in str(error.value)
    assert any("\u4e00" <= char <= "\u9fff" for char in str(error.value))


@pytest.mark.parametrize("exception,expected", [
    (TimeoutError(f"timeout {SECRET}"), "模型请求超时"),
    (UpstreamError(401, SECRET), "模型鉴权失败"),
    (UpstreamError(403, SECRET), "模型鉴权失败"),
    (UpstreamError(429, SECRET), "模型请求受限或余额不足"),
    (UpstreamError(404, SECRET), "模型请求参数不受支持"),
    (RuntimeError(SECRET), "模型调用失败"),
])
async def test_raw_sdk_errors_are_replaced_with_safe_chinese_messages(monkeypatch, exception, expected):
    install_sdk(monkeypatch, exception)
    with pytest.raises(llm.LLMError, match=expected) as error:
        await llm.LiteLLMClient().complete(MESSAGES, settings(), 0.2)
    assert SECRET not in str(error.value)
    assert error.value.__cause__ is None


async def test_second_auto_mode_failure_is_safe_and_never_attempts_a_third_call(monkeypatch):
    sdk = install_sdk(monkeypatch, UpstreamError(400, "response_format unsupported"), UpstreamError(401, SECRET))
    with pytest.raises(llm.LLMError, match="模型鉴权失败"):
        await llm.LiteLLMClient().complete(MESSAGES, settings(), 0.2)
    assert len(sdk.calls) == 2


async def test_outer_timeout_cancels_hung_sdk_and_uses_configured_budget(monkeypatch):
    captured = []
    cancelled = asyncio.Event()
    real_timeout = asyncio.timeout

    def short_timeout(delay):
        captured.append(delay)
        return real_timeout(0.01)

    async def hangs(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(llm, "load_litellm", lambda: SimpleNamespace(acompletion=hangs))
    monkeypatch.setattr(llm.asyncio, "timeout", short_timeout)
    with pytest.raises(llm.LLMError, match="模型请求超时"):
        await llm.LiteLLMClient().complete(MESSAGES, settings(request_timeout=15), 0.2)
    assert captured == [16]
    assert cancelled.is_set()


@pytest.mark.parametrize("content", [None, "", " \n\t", ["not a text response"]])
async def test_empty_or_nontext_content_is_reported_without_retry(monkeypatch, content):
    sdk = install_sdk(monkeypatch, content)
    with pytest.raises(llm.LLMError, match="模型返回了空内容"):
        await llm.LiteLLMClient().complete(MESSAGES, settings(), 0.2)
    assert len(sdk.calls) == 1


@pytest.mark.parametrize("config,expected", [
    (SettingsData(api_key=""), "尚未配置 API 密钥"),
    (SettingsData(api_key=SECRET).model_copy(update={"model": ""}), "尚未填写模型名称"),
])
async def test_missing_credentials_or_model_fail_before_loading_sdk(monkeypatch, config, expected):
    def unexpected_load():
        pytest.fail("配置无效时不得加载 SDK")
    monkeypatch.setattr(llm, "load_litellm", unexpected_load)
    with pytest.raises(llm.LLMError, match=expected):
        await llm.LiteLLMClient().complete(MESSAGES, config, 0.2)


def test_settings_key_is_masked_in_repr_and_public_dict():
    config = settings()
    assert SECRET not in repr(config)
    assert SECRET not in str(config)
    public = config.public_dict()
    assert "api_key" not in public
    assert public["has_api_key"] is True
    assert SECRET not in repr(public)
    assert SettingsData().public_dict()["has_api_key"] is False


def test_privacy_flags_are_set_before_litellm_import(monkeypatch):
    names = {"LITELLM_LOCAL_MODEL_COST_MAP": "True", "LITELLM_TELEMETRY": "False", "DO_NOT_TRACK": "1"}
    for name in names:
        monkeypatch.delenv(name, raising=False)
    sdk = SimpleNamespace(telemetry=True, set_verbose=True, suppress_debug_info=False,
                          disable_token_counter=False, disable_hf_tokenizer_download=False,
                          callbacks=["remote callback"], success_callback=["remote"], failure_callback=["remote"])
    original_import = builtins.__import__
    imports = []

    def intercepted_import(name, *args, **kwargs):
        if name == "litellm":
            imports.append(name)
            assert {key: os.environ.get(key) for key in names} == names
            return sdk
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", intercepted_import)
    assert llm.load_litellm() is sdk
    assert imports == ["litellm"]
    assert sdk.telemetry is False
    assert sdk.set_verbose is False
    assert sdk.suppress_debug_info is True
    assert sdk.disable_token_counter is True
    assert sdk.disable_hf_tokenizer_download is True
    assert sdk.callbacks == sdk.success_callback == sdk.failure_callback == []
