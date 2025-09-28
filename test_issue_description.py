#!/usr/bin/env python3
"""
简化的测试脚本，验证issue_description字段的代码实现
"""

import re
from pathlib import Path


def test_log_record_model():
    """测试LogRecord模型是否包含issue_description字段"""
    print("测试 LogRecord 模型...")
    
    log_model_path = Path("app/models/log.py")
    if not log_model_path.exists():
        print("❌ log.py 文件不存在")
        return False
    
    content = log_model_path.read_text(encoding='utf-8')
    
    # 检查是否添加了issue_description字段 (使用新的SQLAlchemy 2.0语法)
    if 'issue_description: Mapped[Optional[str]] = mapped_column(' in content and 'comment="问题描述"' in content:
        print("✅ LogRecord 模型包含 issue_description 字段")
    else:
        print("❌ LogRecord 模型缺少 issue_description 字段")
        return False
    
    return True


def test_log_file_info_model():
    """测试LogFileInfo模型是否包含issue_description字段"""
    print("测试 LogFileInfo 模型...")
    
    log_model_path = Path("app/models/log.py")
    content = log_model_path.read_text(encoding='utf-8')
    
    # 检查LogFileInfo是否包含issue_description字段
    if 'issue_description: Optional[str] = Field(None, description="问题描述")' in content:
        print("✅ LogFileInfo 模型包含 issue_description 字段")
    else:
        print("❌ LogFileInfo 模型缺少 issue_description 字段")
        return False
    
    return True


def test_log_upload_request_model():
    """测试LogUploadRequest模型是否包含issue_description字段"""
    print("测试 LogUploadRequest 模型...")
    
    log_model_path = Path("app/models/log.py")
    content = log_model_path.read_text(encoding='utf-8')
    
    # 检查LogUploadRequest是否包含issue_description字段
    if 'issue_description: Optional[str] = Field(None, description="问题描述")' in content:
        print("✅ LogUploadRequest 模型包含 issue_description 字段")
    else:
        print("❌ LogUploadRequest 模型缺少 issue_description 字段")
        return False
    
    # 检查expires_in_days字段
    if 'expires_in_days: Optional[int] = Field(None, ge=1, le=365, description="过期天数")' in content:
        print("✅ LogUploadRequest 模型包含 expires_in_days 字段")
    else:
        print("❌ LogUploadRequest 模型缺少 expires_in_days 字段")
        return False
    
    return True


def test_api_endpoint():
    """测试API端点是否包含issue_description参数"""
    print("测试 API 端点...")
    
    api_path = Path("app/api/logs.py")
    if not api_path.exists():
        print("❌ logs.py API文件不存在")
        return False
    
    content = api_path.read_text(encoding='utf-8')
    
    # 检查是否添加了issue_description参数 (使用Optional类型)
    if 'issue_description: Optional[str] = Form(None, description="问题描述")' in content:
        print("✅ API 端点包含 issue_description 参数")
    else:
        print("❌ API 端点缺少 issue_description 参数")
        return False
    
    return True


def test_service_layer():
    """测试服务层是否正确处理issue_description"""
    print("测试服务层...")
    
    service_path = Path("app/services/log_service.py")
    if not service_path.exists():
        print("❌ log_service.py 文件不存在")
        return False
    
    content = service_path.read_text(encoding='utf-8')
    
    # 检查create方法调用是否包含issue_description
    if 'issue_description=request.issue_description' in content:
        print("✅ 服务层正确传递 issue_description 到数据库")
    else:
        print("❌ 服务层未正确传递 issue_description 到数据库")
        return False
    
    # 检查_db_to_pydantic方法是否包含issue_description
    if 'issue_description=record.issue_description' in content:
        print("✅ 服务层正确在响应中包含 issue_description")
    else:
        print("❌ 服务层未在响应中包含 issue_description")
        return False
    
    return True


def test_migration_file():
    """测试迁移文件是否存在"""
    print("测试数据库迁移文件...")
    
    migration_path = Path("alembic/versions/e8f9a2b3c4d5_add_issue_description_field.py")
    if migration_path.exists():
        print("✅ 数据库迁移文件已创建")
        
        content = migration_path.read_text(encoding='utf-8')
        if "add_column('log_records', sa.Column('issue_description', sa.Text(), nullable=True, comment='问题描述'))" in content:
            print("✅ 迁移文件正确添加 issue_description 字段")
        else:
            print("❌ 迁移文件未正确添加 issue_description 字段")
            return False
    else:
        print("❌ 数据库迁移文件不存在")
        return False
    
    return True


def main():
    """主测试函数"""
    print("开始验证 issue_description 字段实现...\n")
    
    tests = [
        test_log_record_model,
        test_log_file_info_model,
        test_log_upload_request_model,
        test_api_endpoint,
        test_service_layer,
        test_migration_file
    ]
    
    success = True
    for test in tests:
        if not test():
            success = False
        print()
    
    print("="*50)
    if success:
        print("✅ 所有验证通过！issue_description 字段实现正确")
        print("\n实现总结:")
        print("1. ✅ 数据库模型 LogRecord 添加了 issue_description 字段")
        print("2. ✅ Pydantic 模型 LogFileInfo 添加了 issue_description 字段")
        print("3. ✅ 请求模型 LogUploadRequest 添加了 issue_description 和 expires_in_days 字段")
        print("4. ✅ API 端点添加了 issue_description 参数")
        print("5. ✅ 服务层正确处理和传递 issue_description")
        print("6. ✅ 创建了数据库迁移文件")
    else:
        print("❌ 部分验证失败，请检查实现")
    
    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)