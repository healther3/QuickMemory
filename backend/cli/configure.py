"""python -m backend.cli.configure：配置本地模型，不输出密钥。"""

import argparse
from getpass import getpass
import json
import os
import sys

from pydantic import ValidationError

from backend.database import init_db, make_engine, make_session_factory
from backend.providers import PRESETS_BY_ID, list_provider_presets
from backend.repositories import get_settings, save_settings
from backend.schemas import SettingsData


def add_model_arguments(parser: argparse.ArgumentParser):
    parser.add_argument("--provider", choices=list(PRESETS_BY_ID), help="选择服务商并填入建议地址、模型")
    parser.add_argument("--base-url", help="自定义接口地址")
    parser.add_argument("--model", help="模型名称，可覆盖建议值")
    parser.add_argument("--judge-count", type=int, choices=[2, 3], help="并行裁判数量")
    parser.add_argument("--json-mode", choices=["auto", "on", "off"], help="JSON 输出模式")
    parser.add_argument("--timeout", type=float, help="单次模型调用超时秒数（1–600）")
    parser.add_argument("--prompt-key", action="store_true", help="安全输入 API 密钥（不回显）")


def apply_arguments(data: dict, args: argparse.Namespace) -> SettingsData:
    data = dict(data)
    if args.provider:
        preset = PRESETS_BY_ID[args.provider]
        # 切换服务商时不把旧服务商密钥发送到新地址。
        if args.provider != data["provider"]:
            data["api_key"] = ""
        data.update(provider=preset.id, base_url=preset.base_url, model=preset.suggested_model)
    for key in ("base_url", "model", "judge_count", "json_mode"):
        value = getattr(args, key, None)
        if value is not None:
            data[key] = value
    if args.timeout is not None:
        data["request_timeout"] = args.timeout
    env_key = os.environ.get("QUICKMEMORY_API_KEY")
    if env_key:
        data["api_key"] = env_key
    if args.prompt_key:
        data["api_key"] = getpass("请输入 API 密钥（不回显）：").strip()
    return SettingsData.model_validate(data)


def main() -> int:
    parser = argparse.ArgumentParser(description="配置本地 LLM；无参数时只显示设置，不显示密钥")
    add_model_arguments(parser)
    parser.add_argument("--db", help="SQLite 数据库路径")
    parser.add_argument("--presets", action="store_true", help="列出服务商预设")
    parser.add_argument("--save", action="store_true", help="保存提供的配置到本机 SQLite（密钥为明文）")
    parser.add_argument("--clear-key", action="store_true", help="清除密钥，配合 --save 生效")
    parser.add_argument("--accuracy-weight", type=float, help="正确率权重；完整度权重自动设为 1 减去此值")
    parser.add_argument("--pass-threshold", type=float, help="及格阈值")
    parser.add_argument("--judge-temperature", type=float, help="裁判温度")
    parser.add_argument("--merge-temperature", type=float, help="合并温度")
    args = parser.parse_args()
    if args.presets:
        print(json.dumps(list_provider_presets(), ensure_ascii=False, indent=2))
        return 0
    engine = make_engine(args.db)
    try:
        init_db(engine)
        with make_session_factory(engine)() as session:
            data = SettingsData.model_validate(get_settings(session)).model_dump()
            if args.accuracy_weight is not None:
                data.update(w_accuracy=args.accuracy_weight, w_completeness=1 - args.accuracy_weight)
            for key in ("pass_threshold", "judge_temperature", "merge_temperature"):
                if getattr(args, key) is not None:
                    data[key] = getattr(args, key)
            config = apply_arguments(data, args)
            if args.clear_key:
                config.api_key = ""
            if args.save:
                save_settings(session, config.model_dump())
                session.commit()
                print("设置已保存。API 密钥仅保存在本机数据库。")
            print(json.dumps(config.public_dict(), ensure_ascii=False, indent=2))
            return 0
    except (ValidationError, ValueError) as exc:
        # 不输出 ValidationError 的 input_value，避免泄露密钥。
        if isinstance(exc, ValidationError):
            messages = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False)]
            print("配置无效：" + "；".join(messages), file=sys.stderr)
        else:
            print("配置无效，请检查输入参数", file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
