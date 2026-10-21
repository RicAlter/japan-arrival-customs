"""Immutable snapshots plus a CAS head. Single local user; not an authentication server."""
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .core import Rejected, digest, validate


def check_sources(batch):
    import hashlib
    for source in batch["sources"]:
        path = Path(source["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise Rejected("源文件已变更；必须新建批次，不能沿用旧确认")


def atomic_json(path, value):
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temp = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            f.write(payload); f.flush(); os.fsync(f.fileno())
        if json.loads(temp.read_text(encoding="utf-8")) != value:
            raise Rejected("落盘重读不一致")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def folder(self, batch_id):
        if len(batch_id) != 24 or any(c not in "0123456789abcdef" for c in batch_id):
            raise Rejected("非法批次路径")
        folder = (self.root / batch_id).resolve()
        if not folder.is_relative_to(self.root):
            raise Rejected("批次目录不能通过链接逃逸输出目录")
        return folder

    def guard(self, batch):
        for s in batch["sources"]:
            source = Path(s["path"]).resolve()
            if (source.is_relative_to(self.root) or self.root.is_relative_to(source.parent)):
                raise Rejected("输出目录必须与源文件所在目录分离，且不能包含源文件")
        validate(batch)

    @contextmanager
    def lock(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ".writer.lock"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise Rejected("批次正在写入或上次异常中断，需核实锁后恢复") from exc
        try:
            os.close(fd)
            yield
        finally:
            path.unlink(missing_ok=True)

    def load(self, batch_id):
        folder = self.folder(batch_id)
        head = json.loads((folder / "head.json").read_text(encoding="utf-8"))
        filename = head["snapshot"]
        if Path(filename).name != filename or not filename.endswith(".json"):
            raise Rejected("非法快照路径")
        batch = json.loads((folder / filename).read_text(encoding="utf-8"))
        self.guard(batch)
        if batch["id"] != batch_id or digest(batch) != head["hash"]:
            raise Rejected("存储校验不一致")
        return batch

    def save(self, batch, *, expected_hash=None):
        self.guard(batch)
        check_sources(batch)
        folder = self.folder(batch["id"])
        with self.lock(folder):
            if (folder / "head.json").exists():
                current = self.load(batch["id"])
                if expected_hash != digest(current) or batch["revision"] != current["revision"] + 1:
                    raise Rejected("并发/过期写入，拒绝覆盖已保存审核")
                if batch["sources"] != current["sources"] or [r["source"] for r in batch["rows"]] != [r["source"] for r in current["rows"]]:
                    raise Rejected("同批次不能改写原始来源")
            elif expected_hash is not None or batch["revision"] != 0:
                raise Rejected("只能从零版创建新批次")
            filename = f"r{batch['revision']:06d}-{digest(batch)}.json"
            snapshot = folder / filename
            if snapshot.exists():
                # May remain after a crash before committing head; never overwrite.
                if json.loads(snapshot.read_text(encoding="utf-8")) != batch:
                    raise Rejected("快照冲突")
            else:
                atomic_json(snapshot, batch)
            atomic_json(folder / "head.json", {"snapshot": filename, "hash": digest(batch)})
            if self.load(batch["id"]) != batch:
                raise Rejected("提交后重读失败")
        return folder
