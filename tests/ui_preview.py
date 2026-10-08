"""仅用于界面验收的模拟服务；独立 .qa 数据库，不是生产入口。"""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.main import create_app
from backend.services.grading import GradingService


class PreviewClient:
    async def complete(self, messages, settings, temperature):
        await asyncio.sleep(0.3)
        system = messages[0]["content"]
        payload = json.loads(messages[1]["content"])
        if "独立裁判" in system:
            value = [88, 76, 100][payload["judge_index"] - 1]
            return json.dumps({"accuracy": value, "completeness": 30,
                "correct_parts": ["【界面模拟】回答中的部分描述与参考定义一致。"],
                "wrong_parts": ["【界面模拟】回答遗漏了参考定义的部分要点。"],
                "uncertain_parts": [], "error_types": ["遗漏要点"],
                "model_knowledge_notes": ["【界面模拟】此处展示不计分的模型提示，与正式评分无关。"],
                "reasoning": "仅用于测试前端显示，不是真实模型评分。"})
        if "合并多位" in system:
            return json.dumps({"correct_parts": ["【界面模拟】已覆盖部分要点。"],
                "wrong_parts": ["【界面模拟】还有部分要点未覆盖。"], "uncertain_parts": [],
                "error_types": ["遗漏要点"], "model_knowledge_notes": ["【界面模拟】这段提示独立显示，不参与计分。"]})
        if "核对" in system:
            return json.dumps({"correct_parts": ["【界面模拟】定义清楚。"], "wrong_parts": [],
                "uncertain_parts": ["【界面模拟】请结合教材复查。"], "clarifying_questions": [],
                "suggested_rewrite": "【界面模拟】可选择采用的定义改写。"})
        return json.dumps({"ok": True, "message": "模拟连接成功（仅界面测试）"})


app = create_app(ROOT / ".qa" / "ui.db")
app.state.grading_service = GradingService(PreviewClient())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8010, access_log=False)
