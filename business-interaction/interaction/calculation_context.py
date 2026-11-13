"""Keep original facts visible when only a partial supplier update is available.

No fallback from original observations to actual price, and no new arithmetic.
Optional reviewed input is hash-bound to this exact row identity and source role.
"""
from . import rt,load,put,digest,Rejected
from pathlib import Path
original_prepare=rt.review.prepare

def prepare(root):
    p=original_prepare(root);svc=rt.updates.Service(root);batch=svc.store.load(svc.bid)
    originals={r['id']:r for r in batch['rows']}
    manifest=Path(root)/'calculation-input-evidence.json'
    inputs={}
    if manifest.exists():
        lock=load(Path(root)/'calculation-input-evidence-lock.json')
        if digest(manifest)!=lock['sha256']:raise Rejected('计算输入证据摘要变化')
        evidence=load(manifest)
        if evidence['base_hash']!=p['base_hash']:raise Rejected('计算输入证据上游版本不符')
        for f,h in evidence['sources'].items():
            if digest(f)!=h:raise Rejected('计算输入来源变化：'+f)
        inputs=evidence['rows']
    p['headers'][7:11]=['日方更新实际价（原Qty口径）','日方价计价单位','日方Qty','Qty实际单位']
    p['headers'][18]='执行单价ROUND0（草稿，完整校验见AB）'
    p['headers']+=['原表到货数量（不替代日方更新）','原表日元单价观察','原表金额／公式缓存','基础表采购参考价（含待依据）',
                   '原表来源坐标','阶段提交材质O','税号依据状态','日方价格／单位异常','包装参考原文（非确认）',
                   '原Qty×原单价（仅保全核验）','原金额差额（应为0）','日方Qty×更新价（仅源表核验）','更新金额差额（应为0）',
                   '业务提交整行总单件数K','业务提交总单件数及口径出处']
    for r in p['rows']:
        old=originals[r['parent_id']];fs=r['basic_fields'];raw=old['raw'];i=inputs.get(r['parent_id'],{})
        if i and (i['jan']!=r['values'][2] or i['specification']!=r['values'][4]):raise Rejected('计算输入商品身份不符')
        for name,item in i.get('fields',{}).items():
            if name not in rt.review.EDIT.values() or item['role'] not in {'supplier_price','purchase_order','operator_submission','tax_reference'} or not item['source_ref'].strip():raise Rejected('计算输入角色/字段/出处不合格')
            col=next(c for c,k in rt.review.EDIT.items() if k==name)
            from openpyxl.utils.cell import column_index_from_string
            r['values'][column_index_from_string(col)-1]=item['value']
        r['values'] += [raw.get('quantity',raw.get('qty')),raw.get('price'),raw.get('amount'),fs.get('purchase_unit_price',{}).get('value',{}).get('value'),
            old['source']['sheet']+'!'+str(old['source']['row']),fs.get('material_reference',{}).get('value',{}).get('value'),
            i.get('hs_status','未找到本轮独立税号依据；不从历史最终成品反填'),
            '缺可靠日方实际价格' if r['raw'] is None else '日方更新价有来源；K总单件数口径已明确，采购单位/盒规仍独立核验',
            r.get('packaging_original_source',{}).get('display_text'),None,None,None,None,
            i.get('single_count'),i.get('single_count_source')]
        # O was submitted by the operator, never copied from R/S reference.
        r['values'][21]=fs.get('material_reference',{}).get('value',{}).get('value')
        r['values'][27]=i.get('checks') or r['values'][27]
    p['submission_policy']='stage-return-is-submission/20261111'
    for col,formula in {'AY':lambda n:f'=IF(AND(ISNUMBER(AP{n}),ISNUMBER(AQ{n})),AP{n}*AQ{n},"")',
        'AZ':lambda n:f'=IF(AND(ISNUMBER(AY{n}),ISNUMBER(AR{n})),AY{n}-AR{n},"")',
        'BA':lambda n:f'=IF(AND(ISNUMBER(J{n}),ISNUMBER(H{n})),J{n}*H{n},"")',
        'BB':lambda n:f'=IF(AND(ISNUMBER(BA{n}),ISNUMBER(L{n})),BA{n}-L{n},"")'}.items():
        p['formulas'][col]=[formula(n) for n in range(5,len(p['rows'])+5)]
    p['code'][str(Path(__file__))]=digest(__file__)
    body={k:v for k,v in p.items() if k not in {'plan_id','version_token'}};pid=put(svc.root,body)
    return {**body,'plan_id':pid,'version_token':pid}

rt.review.prepare=prepare
