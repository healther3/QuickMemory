"""仅为全新空库添加一次示例题库，用户删除后不会自动补回。"""
import json
from pathlib import Path

from sqlalchemy import select

from backend.models import AppMeta, Card, Folder, UserTag


def seed_once(factory):
    with factory.begin() as db:
        if db.get(AppMeta, "sample_library_initialized") is not None:
            return
        if db.scalar(select(Card.id).limit(1)) is None and db.scalar(select(Folder.id).limit(1)) is None:
            entries = json.loads((Path(__file__).resolve().parents[1] / "examples" / "ml_terms.json").read_text(encoding="utf-8"))
            folder = Folder(name="机器学习 · 基础概念")
            tags = {tag.name: tag for tag in db.scalars(select(UserTag))}
            for entry in entries:
                for name in entry["tags"]:
                    if name not in tags:
                        tags[name] = UserTag(name=name)
                db.add(Card(term=entry["term"], definition=entry["definition"],
                            reference_note=entry["reference_note"], folders=[folder],
                            user_tags=[tags[name] for name in entry["tags"]]))
        db.add(AppMeta(key="sample_library_initialized", value="1"))
