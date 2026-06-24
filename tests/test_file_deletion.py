"""
测试文件删除和清理功能
"""

import os
import pytest
import asyncio
from pathlib import Path
from datetime import datetime, timedelta

from app.services.log_service import log_service
from app.utils.temp_directory_cleaner import TempDirectoryCleaner, temp_directory_cleaner
from app.models.log import LogRecord, LogStatus
from app.config import settings


class TestFileDeletion:
    """测试文件删除功能"""
    
    @pytest.mark.asyncio
    async def test_soft_delete_removes_physical_file(self, test_db, test_log_file):
        """测试软删除是否删除物理文件"""
        # 创建测试日志记录
        log_record = LogRecord(
            id="test-log-1",
            filename="test.tgz",
            original_filename="test_log.tgz",
            file_size=1024,
            file_path=str(test_log_file),
            status=LogStatus.COMPLETED
        )
        test_db.add(log_record)
        await test_db.commit()
        
        # 确认文件存在
        assert test_log_file.exists()
        
        # 执行软删除
        result = await log_service.delete_log(test_db, "test-log-1", hard_delete=False)
        
        # 验证结果
        assert result is True
        
        # 验证物理文件已删除
        assert not test_log_file.exists()
        
        # 验证数据库记录仍存在但标记为已删除
        await test_db.refresh(log_record)
        assert log_record.is_deleted is True
        assert log_record.deleted_at is not None
    
    @pytest.mark.asyncio
    async def test_hard_delete_removes_database_record(self, test_db, test_log_file):
        """测试硬删除是否删除数据库记录"""
        # 创建测试日志记录
        log_record = LogRecord(
            id="test-log-2",
            filename="test.tgz",
            original_filename="test_log.tgz",
            file_size=1024,
            file_path=str(test_log_file),
            status=LogStatus.COMPLETED
        )
        test_db.add(log_record)
        await test_db.commit()
        
        # 执行硬删除
        result = await log_service.delete_log(test_db, "test-log-2", hard_delete=True)
        
        # 验证结果
        assert result is True
        
        # 验证物理文件已删除
        assert not test_log_file.exists()
        
        # 验证数据库记录已删除
        record = await log_service.get_by_id(test_db, "test-log-2")
        assert record is None
    
    @pytest.mark.asyncio
    async def test_delete_cleans_processing_directories(self, test_db, test_log_file):
        """测试删除是否清理临时处理目录"""
        # 创建测试日志记录和临时处理目录
        task_id = "test-task-123"
        processing_dir = Path(settings.temp_dir) / f"processing_{task_id}"
        processing_dir.mkdir(parents=True, exist_ok=True)
        
        # 在处理目录中创建一些测试文件
        (processing_dir / "extracted").mkdir()
        (processing_dir / "extracted" / "test.txt").write_text("test content")
        
        log_record = LogRecord(
            id="test-log-3",
            filename="test.tgz",
            original_filename="test_log.tgz",
            file_size=1024,
            file_path=str(test_log_file),
            status=LogStatus.COMPLETED,
            task_id=task_id
        )
        test_db.add(log_record)
        await test_db.commit()
        
        # 确认处理目录存在
        assert processing_dir.exists()
        
        # 执行删除
        await log_service.delete_log(test_db, "test-log-3", hard_delete=False)
        
        # 验证处理目录已被清理
        assert not processing_dir.exists()


