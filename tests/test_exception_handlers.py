"""全局异常处理器对结构化 detail 的处理。

历史缺陷：``HTTPException(detail={...})`` 会被直接塞进 ErrorResponse.message（str），
pydantic 校验失败后 4xx 被吞成 500。
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.exceptions import register_exception_handlers, stringify_detail


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/dict-detail")
    async def _dict_detail():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"affected_logs": 3, "message": "该项目有关联的日志记录。"},
        )

    @app.get("/dict-detail-no-message")
    async def _dict_detail_no_message():
        raise HTTPException(status_code=400, detail={"reason": "bad_input"})

    @app.get("/list-detail")
    async def _list_detail():
        raise HTTPException(status_code=422, detail=["字段A无效", "字段B无效"])

    @app.get("/str-detail")
    async def _str_detail():
        raise HTTPException(status_code=404, detail="记录不存在")

    return TestClient(app, raise_server_exceptions=False)


def test_dict_detail_keeps_status_and_exposes_both_shapes() -> None:
    resp = _client().get("/dict-detail")
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["success"] is False
    # message/detail 均为字符串，前端两种读法都能拿到可读文案
    assert body["message"] == "该项目有关联的日志记录。"
    assert body["detail"] == "该项目有关联的日志记录。"
    # dict 顶层键合并到根节点，结构化字段仍然可读
    assert body["affected_logs"] == 3


def test_dict_detail_without_message_falls_back_to_json() -> None:
    resp = _client().get("/dict-detail-no-message")
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "bad_input" in body["message"]
    assert body["reason"] == "bad_input"


def test_list_detail_is_joined() -> None:
    resp = _client().get("/list-detail")
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["message"] == "字段A无效; 字段B无效"
    assert body["detail"] == "字段A无效; 字段B无效"


def test_str_detail_unchanged() -> None:
    resp = _client().get("/str-detail")
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["message"] == "记录不存在"
    assert body["detail"] is None


def test_stringify_detail_variants() -> None:
    assert stringify_detail("x") == "x"
    assert stringify_detail({"message": "m"}) == "m"
    assert stringify_detail({"detail": "d"}) == "d"
    assert stringify_detail({"error": "e"}) == "e"
    assert stringify_detail(None) == "None"
    assert stringify_detail(42) == "42"
