"""Independent event-backed declaration library. SQLite is a disposable projection.

No approval UI, inferred tariff policy, rule publication or automatic adoption.
Authority: immutable source bundles + chained commits + atomic HEAD. Local host
permissions must protect this directory as they protect B2 session configuration.
"""
import copy,hashlib,json,os,shutil,sqlite3,unicodedata
from datetime import date
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from .core import Rejected,digest,now
from .storage import Store,atomic_json
from .knowledge_source import capture,validate_bundle,eligible,LAYERS

FORMAT=2
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def normal(text):return unicodedata.normalize('NFKC',text).casefold().strip()

def external(path):
    path=Path(path).resolve();skill=Path(__file__).resolve().parents[2]
    if path==path.parent or path.is_relative_to(skill) or skill.is_relative_to(path):
        raise Rejected('决策库/备份必须与Skill安装目录分离，不能选择磁盘根目录')
    return path

class DecisionLibrary:
    def __init__(self,root):
        self.root=external(root)
        self._metadata()

    @classmethod
    def create(cls,root,*,source_root,source_kind):
        root=external(root);source=Path(source_root).resolve()
        if root.is_relative_to(source) or source.is_relative_to(root):raise Rejected('决策库须与批次存储分离')
        if source_kind not in ('business','synthetic','authorized_test_fixture'):raise Rejected('须明确来源性质')
        if root.exists():raise Rejected('只允许在新目录创建决策库')
        root.mkdir(parents=True);(root/'objects').mkdir();(root/'commits').mkdir()
        atomic_json(root/'library.json',{'schema':'japan-arrival/decision-library','format_version':FORMAT,
            'library_id':uuid4().hex,'created_at':now(),'source_root':str(source),'source_kind':source_kind,
            'automatic_rules':False,'formal_output_authorized':False})
        atomic_json(root/'head.json',{'sequence':0,'commit':None})
        return cls(root)

    def _metadata(self):
        value=read(self.root/'library.json')
        if value.get('schema')!='japan-arrival/decision-library' or value.get('format_version') not in (1,FORMAT):raise Rejected('库格式未知，拒绝降级或猜测升级')
        if value.get('automatic_rules') is not False or value.get('formal_output_authorized') is not False:raise Rejected('库不能授权规则或正式输出')
        return value

    def _lock(self):return Store(self.root).lock(self.root)

    def _objects(self,folder,key):
        if not isinstance(key,str) or len(key)!=64 or any(x not in '0123456789abcdef' for x in key):raise Rejected('非法内容地址')
        path=(self.root/folder/(key+'.json')).resolve()
        if not path.is_relative_to(self.root):raise Rejected('禁止链接逃逸')
        return path

    def _put(self,folder,value):
        key=digest(value);path=self._objects(folder,key)
        if path.exists():
            if read(path)!=value:raise Rejected('不可变对象冲突')
        else:atomic_json(path,value)
        return key

    def _load(self):
        """Validate all committed objects. Orphans before a failed HEAD switch are ignored."""
        self._metadata();head=read(self.root/'head.json');pointer=head['commit'];commits=[];seen=set()
        while pointer:
            if pointer in seen:raise Rejected('提交链循环')
            seen.add(pointer);entry=read(self._objects('commits',pointer))
            if digest(entry)!=pointer:raise Rejected('提交校验错误')
            commits.append(entry);pointer=entry['previous']
        commits.reverse()
        if len(commits)!=head['sequence']:raise Rejected('提交序号缺失')
        streams={};events={};bundles={}
        for i,entry in enumerate(commits,1):
            if entry['sequence']!=i:raise Rejected('提交链不连续')
            bundle=read(self._objects('objects',entry['bundle']))
            if digest(bundle)!=entry['bundle']:raise Rejected('权威来源对象损坏，不能用索引代替')
            validate_bundle(bundle);self._merge(streams,events,bundles,bundle)
        return head,streams,events,bundles

    @staticmethod
    def _merge(streams,events,bundles,bundle):
        batch=bundle['batch_id'];old=streams.get(batch)
        if old:
            if len(bundle['events'])<len(old['events']) or bundle['revision']<old['revision']:raise Rejected('来源旧版本不得覆盖当前库')
            if bundle['events'][:len(old['events'])]!=old['events']:raise Rejected('来源事件分叉或改写')
            if bundle['revision']==old['revision'] and bundle!=old:raise Rejected('同一来源版本内容或权限证明变化，须重新审核产生新版本')
            if bundle['store_root']!=old['store_root'] or bundle['source_kind']!=old['source_kind']:raise Rejected('来源身份不可改变')
            for rid,r in old['rows'].items():
                new=bundle['rows'][rid]
                for kind in LAYERS:
                    by_id={x['id']:x for x in new['layers'][kind]}
                    if any(by_id.get(x['id'])!=x for x in r['layers'][kind]):raise Rejected('历史参考层被改写或删除')
        for e in bundle['events']:
            eid=e['event_id']
            if eid in events and events[eid]!=e:raise Rejected('同事件ID不同内容')
            events[eid]=e
        streams[batch]=bundle;bundles[digest(bundle)]=bundle

    def import_batch(self,batch_id):
        """Read only the configured trusted B2 Store; arbitrary JSON is never an import authority."""
        meta=self._metadata();bundle=capture(meta['source_root'],batch_id,source_kind=meta['source_kind'])
        validate_bundle(bundle)
        # Same path guard as batch output, also protecting original source directories.
        for r in bundle['rows'].values():
            parent=Path(r['source']['path']).resolve().parent
            if self.root.is_relative_to(parent) or parent.is_relative_to(self.root):raise Rejected('知识目录不得包含或写入原始资料目录')
        with self._lock():
            head,streams,events,bundles=self._load();old=streams.get(batch_id);before=len(events)
            duplicate=old==bundle
            if not duplicate:
                self._merge(streams,events,bundles,bundle)
                key=self._put('objects',bundle)
                entry={'sequence':head['sequence']+1,'previous':head['commit'],'bundle':key,'committed_at':now()}
                commit=self._put('commits',entry)
                # Authoritative commit point. Index failure after here is recoverable.
                atomic_json(self.root/'head.json',{'sequence':entry['sequence'],'commit':commit})
            error=None
            try:self._rebuild()
            except (OSError,sqlite3.Error,Rejected) as exc:error=type(exc).__name__+': '+str(exc)
            return {'batch_id':batch_id,'received_events':len(bundle['events']),'new_events':len(events)-before,
                'duplicate_events':len(bundle['events'])-(len(events)-before),'replayed':duplicate,
                'journal_committed':True,'index_status':'pending_rebuild' if error else 'ready','index_error':error,
                'formal_learning_not_asserted':True,'automatic_rules':False}

    def _projection(self):
        head,streams,events,bundles=self._load();versions=[];current={}
        for batch,b in streams.items():
            for e in b['events']:
                d=e['decision'];key=(batch,d['decision_id']);version=dict(batch_id=batch,event_id=e['event_id'],
                    decision_id=d['decision_id'],version=d['version'],decision=d,
                    source_bundle=digest(b),source_refs=e['source_refs'],layers=b['rows'][d['row_id']]['layers'],
                    authority=b['authorization'][e['event_id']])
                versions.append(version);current[key]=version
        return head,streams,events,versions,current

    def _rebuild(self):
        head,streams,events,versions,current=self._projection()
        temp=self.root/('index-'+uuid4().hex+'.tmp');connection=None
        try:
            connection=sqlite3.connect(temp)
            connection.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);'
                'CREATE TABLE versions(batch_id TEXT,decision_id TEXT,version INTEGER,event_id TEXT UNIQUE,payload TEXT NOT NULL,PRIMARY KEY(batch_id,decision_id,version));'
                'CREATE TABLE current_decisions(batch_id TEXT,decision_id TEXT,payload TEXT NOT NULL,PRIMARY KEY(batch_id,decision_id));')
            connection.execute('INSERT INTO metadata VALUES(?,?)',('head',digest(head)))
            connection.execute('INSERT INTO metadata VALUES(?,?)',('schema','2'))
            for v in versions:connection.execute('INSERT INTO versions VALUES(?,?,?,?,?)',(v['batch_id'],v['decision_id'],v['version'],v['event_id'],json.dumps(v,ensure_ascii=False)))
            for v in current.values():connection.execute('INSERT INTO current_decisions VALUES(?,?,?)',(v['batch_id'],v['decision_id'],json.dumps(v,ensure_ascii=False)))
            connection.commit();connection.close();connection=None
            with temp.open('r+b') as f:os.fsync(f.fileno())
            os.replace(temp,self.root/'index.sqlite3')
            atomic_json(self.root/'index_receipt.json',{'head_hash':digest(head),'index_sha256':sha(self.root/'index.sqlite3'),'schema':2})
        finally:
            if connection:connection.close()
            temp.unlink(missing_ok=True)
        return {'rebuilt_from':'committed_source_bundles_and_events','events':len(events),'versions':len(versions),
            'current_decisions':len(current),'head':head,'automatic_rules':False}

    def rebuild(self):
        with self._lock():return self._rebuild()

    def _ensure_index(self):
        head,*_=self._load()
        try:
            receipt=read(self.root/'index_receipt.json')
            if receipt['head_hash']!=digest(head) or receipt['index_sha256']!=sha(self.root/'index.sqlite3'):raise Rejected('索引需重建')
            with closing(sqlite3.connect(self.root/'index.sqlite3')) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise Rejected('索引损坏')
        except (OSError,ValueError,KeyError,sqlite3.Error,Rejected):self._rebuild()

    def _current(self,as_of):
        if date.fromisoformat(as_of).isoformat()!=as_of:raise Rejected('查询日期必须明确为YYYY-MM-DD')
        self._ensure_index();head,streams,events,versions,current=self._projection();output=[]
        with closing(sqlite3.connect(self.root/'index.sqlite3')) as db:
            rows=[json.loads(x[0]) for x in db.execute('SELECT payload FROM current_decisions ORDER BY batch_id,decision_id')]
        for value in rows:
            e=events[value['event_id']];b=streams[value['batch_id']];value['eligibility']=eligible(e,b,as_of)
            d=value['decision'];proof=d['reviews'].get('classification');group=None
            if proof:
                origin=next((x for x in b['events'] if x['decision_id']==d['decision_id'] and x['decision_version']==proof['decision_version']),None)
                if origin:
                    group=digest([b['batch_id'],origin.get('transaction_id') or origin['event_id'],proof['confirmed_by'],
                                  proof['credential_ref'],proof['reference'],'classification'])
            value['independent_approval_group']=group;output.append(value)
        return output

    def statistics(self,*,as_of):
        with self._lock():
            rows=self._current(as_of);head,streams,events,bundles=self._load()
            stats={'as_of':as_of,'events':len(events),'decision_versions':len(events),'current_decisions':len(rows),
                'formal_learning_samples':0,'test_learning_samples':0,'excluded_current_decisions':0,
                'formal_independent_approvals':0,'test_independent_approvals':0,'exclusion_reasons':{},
                'automatic_rules':False,'formal_output_authorized':False}
            groups={'formal':set(),'test':set()}
            for r in rows:
                q=r['eligibility']
                if q['eligible']:
                    stats[q['realm']+'_learning_samples']+=1
                    if r['independent_approval_group']:groups[q['realm']].add(r['independent_approval_group'])
                else:
                    stats['excluded_current_decisions']+=1
                    for reason in q['reasons']:stats['exclusion_reasons'][reason]=stats['exclusion_reasons'].get(reason,0)+1
            for realm in groups:stats[realm+'_independent_approvals']=len(groups[realm])
            return stats

    def search(self,criteria,*,as_of,realm='formal'):
        allowed={'product_type','purpose','complete_composition','key_material_features','construction'}
        if realm not in ('formal','test','quarantine'):raise Rejected('未知检索隔离区')
        if not isinstance(criteria,dict) or not criteria or set(criteria)-allowed or any(not isinstance(v,str) or not v.strip() for v in criteria.values()):
            raise Rejected('须明确商品类型/用途/组成/关键构造特征，不能按名称猜测或用空条件匹配')
        with self._lock():
            rows=self._current(as_of);matches=[]
            for r in rows:
                q=r['eligibility']
                if realm=='quarantine' and q['eligible']:continue
                if realm!='quarantine' and (not q['eligible'] or q['realm']!=realm):continue
                facts=r['decision']['facts'];basis=[]
                for key,wanted in criteria.items():
                    observed=facts.get(key,'')
                    # Explicit containment retrieval, not a learned semantic classifier or rule.
                    if normal(wanted) not in normal(observed):break
                    basis.append({'field':key,'query':wanted,'observed':observed,'method':'normalized_text_containment'})
                else:
                    r=copy.deepcopy(r);r.update(match_basis=basis,applicable_scope={
                        'identity':r['decision']['context'],'facts':facts,'tariff_conditions':r['decision']['human_final']},
                        effective_version=r['version'],retrieval_only=True,automatic_adoption=False)
                    matches.append(r)
            return {'as_of':as_of,'realm':realm,'criteria':criteria,'matches':matches,'count':len(matches),
                'automatic_adoption':False,'coverage_or_accuracy_claim':None}

    def integrity(self):
        with self._lock():
            head,streams,events,bundles=self._load();self._ensure_index()
            return {'passed':True,'commits':head['sequence'],'events':len(events),'source_bundles':len(bundles),
                'index_rebuildable':True,'format_version':self._metadata()['format_version'],
                'source_files_required_for_rebuild':False,'protection':'host_administrator_file_permissions_and_hash_chain_not_external_signature'}

    def history(self,batch_id,decision_id):
        with self._lock():
            head,streams,events,versions,current=self._projection()
            selected=[copy.deepcopy(v) for v in versions if v['batch_id']==batch_id and v['decision_id']==decision_id]
            for v in selected:v['is_current']=v['version']==current[(batch_id,decision_id)]['version']
            return {'batch_id':batch_id,'decision_id':decision_id,'versions':selected,'learning_eligibility_not_inferred_from_history':True}

    def _backup(self,target):
        target=external(target)
        if target.exists() or target.is_relative_to(self.root) or self.root.is_relative_to(target):raise Rejected('备份须使用库外全新目录')
        head,streams,events,bundles=self._load();target.mkdir(parents=True)
        paths=[self.root/'library.json',self.root/'head.json']
        # Only HEAD-reachable commits and bundles, not uncommitted crash remnants.
        pointer=head['commit'];keys=set()
        while pointer:
            path=self._objects('commits',pointer);paths.append(path);entry=read(path);keys.add(entry['bundle']);pointer=entry['previous']
        paths.extend(self._objects('objects',k) for k in keys)
        manifest={}
        for path in paths:
            relative=path.relative_to(self.root);dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,dest);manifest[relative.as_posix()]=sha(dest)
        atomic_json(target/'backup_manifest.json',{'schema':'japan-arrival/knowledge-backup-1','head':head,'files':manifest})
        return {'backup':str(target),'files':len(manifest),'index_included':False,'head':head}

    def backup(self,target):
        with self._lock():return self._backup(target)

    @classmethod
    def restore(cls,backup,target):
        backup=Path(backup).resolve();target=external(target)
        if target.exists() or target.is_relative_to(backup) or backup.is_relative_to(target):raise Rejected('恢复须使用独立全新目录')
        manifest=read(backup/'backup_manifest.json')
        if manifest['schema']!='japan-arrival/knowledge-backup-1':raise Rejected('未知备份版本')
        if not {'library.json','head.json'}<=set(manifest['files']):raise Rejected('备份缺少权威入口')
        for name,expected in manifest['files'].items():
            relative=Path(name);path=(backup/relative).resolve()
            if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(backup) or sha(path)!=expected:raise Rejected('备份路径或校验失败')
            if name not in ('library.json','head.json') and not (len(relative.parts)==2 and relative.parts[0] in ('objects','commits') and relative.suffix=='.json'):
                raise Rejected('备份含非权威文件')
        # Validate without relying on any pre-existing index and before creating destination.
        checker=cls(backup);checker._load()
        if read(backup/'head.json')!=manifest['head']:raise Rejected('备份HEAD不符')
        required={'library.json','head.json'};pointer=manifest['head']['commit']
        while pointer:
            relative='commits/'+pointer+'.json';required.add(relative);entry=read(backup/relative)
            required.add('objects/'+entry['bundle']+'.json');pointer=entry['previous']
        if required!=set(manifest['files']):raise Rejected('备份清单未完整覆盖提交链或夹带非提交对象')
        target.mkdir(parents=True)
        for name in manifest['files']:
            dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(backup/name,dest)
        for folder in ('objects','commits'):(target/folder).mkdir(exist_ok=True)
        restored=cls(target);restored.rebuild();restored.integrity();return restored

    def upgrade(self):
        with self._lock():
            meta=self._metadata();self._load()
            if meta['format_version']==FORMAT:return {'changed':False,'format_version':FORMAT}
            # v1 journal/commit representation is unchanged; v2 adds the derived SQLite schema.
            before=digest(read(self.root/'head.json'))
            backup=self.root.parent/(self.root.name+'-before-v2-'+uuid4().hex[:8]);self._backup(backup)
            meta['format_version']=FORMAT;meta['upgraded_at']=now();meta['upgrade_backup']=str(backup)
            atomic_json(self.root/'library.json',meta);self._rebuild()
            if digest(read(self.root/'head.json'))!=before:raise Rejected('升级不得改写历史事件')
            return {'changed':True,'from_version':1,'format_version':FORMAT,'backup':str(backup),'journal_unchanged':True}
