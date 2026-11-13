"""A preparation boundary around existing parsers, reference APIs and math.

There is deliberately no confirmation, database writer, answer reader or pair
publisher here. Preparing a scope must never approve that scope.
"""
from collections import Counter, defaultdict
from contextlib import closing
from fractions import Fraction
import copy
import json
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
sys.path.insert(0,str(REPO/'operations-library-p3a'))
from integrated_arrival.support import dependencies,digest,key,load,save,check_hashes,Rejected
from integrated_arrival.library import inspect_database


def bootstrap():
    dependencies()
    pinned=load(ROOT/'dependency-lock.json')
    for relative,expected in pinned['files'].items():
        path=(REPO/relative).resolve(strict=True)
        if not path.is_relative_to(REPO) or digest(path)!=expected:raise Rejected('P3-C复用依赖变化：'+relative)
    return pinned


def source_key(carton,code):return (str(carton or '').strip(),str(code or '').strip())


def align(raw,plan):
    """Exact unique carton/code linkage only; never guesses recodes or splits."""
    left=defaultdict(list);right=defaultdict(list)
    for row in raw['rows']:
        left[source_key(row['logistics']['carton_raw'],row['identity']['code'])].append(row)
    for row in plan['details']:
        v=row['values'];right[source_key(v['箱号'],v['商品编码'])].append(row)
    linked=[];unmatched_raw=[];linked_ids=set();conflicts=[];formatting=[]
    for row in raw['rows']:
        k=source_key(row['logistics']['carton_raw'],row['identity']['code'])
        matches=right.get(k,[])
        if not k[1] or len(left[k])!=1 or len(matches)!=1:
            unmatched_raw.append({'raw_row_id':row['id'],'source':row['source'],'carton':k[0],'code':k[1],
                                  'reason':'no_unique_exact_carton_code_match'});continue
        other=matches[0];v=other['values'];rid=v['稳定行号'];linked_ids.add(rid)
        differences=[]
        # Same code is only a source link, not an identity approval.
        raw_name=row['identity']['japanese_name'];operations_name=v['日文品名']
        if raw_name.strip()!=operations_name.strip():differences.append('japanese_name')
        elif raw_name!=operations_name:
            formatting.append({'raw_source':row['source'],'operations_source':other['fields']['日文品名'],
              'raw_name':raw_name,'operations_name':operations_name,'comparison_only':'outer_whitespace_ignored',
              'original_values_preserved':True,'business_confirmation_required':False})
        if Fraction(row['authority']['quantity'])!=Fraction(v['业务确认数量']):differences.append('quantity')
        entry={'raw_row_id':row['id'],'operations_row_id':rid,'raw_source':row['source'],
               'operations_source':other['fields']['业务确认数量'],'identity_confirmed':False,
               'current_source_differences':differences}
        linked.append(entry)
        if differences:conflicts.append(entry)
    unmatched_ops=[{'row_id':r['values']['稳定行号'],'source':r['fields']['商品编码'],
                    'carton':r['values']['箱号'],'code':r['values']['商品编码'],
                    'reason':'no_unique_exact_raw_match'} for r in plan['details'] if r['values']['稳定行号'] not in linked_ids]
    return {'linked':linked,'unmatched_raw':unmatched_raw,'unmatched_operations':unmatched_ops,
            'current_source_conflicts':conflicts,'source_formatting_differences':formatting,'raw_order_retained':True,
            'recodes_inferred':0,'splits_inferred':0,'automatic_identity_approval':False}


def conversion_groups(plan,mapping):
    """Observed quantity equations, bound to source cells and the current rows.

    Different internal pieces/box relations stay separate even when the
    declaration factor is equal. Names/BOX/全n種 are never rule inputs.
    """
    linked={r['operations_row_id'] for r in mapping['linked']};groups={}
    for row in plan['details']:
        v=row['values'];factor=Fraction(v['申报数量'])/Fraction(v['业务确认数量'])
        if factor==1:continue
        pieces=Fraction(v['内部数量'])/Fraction(v['内部盒数'])
        a=row['fields']['业务确认数量'];b=row['fields']['申报数量'];boxes=row['fields']['内部盒数']
        signature={'declaration_factor':str(factor),'internal_pieces_per_box':str(pieces),
                   'business_source':{'sha256':a['sha256'],'sheet':a['sheet'],'column':a['cell'].rstrip('0123456789')},
                   'declaration_source':{'sha256':b['sha256'],'sheet':b['sheet'],'column':b['cell'].rstrip('0123456789')},
                   'box_source':{'sha256':boxes['sha256'],'sheet':boxes['sheet'],'column':boxes['cell'].rstrip('0123456789')}}
        gid=key(signature)[:24]
        if gid not in groups:groups[gid]={'id':gid,'relation':signature,'rows':[],
          'status':'needs_scope_confirmation','approved':False,'rule_scope':'this_source_bundle_only',
          'notice':'来源数值关系，不代表通用盒规或未配对身份已经确认'}
        groups[gid]['rows'].append({'row_id':v['稳定行号'],'raw_link_exists':v['稳定行号'] in linked,
          'business_quantity':v['业务确认数量'],'declaration_quantity':v['申报数量'],
          'internal_boxes':v['内部盒数'],'internal_quantity':v['内部数量'],
          'evidence':{'business_quantity':a,'declaration_quantity':b,'internal_boxes':boxes},
          'source_packaging_text':row['preserved'].get('specification')})
    for g in groups.values():
        g['row_count']=len(g['rows']);g['unmatched_raw_scope_rows']=sum(not r['raw_link_exists'] for r in g['rows'])
        g['scope_hash']=key({'relation':g['relation'],'rows':g['rows'],'source_bundle_hash':plan['source_bundle_hash']})
    result=list(groups.values())
    observed=[r['row_id'] for g in result for r in g['rows']]
    if len(observed)!=len(set(observed)) or set(observed)!={r['row_id'] for r in plan['special_conversions']}:
        raise Rejected('换算分组与原适配器特殊范围不一致')
    return result


