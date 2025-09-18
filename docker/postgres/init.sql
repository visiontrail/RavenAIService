-- PostgreSQL数据库初始化脚本

-- 创建数据库（如果不存在）
-- CREATE DATABASE logstagingservice;

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- 设置时区
SET timezone = 'Asia/Shanghai';

-- 创建索引优化查询性能
-- 这些索引将在Alembic迁移中创建，这里仅作为参考

-- 性能优化设置
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
ALTER SYSTEM SET log_statement = 'all';
ALTER SYSTEM SET log_duration = on;
ALTER SYSTEM SET log_min_duration_statement = 1000;

-- 重新加载配置
SELECT pg_reload_conf();