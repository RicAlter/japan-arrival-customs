"""Small current-batch candidate database; never reads or migrates a release DB."""
from pathlib import Path
import hashlib
import json
import sqlite3


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def identity(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_artifacts(
            source_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, role TEXT NOT NULL,
            payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS product_records(
            record_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_artifacts,
            sheet TEXT NOT NULL, source_row INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS procurement_records(
            record_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source_artifacts,
            sheet TEXT NOT NULL, source_row INTEGER NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS batch_rows(
            batch_id TEXT NOT NULL, row_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            source_row INTEGER NOT NULL, raw_payload TEXT NOT NULL,
            PRIMARY KEY(batch_id,row_id), UNIQUE(batch_id,ordinal));
        CREATE TABLE IF NOT EXISTS matched_rows(
            batch_id TEXT NOT NULL,row_id TEXT NOT NULL,payload TEXT NOT NULL,
            PRIMARY KEY(batch_id,row_id),
            FOREIGN KEY(batch_id,row_id) REFERENCES batch_rows);
        CREATE TABLE IF NOT EXISTS adopted_fields(
            batch_id TEXT NOT NULL,row_id TEXT NOT NULL,field TEXT NOT NULL,
            value TEXT NOT NULL,evidence TEXT NOT NULL,
            PRIMARY KEY(batch_id,row_id,field),
            FOREIGN KEY(batch_id,row_id) REFERENCES batch_rows);
        CREATE TABLE IF NOT EXISTS issues(
            issue_id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,row_id TEXT NOT NULL,
            field TEXT,payload TEXT NOT NULL,
            FOREIGN KEY(batch_id,row_id) REFERENCES batch_rows);
        CREATE TABLE IF NOT EXISTS checkpoints(
            step TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL, payload TEXT NOT NULL);
        ''')
        version = self.db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
        if version and version[0] != 'arrival-mvp-candidate/1':
            raise ValueError('CONFIG_INVALID: incompatible candidate schema')
        self.db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)', ('schema', 'arrival-mvp-candidate/1'))
        self.db.commit()

    def close(self):
        self.db.close()

    def checkpoint(self, step, payload):
        encoded = canonical(payload)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)',
                            (step, hashlib.sha256(encoded.encode()).hexdigest(), encoded))

    def get_checkpoint(self, step):
        row = self.db.execute('SELECT content_sha256,payload FROM checkpoints WHERE step=?', (step,)).fetchone()
        if row is None:
            return None
        if hashlib.sha256(row[1].encode()).hexdigest() != row[0]:
            raise ValueError('TASK_CONFLICT: checkpoint payload drift')
        return json.loads(row[1])

    def save_sources(self, collected):
        with self.db:
            for source in collected['sources']:
                sid = source.get('source_id') or source.get('id')
                if not sid:
                    raise ValueError('CONFIG_INVALID: missing source identity')
                existing = self.db.execute('SELECT sha256,role FROM source_artifacts WHERE source_id=?', (sid,)).fetchone()
                pair = (source.get('sha256') or source.get('source_sha256'), source['role'])
                if existing and existing != pair:
                    raise ValueError('TASK_CONFLICT: source identity reused')
                self.db.execute('INSERT OR IGNORE INTO source_artifacts VALUES(?,?,?,?)',
                                (sid, *pair, canonical(source)))
            for record in collected['records']:
                table = 'procurement_records' if record['role'] in {'purchase_list', 'order_detail', 'purchase_order'} else 'product_records'
                rid = identity([record['source_id'], record['sheet'], record['row'], record.get('fields'), record.get('columns')])
                self.db.execute(f'INSERT OR IGNORE INTO {table} VALUES(?,?,?,?,?)',
                                (rid, record['source_id'], record['sheet'], record['row'], canonical(record)))
        self.checkpoint('sources', collected)

    def save_batch(self, batch_id, batch):
        with self.db:
            source = batch['source']
            self.db.execute('INSERT OR IGNORE INTO source_artifacts VALUES(?,?,?,?)',
                            (source.get('source_id', 'batch'), source['sha256'], 'japanese_batch', canonical(source)))
            for ordinal, row in enumerate(batch['rows']):
                payload = canonical({'raw': row['raw'], 'raw_cells': row.get('raw_cells', {}), 'sheet': row['sheet']})
                old = self.db.execute('SELECT ordinal,source_row,raw_payload FROM batch_rows WHERE batch_id=? AND row_id=?',
                                      (batch_id, row['row_id'])).fetchone()
                value = (ordinal, row['source_row'], payload)
                if old and old != value:
                    raise ValueError('TASK_CONFLICT: immutable batch row changed')
                self.db.execute('INSERT OR IGNORE INTO batch_rows VALUES(?,?,?,?,?)',
                                (batch_id, row['row_id'], *value))
        self.checkpoint('extracted', batch)

    def save_matches(self, batch_id, rows):
        with self.db:
            for row in rows:
                raw = self.db.execute('SELECT raw_payload FROM batch_rows WHERE batch_id=? AND row_id=?',
                                      (batch_id, row['row_id'])).fetchone()
                if raw is None or json.loads(raw[0])['raw'] != row['raw']:
                    raise ValueError('TASK_CONFLICT: matched row changed original facts')
                self.db.execute('INSERT OR REPLACE INTO matched_rows VALUES(?,?,?)', (batch_id, row['row_id'], canonical(row)))
                # Replaying the deterministic same checkpoint never accumulates facts.
                self.db.execute('DELETE FROM adopted_fields WHERE batch_id=? AND row_id=?', (batch_id, row['row_id']))
                self.db.execute('DELETE FROM issues WHERE batch_id=? AND row_id=?', (batch_id, row['row_id']))
                for field, value in row.get('values', {}).items():
                    if value in ('', None):
                        continue
                    evidence = row.get('evidence', {}).get(field, [])
                    if not evidence:
                        raise ValueError(f'TASK_CONFLICT: adopted field has no evidence: {field}')
                    self.db.execute('INSERT INTO adopted_fields VALUES(?,?,?,?,?)',
                                    (batch_id, row['row_id'], field, canonical(value), canonical(evidence)))
                for issue in row.get('issues', []):
                    iid = identity([batch_id, row['row_id'], issue])
                    self.db.execute('INSERT OR IGNORE INTO issues VALUES(?,?,?,?,?)',
                                    (iid, batch_id, row['row_id'], issue.get('field'), canonical(issue)))
        self.checkpoint('matched', rows)

    def counts(self):
        return {name: self.db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
                for name in ['source_artifacts', 'product_records', 'procurement_records', 'batch_rows', 'matched_rows', 'adopted_fields', 'issues']}
