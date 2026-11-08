# 书童（Shutong）

把电脑上乱七八糟的漫画和轻小说拖进窗口，书童会用 AI 认出书名和卷号，到 Bangumi（也可以加上 AniList）查资料，整理成整齐的库。

- 支持漫画的 zip、cbz、rar、cbr、7z、cb7、pdf 和图片文件夹，轻小说的 epub
- 原文件默认留在原处，确认没问题后再由你决定是否移进回收站
- 不需要 NAS 或媒体服务器

**需要准备：** 一个兼容 OpenAI 的 AI 接口（自己申请，会产生少量费用）。没有它就不能整理。

## Docker 部署（NAS）

```yaml
services:
  shutong:
    image: ah4o/shutong:latest
    container_name: shutong
    restart: unless-stopped
    ports:
      - "8899:8899"
    environment:
      - TZ=Asia/Shanghai
    volumes:
      - ./config:/config
      - /path/to/media:/data
```

运行 `docker compose up -d` 后打开 `http://<NAS 地址>:8899`，第一次会让你设置登录密码。然后在「设置 → AI」配好接口，在「库」里新建库，目录填容器里的路径，例如 `/data/manga`。

来源、媒体库和原档目录要放在同一个挂载里，否则移动文件会变成复制再删除。代理、权限和升级见[完整部署说明](docs/deploy.md)。

## 桌面版下载