def references(info,raw,source_hashes):
    """Reuse read-only APIs; mask known target lineage before accepting results."""
    from product_reference.database import read_only
    from product_reference.query import BatchQuery
    from offline_identity.lookup import batch_query
    from offline_identity.analyze import analyze
    target='KMT20261002';excluded_sources=set();excluded_hashes=set(source_hashes)
    def same_batch(s):
        label=' '.join(str(s.get(k,'')) for k in ('file_name','path','batch_id','source_id')).casefold()
        return s.get('file_sha256',s.get('sha256')) in excluded_hashes or target.casefold() in label
    with closing(read_only(info['path'])) as c:
        for table in ('source_ingest_corrections','manual_overrides','p2b_basic_events'):
            exists=c.execute("select 1 from sqlite_master where type='table' and name=?",(table,)).fetchone()
            if exists and c.execute('select count(*) from '+table).fetchone()[0]:
                raise Rejected('本阶段人工维护来源需独立隔离，不能自动带入：'+table)
        for r in c.execute('select source_id,record_json from source_ingest_observations'):
            s=json.loads(r['record_json'])['provenance']
            if same_batch(s):
                excluded_sources.add(r['source_id'])
                if s.get('file_sha256'):excluded_hashes.add(s['file_sha256'])
    queries=[{'row_id':r['id'],'code_raw':r['identity']['code'] or None,
      'code_type':'source_identifier' if r['identity']['code'] else None,
      'japanese_name':r['identity']['japanese_name'] or None,'version':None,'specification':None} for r in raw['rows']]
    p1=BatchQuery(info['path']).run(queries,exclude_source_ids=sorted(excluded_sources),exclude_file_sha256=sorted(excluded_hashes))
    for row in p1['rows']:
        for candidate in row['candidates']+row['rejected_candidates']:
            if any(same_batch(s) or s.get('source_id') in excluded_sources for s in candidate['sources']):
                raise Rejected('P1返回待测批来源，查询失效')
    overlay=None;excluded_facts=[]
    if info['p2b_available']:
        request=[{'row_id':q['row_id'],'query':{k:v for k,v in q.items() if k!='row_id'},'context':{}} for q in queries]
        original=batch_query(info['path'],request,batch_id=target)
        facts=[]
        for f in original['facts']:
            if f.get('approval') is not False or f.get('review_status')!='reference_only':raise Rejected('非法来源批准状态')
            if same_batch(f['source']):excluded_facts.append(f['fact_id'])
            else:facts.append(f)
        # Never consume the precomputed rows/metrics containing excluded facts.
        overlay=analyze(p1,facts,{},target_batch_id=target)
        overlay['facts']=facts
    if digest(info['path'])!=info['sha256']:raise Rejected('只读查询期间库变化')
    if [r['row_id'] for r in p1['rows']]!=[r['id'] for r in raw['rows']]:raise Rejected('查询改变原行序')
    return {'p1':p1,'p2b':overlay,'excluded_source_ids':sorted(excluded_sources),
      'excluded_file_sha256':sorted(excluded_hashes),'excluded_p2b_fact_ids':excluded_facts,
      'current_values_applied':0,'automatic_identity_approval':False,'material_approval':False,
      'namespace_basis':'same raw source code; source_identifier, JAN not inferred',
      'scope':'retrospective reference retrieval, not independent new batch coverage'}


