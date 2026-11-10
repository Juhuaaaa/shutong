"""Recognition by AI: one call reads a batch of names from one source folder.

The AI returns the series (title, edition, names to search Bangumi with) and, for every file,
its volume / chapter / special number, each with a confidence. Privacy: only names relative to
the source folder, the folder's own name and, for EPUBs, their OPF title and authors are sent.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from shutong.ai.openai_compat import AiError
from shutong.engine.ai_assist import _bounded, _safe_name, _validate_confidence
from shutong.engine.text import normalize_title, without_separators

BATCH_SIZE = 60
_SEARCH_LIMIT = 4
_KNOWN_LIMIT = 300
_UNITS = frozenset({"volume", "chapter", "special"})
_KIND_LABELS = {"manga": "漫画", "novel": "轻小说"}

SYSTEM_PROMPT = """你是漫画和轻小说文件整理助手。用户给出一个来源目录名（可能为空）和其中的文件名，你要判断它们属于哪部作品、每个文件是第几卷或第几话。

输出一个 JSON 对象，只包含 series 和 files 两个字段：
{"series": [{"id": "s1", "title": "...", "base_title": null, "edition": null, "search_titles": ["..."], "confidence": 0.95, "reason": "..."}],
 "files": [{"name": "...", "series": "s1", "unit": "volume", "number": "1", "end": null, "label": "", "confidence": 0.95}]}

series（作品）：
- title：作品的简体中文通用名（Bangumi 上的中文名）。去掉作者、汉化组、扫图组、来源网站、出版社、完结/连载、卷数范围、文件格式这类标签。
- 如果 library_series 里已经有同一部作品，title 必须与那里的写法完全一致（不含方括号里的版本部分）。
- 如果给了 settled_series，里面是同一目录前几批已经确定的作品：属于其中某一部的文件，沿用它的 title、base_title、edition 和 search_titles，写法完全一致；不属于其中任何一部的文件（一个目录放了多部作品时常见），新增一部作品，不要塞进已有的作品当番外。
- base_title：这部作品是另一部作品的分部、续篇、外传或番外集时（例如「2年级篇」「新约」「第二部」「异闻」），填原作的简体中文通用名，title 保留含分部的完整名称；独立作品填 null。
- edition：目录名或文件名明确标出的发行版本，例如 bili电子版、东立、台版、全彩版；没有就填 null。library_editions 只用来统一同一版本的写法（bilibili 和 Bili）；目录名写着「东立」「电子版」就是 东立电子版，它和库里的 东立 是两个版本，不要因为库里已有就改成已有的那个。kind 是轻小说时没有版本，一律填 null。
- search_titles：用来在 Bangumi 搜索的其他名称，例如日文原名、英文名、其他常见译名，最多 4 个，可以为空数组。
- 目录名如果只是「下载」「桌面」「Downloads」「新建文件夹」这类通用名字，不要当作书名，只看文件名。
- 一个目录通常只有一部作品，也可能放着同一系列的多部作品（正篇、续篇、外传）；目录为空时，每个文件可能属于不同作品。每部作品给一个 id。

files（每个文件一项，name 必须与给出的文件名完全一致，每个文件都要出现）：
- unit：volume 表示卷或册；chapter 表示按话发布、没有卷号的话（单话或几话合在一个文件里）；special 表示番外、特典、画集等不在正卷编号里的内容。
- number：卷号或话号，写成字符串，例如 "1"、"12.5"。special 也给一个从 1 开始的序号。
- end：一个文件里装了多卷或多话时的结束编号（例如 Vol.01-05 时 number 为 "1"、end 为 "5"；Chap.001-Chap.040 时 unit 为 chapter、number 为 "1"、end 为 "40"），否则为 null。
- label：special 的简短名称，例如 "画集"；其他情况为空字符串。
- 文件名开头有阅读顺序号、后面还有另一个话号时（番外夹在正篇中间会让两者错开），用开头的顺序号作为 number。
- 罗马数字、中文数字、「第N卷」「上/中/下」等都换算成数字；上中下分别为 1、2、3。

