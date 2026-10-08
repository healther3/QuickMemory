"""无流式输出、无遥测、无远程模型目录；只调用用户配置的 LLM 接口。"""

import asyncio
import os
from typing import Protocol

from backend.providers import litellm_model
from backend.schemas import SettingsData


class LLMError(Exception):
    """可直接向用户显示、不含服务商原始响应或密钥的错误。"""


class CompletionClient(Protocol):
    async def complete(self, messages: list[dict[str, str]], settings: SettingsData, temperature: float) -> str: ...


def load_litellm():
    # 必须在第一次 import 前设置；禁止启动时向 GitHub 下载模型价格表。
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["LITELLM_TELEMETRY"] = "False"
    os.environ["DO_NOT_TRACK"] = "1"
    import litellm

    litellm.telemetry = False
    litellm.set_verbose = False
    litellm.suppress_debug_info = True
    litellm.disable_token_counter = True
    litellm.disable_hf_tokenizer_download = True
    litellm.callbacks = []
    litellm.success_callback = []
    litellm.failure_callback = []
    return litellm


def _unsupported_json(exc: Exception) -> bool:
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return status in {400, 422} and any(x in text for x in ("response_format", "json_object")) and any(
        x in text for x in ("unsupported", "not support", "not allowed", "unknown", "unrecognized", "not available")
    )


def _safe_error(exc: Exception) -> LLMError:
    status = getattr(exc, "status_code", None)
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or "timeout" in type(exc).__name__.lower():
        return LLMError("模型请求超时，请检查网络或增加请求超时时间")
    if status in {401, 403}:
        return LLMError("模型鉴权失败，请检查 API 密钥和模型访问权限")
    if status == 429:
        return LLMError("模型请求受限或余额不足，请检查服务商配额后重试")
    if status in {400, 404, 422}:
        return LLMError("模型请求参数不受支持，请检查模型名称、接口地址及 JSON 模式")
    return LLMError("模型调用失败，请检查网络、接口地址及服务商状态后重试")


class LiteLLMClient:
    async def complete(self, messages: list[dict[str, str]], settings: SettingsData, temperature: float) -> str:
        if not settings.api_key:
            raise LLMError("尚未配置 API 密钥，请先在设置中填写或使用命令行安全输入")
        if not settings.model:
            raise LLMError("尚未填写模型名称")
        sdk = load_litellm()
        kwargs = dict(
            model=litellm_model(settings.model),
            api_base=settings.base_url,
            api_key=settings.api_key,
            messages=messages,
            temperature=temperature,
            stream=False,
            timeout=settings.request_timeout,
            num_retries=0,
            caching=False,
            mock_response=None,
        )
        if settings.json_mode != "off":
            kwargs["response_format"] = {"type": "json_object"}
        try:
            async with asyncio.timeout(settings.request_timeout + 1):
                try:
                    response = await sdk.acompletion(**kwargs)
                except Exception as exc:
                    if settings.json_mode != "auto" or not _unsupported_json(exc):
                        raise
                    # 服务商明确拒绝 JSON 模式时才降级；鉴权/限流等错误不触发重复请求。
                    kwargs.pop("response_format", None)
                    response = await sdk.acompletion(**kwargs)
                content = response.choices[0].message.content
                if not isinstance(content, str) or not content.strip():
                    raise LLMError("模型返回了空内容，请检查模型是否支持文本对话")
                return content
        except LLMError:
            raise
        except Exception as exc:
            raise _safe_error(exc) from None
