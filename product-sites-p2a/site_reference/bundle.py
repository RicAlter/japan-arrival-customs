"""Validate persisted candidate evidence before producing a B4 V1 source bundle."""
import json
import base64
from pathlib import Path

from .compat import Rejected,validate_response
from .client import sha
from .parser import parse
from source_adapters.common import canonical,write_bundle


def export(candidate_file,runtime,destination,*,authorization_reference,source_id):
    candidate_file=Path(candidate_file).resolve(strict=True);runtime=Path(runtime).resolve()
    batch=json.loads(candidate_file.read_text(encoding='utf-8'));records=[]
    source_version=sha(candidate_file.read_bytes())
    if batch.get('schema')!='product-site-candidate-batch/1':raise Rejected('候选批次结构无效')
    for result in batch['results']:
        core=validate_response(result['site_response'])
        if (result.get('query_mode')!='live_http' or result.get('fetch',{}).get('transport_mode')!='live_http'
                or core['status']!='succeeded' or result['identity_status']=='conflict'):
            continue
        if not result.get('access_scope',{}).get('authorization_reference'):raise Rejected('缺少实际站方授权引用')
        if core['identity']!=result['query_identity']:raise Rejected('候选查询身份与接口身份不一致')
        fetch=result['fetch'];receipt_path=runtime/'cache'/(sha(('live_http'+fetch['url']).encode())+'.json')
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        for key in ('url','final_url','content_sha256','retrieved_at','evidence_file','transport_mode'):
            if receipt.get(key)!=fetch.get(key):raise Rejected('候选与持久化抓取记录不一致')
        for reference in core['references']:
            if any(reference[k]!=fetch[f] for k,f in [('url','final_url'),('retrieved_at','retrieved_at'),('content_sha256','content_sha256'),('evidence_file','evidence_file')]):
                raise Rejected('候选引用与抓取来源不一致')
            relative=reference['evidence_file'];file=(runtime/relative).resolve(strict=True)
            if not file.is_relative_to(runtime/'evidence'):raise Rejected('候选证据路径越界')
            raw=file.read_bytes()
            if sha(raw)!=reference['content_sha256']:raise Rejected('候选证据哈希不一致')
            expected=result['query_identity'];parsed=parse(expected['code_raw'],raw.decode('utf-8'),expected)
            if parsed.get('identity_status')=='conflict' or parsed.get('material_original')!=reference['material_original']:
                raise Rejected('候选与原始网页复算不一致')
            if parsed.get('identity_status')!=result['identity_status']:raise Rejected('候选身份确认状态与复算不一致')
            if parsed.get('material_translation')!=reference['material_translation']:
                raise Rejected('候选译文与原始材质复算不一致')
            observed=parsed['observed_identity'];record_id=sha(canonical([reference['url'],reference['content_sha256'],observed]).encode())
            evidence_name='evidence/'+record_id+'.json'
            fields={}
            values={**observed,'material_original':reference['material_original'],'material_translation':reference['material_translation'],
                    'material_url':reference['url'],'material_site':'anime-store.jp'}
            for field,value in values.items():
                fields[field]={'value':value,'raw_value':value,
                    'reference_type':'historical_reference',
                    'translation_status':'provided_unreviewed' if field=='material_translation' and value else ('pending' if field=='material_translation' else 'not_applicable'),
                    'evidence':[{'file':evidence_name,'quote':reference['material_original'] if field.startswith('material_') else str(value) if value is not None else None}]}
            records.append({'source_record_id':record_id,'identity':observed,
                'provenance':{'source_id':source_id,'source_version':source_version,'file_sha256':reference['content_sha256'],
                              'file_name':file.name,'sheet':None,'row':1,'url':reference['url'],
                              'collected_at':reference['retrieved_at'],'content_sha256':reference['content_sha256']},
                'fields':fields,'status':'succeeded','review_status':'reference_only','approval':False,
                '_evidence':{evidence_name:{'url':reference['url'],'retrieved_at':reference['retrieved_at'],
                    'content_sha256':reference['content_sha256'],'identity_quote':reference['identity_quote'],
                    'observed_identity':observed,'material_original':reference['material_original'],
                    'material_translation':reference['material_translation'],'access_scope':result['access_scope'],
                    'identity_status':result['identity_status'],'raw_snapshot_base64':base64.b64encode(raw).decode('ascii')}}})
    if not records:raise Rejected('没有通过校验的真实成功候选；拒绝生成可导入包')
    # One page observed for repeated query rows contributes one source observation.
    records=list({r['source_record_id']:r for r in records}.values())
    request={'schema_version':'product-source-request/1','source_id':source_id,'source_version':source_version,
             'authorization_reference':authorization_reference,'mapping_version':'anime-product-identity-1',
             'files':[{'path':str(candidate_file)}]}
    return write_bundle(request,records,destination,'material')
