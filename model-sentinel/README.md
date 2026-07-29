# 模型哨塔（Model Sentinel）

一套与 RavenAI 完全解耦的 7×24 小时模型服务器观测服务。它按固定周期发送中等强度的真实 Agent 推理任务，持续记录可用率、首 Token、完整耗时、Token、429、超时和服务端错误，并按小时或每天输出聚合数据。

## 能回答什么

- 此刻模型是否真的可用，而不仅是端口是否存活
- 哪些小时成功率最高、尾延迟最低，适合作为调用窗口
- 当前瓶颈更像限流、排队、网络还是服务异常
- 现有容量是否可承载，是否应扩容或增加负载均衡
- 每小时/每天的数据能否导出给容量评审使用

## 独立性与安全边界

- 所有代码都在 `model-sentinel/`，不导入 RavenAI 的任何模块
- 使用独立容器、独立 Docker 网络、独立 SQLite 数据卷
- 不读取或写入 RavenAI 数据库
- 默认只监听宿主机 `127.0.0.1:8765`
- API Key 使用数据卷中的独立 Fernet 密钥加密；后端接口永不返回 Key 明文
- 不保存完整模型回复，只记录最多 360 字的短摘要和性能元数据

## 启动

```bash
cd model-sentinel
docker compose up -d --build
```

打开 <http://127.0.0.1:8765>，进入「监控设置」填写被测模型 API Key，先执行连接测试，再保存。保存后调度器会热更新并立即开始首轮观测。

查看状态：

```bash
docker compose ps
docker compose logs -f --tail=100
```

停止服务：

```bash
docker compose down
```

以上命令不会删除历史数据。只有显式执行下面的命令才会删除独立数据卷：

```bash
docker compose down -v
```

## Raven 主力模型的初始值

默认配置已沿用当前 Raven 的非敏感主力模型设置：

| 配置 | 初始值 |
| --- | --- |
| 协议 | Anthropic Messages API |
| Base URL | `http://oneapi.yhroot.com` |
| 主模型 | `yinhe-thinking` |
| 调用周期 | 300 秒 |
| 完整超时 | 1800 秒（与 Raven 主力 Agent 一致） |
| 最大输出 | 1024 Token（为 thinking 阶段预留预算） |
| 聚合时区 | `Asia/Singapore` |

这些值只在第一次创建数据库时使用，之后以设置页为准。

## 小时/每日输出

前端结果页可以在「每小时 / 每天」之间切换，并导出 CSV。也可以直接调用：

```text
GET /api/analytics/hourly?periods=168
GET /api/analytics/daily?periods=30
GET /api/export?granularity=hourly&periods=168
GET /api/export?granularity=daily&periods=30
```

每个时间桶包含样本数、成功/失败、可用率、阈值内可用率、平均耗时、P95 完整耗时、P95 首 Token、限流、服务端异常和总 Token。

## 数据备份

数据保存在名为 `model-sentinel-data` 的 Docker 卷。可使用一次性容器导出：

```bash
docker run --rm \
  -v model-sentinel-data:/data:ro \
  -v "$PWD":/backup \
  alpine tar czf /backup/model-sentinel-backup.tgz -C /data .
```

请同时备份数据库和 `.secret-key`；后者用于解密已经保存的 API Key。

## 生产部署提示

默认回环监听适合单机使用。如果需要团队访问，请将 `MODEL_SENTINEL_BIND_IP` 改为受控地址，并在服务前增加带认证与 TLS 的反向代理。不要把设置接口直接暴露到公网。

服务使用 `restart: unless-stopped`、Docker 健康检查、SQLite WAL 和有界日志轮转，适合长期运行。建议再由宿主机监控 Docker daemon 与磁盘空间。
