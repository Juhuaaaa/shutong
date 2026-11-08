"""A metadata source read from a JSON file: for end-to-end tests and demos without network access.

The file is a list of subjects using the same field names as ``Subject``; missing fields get defaults.
A search returns the subjects whose name or Chinese name contains the query.
"""
import json
from pathlib import Path
from typing import Tuple

from shutong.metadata.base import Subject

_DEFAULTS = {"name": "", "name_cn": "", "summary": "", "release_date": None, "writers": (), "publisher": "",
             "genres": (), "completed": False, "total_volumes": None, "platform": "漫画"}


class OfflineSource:
    name = "offline"
    label = "离线"

    def __init__(self, path: Path) -> None:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
        self.subjects = {}
        for entry in entries:
            values = dict(_DEFAULTS, **entry)
            values["writers"] = tuple(values["writers"])
            values["genres"] = tuple(values["genres"])
            values["illustrators"] = tuple(values.get("illustrators") or ())
            subject = Subject(**values)
            self.subjects[subject.subject_id] = subject

    def search(self, query: str, kind: str) -> Tuple[Subject, ...]:
        needle = query.strip().casefold()
        return tuple(subject for subject in self.subjects.values()
                     if needle and (needle in subject.name.casefold() or needle in subject.name_cn.casefold()))

    def get(self, subject_id, *, fresh: bool = False) -> Subject:
        return self.subjects[str(subject_id)]
