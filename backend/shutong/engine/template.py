"""Library naming templates: ``{series}/{series} {volume}{ext}`` with optional ``{name:fmt %s}`` parts."""
from pathlib import Path
import re
from typing import Mapping, Optional

DEFAULT_TEMPLATE = "{series}/{series} {volume}{ext}"
# The default with the edition after the title: 迷宫饭[bili电子版]/迷宫饭[bili电子版] Vol.01.cbz
EDITION_TEMPLATE = "{series}{edition:[%s]}/{series}{edition:[%s]} {volume}{ext}"
VARIABLES = frozenset({"series", "title", "edition", "author", "volume", "year", "bgm", "ext"})
UNKNOWN_AUTHOR = "未知作者"
_PLACEHOLDER = re.compile(r"\{([^{}:]+)(?::([^{}]*))?\}")


class TemplateError(ValueError):
    pass


def uses_edition(template: str) -> bool:
    """A template naming the edition makes each edition a series of its own (in folders and in Kavita)."""
    return any(match.group(1) == "edition" for match in _PLACEHOLDER.finditer(template or ""))


def validate_template(template: str) -> None:
    if not template or not template.endswith("{ext}"):
        raise TemplateError("命名模板必须以 {ext} 结尾")
    stripped = _PLACEHOLDER.sub("", template)
    if "{" in stripped or "}" in stripped:
        raise TemplateError("命名模板里的花括号不成对")
    for match in _PLACEHOLDER.finditer(template):
        name, fmt = match.group(1), match.group(2)
        if name not in VARIABLES:
            raise TemplateError("命名模板里有未知变量 {{{0}}}".format(name))
        if fmt is not None and fmt.count("%s") != 1:
            raise TemplateError("{{{0}}} 的格式里必须恰好有一个 %s".format(name))
    if any(not segment for segment in template.split("/")):
        raise TemplateError("命名模板里有空的目录层级")


def render(template: str, fields: Mapping[str, Optional[str]]) -> Path:
    validate_template(template)

    def substitute(match: "re.Match[str]") -> str:
        value = fields.get(match.group(1)) or ""
        fmt = match.group(2)
        if fmt is None:
            return value
        return fmt.replace("%s", value) if value else ""

    rendered = _PLACEHOLDER.sub(substitute, template)
    segments = rendered.split("/")
    for segment in segments:
        if not segment.strip() or "\\" in segment:
            raise TemplateError("生成的路径里有空的或非法的部分：{0!r}".format(rendered))
    return Path(*segments)
