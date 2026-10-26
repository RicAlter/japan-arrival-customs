"""Local, evidence-first product reference library.

This is deliberately separate from ``decision_library``.  It stores product
facts and their source rows so that a new Japanese arrival sheet can be
prefilled with *candidates*.  It neither stores a declaration decision nor
approves material, tariff, tax, or a quantity conversion.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

from . import _p0_frozen as p0
from .core import Rejected, now


SCHEMA_VERSION = 2
FACT_FIELDS = ("internal_name", "customs_name", "category", "channel", "yd", "version",
               "packaging_label", "historical_material",
               "official_material", "material_url", "material_site")
PREFILL_FIELDS = ("internal_name", "customs_name", "category", "channel", "yd", "version",
                  "packaging_label")
MATERIAL_FIELDS = {"historical_material", "official_material", "material_url", "material_site"}
MANUAL_PRIORITY = 1000
SOURCE_PRIORITY = {"purchase_order": 100, "business_confirmation": MANUAL_PRIORITY, "product_archive": 80,
                   "historical_arrival": 60, "official_reference": 50,
                   "historical_material": 40}


def clean(value):
    return p0.clean(value) if value is not None else ""


def identifier(value):
    """Preserve identifiers exactly except surrounding whitespace.

    In particular, do not pad, coerce to an integer, or assert that a value is
    a 13-digit JAN.  The original value remains in source_rows as well.
    """
    return clean(value)


def comparable(value):
    """Conservative key for harmless presentation differences only."""
    return "".join(clean(value).casefold().replace("　", " ").split()).replace("－", "-").replace("（", "(").replace("）", ")")


def version_key(version, japanese_name):
    return comparable(version) or ("ja:" + comparable(japanese_name) if comparable(japanese_name) else "")


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def chunks(values, size):
    for index in range(0, len(values), size):
        yield values[index:index + size]


class ProductLibrary:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.exists():
            raise Rejected("商品资料库不存在；请先执行 product-library-init")
        self._migrate()

    @classmethod
    def create(cls, path):
        path = Path(path).resolve()
        if path.exists():
            raise Rejected("商品资料库已存在，拒绝覆盖")
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn:
            cls._create_schema(conn)
        return cls(path)

    @staticmethod
    def _create_schema(conn):
        conn.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE imports (
              id INTEGER PRIMARY KEY, content_sha256 TEXT NOT NULL UNIQUE,
              source_path TEXT NOT NULL, source_kind TEXT NOT NULL,
              imported_at TEXT NOT NULL, parser_version TEXT NOT NULL,
              status TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE source_rows (
              id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES imports(id),
              sheet_name TEXT NOT NULL, source_row INTEGER NOT NULL,
              identity_raw TEXT NOT NULL, raw_json TEXT NOT NULL,
              UNIQUE(import_id, sheet_name, source_row)
            );
            CREATE TABLE products (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL);
            CREATE TABLE identifiers (
              id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
              identifier_type TEXT NOT NULL, normalized_value TEXT NOT NULL,
              raw_value TEXT NOT NULL, source_row_id INTEGER NOT NULL REFERENCES source_rows(id),
              UNIQUE(identifier_type, normalized_value)
            );
            CREATE TABLE product_versions (
              id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
              source_row_id INTEGER NOT NULL REFERENCES source_rows(id),
              version_value TEXT NOT NULL, japanese_name TEXT NOT NULL DEFAULT '', version_key TEXT NOT NULL DEFAULT '', packaging_label TEXT NOT NULL,
              fingerprint TEXT NOT NULL UNIQUE
            );
            CREATE TABLE field_evidence (
              id INTEGER PRIMARY KEY, product_version_id INTEGER NOT NULL REFERENCES product_versions(id),
              field_name TEXT NOT NULL, value TEXT NOT NULL, source_kind TEXT NOT NULL,
              priority INTEGER NOT NULL, confidence TEXT NOT NULL,
              source_row_id INTEGER NOT NULL REFERENCES source_rows(id),
              observed_at TEXT NOT NULL,
              UNIQUE(product_version_id, field_name, value, source_row_id)
            );
            CREATE TABLE conflicts (
              id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
              field_name TEXT NOT NULL, values_json TEXT NOT NULL, status TEXT NOT NULL,
              detected_at TEXT NOT NULL,
              UNIQUE(product_id, field_name, values_json)
            );
            CREATE INDEX ix_identifiers_value ON identifiers(identifier_type, normalized_value);
            CREATE INDEX ix_evidence_version_field ON field_evidence(product_version_id, field_name, priority DESC);
            CREATE INDEX ix_product_versions_identity ON product_versions(product_id, version_key);
            CREATE TABLE manual_overrides (
              id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
              version_key TEXT NOT NULL, field_name TEXT NOT NULL, value TEXT NOT NULL,
              reference TEXT NOT NULL, saved_at TEXT NOT NULL,
              UNIQUE(product_id, version_key, field_name)
            );
        """)
        conn.execute("INSERT INTO metadata(key,value) VALUES (?,?)", ("schema_version", str(SCHEMA_VERSION)))
        conn.commit()

    def _migrate(self):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if not row:
                raise Rejected("商品资料库版本不受当前Skill支持")
            if row[0] == "1":
                conn.execute("ALTER TABLE product_versions ADD COLUMN japanese_name TEXT NOT NULL DEFAULT ''")
                conn.execute("ALTER TABLE product_versions ADD COLUMN version_key TEXT NOT NULL DEFAULT ''")
                conn.execute("""CREATE TABLE IF NOT EXISTS manual_overrides (
                  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
                  version_key TEXT NOT NULL, field_name TEXT NOT NULL, value TEXT NOT NULL,
                  reference TEXT NOT NULL, saved_at TEXT NOT NULL,
                  UNIQUE(product_id, version_key, field_name))""")
                conn.execute("CREATE INDEX IF NOT EXISTS ix_product_versions_identity ON product_versions(product_id, version_key)")
                for item in conn.execute("SELECT id,version_value FROM product_versions").fetchall():
                    conn.execute("UPDATE product_versions SET version_key=? WHERE id=?", (version_key(item["version_value"], ""), item["id"]))
                conn.execute("UPDATE metadata SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
                conn.commit()
            elif row[0] != str(SCHEMA_VERSION):
                raise Rejected("商品资料库版本不受当前Skill支持")

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _product_for(self, conn, code, source_row_id):
        existing = conn.execute("SELECT product_id FROM identifiers WHERE identifier_type='source_code' AND normalized_value=?", (code,)).fetchone()
        if existing:
            return existing["product_id"]
        cursor = conn.execute("INSERT INTO products(created_at) VALUES (?)", (now(),))
        product_id = cursor.lastrowid
        conn.execute("INSERT INTO identifiers(product_id,identifier_type,normalized_value,raw_value,source_row_id) VALUES (?,?,?,?,?)",
                     (product_id, "source_code", code, code, source_row_id))
        return product_id

    def _add_record(self, conn, import_id, source_kind, record):
        code = identifier(record.get("code"))
        if not code:
            return False
        raw = {key: clean(value) for key, value in record.items() if key not in {"sheet", "row"}}
        cursor = conn.execute("INSERT OR IGNORE INTO source_rows(import_id,sheet_name,source_row,identity_raw,raw_json) VALUES (?,?,?,?,?)",
                              (import_id, record["sheet"], record["row"], code, json_text(raw)))
        if not cursor.rowcount:
            return False
        source_row_id = cursor.lastrowid
        product_id = self._product_for(conn, code, source_row_id)
        packaging_label = clean(record.get("packaging_label"))
        version = clean(record.get("version"))
        japanese_name = clean(record.get("japanese_name"))
        key = version_key(version, japanese_name)
        fingerprint = hashlib.sha256(json_text({"product": product_id, "version": version, "japanese_name": japanese_name,
                                                "packaging_label": packaging_label,
                                                "source_row": source_row_id}).encode()).hexdigest()
        version_id = conn.execute("INSERT INTO product_versions(product_id,source_row_id,version_value,japanese_name,version_key,packaging_label,fingerprint) VALUES (?,?,?,?,?,?,?)",
                                  (product_id, source_row_id, version, japanese_name, key, packaging_label, fingerprint)).lastrowid
        facts = {field: clean(record.get(field)) for field in FACT_FIELDS}
        facts["version"] = version
        facts["packaging_label"] = packaging_label
        for field, value in facts.items():
            if not value:
                continue
            confidence = "reference_only" if field in MATERIAL_FIELDS else ("trusted_history" if source_kind != "purchase_order" else "purchase_reference")
            conn.execute("INSERT OR IGNORE INTO field_evidence(product_version_id,field_name,value,source_kind,priority,confidence,source_row_id,observed_at) VALUES (?,?,?,?,?,?,?,?)",
                         (version_id, field, value, source_kind, SOURCE_PRIORITY[source_kind], confidence, source_row_id, now()))
        return True

    def import_workbooks(self, paths, *, source_kind="auto"):
        if source_kind != "auto" and source_kind not in SOURCE_PRIORITY:
            raise Rejected("未知商品资料来源类型")
        results = []
        with closing(self._connect()) as conn:
            for raw_path in paths:
                path = Path(raw_path).resolve(strict=True)
                if path.suffix.lower() != ".xlsx":
                    raise Rejected("本期商品资料导入只接受xlsx")
                data = path.read_bytes(); content_sha = hashlib.sha256(data).hexdigest()
                old = conn.execute("SELECT id,source_kind,row_count FROM imports WHERE content_sha256=?", (content_sha,)).fetchone()
                if old:
                    results.append({"path": str(path), "status": "unchanged_duplicate", "sha256": content_sha,
                                    "source_kind": old["source_kind"], "records": old["row_count"]})
                    continue
                records, detected = extract_records(path, data, source_kind)
                cursor = conn.execute("INSERT INTO imports(content_sha256,source_path,source_kind,imported_at,parser_version,status,row_count) VALUES (?,?,?,?,?,?,0)",
                                      (content_sha, str(path), detected, now(), "product-library-v1", "in_progress"))
                inserted = sum(self._add_record(conn, cursor.lastrowid, detected, record) for record in records)
                conn.execute("UPDATE imports SET status='complete',row_count=? WHERE id=?", (inserted, cursor.lastrowid))
                results.append({"path": str(path), "status": "imported", "sha256": content_sha,
                                "source_kind": detected, "records": inserted, "observed_rows": len(records)})
            self._rebuild_conflicts(conn)
            conn.commit()
        return {"imports": results, "statistics": self.statistics()}

    def _rebuild_conflicts(self, conn):
        conn.execute("DELETE FROM conflicts")
        rows = conn.execute("""
          SELECT pv.product_id,pv.id AS version_id,fe.field_name,fe.value,fe.source_row_id,fe.priority
          FROM field_evidence fe JOIN product_versions pv ON pv.id=fe.product_version_id
          WHERE fe.field_name IN ('internal_name','customs_name','category','channel','yd','version','packaging_label')
          ORDER BY pv.product_id,fe.field_name,fe.priority DESC,fe.id DESC
        """).fetchall()
        grouped = defaultdict(lambda: defaultdict(list))
        for row in rows:
            grouped[(row["product_id"], row["version_id"], row["field_name"])][row["priority"], comparable(row["value"])].append((row["value"], row["source_row_id"]))
        for (product_id, version_id, field), variants in grouped.items():
            strongest = max(priority for priority, _ in variants)
            values = {key: rows for (priority, key), rows in variants.items() if priority == strongest}
            if len(values) > 1:
                payload = [{"version_id": version_id, "value": rows[0][0], "source_row_ids": [item[1] for item in rows]} for rows in values.values()]
                conn.execute("INSERT INTO conflicts(product_id,field_name,values_json,status,detected_at) VALUES (?,?,?,?,?)",
                             (product_id, field, json_text(payload), "pending_review", now()))

    def lookup(self, code, *, japanese_name="", version=""):
        code = identifier(code)
        if not code:
            return {"status": "no_source_code", "candidates": {}, "conflicts": {}, "matched_records": []}
        with closing(self._connect()) as conn:
            return self._lookup(conn, code, {"japanese_name": japanese_name, "version": version})

    def record_business_confirmation(self, batch, row_ids, confirmation):
        """Append one user-confirmed basic-product snapshot.

        This records only basic product facts for future *candidate* prefill.
        It intentionally does not write materials, packaging coefficients, tax,
        classification or a D1 declaration decision.
        """
        if not isinstance(confirmation, dict) or confirmation.get("kind") != "single_person_business_confirmation":
            raise Rejected("商品资料库只接受受控单人业务确认回写")
        rows = {row["id"]: row for row in batch["rows"]}
        if not isinstance(row_ids, list) or not row_ids or len(row_ids) != len(set(row_ids)) or set(row_ids) - set(rows):
            raise Rejected("商品资料库回写范围无效")
        records = []
        for index, row_id in enumerate(row_ids, 1):
            row = rows[row_id]
            product = row["product"]
            records.append({"sheet": "single_business_confirmation", "row": index,
                            "code": row["identity"].get("code", ""),
                            "japanese_name": row["identity"].get("japanese_name", ""),
                            "internal_name": product.get("internal_name", ""),
                            "customs_name": product.get("customs_name", ""),
                            "category": product.get("category", ""),
                            "channel": product.get("channel", ""),
                            "yd": product.get("yd", ""),
                            "version": row["identity"].get("version", ""),
                            "packaging_label": ""})
        content = {"batch_id": batch["id"], "revision": batch["revision"],
                   "row_ids": row_ids, "confirmation": confirmation, "records": records}
        content_sha = hashlib.sha256(json_text(content).encode()).hexdigest()
        with closing(self._connect()) as conn:
            old = conn.execute("SELECT row_count FROM imports WHERE content_sha256=?", (content_sha,)).fetchone()
            if old:
                return {"status": "unchanged_duplicate", "records": old["row_count"], "statistics": self.statistics()}
            cursor = conn.execute("INSERT INTO imports(content_sha256,source_path,source_kind,imported_at,parser_version,status,row_count) VALUES (?,?,?,?,?,?,0)",
                                  (content_sha, "business_confirmation:" + batch["id"], "business_confirmation", now(),
                                   "product-library-v1", "in_progress"))
            inserted = sum(self._add_record(conn, cursor.lastrowid, "business_confirmation", record) for record in records)
            conn.execute("UPDATE imports SET status='complete',row_count=? WHERE id=?", (inserted, cursor.lastrowid))
            self._rebuild_conflicts(conn)
            conn.commit()
        return {"status": "recorded_candidate_only", "records": inserted, "statistics": self.statistics(),
                "declaration_decision_written": False}

    def record_maintenance_records(self, records, confirmation):
        """Write an explicit maintenance-Skill queue into the shared library.

        The arrival Skill is intentionally not a database writer.  It creates
        the queue from a confirmed Excel difference; this method is called only
        by the separate product-maintenance Skill and keeps the same immutable
        import trail as workbook imports.
        """
        if not isinstance(confirmation, dict) or confirmation.get("kind") != "product_maintenance_queue":
            raise Rejected("资料库写入只接受商品维护Skill的受控队列")
        if not isinstance(records, list) or not records:
            raise Rejected("商品维护队列缺少基础资料记录")
        allowed = {"sheet", "row", "code", "japanese_name", "internal_name", "customs_name", "category", "channel", "yd", "version", "packaging_label"}
        if any(not isinstance(record, dict) or set(record) - allowed for record in records):
            raise Rejected("商品维护队列包含未知字段")
        content = {"records": records, "confirmation": confirmation}
        content_sha = hashlib.sha256(json_text(content).encode()).hexdigest()
        with closing(self._connect()) as conn:
            old = conn.execute("SELECT row_count FROM imports WHERE content_sha256=?", (content_sha,)).fetchone()
            if old:
                return {"status": "unchanged_duplicate", "records": old["row_count"], "statistics": self.statistics()}
            cursor = conn.execute("INSERT INTO imports(content_sha256,source_path,source_kind,imported_at,parser_version,status,row_count) VALUES (?,?,?,?,?,?,0)",
                                  (content_sha, "product_maintenance_queue:" + clean(confirmation.get("queue_id")), "business_confirmation", now(),
                                   "product-library-v2", "in_progress"))
            inserted = sum(self._add_record(conn, cursor.lastrowid, "business_confirmation", record) for record in records)
            conn.execute("UPDATE imports SET status='complete',row_count=? WHERE id=?", (inserted, cursor.lastrowid))
            self._rebuild_conflicts(conn)
            conn.commit()
        return {"status": "recorded_by_product_maintenance", "records": inserted, "statistics": self.statistics(),
                "declaration_decision_written": False}

    def lookup_many(self, identities):
        """Batch lookup, resolving variants before comparing source values."""
        requested = {}
        for item in identities:
            if isinstance(item, dict):
                code = identifier(item.get("code")); identity = {"japanese_name": clean(item.get("japanese_name")), "version": clean(item.get("version"))}
            else:
                code, identity = identifier(item), {"japanese_name": "", "version": ""}
            if code: requested.setdefault(code, identity)
        normalized = set(requested)
        with closing(self._connect()) as conn:
            code_products = {}
            for group in chunks(sorted(normalized), 900):
                marks = ",".join("?" for _ in group)
                for row in conn.execute("SELECT normalized_value,product_id FROM identifiers WHERE identifier_type='source_code' AND normalized_value IN ("+marks+")", group):
                    code_products[row["normalized_value"]] = row["product_id"]
            evidence_by_product = defaultdict(list); manual_by_product = defaultdict(list)
            for group in chunks(sorted(set(code_products.values())), 900):
                marks = ",".join("?" for _ in group)
                evidence = conn.execute("""SELECT pv.product_id,pv.id AS version_id,pv.version_value,pv.japanese_name,pv.version_key,
                  fe.field_name,fe.value,fe.source_kind,fe.priority,fe.confidence,fe.source_row_id,
                  sr.sheet_name,sr.source_row,i.content_sha256,i.source_path
                  FROM field_evidence fe JOIN product_versions pv ON pv.id=fe.product_version_id
                  JOIN source_rows sr ON sr.id=fe.source_row_id JOIN imports i ON i.id=sr.import_id
                  WHERE pv.product_id IN ("""+marks+") ORDER BY pv.product_id,fe.field_name,fe.priority DESC,fe.id DESC", group).fetchall()
                for row in evidence: evidence_by_product[row["product_id"]].append(row)
                for row in conn.execute("SELECT product_id,version_key,field_name,value,reference,saved_at FROM manual_overrides WHERE product_id IN ("+marks+")", group): manual_by_product[row["product_id"]].append(row)
            return {code: self._result(code_products.get(code), evidence_by_product.get(code_products.get(code), []), requested[code], manual_by_product.get(code_products.get(code), [])) for code in normalized}

    def _lookup(self, conn, code, identity):
        found = conn.execute("SELECT product_id FROM identifiers WHERE identifier_type='source_code' AND normalized_value=?", (code,)).fetchone()
        if not found:
            return {"status": "no_match", "candidates": {}, "conflicts": {}, "matched_records": []}
        product_id = found["product_id"]
        evidence = conn.execute("""
          SELECT pv.id AS version_id,pv.version_value,pv.japanese_name,pv.version_key,fe.field_name,fe.value,fe.source_kind,fe.priority,fe.confidence,fe.source_row_id,
                 sr.sheet_name,sr.source_row,i.content_sha256,i.source_path
          FROM field_evidence fe JOIN product_versions pv ON pv.id=fe.product_version_id
          JOIN source_rows sr ON sr.id=fe.source_row_id JOIN imports i ON i.id=sr.import_id
          WHERE pv.product_id=? ORDER BY fe.field_name,fe.priority DESC,fe.id DESC
        """, (product_id,)).fetchall()
        manual = conn.execute("SELECT product_id,version_key,field_name,value,reference,saved_at FROM manual_overrides WHERE product_id=?", (product_id,)).fetchall()
        return self._result(product_id, evidence, identity, manual)

    def _result(self, product_id, evidence, identity, manual):
        if product_id is None:
            return {"status": "no_match", "candidates": {}, "conflicts": {}, "matched_records": []}
        groups = defaultdict(list)
        for item in evidence: groups[item["version_id"]].append(item)
        wanted_version, wanted_name = comparable(identity.get("version")), comparable(identity.get("japanese_name"))
        matching = list(groups)
        if wanted_version:
            matching = [key for key, items in groups.items() if comparable(items[0]["version_value"]) == wanted_version]
            if not matching:
                return {"status":"version_mismatch","product_id":product_id,"candidates":{},"matched_records":[],"trusted_history_reused":False,"automatic_approval":False,
                        "conflicts":{"version":[{"requested":identity.get("version",""),"available":sorted({x[0]["version_value"] for x in groups.values()})}]}}
        elif wanted_name:
            named = [key for key, items in groups.items() if comparable(items[0]["japanese_name"]) == wanted_name]
            if named: matching = named
            elif len(groups) > 1:
                return {"status":"version_unresolved","product_id":product_id,"candidates":{},"matched_records":[],"trusted_history_reused":False,"automatic_approval":False,
                        "conflicts":{"identity":[{"requested_japanese_name":identity.get("japanese_name", ""),"available_versions":len(groups)}]}}
        elif len(groups) > 1:
            return {"status":"version_unresolved","product_id":product_id,"candidates":{},"matched_records":[],"trusted_history_reused":False,"automatic_approval":False,
                    "conflicts":{"identity":[{"reason":"same code has multiple historical versions"}]}}
        selected = [item for key in matching for item in groups[key]]
        selected_keys = {item["version_key"] for item in selected}
        values, records = defaultdict(list), []
        for item in selected:
            values[item["field_name"]].append(item)
            records.append({"field":item["field_name"],"value":item["value"],"source_kind":item["source_kind"],
                            "source":{"path":item["source_path"],"sha256":item["content_sha256"],"sheet":item["sheet_name"],"row":item["source_row"]},"confidence":item["confidence"]})
        candidates, conflicts, resolutions = {}, {}, {}
        for field, items in values.items():
            highest = max(item["priority"] for item in items)
            strongest = [item for item in items if item["priority"] == highest]
            variants = defaultdict(list)
            for item in strongest: variants[comparable(item["value"])].append(item)
            if len(variants) == 1:
                candidates[field] = strongest[0]["value"]
                if any(item["priority"] != highest for item in items): resolutions[field] = "higher_priority_history"
            else:
                conflicts[field] = [{"value":item[0]["value"],"source_row_ids":[x["source_row_id"] for x in item]} for item in variants.values()]
        for item in manual:
            if item["version_key"] in selected_keys or (not item["version_key"] and len(selected_keys) == 1):
                candidates[item["field_name"]] = item["value"]; conflicts.pop(item["field_name"],None); resolutions[item["field_name"]] = "manual_correction"
        trusted = bool(candidates) and not conflicts
        return {"status":"trusted_history_reused" if trusted else "matched_with_conflict","product_id":product_id,"candidates":candidates,
                "conflicts":conflicts,"matched_records":records,"identity":{"version_key":sorted(selected_keys),"match":"exact_version_or_japanese_name" if (wanted_version or wanted_name) else "single_version"},
                "resolution":resolutions,"trusted_history_reused":trusted,"automatic_approval":False,
                "notice":"可信历史基础资料可直接复用；材质、盒规换算、税号税率及最终申报选择仍须按原流程审核。"}

    def statistics(self):
        with closing(self._connect()) as conn:
            count = lambda table: conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            kinds = {row["source_kind"]: row["count"] for row in conn.execute("SELECT source_kind,COUNT(*) count FROM imports WHERE status='complete' GROUP BY source_kind")}
            return {"database": str(self.path), "imports": count("imports"), "source_rows": count("source_rows"),
                    "products": count("products"), "identifiers": count("identifiers"), "versions": count("product_versions"),
                    "field_evidence": count("field_evidence"), "pending_conflicts": count("conflicts"),
                    "imports_by_kind": kinds, "declaration_decisions_stored": False}


def _stage_records(book, stage, path):
    return [{**{key: value for key, value in record.items()}, "sheet": record["sheet"], "row": record["row"]}
            for record in p0.records(book, stage)]


def _translated(records, kind):
    output = []
    for row in records:
        if kind == "stage2":
            output.append({"sheet": row["sheet"], "row": row["row"], "code": row.get("code"), "japanese_name": row.get("ja"), "internal_name": row.get("internal"),
                           "version": row.get("variant"), "category": row.get("category"), "channel": row.get("channel"), "yd": row.get("yd"),
                           "packaging_label": row.get("variant"),
                           "historical_material": row.get("material"), "official_material": row.get("search_material"),
                           "material_url": row.get("url"), "material_site": row.get("site")})
        elif kind in ("stage1", "stage3"):
            output.append({"sheet": row["sheet"], "row": row["row"], "code": row.get("code"), "japanese_name": row.get("ja"), "internal_name": row.get("internal"),
                           "version": row.get("variant"), "category": row.get("category"), "channel": row.get("channel"), "yd": row.get("yd"),
                           "packaging_label": row.get("variant"),
                           "historical_material": row.get("material")})
        elif kind in ("stage4", "stage5", "stage6"):
            output.append({"sheet": row["sheet"], "row": row["row"], "code": row.get("code"), "japanese_name": row.get("ja"), "internal_name": row.get("internal"),
                           "version": row.get("variant"), "category": row.get("category"), "channel": row.get("channel"), "yd": row.get("yd"),
                           "historical_material": row.get("material"), "packaging_label": row.get("label") or row.get("spec")})
    return output


def _net_order_records(book):
    output = []
    for sheet in book.sheets:
        header_row = None; columns = {}
        for ri in sorted(sheet.rows):
            labels = {col: clean(cell.get("v")) for col, cell in sheet.rows[ri].items()}
            if any(label.lower() in {"jan code", "jancode", "jan"} for label in labels.values()):
                header_row, columns = ri, labels; break
        if header_row is None: continue
        find = lambda *names: next((col for col, label in columns.items() if label.lower() in {name.lower() for name in names}), None)
        code_col, title_col, qty_col = find("Jan Code", "jancode", "JAN"), find("タイトル", "title"), find("オーダー数", "数量", "order quantity")
        supplier_col, web_col = find("仕入先", "supplier"), find("WEB SIDE", "website")
        if not code_col: continue
        for ri in sorted(sheet.rows):
            if ri <= header_row: continue
            row = sheet.rows[ri]; code = row.get(code_col, {}).get("v")
            if not clean(code): continue
            label = clean(row.get(title_col, {}).get("v")) if title_col else ""
            # An order title is useful traceability, but it is not an approved
            # Chinese product name or a packaging specification.
            output.append({"sheet": sheet.name, "row": ri, "code": code, "japanese_name": label,
                           "internal_name": "", "packaging_label": "",
                           "channel": clean(row.get(supplier_col, {}).get("v")) if supplier_col else "",
                           "material_url": clean(row.get(web_col, {}).get("v")) if web_col else ""})
    return output


def extract_records(path, data, requested_kind):
    book = p0.Book(data, str(path))
    if requested_kind == "purchase_order" or (requested_kind == "auto" and "net order" in path.name.lower()):
        return _net_order_records(book), "purchase_order"
    first = book.sheets[0]
    header1 = {col: clean(first.v(1, col)) for col in ("A", "B", "C", "D", "H", "I", "J", "K", "L")}
    header17 = {col: clean(first.v(17, col)) for col in ("D", "M")}
    if header1.get("C") == "编码" and header1.get("I") == "材质":
        return _translated(_stage_records(book, 2, path), "stage2"), "historical_material"
    if "JAN" in header1.get("C", "") and header1.get("J") == "Qty":
        return _translated(_stage_records(book, 3, path), "stage3"), "historical_arrival"
    if header1.get("A") == "箱号" and "Descriptions" in header1.get("C", ""):
        stage = 4 if requested_kind == "product_archive" else 5
        return _translated(_stage_records(book, stage, path), "stage" + str(stage)), ("product_archive" if stage == 4 else "historical_arrival")
    if "JAN" in header1.get("C", "") and header1.get("H") == "盒装数":
        return _translated(_stage_records(book, 6, path), "stage6"), "historical_arrival"
    if "JAN" in header17.get("D", "") and header17.get("M") == "Qty":
        return _translated(_stage_records(book, 1, path), "stage1"), "historical_arrival"
    if requested_kind != "auto":
        raise Rejected("该来源类型未匹配已批准的本地Excel模板")
    raise Rejected("未识别的本地Excel模板；请先补充显式适配，程序不会猜列")


def apply_candidates(batch, library_path):
    """Attach local-library candidates to a newly imported batch.

    Only empty basic-product fields are prefilled.  A source conflict excludes
    that field, and packaging text is recorded as evidence rather than a
    conversion coefficient.  No domain review is written here.
    """
    library = ProductLibrary(library_path)
    matched = pending = conflicts = applied = 0
    reasons = Counter()
    by_code = library.lookup_many({"code": row["identity"].get("code", ""), "japanese_name": row["identity"].get("japanese_name", ""), "version": row["identity"].get("version", "")} for row in batch["rows"])
    for row in batch["rows"]:
        code = identifier(row["identity"].get("code", ""))
        result = by_code.get(code, {"status": "no_source_code", "candidates": {}, "conflicts": {}, "matched_records": []})
        row["product_lookup"] = result
        status = result["status"]
        if status == "no_match":
            pending += 1; reasons["no_match"] += 1; continue
        if status == "no_source_code":
            pending += 1; reasons["no_source_code"] += 1; continue
        if status in ("version_mismatch", "version_unresolved"):
            pending += 1; conflicts += 1; reasons[status] += 1; continue
        matched += 1
        if result["conflicts"]:
            conflicts += 1
            reasons["field_conflict"] += 1
        candidates = result["candidates"]
        filled = []
        for field in ("internal_name", "customs_name", "category", "channel", "yd"):
            if not row["product"].get(field) and candidates.get(field):
                row["product"][field] = candidates[field]
                filled.append(field)
        if not row["identity"].get("version") and candidates.get("version"):
            row["identity"]["version"] = candidates["version"]
            filled.append("version")
        if result.get("trusted_history_reused"):
            row["product"]["history_reused"] = True
            row["identity"]["history_reused"] = True
        package = {key: candidates[key] for key in ("packaging_label",) if candidates.get(key)}
        if package:
            row["arrival"]["product_reference_packaging"] = {"status": "candidate_only_no_conversion",
                                                                  "values": package,
                                                                  "notice": "未批准盒规；不可据此换算申报数量"}
            filled.append("packaging_reference")
        material = {key: candidates[key] for key in MATERIAL_FIELDS if candidates.get(key)}
        if material:
            row["material"]["candidates"].append({"source": "local_product_library", "values": material,
                                                     "review_status": "reference_only_not_final_declaration_material"})
            # The existing UI shows candidate separately from selected material.
            if not row["material"].get("candidate"):
                row["material"]["candidate"] = material.get("official_material") or material.get("historical_material") or ""
                if row["material"]["candidate"]: filled.append("material_candidate")
        applied += len(filled)
    batch["product_review_profile"] = "exception-first-v1"
    batch["product_data_policy"] = "single-person-v1"
    batch["arrival_summary"].update({"product_reference_matches": matched,
                                      "product_reference_pending": pending,
                                      "product_reference_conflicts": conflicts,
                                      "product_reference_prefilled_fields": applied,
                                      "product_reference_pending_reasons": dict(reasons)})
    batch["product_library"] = {"path": str(Path(library_path).resolve()), "statistics": library.statistics(),
                                "automatic_approval": False,
                                 "notice": "可信历史基础资料已直接复用；D1最终申报决策库、归类审批及自动规则均未调用。"}
    return batch
