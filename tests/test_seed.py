from sqlalchemy import delete, func, select

from backend.database import init_db, make_engine, make_session_factory
from backend.models import AppMeta, Card, Folder
from backend.seed import seed_once


def test_sample_library_seed_once_and_delete_stays_deleted(tmp_path):
    engine = make_engine(tmp_path / "seed.db")
    init_db(engine)
    factory = make_session_factory(engine)
    seed_once(factory)
    seed_once(factory)
    with factory.begin() as db:
        assert db.scalar(select(func.count()).select_from(Card)) == 10
        assert db.scalar(select(func.count()).select_from(Folder)) == 1
        db.execute(delete(Card))
        db.execute(delete(Folder))
    seed_once(factory)
    with factory() as db:
        assert db.scalar(select(Card.id)) is None
        assert db.scalar(select(Folder.id)) is None
    engine.dispose()


def test_existing_library_never_injected_with_demo_cards(tmp_path):
    engine = make_engine(tmp_path / "existing.db")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory.begin() as db:
        db.add(Card(term="自己的卡片", definition="自己的定义"))
    seed_once(factory)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Card)) == 1
        assert db.get(AppMeta, "sample_library_initialized").value == "1"
    engine.dispose()