confidence 是 0 到 1 的把握程度。只有在确实知道答案时才给 0.9 以上；拿不准作品名或卷号时给低分，不要猜一个高分。
reason 用一句中文说明判断依据。只输出 JSON，不要输出其他内容。"""


class AiNotConfigured(RuntimeError):
    """Recognition needs an AI provider; the user has not set one up."""

    def __init__(self) -> None:
        super().__init__("请先在「设置 → AI」里配置 AI 接口，识别需要用到它")


@dataclass(frozen=True)
class SeriesReading:
    title: str
    edition: Optional[str]
    search_titles: Tuple[str, ...]
    confidence: float
    reason: str
    base_title: Optional[str] = None  # the original work, when this series is a part or spin-off of it


@dataclass(frozen=True)
class FileReading:
    unit: str  # "volume" | "chapter" | "special"
    number: Optional[Decimal]
    end: Optional[Decimal]
    label: str
    confidence: float


@dataclass(frozen=True)
class Reading:
    """What the AI said about one file; ``problem`` is set when it said nothing usable."""

    series: Optional[SeriesReading] = None
    file: Optional[FileReading] = None
    call_id: Optional[int] = None
    problem: Optional[str] = None
    retry: bool = False  # the AI could not be reached: try again later, do not send to review


def read_batch(ai, *, kind: str, folder: Optional[str], names: Sequence[str],
               facts: Mapping[str, Mapping[str, Any]] = {}, settled: Sequence[SeriesReading] = (),
               library_series: Sequence[str] = (), library_editions: Sequence[str] = (),
               item_id: Optional[int] = None) -> Dict[str, Reading]:
    """Ask about up to :data:`BATCH_SIZE` names; every name gets a :class:`Reading`, never an exception."""
    payload: Dict[str, Any] = {
        "kind": _KIND_LABELS.get(kind, kind),
        "folder": folder or "",
        "files": list(names),
        "library_series": list(library_series)[:_KNOWN_LIMIT],
        "library_editions": [] if kind == "novel" else list(library_editions)[:_KNOWN_LIMIT],
    }
    if settled:
        payload["settled_series"] = [{"title": reading.title, "edition": reading.edition, "base_title": reading.base_title,
                                      "search_titles": list(reading.search_titles)} for reading in settled]
    wanted = {name: facts[name] for name in names if facts.get(name)}
    if wanted:
        payload["file_facts"] = {name: {key: _facts_value(value) for key, value in fact.items()}
                                 for name, fact in wanted.items()}
    try:
        response, call_id = ai.complete_json("recognize", SYSTEM_PROMPT, payload, item_id=item_id)
    except AiError as error:
        if error.raw is not None and len(names) > 1:
            # A reply that is not JSON is mostly one cut off half way (long answers time out at the relay):
            # ask about each half, the answers are shorter.
            half = (len(names) + 1) // 2
            found: Dict[str, Reading] = {}
            for part in (names[:half], names[half:]):
                found.update(read_batch(ai, kind=kind, folder=folder, names=part, facts=facts, settled=settled,
                                        library_series=library_series, library_editions=library_editions,
                                        item_id=item_id))
            return found
        # No raw text: the request itself failed (network, HTTP error). With raw text: the reply was not JSON.
        retry = error.raw is None
        return {name: Reading(problem="AI 调用失败：{0}".format(error), retry=retry) for name in names}
    try:
        return _readings(response, names, call_id, kind)
    except ValueError as error:
        problem = "AI 返回的内容不符合要求：{0}".format(error)
        return {name: Reading(call_id=call_id, problem=problem) for name in names}


def batches(names: Sequence[str]) -> List[Tuple[str, ...]]:
    ordered = tuple(names)
    return [ordered[start:start + BATCH_SIZE] for start in range(0, len(ordered), BATCH_SIZE)]


def _readings(response: Any, names: Sequence[str], call_id: int, kind: str = "manga") -> Dict[str, Reading]:
    # Models often add a field of their own (a per-file "reason"): unknown fields are ignored and
    # optional ones default; only the fields the answer cannot do without are required.
    if not isinstance(response, dict):
        raise ValueError("response must be an object")
    _require_fields(response, {"series", "files"})
    if not isinstance(response["series"], list) or not isinstance(response["files"], list):
        raise ValueError("series and files must be arrays")
    series = {}
    for entry in response["series"]:
        key, reading = _series(entry, kind)
        series[key] = reading
    found: Dict[str, Reading] = {}
    for entry in response["files"]:
        if not isinstance(entry, dict):
            raise ValueError("every file must be an object")
        _require_fields(entry, {"name", "series", "unit", "confidence"})
        name = entry["name"]
        if name not in names or name in found:
            continue  # a name we did not ask about, or repeated: ignore it
        if entry["series"] not in series:
            found[name] = Reading(call_id=call_id, problem="AI 认不出这个文件属于哪部作品")
            continue
        found[name] = Reading(series=series[entry["series"]], file=_file(entry), call_id=call_id)
    missing = Reading(call_id=call_id, problem="AI 没有给出这个文件的结果")
    return {name: found.get(name, missing) for name in names}


def _named(value: Any) -> Any:
    return without_separators(value) if isinstance(value, str) else value


def _series(entry: Any, kind: str = "manga") -> Tuple[Any, SeriesReading]:
    if not isinstance(entry, dict):
        raise ValueError("every series must be an object")
    _require_fields(entry, {"id", "title", "confidence"})
    title, edition = _named(entry["title"]), None if kind == "novel" else _named(entry.get("edition"))
    if not isinstance(title, str) or not title.strip() or not _safe_name(title):
        raise ValueError("title must be a usable name")
    if edition is not None and (not isinstance(edition, str) or not edition.strip() or not _safe_name(edition)):
        raise ValueError("edition must be a usable name or null")
    titles = entry.get("search_titles") or []
    if not isinstance(titles, list) or not all(isinstance(value, str) for value in titles):
        raise ValueError("search_titles must be an array of strings")
    search = tuple(dict.fromkeys(_bounded(value.strip()) for value in titles if value.strip()))[:_SEARCH_LIMIT]
    base = _named(entry.get("base_title")) or None
    if base is not None and (not isinstance(base, str) or not base.strip() or not _safe_name(base)):
        raise ValueError("base_title must be a usable name or null")
    title = normalize_title(title)
    base = normalize_title(base) if base else None
    reading = SeriesReading(title, edition.strip() if edition else None, search,
                            _validate_confidence(entry["confidence"]), _reason(entry.get("reason")),
                            base if base != title else None)
    return entry["id"], reading


def _file(entry: Mapping[str, Any]) -> FileReading:
    unit = entry["unit"]
    if unit not in _UNITS:
        raise ValueError("unit must be volume, chapter or special")
    label = entry.get("label") if isinstance(entry.get("label"), str) else ""
    return FileReading(unit, _number(entry.get("number")), _number(entry.get("end")), label.strip(),
                       _validate_confidence(entry["confidence"]))


def _reason(value: Any) -> str:
    return _bounded(value.strip()) if isinstance(value, str) else ""


def _require_fields(entry: Mapping[str, Any], required: set) -> None:
    missing = sorted(required - set(entry))
    if missing:
        raise ValueError("missing fields: {0}".format(", ".join(missing)))


def _number(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("numbers must be strings")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise ValueError("not a number: {0}".format(value))
    if not number.is_finite() or number < 0:
        raise ValueError("not a usable number: {0}".format(value))
    return number


def _facts_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_bounded(str(part)) for part in value[:8]]
    return _bounded(str(value)) if value is not None else None