到 [Releases](https://github.com/Juhuaaaa/shutong/releases/latest) 下载：

| 你的电脑 | 下载 |
|---|---|
| Windows 10 或更新 | `Shutong-版本号-win-x64.exe` |
| Mac，M 系列芯片，macOS 13 或更新 | `Shutong-版本号-mac-arm64.dmg` |
| Mac，Intel 芯片，macOS 13 或更新 | `Shutong-版本号-mac-x64.dmg`（**未在真机上实测**，只通过了自动测试，遇到问题欢迎反馈） |

不确定 Mac 是哪种芯片：点屏幕左上角苹果图标 →「关于本机」，看「芯片」或「处理器」那一行。

## 为什么会弹安全警告

书童没有购买苹果和微软的开发者证书，系统认不出发布者，所以第一次打开时会警告。**这不代表文件有问题**，但也说明系统无法替你确认来源，所以请只从这个页面下载。想再确认一下的话，可以[核对校验值](#核对校验值)。

## macOS 安装

1. 打开 dmg，把 `shutong` 拖进「应用程序」文件夹。
2. 在「应用程序」里双击 `shutong`。系统提示无法验证，点「完成」关掉提示。
3. 打开「系统设置 → 隐私与安全性」，滚动到「安全性」一栏，点 `shutong` 旁边的「仍要打开」。下图是英文系统，按钮显示为 `Open Anyway`：

   ![点仍要打开](docs/images/mac-open-anyway.png)

4. 系统会再弹一个确认窗口，点中间的「仍要打开」（`Open Anyway`），然后输入开机密码或用 Touch ID。**最上面蓝色的按钮是移到废纸篓，不要点错：**

   <img src="docs/images/mac-confirm.png" width="260" alt="确认窗口：点中间的仍要打开">

5. 之后就可以正常打开了。**安装新版本后，要再做一次第 2 到 4 步。**

## Windows 安装

1. 双击下载的 exe。出现「Windows 已保护你的电脑」时，先点「更多信息」：

   ![点更多信息](docs/images/win-smartscreen-1.png)

2. 核对应用名是 `Shutong-版本号-win-x64.exe`，发布者显示「发布者未知」是正常的，点「仍要运行」：

   ![点仍要运行](docs/images/win-smartscreen-2.png)

3. 在安装程序里选「仅为我安装」，一路点下一步。这个选项不需要管理员权限。

**杀毒软件报毒或删除文件：** 这类没有证书、由 Python 打包的程序偶尔会被误报。先[核对校验值](#核对校验值)，一致的话把 shutong 的安装目录加入杀毒软件的信任列表。

## 第一次使用

![首次向导](docs/images/welcome.png)

1. **选库目录：** 整理好的文件放在这里，默认在「文档/书童库」。
2. **配置 AI：** 填接口地址、API Key 和模型名，保存后测试连接。
   **文件名、目录名，以及 EPUB 里的书名和作者会发给你配置的 AI 服务商；文件内容不会发送。**
3. **元数据源：** 可以跳过。默认只用 Bangumi；想补上 Bangumi 没有的作品，可以在这里或「设置 → 元数据」里打开 AniList 并排好顺序。AniList 按日文或英文原名查找，简介是英文。
4. 把文件或文件夹拖进窗口，选放进漫画库还是轻小说库。

AI 有把握的会直接入库；没把握的会放进「复核」，等你确认。整理后，原文件仍然留在原处，所以**硬盘要有足够空间放下另一份**。

## 命名模板

整理后的文件放在哪、叫什么，由「库 → 命名 → 命名模板」决定。留空就用默认模板：

```
{series}/{series} {volume}{ext}      →  迷宫饭/迷宫饭 Vol.01.cbz
```

默认不带版本，同一部作品的不同版本（如东立版、bili 版）放在同一个系列里。可用变量：

| 变量 | 含义 | 例子 |
|------|------|------|
| `{series}` | 系列名 | 迷宫饭 |
| `{edition}` | 版本（只有漫画有） | bili电子版 |
| `{author}` | 作者（取第一位；查不到时是「未知作者」） | 九井谅子 |
| `{volume}` | 卷号 | Vol.01 |
| `{year}` | 出版年份 | 2014 |
| `{title}` | AI 认出的书名 | 迷宫饭 |
| `{bgm}` | Bangumi 条目编号 | 133315 |
| `{ext}` | 扩展名，模板必须以它结尾 | .cbz |

- `/` 分隔目录层级。
- `{变量:格式}` 只在变量有值时输出格式，`%s` 换成变量的值；没有值时整段省略。

常用写法：

```
{series}{edition:[%s]}/{series}{edition:[%s]} {volume}{ext}   →  迷宫饭[bili电子版]/迷宫饭[bili电子版] Vol.01.cbz
{author}/{series}/{series} {volume}{ext}                        →  九井谅子/迷宫饭/迷宫饭 Vol.01.cbz
{series}{year: (%s)}/{series} {volume}{ext}                     →  迷宫饭 (2014)/迷宫饭 Vol.01.cbz
```

模板里写了 `{edition}`，不同版本就会分成不同的系列，Kavita、Komga 里也一样。改模板只影响之后整理的文件；已经整理好的要在「历史」里重新整理才会挪过去。

## 更新

有新版本时，书童会在窗口顶部提示，点击后到这个页面下载，覆盖安装即可，数据不会丢。

## 卸载

- **macOS：** 把「应用程序」里的 `shutong` 移进废纸篓。
- **Windows：** 在「设置 → 应用」里卸载。

卸载不会删除你的库和原文件。书童自己的数据（设置、记录、日志，其中包括你的 AI 密钥）想一起清掉的话，手动删除下面的目录：

- **macOS：** `~/Library/Application Support/shutong`
- **Windows：** `%APPDATA%\shutong`

Windows 卸载后还会留下一份安装缓存（约 145 MB），可以直接删除：`%LOCALAPPDATA%\shutong-desktop-updater`。

## 核对校验值

每个版本的 Releases 里都有 `SHA256SUMS.txt`。

- **macOS 终端：** `shasum -a 256 下载的文件`
- **Windows PowerShell：** `Get-FileHash 下载的文件`

算出来的值和 `SHA256SUMS.txt` 里的一致，就说明文件和发布的是同一个。

## 遇到问题

到 [Issues](https://github.com/Juhuaaaa/shutong/issues) 提问。菜单「帮助 → 打开日志目录」里有日志，提问时请附上，但先检查有没有你不想公开的文件名。

## 开发

见[开发说明](docs/development.md)。

## 许可证

[MIT](LICENSE)