class TestTempDirectoryCleaner:
    """测试临时文件清理器"""
    
    def test_cleanup_old_processing_directories(self, temp_test_dir):
        """测试清理过期的处理目录"""
        # 创建一个旧的处理目录
        old_processing_dir = temp_test_dir / "processing_old_task"
        old_processing_dir.mkdir()
        old_file = old_processing_dir / "test.txt"
        old_file.write_text("old file")
        
        # 修改目录的修改时间为25小时前
        old_time = (datetime.utcnow() - timedelta(hours=25)).timestamp()
        os.utime(old_file, (old_time, old_time))
        os.utime(old_processing_dir, (old_time, old_time))
        
        # 创建一个新的处理目录
        new_processing_dir = temp_test_dir / "processing_new_task"
        new_processing_dir.mkdir()
        (new_processing_dir / "test.txt").write_text("new file")
        
        # 执行清理（保留时间24小时）
        cleaner = TempDirectoryCleaner(temp_dir=str(temp_test_dir))
        stats = cleaner.cleanup_processing_directories(max_age_hours=24)
        
        # 验证结果
        assert stats["deleted"] == 1
        assert not old_processing_dir.exists()
        assert new_processing_dir.exists()
    
    def test_cleanup_empty_processing_directories(self, temp_test_dir):
        """测试清理空的处理目录"""
        # 创建一个空的处理目录
        empty_processing_dir = temp_test_dir / "processing_empty_task"
        empty_processing_dir.mkdir()
        
        # 创建一个非空的处理目录
        nonempty_processing_dir = temp_test_dir / "processing_nonempty_task"
        nonempty_processing_dir.mkdir()
        (nonempty_processing_dir / "test.txt").write_text("content")
        
        # 执行清理
        cleaner = TempDirectoryCleaner(temp_dir=str(temp_test_dir))
        stats = cleaner.cleanup_processing_directories(max_age_hours=24)
        
        # 验证空目录被删除
        assert not empty_processing_dir.exists()
        # 验证非空目录仍然存在（如果不是过期的）
        # 注意：这取决于目录的修改时间
    
    def test_cleanup_extracted_files(self, temp_test_dir):
        """测试清理解压文件"""
        # 创建一个旧的解压目录
        processing_dir = temp_test_dir / "processing_test"
        processing_dir.mkdir()
        extracted_dir = processing_dir / "extracted"
        extracted_dir.mkdir()
        extracted_file = extracted_dir / "test.txt"
        extracted_file.write_text("extracted file")
        
        # 修改目录的修改时间为49小时前
        old_time = (datetime.utcnow() - timedelta(hours=49)).timestamp()
        os.utime(extracted_file, (old_time, old_time))
        os.utime(extracted_dir, (old_time, old_time))
        
        # 执行清理（保留时间48小时）
        cleaner = TempDirectoryCleaner(temp_dir=str(temp_test_dir))
        stats = cleaner.cleanup_old_extracted_files(max_age_hours=48)
        
        # 验证结果
        assert stats["deleted"] >= 1
        assert not extracted_dir.exists()
    
    def test_cleanup_all(self, temp_test_dir):
        """测试完整清理"""
        # 创建各种测试目录
        # 1. 旧的处理目录
        old_processing = temp_test_dir / "processing_old"
        old_processing.mkdir()
        old_time = (datetime.utcnow() - timedelta(hours=25)).timestamp()
        os.utime(old_processing, (old_time, old_time))
        
        # 2. 旧的解压目录
        processing = temp_test_dir / "processing_test"
        processing.mkdir()
        extracted = processing / "extracted"
        extracted.mkdir()
        old_time = (datetime.utcnow() - timedelta(hours=49)).timestamp()
        os.utime(processing, (old_time, old_time))
        os.utime(extracted, (old_time, old_time))
        
        # 执行完整清理
        cleaner = TempDirectoryCleaner(temp_dir=str(temp_test_dir))
        stats = cleaner.cleanup_all(processing_max_age=24, extracted_max_age=48)
        
        # 验证结果
        assert stats["total_deleted"] >= 2
        assert stats["total_freed_space_bytes"] >= 0
        assert not old_processing.exists()
        assert not extracted.exists()


# Pytest fixtures

@pytest.fixture
async def test_db(tmp_path):
    """创建测试数据库会话"""
    from app.models.database import db_manager

    prev_url = settings.database_url
    prev_engine = db_manager.engine
    prev_factory = db_manager.session_factory

    settings.database_url = f"sqlite+aiosqlite:///{tmp_path / 'file_deletion.sqlite'}"
    db_manager.initialize()
    await db_manager.create_tables()

    try:
        async for db in db_manager.get_session():
            yield db
            break
    finally:
        await db_manager.close()
        settings.database_url = prev_url
        db_manager.engine = prev_engine
        db_manager.session_factory = prev_factory


@pytest.fixture
def test_log_file(tmp_path):
    """创建测试日志文件"""
    log_file = tmp_path / "test_log.tgz"
    log_file.write_bytes(b"test content")
    return log_file


@pytest.fixture
def temp_test_dir(tmp_path):
    """创建临时测试目录"""
    test_dir = tmp_path / "temp"
    test_dir.mkdir()
    return test_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
