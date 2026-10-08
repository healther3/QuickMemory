"""Catalog API integration tests against disposable local SQLite databases."""

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.models import ExamAnswer, ExamSession


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "catalog.db", seed=False)) as instance:
        yield instance


def folder(client, name="机器学习"):
    response = client.post("/api/folders", json={"name": name})
    assert response.status_code == 201
    return response.json()


def card(client, **changes):
    data = {"term": "过拟合", "definition": "训练好，泛化差", "reference_note": "课本第 1 页",
            "tags": ["正则化"], "folder_ids": []}
    data.update(changes)
    response = client.post("/api/cards", json=data)
    assert response.status_code == 201, response.text
    return response.json()


def test_card_crud_trim_and_many_to_many(client):
    first, second = folder(client), folder(client, "面试")
    created = card(client, term="  Dropout  ", definition="  随机丢弃神经元  ",
                   tags=[" 正则化 ", "正则化", " ML ", "ml"],
                   folder_ids=[first["id"], second["id"], first["id"]])
    assert created["term"] == "Dropout"
    assert created["definition"] == "随机丢弃神经元"
    assert [tag["name"] for tag in created["tags"]] == ["正则化", "ML"]
    assert len(created["folders"]) == 2
    assert created["created_at"].endswith("+00:00")
    assert client.get(f'/api/cards/{created["id"]}').json() == created
    assert [item["card_count"] for item in client.get("/api/folders").json()] == [1, 1]
    updated = client.put(f'/api/cards/{created["id"]}', json={
        "term": "Dropout", "definition": "训练时随机将部分激活置零",
        "tags": ["网络"], "folder_ids": [second["id"]], "reference_note": "新版说明",
    }).json()
    assert updated["updated_at"] != created["updated_at"]
    assert updated["tags"][0]["name"] == "网络"
    assert [item["id"] for item in updated["folders"]] == [second["id"]]
    assert client.get("/api/cards", params={"folder_id": first["id"]}).json()["total"] == 0
    assert client.delete(f'/api/cards/{created["id"]}').status_code == 204
    assert client.get(f'/api/cards/{created["id"]}').status_code == 404


def test_keyword_casefold_filters_pagination_and_total(client):
    first, second = folder(client), folder(client, "其他")
    a = card(client, term="Straße", definition="LOCAL Definition", folder_ids=[first["id"]])
    card(client, term="第二张", definition="local 另一个定义", tags=["算法"], folder_ids=[second["id"]])
    assert client.get("/api/cards", params={"q": " STRASSE "}).json()["items"][0]["id"] == a["id"]
    found = client.get("/api/cards", params={"q": " LOCAL ", "limit": 1}).json()
    assert found["total"] == 2 and len(found["items"]) == 1
    assert len(client.get("/api/cards", params={"q": "local", "limit": 1, "offset": 1}).json()["items"]) == 1
    assert client.get("/api/cards", params={"q": "LOCAL", "tag_id": a["tags"][0]["id"],
                                         "folder_id": first["id"]}).json()["total"] == 1
    assert client.get("/api/cards", params={"limit": 0}).status_code == 422


def test_bad_card_inputs_never_create_tags_or_partial_card(client):
    for invalid in ["", " \n "]:
        response = client.post("/api/cards", json={"term": invalid, "definition": "定义"})
        assert response.status_code == 422
    response = client.post("/api/cards", json={"term": "x", "definition": "定义", "folder_ids": [999], "tags": ["新标签"]})
    assert response.status_code == 404
    assert client.get("/api/cards").json()["total"] == 0
    assert client.get("/api/tags").json() == []
    assert client.post("/api/cards", json={"term": 123, "definition": "定义"}).status_code == 422


def test_tags_rename_delete_propagate_and_case_insensitive_collision(client):
    created = card(client, tags=["ML"])
    tag_id = created["tags"][0]["id"]
    assert client.post("/api/tags", json={"name": " ml "}).status_code == 409
    other = client.post("/api/tags", json={"name": "中文"}).json()
    assert client.put(f'/api/tags/{other["id"]}', json={"name": "ml"}).status_code == 409
    assert client.put(f"/api/tags/{tag_id}", json={"name": "深度学习"}).json()["card_count"] == 1
    assert client.get(f'/api/cards/{created["id"]}').json()["tags"][0]["name"] == "深度学习"
    assert client.delete(f"/api/tags/{tag_id}").status_code == 204
    assert client.get(f'/api/cards/{created["id"]}').json()["tags"] == []


def test_folder_export_is_roundtrippable_plain_text(client):
    target = folder(client, "中文 / 题库")
    created = card(client, folder_ids=[target["id"]], definition="<script>普通文本</script>\n第二行")
    response = client.get(f'/api/folders/{target["id"]}/export')
    assert response.status_code == 200
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.json() == [{"term": created["term"], "definition": created["definition"],
                                "reference_note": created["reference_note"], "tags": ["正则化"]}]
    renamed = client.put(f'/api/folders/{target["id"]}', json={"name": " 重命名 "}).json()
    assert renamed["name"] == "重命名" and renamed["card_count"] == 1


def test_deleting_folder_and_card_keeps_answer_snapshot(client):
    target = folder(client)
    created = card(client, folder_ids=[target["id"]])
    with client.app.state.session_factory() as db:
        exam = ExamSession(folder_id=target["id"], folder_name_snapshot=target["name"])
        db.add(exam)
        db.flush()
        answer = ExamAnswer(session_id=exam.id, card_id=created["id"], position=0,
                            term_snapshot=created["term"], definition_snapshot=created["definition"])
        db.add(answer)
        db.commit()
        answer_id, exam_id = answer.id, exam.id
    assert client.delete(f'/api/folders/{target["id"]}').status_code == 204
    assert client.get(f'/api/cards/{created["id"]}').json()["folders"] == []
    assert client.delete(f'/api/cards/{created["id"]}').status_code == 204
    with client.app.state.session_factory() as db:
        answer = db.get(ExamAnswer, answer_id)
        assert answer.card_id is None
        assert answer.definition_snapshot == created["definition"]
        assert db.get(ExamSession, exam_id).folder_id is None
