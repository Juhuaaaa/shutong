"""Why organizing a file failed, in words a person can act on; and the checks worth making before building."""
import errno
import os
from pathlib import Path
import shutil
from typing import Iterator, Optional
import zipfile

from shutong.engine.kinds.manga.cbz import ArchiveLimits

# Room kept free on top of the source's size: the output is about as big as the source, plus a margin.
_SPARE_BYTES = 64 * 1024**2

_ERRNO = {
    errno.ENOSPC: "磁盘空间不足",
    errno.EDQUOT: "磁盘空间不足（超出配额）",
    errno.EACCES: "没有权限读写文件",
    errno.EPERM: "没有权限读写文件",
    errno.EROFS: "库目录所在的磁盘是只读的",
    errno.ENOENT: "文件或目录不见了（可能被移走，或者网络盘断开了）",
    errno.EIO: "读写硬盘出错，可能是硬盘或网络盘有问题",
    errno.ENAMETOOLONG: "文件名太长，系统不接受",
}
_STALE = getattr(errno, "ESTALE", None)
if _STALE is not None:
    _ERRNO[_STALE] = "网络盘连接已失效，请检查挂载后重试"

# Messages raised by the adapters (see kinds/manga/cbz.py, pdf.py and kinds/novel), matched by prefix.
_MESSAGES = (
    ("archive contains too many files", "压缩包里的文件太多（超过 {0} 个）".format(ArchiveLimits().max_files)),
    ("archive total size limit exceeded", "压缩包解压后太大（超过 8 GB）"),
    ("archive snapshot size limit exceeded", "压缩包解压后太大（超过 8 GB）"),
    ("archive file size limit exceeded", "压缩包里有单个文件太大（超过 512 MB）"),
    ("archive compression ratio limit exceeded", "压缩包的压缩比异常，可能是损坏或恶意文件"),
    ("archive contains no valid images", "压缩包里没有能用的图片"),
    ("unsupported archive type", "不支持这种压缩格式"),
    ("unsafe archive path", "压缩包里有不安全的路径"),
    ("archive link or special entry", "压缩包里有链接或特殊文件"),
    ("source archive changed", "整理过程中来源文件被改动了"),
    ("PDF is encrypted", "PDF 有密码保护，读不出来"),
    ("PDF has no pages", "PDF 里没有页面"),
    ("output CBZ failed verification", "生成的 CBZ 没通过校验"),
    ("output EPUB failed verification", "生成的 EPUB 没通过校验"),
    ("EPUB manifest is not Kavita-compatible", "EPUB 的目录结构 Kavita 读不了"),
    ("ComicInfo", "写入的漫画信息和计划不一致"),
)


def _chain(error: BaseException) -> Iterator[BaseException]:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def describe(error: BaseException) -> str:
    """One Chinese sentence for a failed build; unknown errors keep their own message after it."""
    for link in _chain(error):
        if isinstance(link, OSError) and link.errno in _ERRNO:
            return _ERRNO[link.errno]
        if isinstance(link, zipfile.BadZipFile) or "not a zip file" in str(link).lower():
            return "压缩包损坏，或者不是有效的压缩包"
        text = str(link)
        for prefix, sentence in _MESSAGES:
            if text.startswith(prefix):
                return sentence
    return "整理时出错：{0}".format(error) if str(error) else "整理时出错（{0}）".format(type(error).__name__)


def raw(error: BaseException) -> str:
    """The technical error, kept beside the sentence for whoever debugs it."""
    return " ← ".join("{0}: {1}".format(type(link).__name__, link) for link in _chain(error))


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for directory, _, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(directory, name)).st_size
            except OSError:
                pass
    return total


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return "{0:.0f} {1}".format(size, unit)
        size /= 1024
    return "{0:.1f} TB".format(size)


def preflight(library_dir: Path, source: Path) -> Optional[str]:
    """What would make building fail, found before spending minutes on it; None when nothing is wrong."""
    if not os.access(library_dir, os.W_OK):
        return "没有权限写入库目录"
    try:
        needed = _size(source) + _SPARE_BYTES
        free = shutil.disk_usage(library_dir)[2]
    except OSError:
        return None  # cannot tell: let the build try
    if free < needed:
        return "库所在的磁盘空间不足（还剩 {0}，大约需要 {1}）".format(_human(free), _human(needed))
    return None
