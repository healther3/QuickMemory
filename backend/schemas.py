"""阶段一建立的共享数据契约；后续 API 和前端沿用这些字段。"""

import math
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

Score = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False, strict=True)]
Text = Annotated[str, Field(min_length=1, strict=True)]
Provider = Literal["deepseek", "gemini", "openai", "kimi", "qwen", "custom"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SettingsData(StrictModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)
    provider: Provider = "deepseek"
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = Field(default="", repr=False)
    model: str = Field(default="deepseek-chat", min_length=1)
    judge_count: Literal[2, 3] = 3
    judge_temperature: float = Field(default=0.7, ge=0, le=2, allow_inf_nan=False)
    merge_temperature: float = Field(default=0.2, ge=0, le=2, allow_inf_nan=False)
    w_accuracy: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    w_completeness: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    pass_threshold: float = Field(default=60, ge=0, le=100, allow_inf_nan=False)
    json_mode: Literal["auto", "on", "off"] = "auto"
    request_timeout: float = Field(default=60, ge=1, le=600, allow_inf_nan=False)

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("接口地址必须是完整的 HTTP 或 HTTPS 地址")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("接口地址不能包含账号、密码、查询参数或片段")
        return value.rstrip("/")

    @model_validator(mode="after")
    def valid_weights(self):
        if not math.isclose(self.w_accuracy + self.w_completeness, 1, abs_tol=1e-9, rel_tol=0):
            raise ValueError("正确率权重与完整度权重之和必须为 1")
        # 消除容差内浮点尾差，防止满分加权后大于 100。
        self.w_completeness = 1 - self.w_accuracy
        return self

    def public_dict(self) -> dict:
        return {**self.model_dump(exclude={"api_key"}), "has_api_key": bool(self.api_key)}


class FeedbackSections(StrictModel):
    correct_parts: list[Text]
    wrong_parts: list[Text]
    uncertain_parts: list[Text]
    error_types: list[Text]

    @field_validator("error_types")
    @classmethod
    def allowed_labels(cls, values: list[str], info: ValidationInfo) -> list[str]:
        allowed = (info.context or {}).get("allowed_error_types")
        if allowed is not None and any(value not in allowed for value in values):
            raise ValueError("错误类型必须从当前允许列表中选择")
        return list(dict.fromkeys(values))


class JudgeFeedback(FeedbackSections):
    accuracy: Score
    completeness: Score
    model_knowledge_notes: list[Text]
    reasoning: Text


class MergeFeedback(FeedbackSections):
    model_knowledge_notes: list[Text]


class PrecheckFeedback(StrictModel):
    correct_parts: list[Text]
    wrong_parts: list[Text]
    uncertain_parts: list[Text]
    clarifying_questions: list[Text] = Field(max_length=3)
    suggested_rewrite: str | None


class ConnectionFeedback(StrictModel):
    ok: Literal[True]
    message: Text


class JudgeOutcome(StrictModel):
    judge_index: int = Field(ge=1, le=3)
    success: bool
    accuracy: Score | None = None
    completeness: Score | None = None
    raw_json: dict | None = None
    raw_text: str | None = None
    error: str | None = None


class GradingResult(StrictModel):
    status: Literal["pending", "graded", "failed"]
    accuracy: Score | None = None
    completeness: Score | None = None
    final_score: Score | None = None
    merged_feedback: FeedbackSections | None = None
    model_knowledge_notes: list[str] = Field(default_factory=list)
    judges: list[JudgeOutcome] = Field(default_factory=list)
    disagreement: bool = False
    merge_fallback: bool = False
    error: str | None = None
    prompt_version: str
    model_name: str

    @model_validator(mode="after")
    def scores_match_status(self):
        scores = (self.accuracy, self.completeness, self.final_score)
        if self.status == "graded" and (any(v is None for v in scores) or self.merged_feedback is None):
            raise ValueError("已评分结果必须包含有效分数与反馈")
        if self.status != "graded" and any(v is not None for v in scores):
            raise ValueError("未评分结果不得包含分数")
        return self