def execute(output,request):
    output=Path(output).resolve()
    if output.exists():raise Rejected('准备输出必须是新目录，不覆盖旧现场')
    allowed={'batch_id','raw_file','business_file','declaration_file','library_config'}
    if not isinstance(request,dict) or set(request)-allowed or request.get('batch_id')!='KMT20261002':
        raise Rejected('本阶段仅接受KMT20261002来源准备，不接受确认、最终答案或正式输出参数')
    if not isinstance(request.get('raw_file'),str):raise Rejected('缺少日方原始附件路径')
    if bool(request.get('business_file'))!=bool(request.get('declaration_file')):raise Rejected('第3＋4步上下文须配套提供或均不提供')
    paths=[Path(request[k]).resolve(strict=True) for k in ('raw_file','business_file','declaration_file') if request.get(k)]
    if len(set(paths))!=len(paths):raise Rejected('来源角色不能使用同一文件')
    for path in paths:
        if output.is_relative_to(path.parent) or path.is_relative_to(output):raise Rejected('输出须与原件目录隔离')
    output.mkdir(parents=True);technical=output/'technical';technical.mkdir();snapshot={};stage='dependencies'
    result={'schema':'p3c-raw-operations-preparation/1','status':'validation_incomplete',
      'business_exception_total':None,'manual_input_cells':None,'business_files':[],
      'preparation_files':[],'can_enter_pair_calculation':False,'formal_output':False,
      'independent_new_batch_status':'not_verified','actual_human_actions':None,'time_saved_seconds':None}
    try:
        lock=bootstrap();snapshot={str(p):digest(p) for p in paths}
        stage='raw_identification'
        from arrival_core.importer import import_raw_invoice
        from arrival_core.preliminary import export_preliminary
        from arrival_core.logistics import read_weights,reconcile_logistics
        raw=import_raw_invoice(paths[0])
        raw['product_data_policy']='single-person-v1'  # YD absent is legal, no inferred values.
        save(technical/'raw-observations.json',raw)
        stage='readonly_library'
        cfg=request.get('library_config')
        if not isinstance(cfg,dict) or set(cfg)!={'database'}:raise Rejected('资料库配置只接受只读database路径')
        info=inspect_database({'database':cfg['database'],'current_batch_id':'KMT20261002'})
        if Path(info['path']).is_relative_to(output):raise Rejected('资料库须与新输出隔离')
        snapshot[info['path']]=info['sha256']
        candidates=references(info,raw,set(snapshot.values()))
        save(technical/'reference-candidates.json',candidates)
        # Display lookup state only. Do not copy candidates into product/material.
        display=copy.deepcopy(raw)
        for row,candidate in zip(display['rows'],candidates['p1']['rows']):
            row['product_lookup']['status']=candidate['status']+'（仅参考，未采用）'
        display['arrival_summary']['product_reference_matches']=sum(bool(r['candidates']) for r in candidates['p1']['rows'])
        stage='preliminary'
        preliminary=export_preliminary(display,technical/'KMT_初步业务整理.xlsx')
        weights=read_weights(paths[0],'重さとサイズ');logistics=reconcile_logistics(raw['rows'],weights)
        save(technical/'logistics.json',logistics)
        groups=[];mapping=None;plan=None
        if request.get('business_file'):
            stage='operations_context'
            from arrival_core.operations_adapter import prepare
            plan=prepare([str(p) for p in paths[1:]],(),None)
            if plan['business_profile']!='kmt-stage3-v1' or plan['completed_input']:raise Rejected('仅接第3＋4步，不把已填执行价成品作为准备输入')
            if any(r['execution_input'].get('price') not in (None,'') or r['execution_input'].get('amount') not in (None,'') for r in plan['details']):
                raise Rejected('最终执行价不能进入准备输入')
            mapping=align(raw,plan);groups=conversion_groups(plan,mapping)
            save(technical/'source-linkage.json',mapping);save(technical/'conversion-groups.json',groups)
            save(technical/'operations-input-candidate.json',{'status':'pending_confirmation','plan':plan,
              'linkage':mapping,'current_values_from_operations_context':True,
              'no_new_identity_or_material_approval':True,'confirmed_arrival_v1_generated':False})
        pending=[{'kind':'business_amount_authority','action':'确认第3步是否为本批数量/金额及现有业务字段基准；已有值不重填'},
                 {'kind':'batch_units','action':'确认实际业务/内部/申报单位，未从商品名推断'}]
        if plan:
            pending += [{'kind':'conversion_scope','group_id':g['id'],'scope_hash':g['scope_hash'],
                         'rows':g['row_count'],'unmatched_raw_rows':g['unmatched_raw_scope_rows']} for g in groups]
            if mapping['unmatched_raw'] or mapping['unmatched_operations']:
                pending.append({'kind':'unresolved_source_linkage','raw_rows':len(mapping['unmatched_raw']),
                  'operations_rows':len(mapping['unmatched_operations']),'action':'保留源行异常；不得按名称、金额合计或最终答案推断改码/拆行'})
            if mapping['current_source_conflicts']:pending.append({'kind':'current_source_conflict','rows':len(mapping['current_source_conflicts'])})
        else:pending.append({'kind':'missing_operations_context','action':'缺第3＋4步确认资料，原表不能自动生成已确认名称/材质/金额/换算'})
        if not logistics['passed']:pending.append({'kind':'logistics','action':'原箱号/箱数/箱组总重未通过'})
        facts={'raw_rows':len(raw['rows']),'raw_retail_subtotal_jpy':raw['arrival_summary']['subtotal_jpy'],
          'raw_quantity_sum_mixed_units':raw['arrival_summary']['qty_numeric_sum'],
          'operations_rows':len(plan['details']) if plan else None,
          'business_source_amount_jpy':str(sum((Fraction(r['values']['业务确认金额JPY']) for r in plan['details']),Fraction())) if plan else None,
          'exact_source_links':len(mapping['linked']) if mapping else None,
          'unmatched_raw_rows':len(mapping['unmatched_raw']) if mapping else None,
          'unmatched_operations_rows':len(mapping['unmatched_operations']) if mapping else None,
          'current_source_conflict_rows':len(mapping['current_source_conflicts']) if mapping else None,
          'source_formatting_difference_rows':len(mapping['source_formatting_differences']) if mapping else None,
          'special_conversion_rows':sum(g['row_count'] for g in groups) if plan else None,
          'conversion_confirmation_groups':len(groups) if plan else None,
          'library_status_counts':candidates['p1']['summary'],'historical_candidates_applied':0,
          'units_confirmed':False,'identity_approved':False,'material_approved':False}
        save(technical/'pending-confirmations.json',{'facts':facts,'pending':pending,
          'not_business_exception_total':True,'actual_manual_work_unmeasured':True})
        note='本次仅完成原始观察和运营候选准备。零售Subtotal不替代第3步金额；历史候选不覆盖当前值。\n'
        note+=f'原件{facts["raw_rows"]}行，运营上下文{facts["operations_rows"]}行；精确来源对应{facts["exact_source_links"]}行。\n'
        note+=f'未配对原行{facts["unmatched_raw_rows"]}、后续行{facts["unmatched_operations_rows"]}，保持异常，不推断改码或拆行。\n'
        note+=f'特殊换算{facts["special_conversion_rows"]}行，按来源数量关系组成{facts["conversion_confirmation_groups"]}组；按组核对当前范围，无需重复填每行。\n'
        for n,g in enumerate(groups,1):
            note+=f'组{n}：申报/业务数量比={g["relation"]["declaration_factor"]}，内部数量/盒数={g["relation"]["internal_pieces_per_box"]}；{g["row_count"]}行，其中未配对{g["unmatched_raw_scope_rows"]}行。\n'
        note+='分组只确认当前来源数量关系；带未配对行的范围仍须先解决来源身份，不能据此自动改码/拆行。\n'
        note+='待确认：第3步业务基准、实际单位、分组范围和未配对来源。已有名称/材质/F/备注/YD不因资料库缺项要求重填。\n'
        note+='未进行真人确认，不生成两张结果表；实际业务异常总数及人工量尚未验证。\n'
        (technical/'必要确认说明.txt').write_text(note,encoding='utf-8')
        stage='integrity';check_hashes(snapshot);bootstrap()
        # The preliminary display copy may contain query status, never adoption.
        for original,shown in zip(raw['rows'],display['rows']):
            if original['product']!=shown['product'] or original['material']!=shown['material']:raise Rejected('候选覆盖原始数据')
        if key(raw)!=key(load(technical/'raw-observations.json')):raise Rejected('准备改变原始观察')
        frozen={str(p):digest(p) for p in technical.iterdir() if p.is_file()}
        save(output/'preparation-snapshot.json',{'files':frozen,'input_hashes':snapshot,
          'answers_read':False,'formal_output':False,'dependency_files_checked':len(lock['files'])})
        result.update({'status':'needs_confirmation' if plan else 'needs_input','stage':'preparation_complete','facts':facts,
          'pending_confirmations':pending,'preparation_files':[preliminary['file'],str(technical/'必要确认说明.txt')],
          'snapshot':str(output/'preparation-snapshot.json'),'input_and_database_unchanged':True,
          'reason':'原始来源对应、业务金额基准、单位及换算范围尚未明确确认；未进入双表计算'})
        save(output/'result.json',result);return result
    except Exception as exc:
        save(technical/'failure.json',{'stage':stage,'reason':str(exc),'traceback':traceback.format_exc()})
        result.update(stage=stage,reason=str(exc));save(output/'result.json',result);return result
