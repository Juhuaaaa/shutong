"""The server's folders, for choosing library folders on a page that has no folder dialog (the web version)."""
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from shutong.api.auth import require_login

router = APIRouter(prefix="/api/folders", tags=["folders"], dependencies=[Depends(require_login)])


class FolderList(BaseModel):
    path: str
    parent: Optional[str]
    folders: List[str]


@router.get("", response_model=FolderList)
def folders(path: str = "/") -> FolderList:
    """The folders directly in ``path``, by name; no files, nothing hidden. Only ever lists, never changes anything."""
    folder = Path(path)
    if not folder.is_absolute():
        raise HTTPException(422, "要填完整路径，比如 /data")
    if not folder.exists():
        raise HTTPException(404, "目录不存在：{0}".format(path))
    if not folder.is_dir():
        raise HTTPException(422, "这不是目录：{0}".format(path))
    try:
        names = sorted((entry.name for entry in folder.iterdir()
                        if not entry.name.startswith(".") and entry.is_dir()), key=str.casefold)
    except OSError as error:
        raise HTTPException(403, "读不了这个目录：{0}".format(error.strerror or error))
    parent = folder.parent if folder.parent != folder else None
    return FolderList(path=str(folder), parent=str(parent) if parent is not None else None, folders=names)
