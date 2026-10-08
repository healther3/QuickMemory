"""独立裁判并发评分；程序聚合分数，模型只合并文字。"""

import asyncio
import json
import re
from dataclasses import dataclass
from statistics import mean
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from backend import prompts
from backend.schemas import (
    ConnectionFeedback, FeedbackSections, GradingResult, JudgeFeedback,
    JudgeOutcome, MergeFeedback, PrecheckFeedback, SettingsData,
)
from backend.services.llm import CompletionClient, LLMError, LiteLLMClient

T = TypeVar("T", bound=BaseModel)


@dataclass
class JSONCallError(Exception):
    message: str
    raw_text: str | None = None
    raw_json: dict | None = None


def _parse_json(text: str):
    # 兼容仅包裹 JSON 的代码围栏，不从混杂说明中猜测/截取对象。
    value = text.strip().lstrip("\ufeff")
    match = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", value, flags=re.IGNORECASE)
    if match:
        value = match.group(1)
    def reject_constant(value):
        raise ValueError("JSON 不允许非有限数值")
    return json.loads(value, parse_constant=reject_constant)


class GradingService:
    def __init__(self, client: CompletionClient | None = None):
        self.client = client or LiteLLMClient()

    async def _json_call(self, schema: type[T], system: str, payload: dict, settings: SettingsData,
                         temperature: float, allowed: list[str] | None = None) -> tuple[T, str, dict]:
        messages = prompts.build_messages(system, payload, schema.model_json_schema())
        raw_text = None
        raw_json = None
        for attempt in range(2):
            try:
                raw_text = await self.client.complete(messages, settings, temperature)
            except LLMError as exc:
                raise JSONCallError(str(exc), raw_text, raw_json) from None
            except Exception:
                raise JSONCallError("模型调用失败，请检查设置后重试", raw_text, raw_json) from None
            try:
                raw_json = None
                decoded = _parse_json(raw_text)
                json.dumps(decoded, allow_nan=False)
                raw_json = decoded if isinstance(decoded, dict) else None
                validated = schema.model_validate(decoded, context={"allowed_error_types": allowed})
                return validated, raw_text, raw_json
            except (ValueError, TypeError, ValidationError):
                if attempt == 0:
                    messages = [*messages, {"role": "user", "content": prompts.JSON_RETRY}]
        raise JSONCallError("模型输出连续两次未通过 JSON 校验，该次结果未计入评分", raw_text, raw_json)

    async def _judge(self, index: int, payload: dict, settings: SettingsData, allowed: list[str]) -> JudgeOutcome:
        try:
            feedback, text, raw = await self._json_call(
                JudgeFeedback, prompts.JUDGE_SYSTEM, {**payload, "judge_index": index},
                settings, settings.judge_temperature, allowed,
            )
            return JudgeOutcome(judge_index=index, success=True, accuracy=feedback.accuracy,
                                completeness=feedback.completeness, raw_json=raw, raw_text=text)
        except JSONCallError as exc:
            return JudgeOutcome(judge_index=index, success=False, error=exc.message,
                                raw_json=exc.raw_json, raw_text=exc.raw_text)

    async def grade(self, *, term: str, reference_definition: str, user_answer: str,
                    settings: SettingsData, error_types: list[str]) -> GradingResult:
        allowed = list(dict.fromkeys(error_types))
        payload = {"term": term, "reference_definition": reference_definition,
                   "user_answer": user_answer, "allowed_error_types": allowed}
        # 不共享数据库 Session；所有网络操作独立于数据库事务。
        judges = await asyncio.gather(*(
            self._judge(index, payload, settings, allowed) for index in range(1, settings.judge_count + 1)
        ))
        valid = [j for j in judges if j.success]
        metadata = dict(judges=judges, prompt_version=prompts.PROMPT_VERSION, model_name=settings.model)
        if not valid:
            return GradingResult(status="failed", error="所有裁判均失败，本题未评分，可修正设置后重新评分", **metadata)

        feedbacks = [JudgeFeedback.model_validate(j.raw_json, context={"allowed_error_types": allowed}) for j in valid]
        accuracy = mean(f.accuracy for f in feedbacks)
        completeness = mean(f.completeness for f in feedbacks)
        # 仅消除合法加权运算的浮点越界（如 100.00000000000001），不舍入正常分数。
        score = min(100.0, max(0.0, settings.w_accuracy * accuracy + settings.w_completeness * completeness))
        judge_scores = [settings.w_accuracy * f.accuracy + settings.w_completeness * f.completeness for f in feedbacks]
        disagreement = any(max(values) - min(values) > 20 for values in (
            [f.accuracy for f in feedbacks], [f.completeness for f in feedbacks], judge_scores,
        ))
        merge_allowed = list(dict.fromkeys(label for f in feedbacks for label in f.error_types))
        fallback = False
        try:
            merged, _, _ = await self._json_call(
                MergeFeedback, prompts.MERGE_SYSTEM,
                {**payload, "allowed_error_types": merge_allowed,
                 "judges": [f.model_dump(exclude={"accuracy", "completeness"}) for f in feedbacks]},
                settings, settings.merge_temperature, merge_allowed,
            )
            sections = FeedbackSections.model_validate(merged.model_dump(exclude={"model_knowledge_notes"}))
            notes = list(dict.fromkeys(merged.model_knowledge_notes))
        except JSONCallError:
            fallback = True
            first = feedbacks[0]
            sections = FeedbackSections.model_validate(first.model_dump(include={
                "correct_parts", "wrong_parts", "uncertain_parts", "error_types",
            }))
            notes = list(dict.fromkeys(note for f in feedbacks for note in f.model_knowledge_notes))

        return GradingResult(status="graded", accuracy=accuracy, completeness=completeness,
                             final_score=score, merged_feedback=sections, model_knowledge_notes=notes,
                             disagreement=disagreement, merge_fallback=fallback, **metadata)

    async def precheck(self, *, term: str, definition: str, reference_note: str = "",
                       settings: SettingsData) -> PrecheckFeedback:
        # 刻意不依赖数据库：核对结果仅存在于当前请求。
        try:
            result, _, _ = await self._json_call(PrecheckFeedback, prompts.PRECHECK_SYSTEM,
                {"term": term, "definition": definition, "reference_note": reference_note}, settings, 0.2)
            return result
        except JSONCallError as exc:
            raise LLMError(exc.message) from None

    async def test_connection(self, settings: SettingsData) -> ConnectionFeedback:
        try:
            result, _, _ = await self._json_call(ConnectionFeedback, prompts.CONNECTION_SYSTEM, {}, settings, 0.2)
            return result
        except JSONCallError as exc:
            raise LLMError(exc.message) from None
