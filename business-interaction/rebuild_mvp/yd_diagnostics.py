"""Field-specific YD reasons, without interpreting a Chinese name as an ID."""
from collections import Counter


def explain_yd(rows,header_row=1):
    cases=[]
    exempt=[]
    for row in rows:
        if row['values'].get('yd'):continue
        if row.get('yd_requirement',{}).get('status')=='not_required':
            exempt.append({'row_id':row['row_id'],'source_row':row['source_row'],'output_row':row['source_row']-header_row+1,
                           'code':row['raw']['code'],'name':row['values'].get('name',''),'requirement':row['yd_requirement']})
            continue
        conflicts=[i for i in row.get('issues',[]) if i.get('field')=='yd' and 'CONFLICT' in i.get('code','')]
        name=row['values'].get('name','')
        if conflicts:
            reason='MULTIPLE_YD_CANDIDATES'
            text='相同编码/PCS/日文名关联到多个采购YD，可能涉及再贩或不同采购记录，当前没有足够依据自动选一个。'
        elif name:
            reason='NAME_FOUND_WITHOUT_RELIABLE_YD_LINK'
            text='中文名称已从业务汇总或商品资料取得，但这些记录没有可采用的YD；现有实际采购资料未建立唯一有效的对应关系。名称命中不等于采购YD已经确认。'
        else:
            reason='IDENTITY_AND_YD_UNRESOLVED'
            text='商品对应仍不明确，尚未取得可靠中文名称及YD。'
        cases.append({'row_id':row['row_id'],'source_row':row['source_row'],
                      'output_row':row['source_row']-header_row+1, 'carton':row['raw']['carton'],
                      'code':row['raw']['code'],'japanese_name':row['raw']['ja'],
                      'chinese_name':name,'reason_code':reason,'reason':text,
                      'name_sources':row['evidence'].get('name',[]),'matching_basis':row.get('matching',{}),
                      'YD_conflicts':conflicts})
    return {'total_missing':len(cases),'total_exempt':len(exempt),'exempt_rows':exempt,'with_chinese_name':sum(bool(c['chinese_name']) for c in cases),
            'reason_counts':dict(Counter(c['reason_code'] for c in cases)), 'rows':cases}
