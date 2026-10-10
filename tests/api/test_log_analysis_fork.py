"""Fork 的鉴权、历史兼容、工作区与后续写入隔离回归。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import logs as logs_api, users as users_api
from app.config import settings
from app.models.database import Base, get_db
from app.models.log import LogRecord, LogStatus
from app.models.user import ChatAgentRun, ChatMessage, ChatSession, User
from app.security.user_auth import user_auth_manager
from app.services.log_analysis_chat_service import log_analysis_chat_service as chat
from app.services import log_analysis_fork_service as forks


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fork.db'}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(settings, 'code_repo_clone_base_dir', str(tmp_path / 'workspaces'))
    monkeypatch.setattr(chat, 'registry_dir', tmp_path / 'registry')
    monkeypatch.setattr(chat, '_inject_repo_info', lambda ctx: None)
    source = json.dumps({'extra_fields': {'ai_analysis_conversation': [
        {'status': 'ok', 'query': '为什么断链？', 'answer': '超时导致断链'},
        {'status': 'ok', 'query': '怎样验证？', 'answer': '检查重试计数'},
    ]}})

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            for uid in ['alice', 'bob']:
                db.add(User(id=uid, username=uid, password_hash='unused', is_active=True))
            for lid in ['one', 'two', 'empty', 'legacy', 'deleted']:
                p = tmp_path / f'{lid}.log'
                p.write_text(f'{lid}: timeout retry=3')
                meta = source if lid in ['one', 'deleted'] else '{}'
                if lid == 'legacy':
                    meta = json.dumps({'extra_fields': {'ai_analysis_result': {
                        'query': '旧问题', 'final_result': {'content': '旧正文', 'recommendations': ['旧建议']}
                    }}})
                db.add(LogRecord(id=lid, filename=p.name, original_filename=p.name,
                    file_path=str(p), archive_path=str(p), file_size=p.stat().st_size,
                    status=LogStatus.COMPLETED, is_deleted=lid == 'deleted', metadata_json=meta,
                    analysis_group_id='group' if lid in ['one', 'two'] else None))
            await db.commit()
    asyncio.run(seed())

    async def get_test_db():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    app = FastAPI()
    app.include_router(logs_api.router, prefix='/api/v1/logs')
    app.include_router(users_api.router)
    app.dependency_overrides[get_db] = get_test_db
    tokens = {uid: {'Authorization': 'Bearer ' + user_auth_manager.issue_token(uid, uid)[0]} for uid in ['alice', 'bob']}
    with TestClient(app) as client:
        yield client, factory, tokens, tmp_path, source
    asyncio.run(engine.dispose())


def test_fork_owned_multi_turn_multi_attachment_and_reload(setup):
    client, factory, tokens, tmp, source = setup
    # 任一分组附件入口都复制详情页相同的分析，另一个用户也可 Fork。
    a = client.post('/api/v1/logs/two/analysis/fork', headers=tokens['alice'])
    b = client.post('/api/v1/logs/one/analysis/fork', headers=tokens['bob'])
    assert a.status_code == b.status_code == 201, (a.text, b.text)
    aid, bid = a.json()['data']['id'], b.json()['data']['id']
    assert aid != bid
    messages = client.get(f'/api/v1/users/chat-sessions/{bid}/messages', headers=tokens['bob']).json()
    assert messages['workspace_context'] == {'agent_kind': 'log_analysis', 'project_repo_id': None, 'has_log_workspace': True}
    assert [m['role'] for m in messages['data']] == ['user', 'ai', 'user', 'ai']
    assert '为什么断链' in messages['data'][0]['content']
    assert '超时导致断链' in messages['data'][1]['content']
    assert '检查重试计数' in messages['data'][3]['content']
    assert client.get(f'/api/v1/users/chat-sessions/{bid}/messages', headers=tokens['alice']).status_code == 404
    with pytest.raises(PermissionError):
        chat._load_context(bid, user=SimpleNamespace(id='alice'))
    actx, ameta = chat._load_context(aid, user=SimpleNamespace(id='alice'))
    bctx, bmeta = chat._load_context(bid, user=SimpleNamespace(id='bob'))
    assert actx.temp_dir != bctx.temp_dir
    assert len([p for p in Path(bctx.logs_dir).rglob('*.log') if p.is_file()]) == 2
    ap = next(p for p in Path(actx.logs_dir).rglob('*.log') if p.is_file())
    bp = Path(bctx.logs_dir) / ap.relative_to(actx.logs_dir)
    ap.write_text('alice changed')
    assert bp.read_text() != 'alice changed'
    assert (tmp / 'one.log').read_text() == 'one: timeout retry=3'

    async def follow_up():
        async with factory() as db:
            await chat._save_analysis_result(db=db, context_meta=bmeta, result={'answer': 'new'}, question='追问')
            await chat._persist_exchange(db=db, user_id='bob', session_id=bid, question='追问', answer='new', filename='one.log')
            await db.commit()
            assert (await db.get(LogRecord, 'one')).metadata_json == source
            assert (await db.get(ChatSession, bid)).message_count == 6
            assert (await db.get(ChatSession, aid)).message_count == 4
    asyncio.run(follow_up())
    job = SimpleNamespace(context_meta=bmeta, result={'requires_code_fix': True})
    asyncio.run(chat._maybe_dispatch_bug_fix(job))


@pytest.mark.parametrize('log_id,code', [('unknown',404),('deleted',404),('empty',422)])
def test_reject_without_partial_state(setup, log_id, code):
    client, factory, tokens, tmp, _ = setup
    assert client.post(f'/api/v1/logs/{log_id}/analysis/fork', headers=tokens['bob']).status_code == code
    assert not (tmp / 'registry').exists()
    async def check():
        async with factory() as db:
            assert not list((await db.execute(select(ChatSession))).scalars())
    asyncio.run(check())


@pytest.mark.parametrize('query_in_result', [True, False])
def test_auth_and_legacy(setup, query_in_result):
    client, factory, tokens, _, _ = setup
    if not query_in_result:
        async def make_legacy_task_query():
            async with factory() as db:
                log = await db.get(LogRecord, 'legacy')
                meta = json.loads(log.metadata_json)
                meta['extra_fields']['ai_analysis_result'].pop('query')
                meta['extra_fields']['ai_analysis_task'] = {'query': '旧问题'}
                log.metadata_json = json.dumps(meta)
                await db.commit()
        asyncio.run(make_legacy_task_query())
    assert client.post('/api/v1/logs/one/analysis/fork').status_code == 401
    response = client.post('/api/v1/logs/legacy/analysis/fork', headers=tokens['bob'])
    assert response.status_code == 201, response.text
    sid = response.json()['data']['id']
    msgs = client.get(f'/api/v1/users/chat-sessions/{sid}/messages', headers=tokens['bob']).json()['data']
    assert len(msgs) == 2
    assert '旧问题' in msgs[0]['content']
    assert '旧正文' in msgs[1]['content'] and '旧建议' in msgs[1]['content']


def test_missing_attachment_and_persistence_failure_cleanup(setup, monkeypatch):
    client, factory, tokens, tmp, _ = setup
    (tmp / 'two.log').unlink()
    assert client.post('/api/v1/logs/one/analysis/fork', headers=tokens['bob']).status_code == 422
    assert not list((tmp / 'workspaces').glob('*'))
    (tmp / 'two.log').write_text('restored')
    save_exchange = forks.chat_history_service.save_exchange
    async def partial_write_then_fail(*args, **kwargs):
        await save_exchange(*args, **kwargs)
        raise RuntimeError('DB failed')
    monkeypatch.setattr(forks.chat_history_service, 'save_exchange', partial_write_then_fail)
    with pytest.raises(RuntimeError, match='DB failed'):
        client.post('/api/v1/logs/one/analysis/fork', headers=tokens['bob'])
    assert not list((tmp / 'workspaces').glob('*'))
    assert not list((tmp / 'registry').glob('*.json'))
    async def check():
        async with factory() as db:
            assert not list((await db.execute(select(ChatSession))).scalars())
            assert not list((await db.execute(select(ChatMessage))).scalars())
    asyncio.run(check())


def test_fork_runs_do_not_replace_source_analysis_attribution(setup):
    from datetime import datetime, timedelta
    from app.services.log_service import log_service

    _, factory, _, _, _ = setup
    async def check():
        async with factory() as db:
            source_run = ChatAgentRun(
                session_id='original', user_id='alice', owner_scope='user:alice',
                agent_kind='log_analysis', status='succeeded', user_message='original',
                request_json=json.dumps({'log_id':'one'}), started_at=datetime(2026, 1, 1),
            )
            db.add(source_run)
            # 多于旧回填的 limit，Fork 也不能挤掉真正的来源用户。
            for index in range(25):
                db.add(ChatAgentRun(
                    session_id=f'fork-{index}', user_id='bob', owner_scope='user:bob',
                    agent_kind='log_analysis', status='succeeded', user_message='follow-up',
                    request_json=json.dumps({'log_id':'one','forked_from_log_id':'one'}),
                    started_at=datetime(2026, 1, 2) + timedelta(minutes=index),
                ))
            await db.flush()
            source = await db.get(LogRecord, 'one')
            result = await log_service._enrich_ai_analysis_trigger(db, source, {'answer':'original answer'})
            assert result['triggered_by']['user']['id'] == 'alice'
            assert result['triggered_by']['session_id'] == 'original'
    asyncio.run(check())
