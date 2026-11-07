# 开发说明

## 目录

| 路径 | 内容 |
| --- | --- |
| `backend/shutong/engine` | 统一整理引擎：AI 识别（`ai_recognize.py`，内置提示词）、适配器（漫画 / 轻小说）、规划、发布、复核与重新整理 |
| `backend/shutong/api` | Web API（FastAPI）：登录、后台任务、各资源接口，说明见 [api.md](api.md) |
| `backend/shutong/store` | SQLite 存储与迁移 |
| `backend/shutong/metadata` | Bangumi 元数据（带缓存） |
| `backend/shutong/servers` | 媒体服务器（Kavita）：连接、发布后扫描、封面刷新 |
| `web/` | Web 界面：Vue 3 + TypeScript + Naive UI，接口类型由后端 OpenAPI 生成 |

## 开发

```bash
cd backend
uv sync
uv run python -m unittest discover -s tests -t .
uv run shutong --help
```

## 启动 Web 服务

```bash
cd backend
uv run shutong --data ~/.shutong serve --host 0.0.0.0 --port 8080
```

先构建一次界面（`cd web && pnpm install && pnpm build`），`serve` 会自动使用 `web/dist`；也可以用 `--web` 或环境变量 `SHUTONG_WEB` 指定目录。第一次打开时会引导设置密码；接口文档在 `/api/docs`。

## 部署

Docker（NAS）部署见 [deploy.md](deploy.md)：一个容器、端口 8899、数据在 `/config`。

## 前端开发

```bash
cd backend && uv run shutong --data ~/.shutong-dev serve --port 8080   # 后端
cd web && pnpm install && pnpm dev                                     # 界面，/api 代理到 8080
pnpm lint && pnpm test                                                  # 检查与单元测试
pnpm gen:api                                                            # 后端接口改了以后重新生成类型
pnpm e2e                                                                # 端到端冒烟（Playwright，离线元数据）
```
