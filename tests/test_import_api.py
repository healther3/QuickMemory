"""Import previews must be pure, explicit, reproducible and safe to confirm once."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from backend.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "imports.db", seed=False)) as instance:
        yield instance


def preview(client, content, **extra):
    request = {"content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
               "filename": "机器学习.json", "duplicate_mode": "skip", **extra}
    response = client.post("/api/imports/preview", json=request)
    assert response.status_code == 200, response.text
    return request, response.json()


def confirm(client, request, report):
    return client.post("/api/imports/confirm", json={**request, "preview_token": report["preview_token"]})


@pytest.mark.parametrize("content", [
    '\ufeff {"  Dropout  ": " 随机丢弃 ", "过拟合": "泛化差"}',
    [{"term": "  Dropout  ", "definition": " 随机丢弃 ", "tags": ["正则化"], "reference_note": " 教材 "},
     {"term": "过拟合", "definition": "泛化差"}],
])
def test_both_formats_preview_without_mutation_and_confirm(client, content):
    request, report = preview(client, content)
    assert (report["added"], report["skipped"], report["overwritten"], report["invalid"]) == (2, 0, 0, 0)
    assert report["rows"][0]["term"] == "Dropout"
    assert client.get("/api/folders").json() == []
    assert client.get("/api/tags").json() == []
    assert client.get("/api/cards").json()["total"] == 0
    result = confirm(client, request, report)
    assert result.status_code == 200, result.text
    assert result.json()["added"] == 2
    folders = client.get("/api/folders").json()
    assert folders[0]["name"] == "机器学习"
    cards = client.get("/api/cards", params={"folder_id": folders[0]["id"]}).json()
    assert cards["total"] == 2
    assert sorted(item["term"] for item in cards["items"]) == ["Dropout", "过拟合"]
    assert confirm(client, request, report).status_code == 409
    assert len(client.get("/api/folders").json()) == 1


@pytest.mark.parametrize("content", ["not json", '{"x":', '"just a string"', "null", "123", '{"term": {"bad": true}}', '{"term": 12}', "NaN"])
def test_invalid_files_are_rejected_with_chinese_reason(client, content):
    response = client.post("/api/imports/preview", json={"content": content, "folder_name": "新题库"})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert "JSON" in response.json()["detail"] or "格式" in response.json()["detail"]
    assert client.get("/api/folders").json() == []


def test_row_validation_skip_blank_invalid_types_and_report_reasons(client):
    request, report = preview(client, [
        {"term": " ", "definition": "说明"}, {"term": "x", "definition": "\n"},
        {"term": "missing"}, {"term": "wrong type", "definition": 23},
        {"term": "bad tags", "definition": "说明", "tags": "标签"}, "not an object",
        {"term": "有效", "definition": "定义", "reference_note": " 笔记 ", "tags": [" A ", "a"]},
    ])
    assert report["invalid"] == 6 and report["added"] == 1
    assert all(row["reason"].startswith("第 ") for row in report["rows"][:-1])
    assert confirm(client, request, report).json()["invalid"] == 6
    saved = client.get("/api/cards").json()["items"][0]
    assert saved["reference_note"] == "笔记" and [tag["name"] for tag in saved["tags"]] == ["A"]


def test_duplicate_terms_within_object_and_array_are_not_silently_lost(client):
    request, report = preview(client, '{"A":"首条", " a ":"第二条", "A":"第三条"}')
    assert (report["added"], report["skipped"]) == (1, 2)
    assert confirm(client, request, report).status_code == 200
    assert client.get("/api/cards").json()["items"][0]["definition"] == "首条"
    request, report = preview(client, [
        {"term": "Straße", "definition": "首条", "tags": ["原标签"], "reference_note": "原笔记"},
        {"term": " STRASSE ", "definition": "末条", "tags": ["不采用"], "reference_note": "不采用"},
    ], duplicate_mode="overwrite")
    assert (report["added"], report["overwritten"]) == (1, 1)
    result = confirm(client, request, report).json()
    saved = client.get("/api/cards", params={"folder_id": result["folder_id"]}).json()["items"][0]
    assert saved["term"] == "Straße" and saved["definition"] == "末条"
    assert saved["reference_note"] == "原笔记" and saved["tags"][0]["name"] == "原标签"


def test_shared_card_overwrite_warns_and_preserves_other_metadata(client):
    folder_a = client.post("/api/folders", json={"name": "A"}).json()["id"]
    folder_b = client.post("/api/folders", json={"name": "B"}).json()["id"]
    card = client.post("/api/cards", json={"term": "Dropout", "definition": "旧定义",
                       "reference_note": "原笔记", "tags": ["保留标签"], "folder_ids": [folder_a, folder_b]}).json()
    incoming = [{"term": " dropout ", "definition": "新定义", "tags": ["不用标签"], "reference_note": "不用笔记"}]
    request, report = preview(client, incoming, folder_id=folder_a)
    assert report["skipped"] == 1
    assert confirm(client, request, report).status_code == 200
    assert confirm(client, request, report).status_code == 409  # No-op tokens are still consumed.
    request, report = preview(client, incoming, folder_id=folder_a, duplicate_mode="overwrite")
    assert report["overwritten"] == 1
    assert "共享卡片" in report["rows"][0]["reason"] and "2 个文件夹" in report["rows"][0]["reason"]
    assert confirm(client, request, report).status_code == 200
    saved = client.get(f'/api/cards/{card["id"]}').json()
    assert saved["term"] == "Dropout" and saved["definition"] == "新定义"
    assert saved["reference_note"] == "原笔记"
    assert saved["tags"] == card["tags"] and saved["folders"] == card["folders"]
    assert client.get("/api/cards", params={"folder_id": folder_b}).json()["items"][0]["definition"] == "新定义"


@pytest.mark.parametrize("change", ["definition", "tags", "folders", "folder_name", "delete_folder"])
def test_preview_detects_changed_target_and_metadata(client, change):
    target = client.post("/api/folders", json={"name": "目标"}).json()["id"]
    other = client.post("/api/folders", json={"name": "其他"}).json()["id"]
    payload = {"term": "x", "definition": "旧定义", "tags": ["原标签"], "folder_ids": [target]}
    card = client.post("/api/cards", json=payload).json()
    request, report = preview(client, {"x": "新定义"}, folder_id=target, duplicate_mode="overwrite")
    if change in {"definition", "tags", "folders"}:
        payload.update({"definition": "用户修改"} if change == "definition" else
                       {"tags": ["用户改标签"]} if change == "tags" else {"folder_ids": [target, other]})
        assert client.put(f'/api/cards/{card["id"]}', json=payload).status_code == 200
    elif change == "folder_name":
        assert client.put(f"/api/folders/{target}", json={"name": "改名"}).status_code == 200
    else:
        assert client.delete(f"/api/folders/{target}").status_code == 204
    assert confirm(client, request, report).status_code == 409
    assert client.get(f'/api/cards/{card["id"]}').json()["definition"] != "新定义"


def test_confirm_requires_matching_request_and_real_preview_token(client):
    request, report = preview(client, {"x": "定义"})
    for changed in [{**request, "content": '{"x":"偷换内容"}'}, {**request, "duplicate_mode": "overwrite"}]:
        assert confirm(client, changed, report).status_code == 409
    assert confirm(client, request, {"preview_token": "forged"}).status_code == 409
    assert client.post("/api/imports/confirm", json=request).status_code == 422
    assert confirm(client, request, report).status_code == 200


def test_import_rollback_preserves_no_partial_folder_cards_or_tags(client, monkeypatch):
    import backend.api.imports as routes
    original = routes.apply_plan

    def fail_after_writing(db, plan):
        original(db, plan)
        raise IntegrityError("simulated transaction failure", None, Exception("test"))

    request, report = preview(client, [{"term": "x", "definition": "y", "tags": ["新标签"]}])
    monkeypatch.setattr(routes, "apply_plan", fail_after_writing)
    assert confirm(client, request, report).status_code == 409
    assert client.get("/api/cards").json()["total"] == 0
    assert client.get("/api/folders").json() == []
    assert client.get("/api/tags").json() == []
    monkeypatch.setattr(routes, "apply_plan", original)
    assert confirm(client, request, report).status_code == 200


def test_concurrent_double_confirmation_only_imports_once(client):
    request, report = preview(client, {"x": "定义"})
    barrier = threading.Barrier(2)

    def run():
        barrier.wait(timeout=5)
        return confirm(client, request, report).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _: run(), range(2)))
    assert statuses == [200, 409]
    assert len(client.get("/api/folders").json()) == 1
    assert client.get("/api/cards").json()["total"] == 1
