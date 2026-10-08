"""用真实模型评分一个回答；默认不写入考试历史，不伪造示例分数。"""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from pydantic import Field, ValidationError
from sqlalchemy import select

from backend.cli.configure import add_model_arguments, apply_arguments
from backend.database import init_db, make_engine, make_session_factory
from backend.models import ErrorType, ExamAnswer, ExamSession, utc_now
from backend.repositories import get_settings, persist_grade
from backend.schemas import SettingsData, StrictModel
from backend.services.grading import GradingService


class SampleAnswer(StrictModel):
    term: str = Field(min_length=1)
    reference_definition: str = Field(min_length=1)
    user_answer: str
    time_spent_ms: int = Field(default=0, ge=0)


DEFAULT_SAMPLE = SampleAnswer(
    term="过拟合",
    reference_definition="模型过度拟合训练数据中的噪声或偶然特征，在训练集上表现好，但在未见数据上泛化表现差。",
    user_answer="模型在训练数据上效果很好，但是在新数据上表现差。",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="使用配置的真实 LLM 并行评分样例；默认只打印结果")
    add_model_arguments(parser)
    parser.add_argument("--db", help="本地 SQLite 路径")
    parser.add_argument("--sample", type=Path, help="UTF-8 JSON 文件：term、reference_definition、user_answer")
    parser.add_argument("--save-result", action="store_true", help="将这次真实评分及裁判明细保存到考试历史")
    args = parser.parse_args()
    engine = make_engine(args.db)
    try:
        sample = SampleAnswer.model_validate_json(args.sample.read_text(encoding="utf-8-sig")) if args.sample else DEFAULT_SAMPLE
        init_db(engine)
        factory = make_session_factory(engine)
        with factory() as session:
            config = apply_arguments(SettingsData.model_validate(get_settings(session)).model_dump(), args)
            labels = list(session.scalars(select(ErrorType.name).order_by(ErrorType.id)))
        if not config.api_key:
            print("未配置密钥。请使用 --prompt-key，或设置 QUICKMEMORY_API_KEY；也可先运行配置脚本。", file=sys.stderr)
            return 2
        print(f"正在使用 {config.model} 的 {config.judge_count} 位裁判评分……", file=sys.stderr)
        result = asyncio.run(GradingService().grade(
            term=sample.term, reference_definition=sample.reference_definition,
            user_answer=sample.user_answer, settings=config, error_types=labels,
        ))
        if args.save_result:
            with factory.begin() as session:
                exam = ExamSession(folder_name_snapshot="命令行评分样例",
                                   settings_snapshot=config.model_dump(exclude={"api_key"}), finished_at=utc_now())
                answer = ExamAnswer(session=exam, position=0, term_snapshot=sample.term,
                                    definition_snapshot=sample.reference_definition, user_answer=sample.user_answer,
                                    time_spent_ms=sample.time_spent_ms, submitted_at=utc_now())
                session.add(exam)
                session.flush()
                persist_grade(session, answer.id, result)
                print(f"已保存到考试历史，考试编号：{exam.id}", file=sys.stderr)
        print(result.model_dump_json(indent=2))
        return 0 if result.status == "graded" else 1
    except ValidationError as exc:
        errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False)]
        print("输入校验失败：" + "；".join(errors), file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print("无法读取样例，请检查文件路径、UTF-8 编码和 JSON 格式", file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
