import json
import shutil
import uuid
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import bug_fix_context as context
from app.services.chat_image_store import StoredImage


def test_preserves_all_logs_question_history_and_original_screenshot(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'bug_fix_context_dir', str(tmp_path / 'persistent'))
    source = tmp_path / 'analysis'
    (source / 'logs' / '1_a').mkdir(parents=True)
    (source / 'logs' / '2_b').mkdir()
    (source / 'logs' / '1_a' / 'same.log').write_text('first original')
    (source / 'logs' / '2_b' / 'same.log').write_text('second original')
    task = {'question': 'Question with OCR evidence', 'hints': 'previous turn',
            'repo_info': {'clone_url': 'https://oauth2:secret@host/repo.git'}}
    (source / 'task.json').write_text(json.dumps(task))
    original = tmp_path / 'original.png'
    original.write_bytes(b'original screenshot bytes')
    ctx = SimpleNamespace(temp_dir=str(source), task_json_path=str(source / 'task.json'))
    captured = context.capture_source(ctx, images=[StoredImage('id', 'image/png', 'screen', 25, str(original))])
    analysis = {'summary': 'Full original analysis', 'tool_trace': [{'output': 'x' * 100_000}]}
    ref = context.persist(str(uuid.uuid4()), captured, analysis)
    shutil.rmtree(source)
    original.unlink()
    restored = tmp_path / 'repair'
    data = context.restore(ref, restored)
    assert (restored / 'logs/1_a/same.log').read_text() == 'first original'
    assert (restored / 'logs/2_b/same.log').read_text() == 'second original'
    assert (restored / 'images/original.png').read_bytes() == b'original screenshot bytes'
    assert data['task']['question'] == task['question']
    assert data['task']['hints'] == task['hints']
    assert 'secret' not in json.dumps(data)
    index = json.loads((restored / 'source_analysis.json').read_text())
    assert 'tool_trace' not in index['analysis_result']
    assert json.loads((restored / index['full_analysis_result_file']).read_text()) == analysis
    context.restore(ref, tmp_path / 'retry')
    snapshot_file = context.context_root() / ref['snapshot_id'] / 'logs/1_a/same.log'
    snapshot_file.write_text('changed')
    with pytest.raises(ValueError, match='source_context_changed'):
        context.restore(ref, tmp_path / 'corrupt-retry')


@pytest.mark.asyncio
async def test_history_originals_survive_text_only_analysis(tmp_path, monkeypatch):
    from app.models.chat import ChatMessage
    from app.services import chat_image_store
    from app.services.log_analysis_chat_service import LogAnalysisChatService, chat_history_service

    previous = tmp_path / 'previous.png'
    previous.write_bytes(b'earlier screenshot')
    record = SimpleNamespace(images_json=json.dumps([
        {'id': 'previous', 'media_type': 'image/png', 'name': 'Earlier screenshot', 'size': 18},
        {'id': 'missing', 'media_type': 'image/png', 'name': 'Deleted screenshot', 'size': 18},
    ]))

    async def fetch(*args, **kwargs):
        assert kwargs == {'user_id': 7, 'session_id': 'session'}
        return [record]

    monkeypatch.setattr(chat_history_service, 'fetch_messages', fetch)
    monkeypatch.setattr(chat_history_service, 'to_chat_messages', lambda records: [
        ChatMessage(role='user', content='Earlier question and OCR'),
    ])
    monkeypatch.setattr(chat_image_store, 'resolve_path', lambda session_id, image_id: previous if image_id == 'previous' else None)
    images = []
    hints = await LogAnalysisChatService()._build_history_hint(
        db=object(), user=SimpleNamespace(id=7), session_id='session',
        history_json=None, source_images=images,
    )
    assert 'Earlier question and OCR' in hints
    assert '历史截图原件不可用' in hints and 'missing' in hints
    assert len(images) == 1
    assert images[0].path == str(previous)
    # No provider-dependent images/ directory is required to collect originals.
    assert images[0].to_meta()['name'] == 'Earlier screenshot'
