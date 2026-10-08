"""可编辑的服务商建议值；评分逻辑不依赖任何具体模型版本。"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    name: str
    base_url: str
    suggested_model: str


# 所有预设使用服务商的 OpenAI 兼容接口，经 LiteLLM 调用。
PROVIDER_PRESETS = (
    ProviderPreset("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ProviderPreset("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    ProviderPreset("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ProviderPreset("kimi", "Kimi（Moonshot）", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ProviderPreset("qwen", "通义千问（DashScope）", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ProviderPreset("custom", "自定义 OpenAI 兼容接口", "http://localhost:8001/v1", ""),
)
PRESETS_BY_ID = {item.id: item for item in PROVIDER_PRESETS}


def list_provider_presets() -> list[dict]:
    return [asdict(item) for item in PROVIDER_PRESETS]


def litellm_model(model: str) -> str:
    # 保留服务商模型 ID 中的斜线（例如组织名/模型名）。
    return model if model.startswith("openai/") else f"openai/{model}"
