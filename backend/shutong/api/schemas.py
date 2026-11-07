"""Response models: the OpenAPI schema generated from these is the contract with the web UI."""
from typing import Dict, List, Optional

from pydantic import BaseModel


class JobRef(BaseModel):
    job_id: int


class LibraryOut(BaseModel):
    id: int
    name: str
    kind: str
    source_dir: str
    library_dir: str
    naming_template: str
    source_policy: str
    archive_dir: Optional[str]
    pdf_to_cbz: bool
    include_edition: bool
    overwrite_policy: str
    rename_files: bool
    available: bool
    server_id: Optional[int]
    server_library_id: Optional[str]
    watch: bool


class RunOut(BaseModel):
    id: int
    trigger: str
    started_at: str
    finished_at: Optional[str]
    counts: Dict[str, int]


class Summary(BaseModel):
    counts: Dict[str, int]


class TemplateExample(BaseModel):
    source: str
    target: str


class TemplatePreview(BaseModel):
    examples: List[TemplateExample]


class ItemOut(BaseModel):
    id: int
    library_id: int
    status: str
    review_reason: Optional[str]
    source_path: str
    source_name: str
    parsed: dict
    subject_id: Optional[str]
    target_path: Optional[str]
    plan: dict
    error: Optional[str]
    overrides: dict
    updated_at: str


class ItemPage(BaseModel):
    items: List[ItemOut]
    total: int


class HistoryGroup(BaseModel):
    library_id: int
    group_key: str
    folder: str
    series: Optional[str]
    subject_id: Optional[int]
    counts: Dict[str, int]
    total: int
    updated_at: str
    item_ids: List[int]
    missing_metadata: int = 0


class HistoryPage(BaseModel):
    groups: List[HistoryGroup]
    total: int


class EventOut(BaseModel):
    at: str
    kind: str
    detail: dict


class AiCallOut(BaseModel):
    id: int
    item_id: Optional[int]
    purpose: str
    model: str
    response_text: Optional[str]
    error: Optional[str]
    duration_ms: int
    adopted: bool
    created_at: str


class ItemDetail(ItemOut):
    events: List[EventOut]
    ai_calls: List[AiCallOut]


class CancelResult(BaseModel):
    cancelled: int
    skipped: int


def item_out(item) -> dict:
    return {
        "id": item.id, "library_id": item.library_id, "status": item.status.value,
        "review_reason": item.review_reason.value if item.review_reason else None,
        "source_path": str(item.source_path), "source_name": item.source_path.name, "parsed": item.parsed,
        "subject_id": item.subject_id,
        "target_path": item.target_path.as_posix() if item.target_path is not None else None,
        "plan": item.plan, "error": item.error, "overrides": item.overrides or {}, "updated_at": item.updated_at,
    }


def ai_call_out(call) -> dict:
    return {"id": call.id, "item_id": call.item_id, "purpose": call.purpose, "model": call.model,
            "response_text": call.response_text, "error": call.error, "duration_ms": call.duration_ms,
            "adopted": call.adopted, "created_at": call.created_at}


class ReviewGroup(BaseModel):
    key: str
    library_id: int
    folder: str
    reasons: List[str]
    title_hint: str
    edition: Optional[str]
    count: int
    item_ids: List[int]
    sample_names: List[str]
    candidates: List[int]
    ai_suggestion: Optional[dict]


class SubjectOut(BaseModel):
    subject_id: int
    name: str
    name_cn: str
    summary: str
    writers: List[str]
    publisher: str
    platform: str
    release_date: Optional[str]
    total_volumes: Optional[int]
    image: Optional[str]


def subject_out(subject) -> dict:
    return {"subject_id": subject.subject_id, "name": subject.name, "name_cn": subject.name_cn,
            "summary": subject.summary, "writers": list(subject.writers), "publisher": subject.publisher,
            "platform": subject.platform, "release_date": subject.release_date,
            "total_volumes": subject.total_volumes,
            "image": "https://api.bgm.tv/v0/subjects/{0}/image?type=common".format(subject.subject_id)
            if subject.source == "bangumi" else None}


class AiTestResult(BaseModel):
    ok: bool
    error: Optional[str]


class ProxyTestIn(BaseModel):
    proxy: Optional[str] = None


class ProxyTestResult(BaseModel):
    ok: bool
    error: Optional[str]
    elapsed_ms: int


class ServerOut(BaseModel):
    id: int
    kind: str
    name: str
    base_url: str
    username: str
    password: str  # "已设置" or ""
    enabled: bool


class ServerLibraryOut(BaseModel):
    id: str
    name: str


class ServerTestOut(BaseModel):
    ok: bool
    error: Optional[str]
    libraries: List[ServerLibraryOut]


class SavedFile(BaseModel):
    name: str
    path: str


class UploadResult(BaseModel):
    saved: List[SavedFile]
    skipped: List[str]  # hidden files such as .DS_Store
