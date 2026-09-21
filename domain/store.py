"""内存仓库：按类型分表，提供基础查询与事件日志。

保持无外部依赖，方便单测与联调；接口层每个请求新建或复用同一 Store。
"""

from collections import defaultdict

from .errors import ConflictError, NotFoundError


class Store:
    def __init__(self):
        self.tables = defaultdict(dict)   # 类型 -> {id: record}
        self.indexes = defaultdict(lambda: defaultdict(list))  # (类型, 字段) -> 值 -> [id]
        self.events = []                  # 追加式领域事件日志

    # ── 基本存取 ───────────────────────────────────────────────────

    def add(self, rec, *, replace=False):
        table = self.tables[rec["类型"]]
        if rec["id"] in table and not replace:
            raise ConflictError(
                f"{rec['类型']} {rec['id']} 已存在",
                details={"id": rec["id"], "类型": rec["类型"]},
            )
        table[rec["id"]] = rec
        return rec

    def get(self, kind, rid):
        rec = self.tables.get(kind, {}).get(rid)
        if rec is None:
            raise NotFoundError(f"{kind} {rid} 不存在", details={"id": rid, "类型": kind})
        return rec

    def find(self, kind, rid):
        return self.tables.get(kind, {}).get(rid)

    def list(self, kind):
        return list(self.tables.get(kind, {}).values())

    def query(self, kind, **fields):
        out = []
        for rec in self.list(kind):
            if all(rec.get(k) == v for k, v in fields.items()):
                out.append(rec)
        return out

    # ── 事件日志 ───────────────────────────────────────────────────

    def log(self, event_type, **payload):
        event = {"seq": len(self.events) + 1, "事件": event_type}
        event.update(payload)
        self.events.append(event)
        return event

    # ── 整库快照（用于看板与排障）──────────────────────────────────

    def snapshot(self):
        return {kind: list(rows.values()) for kind, rows in self.tables.items()}
