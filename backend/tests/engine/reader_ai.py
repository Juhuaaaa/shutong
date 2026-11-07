"""A stand-in AI for organizer and API tests: answers ``recognize`` like a careful model would on simple names.

Folder ``迷宫饭`` + ``迷宫饭 Vol.01.zip`` → series 迷宫饭, volume 1. ``answers`` overrides what it says per
file name (or per folder for the series), and ``unsure`` lowers its confidence for those names.
A folder named ``[]…`` stands for one nobody could read: the series comes back unsure.
"""
import re

_VOLUME = re.compile(r"(?i)vol\.?\s*0*(\d+(?:\.\d+)?)(?:\s*-\s*0*(\d+))?")
_CHAPTER = re.compile(r"(?i)(?:ch\.?\s*0*(\d+(?:\.\d+)?)|第(\d+)[话話])")
_SPECIAL = re.compile(r"(?i)SP\s*0*(\d+)")
_CJK_VOLUME = re.compile(r"第\s*(\d+)\s*[卷巻]")


class ReaderAi:
    def __init__(self, answers=None, series=None, unsure=(), unsure_series=(), choose=None, choose_confidence=None):
        self.answers = dict(answers or {})  # file name -> dict of FileReading fields to override
        self.series = dict(series or {})  # folder (or file name for loose files) -> dict of series fields
        self.unsure = set(unsure)
        self.unsure_series = set(unsure_series)
        self.choose = choose  # subject id to pick in choose_subject; None: the first candidate
        self.choose_confidence = choose_confidence  # None: 0.99 for a pick, 0.1 for no pick
        self.requests = []

    def complete_json(self, purpose, system, payload, *, item_id=None):
        self.requests.append({"purpose": purpose, "payload": payload, "item_id": item_id})
        if purpose == "choose_subject":
            candidates = payload["candidates"]
            pick = self.choose if self.choose is not None else (candidates[0]["subject_id"] if candidates else None)
            pick = pick or None  # choose=0: none of the candidates
            confidence = self.choose_confidence if self.choose_confidence is not None else (0.99 if pick else 0.1)
            return {"subject_id": pick, "confidence": confidence, "reason": "测试"}, 7
        series, files = {}, []
        for name in payload["files"]:
            key = payload["folder"] or name
            if key not in series:
                entry = {"id": "s{0}".format(len(series) + 1), "title": _title(payload["folder"], name),
                         "edition": None, "search_titles": [], "confidence": 0.97, "reason": "测试"}
                if key in self.unsure_series or key.startswith("[]"):
                    entry["confidence"] = 0.3
                entry.update(self.series.get(key, {}))
                series[key] = entry
            files.append(dict(_file(name), name=name, series=series[key]["id"],
                              **({"confidence": 0.3} if name in self.unsure else {}),
                              **self.answers.get(name, {})))
        return {"series": list(series.values()), "files": files}, 7

    def purposes(self):
        return [request["purpose"] for request in self.requests]


def _title(folder, name):
    if folder:
        return folder
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", name.rsplit("/", 1)[-1])
    for pattern in (_VOLUME, _CHAPTER, _SPECIAL, _CJK_VOLUME):
        stem = pattern.sub("", stem)
    return stem.strip(" _-.") or stem


def _file(name):
    base = {"unit": "volume", "number": None, "end": None, "label": "", "confidence": 0.96}
    special = _SPECIAL.search(name)
    if special:
        return dict(base, unit="special", number=special.group(1))
    volume = _VOLUME.search(name)
    if volume:
        return dict(base, number=volume.group(1), end=volume.group(2))
    chapter = _CHAPTER.search(name)
    if chapter:
        return dict(base, unit="chapter", number=chapter.group(1) or chapter.group(2))
    volume = _CJK_VOLUME.search(name)
    if volume:
        return dict(base, number=volume.group(1))
    return dict(base, confidence=0.2)
