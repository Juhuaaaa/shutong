# 部署书童（Docker）

书童的 Docker 镜像同时提供 Web 界面和 API，一个容器、一个端口（8899）。数据库在容器的 `/config`，媒体目录由你挂载。

## 挂载原则

- **来源、媒体库、原档目录放在同一个挂载里。** 整理时的「移动」只有在同一个文件系统内才是瞬间完成的重命名；跨挂载会变成复制再删除，大文件慢，还要两份空间
- `/config` 必须持久化（数据库和设置都在这里）；删掉容器重建不丢数据
- 库设置成「整理后删除原档」或重新整理替换旧文件时，文件是直接删除的，没有回收站

## docker compose

```yaml
services:
  shutong:
    image: ah4o/shutong:latest   # 或自己构建的 shutong:latest
    container_name: shutong
    restart: unless-stopped
    ports:
      - "8899:8899"
    environment:
      - TZ=Asia/Shanghai
      # - PUID=1000      # 可选：不用 root 运行
      # - PGID=1000
    volumes:
      - ./config:/config
      - /path/to/media:/data
```

`docker compose up -d` 后打开 `http://<NAS 地址>:8899`，第一次会让你设置登录密码。然后在「库」里新建库，目录填容器里的路径（例如 `/data/downloads/manga`、`/data/manga/漫画`）。

### 用户与权限

- 默认以 root 运行：很多 NAS 上的媒体文件属于 root，这样读写最省事
- 设置 `PUID` / `PGID` 后以该用户运行，`/config` 会自动改成这个用户所有；媒体目录需要你自己保证该用户可读写

## 访问元数据源需要代理时

书童用 Python 标准库请求 Bangumi、AniList 和 AI 接口，认标准的代理环境变量：

```yaml
    environment:
      - HTTPS_PROXY=http://<代理地址>:<端口>
      - NO_PROXY=<NAS 地址>,localhost,127.0.0.1    # 连 Kavita、Komga 等局域网服务不走代理
```

连不上元数据源时，新来源会停在「元数据待重试」，不会被误判成「没有匹配」；代理配好后在历史里对这些条目「重试」即可。

## 联动 Kavita 或 Komga

在「设置 → 媒体服务器」里添加，再在库设置里选对应的服务器库。整理进新文件后，书童会通知服务器扫描。Komga 用邮箱和密码登录。

Komga 默认会把卷号拼进系列名，比如显示成「书名 (3)」。建议在 Komga 的库设置里关掉「在系列标题中添加卷号」（Append volume to series title）。

## 群晖 / 其他 Docker

和上面一样，把共享文件夹（例如 `/volume1/media`）挂到 `/data`。群晖的文件通常属于某个普通用户，建议设置 `PUID` / `PGID` 为该用户（`id <用户名>` 可以查到）。

## 自己构建镜像

在仓库根目录：

```bash
docker build -f docker/Dockerfile -t shutong:latest .
docker/smoke.sh shutong:latest   # 可选：冒烟测试
```

NAS 是 x86_64 时直接在 NAS 上构建最快，不需要镜像仓库。国内网络可以加 `--build-arg NPM_REGISTRY=https://registry.npmmirror.com`（前端依赖走国内源）和 `--build-arg PYPI_INDEX=…`（后端依赖走国内源）。构建只从 Docker Hub 拉基础镜像，所以 Docker 配置的镜像加速对它有效。

## 镜像

Docker Hub：`ah4o/shutong`，支持 amd64 和 arm64。`latest` 是最新发布版，也可以写具体版本号。

## 升级

```bash
docker compose pull      # 或重新构建
docker compose up -d
```

数据都在 `/config`，升级不会丢；数据库结构会在启动时自动迁移。
