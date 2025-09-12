#!/usr/bin/env python3
"""
数据库管理脚本
用于数据库初始化、迁移和管理
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from app.database import init_database, create_tables, drop_tables, reset_database, check_database_connection
from app.config import settings


async def init_db():
    """初始化数据库"""
    print("正在初始化数据库...")
    try:
        await init_database()
        print("✅ 数据库初始化成功")
    except Exception as e:
        print(f"❌ 数据库初始化失败: {str(e)}")
        return False
    return True


async def create_db_tables():
    """创建数据库表"""
    print("正在创建数据库表...")
    try:
        await create_tables()
        print("✅ 数据库表创建成功")
    except Exception as e:
        print(f"❌ 创建数据库表失败: {str(e)}")
        return False
    return True


async def drop_db_tables():
    """删除数据库表"""
    print("正在删除数据库表...")
    try:
        await drop_tables()
        print("✅ 数据库表删除成功")
    except Exception as e:
        print(f"❌ 删除数据库表失败: {str(e)}")
        return False
    return True


async def reset_db():
    """重置数据库"""
    print("正在重置数据库...")
    try:
        await reset_database()
        print("✅ 数据库重置成功")
    except Exception as e:
        print(f"❌ 数据库重置失败: {str(e)}")
        return False
    return True


async def check_db():
    """检查数据库连接"""
    print("正在检查数据库连接...")
    try:
        is_connected = await check_database_connection()
        if is_connected:
            print("✅ 数据库连接正常")
        else:
            print("❌ 数据库连接失败")
        return is_connected
    except Exception as e:
        print(f"❌ 检查数据库连接时出错: {str(e)}")
        return False


def show_db_info():
    """显示数据库配置信息"""
    print("数据库配置信息:")
    print(f"  环境: {settings.environment}")
    print(f"  数据库URL: {settings.get_database_url()}")
    if settings.environment == "development":
        print(f"  SQLite文件: {settings.sqlite_file}")
    else:
        print(f"  PostgreSQL主机: {settings.postgres_host}")
        print(f"  PostgreSQL端口: {settings.postgres_port}")
        print(f"  PostgreSQL数据库: {settings.postgres_db}")


def create_alembic_migration():
    """创建Alembic迁移"""
    import subprocess
    
    print("正在创建Alembic迁移...")
    try:
        # 检查是否已经有迁移文件
        versions_dir = Path("alembic/versions")
        if not versions_dir.exists():
            versions_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建初始迁移
        result = subprocess.run([
            sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", "Initial migration"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Alembic迁移创建成功")
            print(result.stdout)
        else:
            print("❌ 创建Alembic迁移失败")
            print(result.stderr)
    except Exception as e:
        print(f"❌ 创建迁移时出错: {str(e)}")


def run_alembic_migration():
    """运行Alembic迁移"""
    import subprocess
    
    print("正在运行Alembic迁移...")
    try:
        result = subprocess.run([
            sys.executable, "-m", "alembic", "upgrade", "head"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Alembic迁移运行成功")
            print(result.stdout)
        else:
            print("❌ 运行Alembic迁移失败")
            print(result.stderr)
    except Exception as e:
        print(f"❌ 运行迁移时出错: {str(e)}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="数据库管理工具")
    parser.add_argument("command", choices=[
        "init", "create", "drop", "reset", "check", "info", 
        "make-migration", "migrate", "setup"
    ], help="要执行的命令")
    
    args = parser.parse_args()
    
    if args.command == "info":
        show_db_info()
        return
    
    if args.command == "make-migration":
        create_alembic_migration()
        return
    
    if args.command == "migrate":
        run_alembic_migration()
        return
    
    if args.command == "setup":
        # 完整设置流程
        print("🚀 开始完整数据库设置...")
        show_db_info()
        
        success = await init_db()
        if not success:
            return
        
        success = await check_db()
        if not success:
            return
        
        print("🎉 数据库设置完成！")
        return
    
    # 其他需要数据库连接的命令
    try:
        if args.command == "init":
            await init_db()
        elif args.command == "create":
            await create_db_tables()
        elif args.command == "drop":
            confirm = input("确定要删除所有数据库表吗？输入 'yes' 确认: ")
            if confirm.lower() == "yes":
                await drop_db_tables()
            else:
                print("操作已取消")
        elif args.command == "reset":
            confirm = input("确定要重置数据库吗？这将删除所有数据！输入 'yes' 确认: ")
            if confirm.lower() == "yes":
                await reset_db()
            else:
                print("操作已取消")
        elif args.command == "check":
            await check_db()
    
    except KeyboardInterrupt:
        print("\n操作已中断")
    except Exception as e:
        print(f"❌ 执行命令时出错: {str(e)}")


if __name__ == "__main__":
    asyncio.run(main())
