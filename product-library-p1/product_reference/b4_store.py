"""Validated source-bundle storage for an isolated product-reference database.

The store keeps every source observation separate.  It never creates or merges
``products`` and it never writes a declaration choice, packaging conversion or
final amount.  The maintenance Skill is the only writer; the arrival Skill
opens this component with ``read_only=True``.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from .core import Rejected, now


SCHEMA_VERSION = "1"
IDENTITY_FIELDS = ("code_raw", "code_type", "japanese_name", "version", "specification")
BASIC_FIELDS = {"internal_name", "customs_name", "brand", "category", "channel", "yd"}
ORDER_FIELDS = {"order_id", "order_line_id", "supplier", "purchase_quantity", "purchase_unit", "unit_price", "currency"}
PACKAGING_FIELDS = {"packaging_original", "packaging_label", "packaging_relations"}
MATERIAL_FIELDS = {"material_original", "material_translation", "complete_composition", "material_url", "material_site"}
ALLOWED_FIELDS = set(IDENTITY_FIELDS) | BASIC_FIELDS | ORDER_FIELDS | PACKAGING_FIELDS | MATERIAL_FIELDS
ALLOWED_STATUSES = {"succeeded", "no_match", "no_data", "permission_denied", "rate_limited", "network_error", "unsupported_mapping", "partial_failure"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe_relative(name):
    path = Path(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and "\\" not in name


def identity_key(identity):
    normalized = {field: identity.get(field) if identity.get(field) not in ("", None) else None for field in IDENTITY_FIELDS}
    return sha256(canonical(normalized).encode("utf-8"))


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise Rejected("来源包JSON无法读取或格式无效：" + path.name) from exc


def verify_bundle(directory, *, allow_unselected_partial=False):
    """Verify the frozen V1 envelope, every declared file hash and every row."""
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise Rejected("来源证据包必须是目录")
    manifest_path = root / "manifest.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = _read_json(manifest_path)
    required = {"schema_version", "adapter_id", "adapter_version", "mapping_version", "source_id",
                "source_version", "authorization_reference", "files", "record_count", "status"}
    if set(manifest) != required or manifest.get("schema_version") != "product-source-bundle/1":
        raise Rejected("来源包manifest不符合冻结V1合同")
    if manifest.get("adapter_id") not in {"order", "packaging", "material"}:
        raise Rejected("来源包适配器类型无效")
    if manifest.get("status") not in ALLOWED_STATUSES:
        raise Rejected("来源包状态无效")
    files = manifest.get("files")
    if not isinstance(files, dict) or "records.jsonl" not in files or "validation_report.json" not in files:
        raise Rejected("来源包缺少记录或校验报告")
    payload = {}
    for name, expected in files.items():
        if not safe_relative(name) or not isinstance(expected, str) or len(expected) != 64:
            raise Rejected("来源包文件清单含非法路径或哈希")
        path = root / name
        if not path.is_file():
            raise Rejected("来源包声明文件缺失：" + name)
        data = path.read_bytes()
        if sha256(data) != expected:
            raise Rejected("来源包文件哈希不一致：" + name)
        payload[name] = data
    records = []
    seen = set()
    try:
        lines = payload["records.jsonl"].decode("utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            _validate_record(record, manifest, files)
            key = record["source_record_id"]
            if key in seen:
                raise Rejected("来源包记录ID重复")
            seen.add(key)
            records.append(record)
    except (UnicodeError, ValueError) as exc:
        raise Rejected("records.jsonl不是有效UTF-8 JSONL") from exc
    if len(records) != manifest.get("record_count"):
        raise Rejected("来源包记录数与manifest不一致")
    report = json.loads(payload["validation_report.json"].decode("utf-8"))
    selection = None
    if "selection.json" in payload:
        selection = json.loads(payload["selection.json"].decode("utf-8"))
        _validate_selection(selection, manifest, records, payload)
    if manifest["status"] == "partial_failure" and selection is None and not allow_unselected_partial:
        raise Rejected("partial_failure来源包须先生成可校验有效子包，禁止直接导入")
    return {"root": root, "manifest": manifest, "manifest_raw": manifest_raw, "manifest_sha256": sha256(manifest_raw),
            "records": records, "report": report, "selection": selection, "payload": payload}


def _validate_record(record, manifest, files):
    required = {"source_record_id", "identity", "provenance", "fields", "status", "review_status", "approval"}
    if not isinstance(record, dict) or set(record) != required:
        raise Rejected("来源记录字段不符合冻结V1合同")
    if record["status"] not in ALLOWED_STATUSES or record["review_status"] != "reference_only" or record["approval"] is not False:
        raise Rejected("来源记录状态或权限越界")
    identity = record["identity"]
    if not isinstance(identity, dict) or set(identity) != set(IDENTITY_FIELDS):
        raise Rejected("来源记录商品身份结构无效")
    fields = record["fields"]
    if not isinstance(fields, dict) or set(fields) - ALLOWED_FIELDS:
        raise Rejected("来源记录含冻结合同之外的字段")
    provenance = record["provenance"]
    if provenance.get("source_id") != manifest["source_id"] or provenance.get("source_version") != manifest["source_version"]:
        raise Rejected("来源记录与manifest来源身份不一致")
    for field in fields.values():
        if not isinstance(field, dict) or field.get("reference_type") not in {"historical_reference", "official_reference", "purchase_reference"}:
            raise Rejected("来源字段证据结构无效")
        evidence = field.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise Rejected("来源字段缺少逐字段证据")
        for item in evidence:
            if not isinstance(item, dict) or item.get("file") not in files or not item["file"].startswith("evidence/"):
                raise Rejected("来源字段引用未登记证据")


def _validate_selection(selection, manifest, records, payload):
    required = {"kind", "parent_manifest_sha256", "selected_status", "selected_count", "original_counts", "excluded_counts"}
    if not isinstance(selection, dict) or set(selection) != required or selection.get("kind") != "source-record-subset/1":
        raise Rejected("有效子包选择声明无效")
    if selection.get("selected_status") != "succeeded" or selection.get("selected_count") != len(records):
        raise Rejected("有效子包选择数量不一致")
    if not isinstance(selection.get("original_counts"), dict) or not isinstance(selection.get("excluded_counts"), dict):
        raise Rejected("有效子包未保留原始状态统计")
    if any(record["status"] != "succeeded" for record in records):
        raise Rejected("有效子包包含非成功记录")
    if manifest["status"] != "partial_failure":
        raise Rejected("有效子包必须继续保留partial_failure门禁状态")
    parent_raw = payload.get("parent_manifest.json")
    if parent_raw is None or sha256(parent_raw) != selection.get("parent_manifest_sha256"):
        raise Rejected("有效子包缺少可校验的父manifest")
    try:
        parent = json.loads(parent_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise Rejected("有效子包父manifest无效") from exc
    if (parent.get("status") != "partial_failure" or parent.get("adapter_id") != manifest.get("adapter_id") or
            parent.get("source_id") != manifest.get("source_id") or parent.get("source_version") != manifest.get("source_version")):
        raise Rejected("有效子包与父manifest来源不一致")
    if sum(selection["original_counts"].values()) != parent.get("record_count"):
        raise Rejected("有效子包原始状态统计与父manifest记录数不一致")
    expected_excluded = {key: value for key, value in selection["original_counts"].items() if key != "succeeded"}
    if selection["excluded_counts"] != expected_excluded:
        raise Rejected("有效子包排除统计不完整")


def rebuild_material_subset(source_directory, destination):
    """Create a hash-verifiable material subset without hiding no_data rows."""
    checked = verify_bundle(source_directory, allow_unselected_partial=True)
    manifest = checked["manifest"]
    if manifest["adapter_id"] != "material" or manifest["status"] != "partial_failure":
        raise Rejected("仅允许从partial_failure材质包生成有效子包")
    if checked["selection"] is not None:
        raise Rejected("输入已经是有效子包，拒绝重复裁剪")
    counts = Counter(record["status"] for record in checked["records"])
    selected = [record for record in checked["records"] if record["status"] == "succeeded"]
    if not selected or not counts.get("no_data"):
        raise Rejected("材质子包须同时存在成功记录和no_data统计")
    out = Path(destination).resolve()
    if out.exists():
        raise Rejected("子包输出目录已存在，拒绝覆盖")
    selection = {"kind": "source-record-subset/1", "parent_manifest_sha256": checked["manifest_sha256"],
                 "selected_status": "succeeded", "selected_count": len(selected),
                 "original_counts": dict(counts), "excluded_counts": {key: value for key, value in counts.items() if key != "succeeded"}}
    needed = {item["file"] for record in selected for field in record["fields"].values() for item in field["evidence"]}
    payload = {"records.jsonl": ("".join(canonical(record) + "\n" for record in selected)).encode("utf-8"),
               "selection.json": (canonical(selection) + "\n").encode("utf-8"),
               "parent_manifest.json": checked["manifest_raw"]}
    report = dict(checked["report"])
    report.update({"scanned": sum(counts.values()), "succeeded": len(selected), "no_data": counts["no_data"],
                   "selected_for_import": len(selected), "notice": "仅成功记录进入候选；no_data统计保留，partial_failure门禁未绕过"})
    payload["validation_report.json"] = (canonical(report) + "\n").encode("utf-8")
    for name in needed:
        payload[name] = checked["payload"][name]
    child = dict(manifest)
    child["files"] = {name: sha256(data) for name, data in sorted(payload.items())}
    child["record_count"] = len(selected)
    child["status"] = "partial_failure"
    out.mkdir(parents=True)
    for name, data in payload.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (out / "manifest.json").write_text(canonical(child) + "\n", encoding="utf-8")
    verified = verify_bundle(out)
    return {"directory": str(out), "manifest_sha256": verified["manifest_sha256"],
            "selected": len(selected), "excluded": selection["excluded_counts"], "status": child["status"]}


class SourceBundleStore:
    def __init__(self, path, *, read_only=False):
        self.path = Path(path).resolve(strict=True)
        self.read_only = read_only
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key='source_bundle_schema_version'").fetchone()
            if not row or row[0] != SCHEMA_VERSION:
                raise Rejected("来源证据库结构未初始化或版本不匹配")

    @classmethod
    def initialize(cls, path, *, backup_directory=None, new_database=False):
        target = Path(path).resolve(strict=True)
        with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as current:
            existing = current.execute("SELECT value FROM metadata WHERE key='source_bundle_schema_version'").fetchone()
        if existing:
            if existing[0] != SCHEMA_VERSION:
                raise Rejected("来源证据库结构版本不受支持")
            return cls(target)
        if not new_database:
            if backup_directory is None:
                raise Rejected("既有隔离库初始化来源结构前必须指定备份目录")
            backup_root = Path(backup_directory).resolve()
            backup_root.mkdir(parents=True, exist_ok=True)
            before = sha256(target.read_bytes())
            backup = backup_root / (target.name + ".pre-source-schema-" + before[:16] + ".backup.sqlite3")
            if not backup.exists():
                with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(backup)) as copy:
                    source.backup(copy)
                    if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise Rejected("来源结构初始化备份完整性检查失败")
        with closing(sqlite3.connect(target)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript("""
              CREATE TABLE IF NOT EXISTS source_ingest_bundles (
                sha256 TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, reference TEXT NOT NULL,
                imported_at TEXT NOT NULL, record_count INTEGER NOT NULL, original_counts_json TEXT NOT NULL,
                backup_path TEXT NOT NULL, backup_sha256 TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS source_ingest_files (
                bundle_sha256 TEXT NOT NULL REFERENCES source_ingest_bundles(sha256), relative_path TEXT NOT NULL,
                sha256 TEXT NOT NULL, content BLOB NOT NULL, PRIMARY KEY(bundle_sha256,relative_path));
              CREATE TABLE IF NOT EXISTS source_ingest_observations (
                observation_sha256 TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_record_id TEXT NOT NULL,
                adapter_id TEXT NOT NULL, identity_key TEXT NOT NULL, identity_json TEXT NOT NULL,
                fields_json TEXT NOT NULL, record_json TEXT NOT NULL, status TEXT NOT NULL,
                purchase_candidate_state TEXT, candidate_reasons_json TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS source_ingest_bundle_records (
                bundle_sha256 TEXT NOT NULL REFERENCES source_ingest_bundles(sha256),
                observation_sha256 TEXT NOT NULL REFERENCES source_ingest_observations(observation_sha256),
                PRIMARY KEY(bundle_sha256,observation_sha256));
              CREATE TABLE IF NOT EXISTS source_ingest_conflicts (
                identity_key TEXT NOT NULL, field_name TEXT NOT NULL, values_json TEXT NOT NULL,
                status TEXT NOT NULL, detected_at TEXT NOT NULL, PRIMARY KEY(identity_key,field_name));
              CREATE TABLE IF NOT EXISTS source_ingest_corrections (
                identity_key TEXT NOT NULL, field_name TEXT NOT NULL, value_json TEXT NOT NULL,
                reference TEXT NOT NULL, saved_at TEXT NOT NULL, PRIMARY KEY(identity_key,field_name));
              CREATE TABLE IF NOT EXISTS source_ingest_authorizations (
                reference TEXT PRIMARY KEY, source_ids_json TEXT NOT NULL, adapter_ids_json TEXT NOT NULL,
                confirmation_json TEXT NOT NULL, saved_at TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS ix_source_ingest_identity ON source_ingest_observations(identity_key);
              CREATE INDEX IF NOT EXISTS ix_source_ingest_record ON source_ingest_observations(source_id,source_record_id);
            """)
            conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES ('source_bundle_schema_version',?)", (SCHEMA_VERSION,))
            conn.commit()
        return cls(target)

    def _connect(self):
        if self.read_only:
            conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            conn.execute("PRAGMA query_only=ON")
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _require_writable(self):
        if self.read_only:
            raise Rejected("主Skill来源库为只读；导入、纠正和回滚仅由维护Skill执行")

    def _backup(self, directory):
        self._require_writable()
        root = Path(directory).resolve()
        root.mkdir(parents=True, exist_ok=True)
        before = sha256(self.path.read_bytes())
        target = root / (self.path.name + "." + before[:16] + ".backup.sqlite3")
        if not target.exists():
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(target)) as copy:
                source.backup(copy)
                if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise Rejected("隔离库备份完整性检查失败")
        return {"path": str(target), "sha256": sha256(target.read_bytes()), "source_sha256": before}

    def import_bundle(self, directory, *, authorization_reference, backup_directory, purchase_policy=None):
        self._require_writable()
        checked = verify_bundle(directory)
        manifest = checked["manifest"]
        if authorization_reference != manifest["authorization_reference"]:
            raise Rejected("来源授权引用与manifest不一致")
        with closing(self._connect()) as conn:
            if not authorization_reference.startswith("TEST:"):
                authorization = conn.execute("SELECT source_ids_json,adapter_ids_json FROM source_ingest_authorizations WHERE reference=?",
                                             (authorization_reference,)).fetchone()
                if (not authorization or manifest["source_id"] not in json.loads(authorization["source_ids_json"]) or
                        manifest["adapter_id"] not in json.loads(authorization["adapter_ids_json"])):
                    raise Rejected("真实来源导入授权尚未由用户确认或授权范围不匹配")
            old = conn.execute("SELECT record_count FROM source_ingest_bundles WHERE sha256=?", (checked["manifest_sha256"],)).fetchone()
        if old:
            return {"status": "unchanged_duplicate", "bundle_sha256": checked["manifest_sha256"],
                    "records": old[0], "statistics": self.statistics()}
        decisions = _purchase_decisions(checked["records"], manifest["adapter_id"], purchase_policy)
        backup = self._backup(backup_directory)
        original_counts = checked["selection"]["original_counts"] if checked["selection"] else dict(Counter(r["status"] for r in checked["records"]))
        with closing(self._connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT INTO source_ingest_bundles VALUES (?,?,?,?,?,?,?,?)",
                             (checked["manifest_sha256"], canonical(manifest), authorization_reference, now(), len(checked["records"]),
                              canonical(original_counts), backup["path"], backup["sha256"]))
                for name, data in checked["payload"].items():
                    conn.execute("INSERT INTO source_ingest_files VALUES (?,?,?,?)",
                                 (checked["manifest_sha256"], name, sha256(data), data))
                new_observations = 0
                for record in checked["records"]:
                    raw = canonical(record)
                    observation_sha = sha256(raw.encode("utf-8"))
                    decision = decisions.get(record["source_record_id"], {"state": None, "reasons": []})
                    cursor = conn.execute("INSERT OR IGNORE INTO source_ingest_observations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                          (observation_sha, manifest["source_id"], record["source_record_id"], manifest["adapter_id"],
                                           identity_key(record["identity"]), canonical(record["identity"]), canonical(record["fields"]), raw,
                                           record["status"], decision["state"], canonical(decision["reasons"])))
                    new_observations += cursor.rowcount
                    conn.execute("INSERT INTO source_ingest_bundle_records VALUES (?,?)", (checked["manifest_sha256"], observation_sha))
                self._rebuild_conflicts(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"status": "imported_candidate_only", "bundle_sha256": checked["manifest_sha256"],
                "records": len(checked["records"]), "new_observations": new_observations,
                "backup": backup, "statistics": self.statistics(), "formal_output": False}

    def record_authorization(self, confirmation):
        """Record a user-confirmed import scope; never infer it from a bundle."""
        self._require_writable()
        required = {"kind", "reference", "source_ids", "adapter_ids", "confirmed_by", "confirmed_at"}
        if (not isinstance(confirmation, dict) or set(confirmation) != required or
                confirmation.get("kind") != "explicit_user_source_import_authorization"):
            raise Rejected("真实来源授权确认结构无效")
        reference = confirmation.get("reference")
        source_ids = confirmation.get("source_ids")
        adapter_ids = confirmation.get("adapter_ids")
        if (not isinstance(reference, str) or not reference or reference.startswith("TEST:") or
                not isinstance(source_ids, list) or not source_ids or not all(isinstance(item, str) and item for item in source_ids) or
                not isinstance(adapter_ids, list) or not adapter_ids or set(adapter_ids) - {"order", "packaging", "material"} or
                not confirmation.get("confirmed_by") or not confirmation.get("confirmed_at")):
            raise Rejected("真实来源授权引用或范围无效")
        with closing(self._connect()) as conn:
            old = conn.execute("SELECT confirmation_json FROM source_ingest_authorizations WHERE reference=?", (reference,)).fetchone()
            payload = canonical(confirmation)
            if old and old[0] != payload:
                raise Rejected("同一授权引用已有不同确认内容")
            conn.execute("INSERT OR IGNORE INTO source_ingest_authorizations VALUES (?,?,?,?,?)",
                         (reference, canonical(sorted(set(source_ids))), canonical(sorted(set(adapter_ids))), payload, now()))
            conn.commit()
        return {"status": "source_authorization_recorded", "reference": reference,
                "source_ids": sorted(set(source_ids)), "adapter_ids": sorted(set(adapter_ids))}

    def _rebuild_conflicts(self, conn):
        conn.execute("DELETE FROM source_ingest_conflicts")
        corrected = {(row[0], row[1]) for row in conn.execute("SELECT identity_key,field_name FROM source_ingest_corrections")}
        grouped = defaultdict(lambda: defaultdict(set))
        for row in conn.execute("SELECT identity_key,fields_json FROM source_ingest_observations WHERE status='succeeded'"):
            for field, body in json.loads(row["fields_json"]).items():
                # Separate order lines are immutable purchase observations, not
                # competing product-master values to be collapsed or resolved.
                if field in ORDER_FIELDS:
                    continue
                value = body.get("value")
                if value not in (None, "", []):
                    grouped[row["identity_key"]][field].add(canonical(value))
        for key, fields in grouped.items():
            for field, values in fields.items():
                if len(values) > 1:
                    conn.execute("INSERT INTO source_ingest_conflicts VALUES (?,?,?,?,?)",
                                 (key, field, canonical([json.loads(value) for value in sorted(values)]),
                                  "resolved_manual" if (key, field) in corrected else "pending_review", now()))

    def record_correction(self, identity, field, value, reference):
        self._require_writable()
        if set(identity) != set(IDENTITY_FIELDS) or field not in ALLOWED_FIELDS or value in (None, "") or not reference:
            raise Rejected("人工纠正身份、字段、值或依据无效")
        key = identity_key(identity)
        with closing(self._connect()) as conn:
            if not conn.execute("SELECT 1 FROM source_ingest_observations WHERE identity_key=?", (key,)).fetchone():
                raise Rejected("人工纠正未命中精确商品身份")
            conn.execute("INSERT OR REPLACE INTO source_ingest_corrections VALUES (?,?,?,?,?)",
                         (key, field, canonical(value), reference, now()))
            conn.execute("UPDATE source_ingest_conflicts SET status='resolved_manual' WHERE identity_key=? AND field_name=?", (key, field))
            conn.commit()
        return {"status": "manual_correction_recorded", "identity_key": key, "field": field, "approval": False}

    def lookup(self, identity):
        if not isinstance(identity, dict) or set(identity) != set(IDENTITY_FIELDS):
            raise Rejected("来源查询必须提供完整身份结构；未知值显式为null")
        key = identity_key(identity)
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM source_ingest_observations WHERE identity_key=? ORDER BY source_id,source_record_id,observation_sha256", (key,)).fetchall()
            corrections = conn.execute("SELECT field_name,value_json,reference,saved_at FROM source_ingest_corrections WHERE identity_key=?", (key,)).fetchall()
        if not rows:
            return {"status": "no_match", "identity": identity, "candidates": {}, "conflicts": {}, "records": [], "automatic_approval": False}
        values = defaultdict(dict)
        records = []
        for row in rows:
            fields = json.loads(row["fields_json"])
            for field, body in fields.items():
                if field in ORDER_FIELDS:
                    continue
                value = body.get("value")
                if value not in (None, "", []):
                    values[field][canonical(value)] = value
            records.append({"source_id": row["source_id"], "source_record_id": row["source_record_id"],
                            "adapter_id": row["adapter_id"], "status": row["status"],
                            "purchase_reference": {field: body.get("value") for field, body in fields.items()
                                                   if field in ORDER_FIELDS and body.get("value") not in (None, "")},
                            "purchase_candidate_state": row["purchase_candidate_state"],
                            "candidate_reasons": json.loads(row["candidate_reasons_json"])})
        candidates, conflicts, resolution = {}, {}, {}
        for field, variants in values.items():
            if len(variants) == 1:
                candidates[field] = next(iter(variants.values()))
            else:
                conflicts[field] = list(variants.values())
        for correction in corrections:
            field = correction["field_name"]
            candidates[field] = json.loads(correction["value_json"])
            conflicts.pop(field, None)
            resolution[field] = {"kind": "manual_correction", "reference": correction["reference"]}
        return {"status": "matched_with_conflict" if conflicts else "matched_reference_only", "identity": identity,
                "candidates": candidates, "conflicts": conflicts, "resolution": resolution, "records": records,
                "automatic_approval": False, "packaging_conversion_approved": False, "final_amount_generated": False}

    def statistics(self):
        with closing(self._connect()) as conn:
            scalar = lambda sql: conn.execute(sql).fetchone()[0]
            by_adapter = {row[0]: row[1] for row in conn.execute("SELECT adapter_id,COUNT(*) FROM source_ingest_observations GROUP BY adapter_id")}
            purchase = {row[0] or "not_applicable": row[1] for row in conn.execute("SELECT purchase_candidate_state,COUNT(*) FROM source_ingest_observations GROUP BY purchase_candidate_state")}
            original = Counter()
            for row in conn.execute("SELECT original_counts_json FROM source_ingest_bundles"):
                original.update(json.loads(row[0]))
            return {"database": str(self.path), "bundles": scalar("SELECT COUNT(*) FROM source_ingest_bundles"),
                    "observations": scalar("SELECT COUNT(*) FROM source_ingest_observations"),
                    "bundle_record_links": scalar("SELECT COUNT(*) FROM source_ingest_bundle_records"),
                    "conflicts": scalar("SELECT COUNT(*) FROM source_ingest_conflicts"),
                    "pending_conflicts": scalar("SELECT COUNT(*) FROM source_ingest_conflicts WHERE status='pending_review'"),
                    "manual_corrections": scalar("SELECT COUNT(*) FROM source_ingest_corrections"),
                    "source_authorizations": scalar("SELECT COUNT(*) FROM source_ingest_authorizations"),
                    "observations_by_adapter": by_adapter, "purchase_candidate_states": purchase,
                    "original_status_counts": dict(original), "declaration_decisions_stored": False}

    def rollback(self, backup_path, expected_sha256, *, safety_backup_directory):
        self._require_writable()
        source = Path(backup_path).resolve(strict=True)
        if sha256(source.read_bytes()) != expected_sha256:
            raise Rejected("回滚备份哈希不一致")
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as check:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise Rejected("回滚备份完整性检查失败")
        safety = self._backup(safety_backup_directory)
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as old, closing(sqlite3.connect(self.path)) as current:
            old.backup(current)
            if current.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise Rejected("回滚后的隔离库完整性检查失败")
        return {"status": "rolled_back", "restored_sha256": expected_sha256, "safety_backup": safety}


def _purchase_decisions(records, adapter_id, policy):
    if adapter_id != "order":
        if policy is not None:
            raise Rejected("非订单包不能携带采购有效性策略")
        return {}
    # An opening/master-data export may legitimately contain only a reference
    # price.  It is not an order line unless an order id or purchase quantity
    # is present, so do not require a purchase-effectiveness decision for it.
    purchase_records = [record for record in records if any(
        record["fields"].get(field, {}).get("value") not in (None, "")
        for field in ("order_id", "order_line_id", "purchase_quantity")
    )]
    if not purchase_records:
        if policy is not None:
            raise Rejected("无采购字段的开订基础资料包不能携带采购有效性策略")
        return {}
    if not isinstance(policy, dict) or policy.get("kind") != "purchase-candidate-policy/1" or policy.get("approval") is not False:
        raise Rejected("订单包必须提供逐来源行的待确认采购候选策略")
    decisions = policy.get("records")
    if not isinstance(decisions, dict) or set(decisions) != {record["source_record_id"] for record in purchase_records}:
        raise Rejected("采购候选策略必须逐行覆盖全部含采购字段的原始订单")
    output = {}
    for record_id, decision in decisions.items():
        if not isinstance(decision, dict) or set(decision) != {"state", "reasons"}:
            raise Rejected("采购候选策略结构无效")
        if decision["state"] not in {"pending_effective", "excluded"} or not isinstance(decision["reasons"], list):
            raise Rejected("采购候选状态无效")
        if decision["state"] == "excluded" and not decision["reasons"]:
            raise Rejected("排除的采购行必须保留原因")
        output[record_id] = decision
    return output


def apply_source_candidates(batch, database_path):
    """Read-only, exact-identity reuse for the arrival Skill."""
    store = SourceBundleStore(database_path, read_only=True)
    matched = prefilled = manual = 0
    reason_counts = Counter()
    for row in batch["rows"]:
        incoming = row["identity"]
        # The raw KMT importer labels a source identifier more narrowly as
        # ``raw_source_identifier``.  It is the same identifier namespace as
        # the frozen source-bundle ``source_identifier`` label; normalize only
        # for the lookup key and retain the observed label on the arrival row.
        # Every other identity component remains exact, so this is not a
        # JAN-only or version-wildcard match.
        observed_code_type = incoming.get("code_type")
        lookup_code_type = "source_identifier" if observed_code_type == "raw_source_identifier" else observed_code_type
        identity = {"code_raw": incoming.get("code"), "code_type": lookup_code_type,
                    "japanese_name": incoming.get("japanese_name"), "version": incoming.get("version"),
                    "specification": incoming.get("specification")}
        result = store.lookup(identity)
        result["binding"] = {"kind": "exact_source_bundle_identity",
                             "observed_code_type": observed_code_type,
                             "lookup_code_type": lookup_code_type,
                             "approval": False}
        row["source_product_lookup"] = result
        if result["status"] == "no_match":
            reason_counts["no_match"] += 1
            continue
        matched += 1
        if result["conflicts"]:
            reason_counts["conflict"] += 1
        filled = []
        for field in BASIC_FIELDS:
            if field in row.get("product", {}) and not row["product"].get(field) and result["candidates"].get(field) and field not in result["conflicts"]:
                row["product"][field] = result["candidates"][field]
                filled.append(field)
        result["prefilled_fields"] = sorted(filled)
        materials = {field: result["candidates"][field] for field in MATERIAL_FIELDS if result["candidates"].get(field)}
        if materials:
            row["material"]["candidates"].append({"source": "source_bundle_store", "values": materials,
                                                       "review_status": "reference_only_not_final_declaration_material"})
        if result["resolution"]:
            manual += 1
        prefilled += len(filled)
    total = len(batch["rows"])
    batch["source_bundle_reuse"] = {"database": str(Path(database_path).resolve()), "matched_rows": matched,
                                    "prefilled_fields": prefilled, "manual_resolution_rows": manual,
                                    "manual_processing_rows": total - matched + reason_counts["conflict"],
                                    "match_rate": (matched / total if total else 0),
                                    "reasons": dict(reason_counts), "read_only": True,
                                    "automatic_approval": False, "formal_output": False}
    return batch
