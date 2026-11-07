# 书童 Web API

字段级的定义以运行中的 `/api/openapi.json`（交互文档 `/api/docs`）为准，本文只讲整体约定。

## 启动

```bash
cd backend
uv run shutong --data <数据目录> serve --host 0.0.0.0 --port 8080 [--web ../web/dist]
```

- 数据库在 `<数据目录>/shutong.db`；启动时会先恢复中断的入库
- 界面：默认使用仓库里的 `web/dist`（或 `--web` / 环境变量 `SHUTONG_WEB` 指定的目录），同一个端口同时提供；没有匹配到文件的路径都返回 `index.html`
- 前端的 TypeScript 类型由 `python -m shutong.api.export` 导出的 OpenAPI 生成（`web/src/api/schema.d.ts`），CI 会检查两边是否一致

## 登录

单用户、密码登录：

| 接口 | 说明 |
|---|---|
| `GET /api/auth/status` | `{"configured", "logged_in"}`：是否已设置密码、当前是否已登录 |
| `POST /api/auth/setup {"password"}` | 只在还没设置密码时可用，至少 8 位；成功即登录 |
| `POST /api/auth/login {"password"}` | 密码错误返回 401「密码错误」 |
| `POST /api/auth/logout` | 退出登录 |
| `POST /api/auth/password {"old", "new"}` | 修改密码 |

登录后服务端下发 `HttpOnly` 的 `shutong_session` cookie，有效期 30 天。除 `/api/auth/*` 和 `/api/openapi.json` 外，未登录访问任何 `/api` 接口都返回 `401 {"detail": "未登录"}`。

## 错误

错误响应统一是 `{"detail": "中文说明"}`；参数校验失败是 422，资源不存在 404，状态冲突 409，Bangumi 不可用 503。

## 后台任务

扫描、执行、复核确认、重新整理、重试都是长操作，接口立即返回 `{"job_id"}`，在后台按提交顺序一个一个执行：

- `GET /api/jobs/{id}`：`state` 为 `queued` / `running` / `done` / `failed`；`result` 是各操作的计数；失败时 `error` 是中文原因（库目录掉线时以「库目录不可用」开头）
- `GET /api/jobs`：最近的任务
- 任务列表只保存在内存里，重启后清空；任务改动的条目和扫描记录都在数据库里

### 进度推送

`WS /api/ws`（需要已登录的 cookie，否则以 4401 关闭）。每次任务状态变化推送一条：

```json
{"type": "job", "job": {"id": 3, "kind": "scan", "library_id": 1, "state": "done", "result": {...}, "error": null, "created_at": "...", "finished_at": "..."}}
```

前端收到 `done` / `failed` 后重新拉取相关列表即可。

## 资源一览

| 资源 | 主要接口 |
|---|---|
| 库 | `GET/POST /api/libraries`、`GET/PATCH /api/libraries/{id}`、`POST /api/libraries/{id}/scan`、`GET /api/libraries/{id}/runs`、`GET /api/libraries/{id}/summary`、`POST /api/libraries/{id}/template-preview` |
| 条目（预览 / 历史） | `GET /api/items`（按库、状态、复核原因、关键词筛选，分页）、`GET /api/items/{id}`（含事件时间线和 AI 记录）、`POST /api/items/execute`、`POST /api/items/retry`、`POST /api/items/reorganize`、`POST /api/items/cancel` |
| 复核 | `GET /api/review/groups`（按来源目录分组）、`POST /api/review/confirm`、`POST /api/review/reidentify` |
| 元数据 | `GET /api/metadata/search?q=&kind=`、`GET /api/metadata/subjects/{id}` |
| 设置 | `GET/PATCH /api/settings`、`POST /api/settings/ai-test` |
| AI 记录 | `GET /api/ai/calls` |
| 媒体服务器 | `GET/POST /api/servers`、`PATCH/DELETE /api/servers/{id}`、`POST /api/servers/{id}/test`（返回连接结果和媒体服务器的库列表；库 id 一律是字符串） |
| 上传 | `POST /api/libraries/{id}/upload`（`multipart/form-data`，多个 `files`） |

### 复核确认会做什么

`POST /api/review/confirm` 把选定的系列名 / 版本 / Bangumi 条目和按条目指定的卷号（`volumes`：`13`、`1.5`、`01-05`、`SP1`）记在这些条目上（`overrides`），以后重新识别也沿用；然后重新规划，规划好的直接入库。

### 识别

扫描和重新识别都要先配置 AI，没配时接口返回 409。同一来源目录的文件名每批最多 60 个一起交给 AI，AI 返回系列名、版本、用来搜 Bangumi 的其他名称（原文名等）以及每个文件的卷号 / 话号 / 番外序号和把握程度。把握低于 `ai.threshold`（默认 0.85，最低 0.8）的进复核；AI 连不上的条目停在「待识别」，下次扫描再试。

### 重新整理会做什么

`POST /api/items/reorganize` 只处理已整理的条目：先直接删除库里的旧文件（不可恢复），再按新的选择重新规划并入库。来源文件已经不在或变了的条目会跳过，旧文件保留。

### 媒体服务器联动（Kavita / Komga）

库可以关联一个媒体服务器和它的库 id（`PATCH /api/libraries/{id} {"server_id", "server_library_id"}`）。每次任务整理进了新文件后，同一个服务器库只扫描一次；重新整理过的系列再刷新（Kavita 文件名不变时不会换封面；Komga 扫描时会自己更新，再刷新一次系列元数据）。通知结果在任务 `result.kavita` 里：`{"scanned": [...], "refreshed": [...], "errors": [...]}`；服务器连不上或密码错误只记进 `errors`，不影响已整理的文件和任务状态。

### 上传

文件名可以带相对路径（浏览器拖入文件夹时用 `webkitRelativePath`），按这个路径放进库的来源目录：`迷宫饭/Vol.01.zip` → `<来源>/迷宫饭/Vol.01.zip`。同名文件自动改成 `Vol.01-1.zip`，绝不覆盖；带 `..`、绝对路径或 `.shutong` 的路径返回 422。上传不会自动扫描，上传完再调 `POST /api/libraries/{id}/scan`。

### 密钥

`ai.api_key`、`bangumi.token` 和媒体服务器密码读取时只返回「已设置」或空字符串；提交表单时原样回传「已设置」表示不修改。登录相关的 `auth.*` 不能通过设置接口读写。
