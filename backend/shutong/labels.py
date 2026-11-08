"""Chinese words for the log: engine notes and job counts are English identifiers in the data."""

NOTES = {
    "no volume number": "认不出卷号",
    "library already has this volume": "库里已经有这一卷",
    "target path is taken": "目标位置已被占用",
    "target path is taken (possibly another edition)": "目标位置已被占用（可能是另一个版本）",
    "volume repeated in this batch": "同一批里卷号重复",
    "library file already has this series and volume": "库里的文件就是这一卷，直接认领",
    "source changed after preview": "识别后来源文件变了",
    "source is gone or changed": "来源文件已不在或已变",
    "source is outside the library": "来源不在库的来源目录里",
    "target appeared before publishing": "入库前目标位置出现了文件",
    "interrupted before staging": "中断于准备阶段",
    "interrupted build discarded": "中断的整理已丢弃",
    "recovered after restart": "重启后已恢复",
    "target taken while interrupted": "中断期间目标位置被占用",
}

COUNTS = {
    "planned": "待入库", "executed": "入库", "needs_review": "复核", "review": "转入复核", "published": "已整理", "failed": "整理出错",
    "skipped": "跳过", "known": "已见过", "duplicate": "重复", "cancelled": "已取消", "parsed": "待识别",
    "ready": "就绪", "replanned": "重新规划", "deleted": "删除旧文件", "claimed": "认领", "merged_into_original": "分部并入原作",
    "matched": "已匹配", "removed": "清理", "kavita": "Kavita", "counts": "", "groups": "采纳的组",
}
HIDDEN_COUNTS = frozenset({"run_id"})


def note(text: str) -> str:
    return NOTES.get(text, text)
