"""Bounded, durable-by-database background grading for the local application."""

import asyncio
import logging

from sqlalchemy import select

from backend.models import ErrorType, ExamAnswer
from backend.prompts import PROMPT_VERSION
from backend.repositories import get_settings, persist_grade
from backend.schemas import GradingResult, SettingsData

logger = logging.getLogger(__name__)


class GradingQueue:
    """At most ``workers`` answers (three judges each) use the network at once.

    A pending, submitted database answer is the durable queue entry. Cancellation
    leaves that entry pending so the next process start can safely recover it.
    All methods are used on the application's event loop.
    """

    def __init__(self, session_factory, grading_service, workers: int = 2):
        if workers < 1:
            raise ValueError("后台评分并发数必须大于零")
        self.session_factory = session_factory
        self.grading_service = grading_service
        self.workers = workers
        self._queue = asyncio.Queue()
        self._scheduled: set[int] = set()
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._worker()) for _ in range(self.workers)]
        with self.session_factory() as db:
            pending = list(db.scalars(select(ExamAnswer.id).where(
                ExamAnswer.status == "pending", ExamAnswer.submitted_at.is_not(None)
            ).order_by(ExamAnswer.id)))
        for answer_id in pending:
            self.enqueue(answer_id)

    def enqueue(self, answer_id: int):
        if answer_id not in self._scheduled:
            self._scheduled.add(answer_id)
            self._queue.put_nowait(answer_id)

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._scheduled.clear()
        # A queue can be restarted in tests without retaining duplicate entries.
        self._queue = asyncio.Queue()

    async def _worker(self):
        while True:
            answer_id = await self._queue.get()
            try:
                await self._grade(answer_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never log provider exceptions: they may contain credentials.
                logger.error("后台评分保存失败，作答编号 %s 将在下次启动时恢复", answer_id)
            finally:
                self._scheduled.discard(answer_id)
                self._queue.task_done()

    async def _grade(self, answer_id: int):
        model_name = ""
        failure = "后台评分失败，请检查设置后重新评分"
        try:
            with self.session_factory() as db:
                answer = db.get(ExamAnswer, answer_id)
                if answer is None or answer.status != "pending" or answer.submitted_at is None:
                    return
                snapshot = dict(answer.session.settings_snapshot)
                model_name = snapshot.get("model", "")
                current = get_settings(db)
                if (snapshot.get("provider") != current.provider or
                        snapshot.get("base_url", "").rstrip("/") != current.base_url.rstrip("/")):
                    failure = "当前提供商或接口地址与本场考试不一致，请恢复原提供商和接口地址并配置密钥后重新评分"
                    raise ValueError(failure)
                settings = SettingsData.model_validate({**snapshot, "api_key": current.api_key})
                vocabulary = {item.id: item.name for item in db.scalars(select(ErrorType).order_by(ErrorType.id))}
                payload = dict(term=answer.term_snapshot, reference_definition=answer.definition_snapshot,
                               user_answer=answer.user_answer, settings=settings,
                               error_types=list(vocabulary.values()))
            # No SQLAlchemy session or transaction survives this await.
            result = await self.grading_service.grade(**payload)
            result = GradingResult.model_validate(result)
            if result.status == "pending":
                raise ValueError("评分服务未返回最终结果")
            with self.session_factory() as db:
                answer = db.get(ExamAnswer, answer_id)
                if answer is None or answer.status != "pending":
                    return
                if result.merged_feedback is not None:
                    current_names = {item.id: item.name for item in db.scalars(select(ErrorType))}
                    selected = set(result.merged_feedback.error_types)
                    mapped = list(dict.fromkeys(current_names[identifier] for identifier, original in vocabulary.items()
                                                if original in selected and identifier in current_names))
                    result = result.model_copy(update={"merged_feedback":
                        result.merged_feedback.model_copy(update={"error_types": mapped})})
                persist_grade(db, answer_id, result)
                db.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            with self.session_factory() as db:
                answer = db.get(ExamAnswer, answer_id)
                if answer is not None and answer.status == "pending":
                    persist_grade(db, answer_id, GradingResult(status="failed", error=failure,
                                  prompt_version=PROMPT_VERSION, model_name=model_name))
                    db.commit()
