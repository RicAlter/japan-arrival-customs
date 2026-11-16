"""Read-only, version-bound R3 delivery and audited weight-field adapters."""
from pathlib import Path
import re,unicodedata
from .service import MvpError,load_json,digest
from .storage import identity
from .quantity_sources import Evidence,norm
from .quantity_conversion import read_quantity_source
from .pricing_conversion import read_pricing_source
from .quantity_export import compare
from .xlsxio import read_book
from .quantity_math import number,exact
from .logistics_math import expand,frac


def upstream(quantity_ref,pricing_ref):
    q=read_quantity_source(quantity_ref);p=read_pricing_source(pricing_ref)
    if len({r['row_id']for r in q['rows']})!=len(q['rows']):raise MvpError('SOURCE_CHANGED','上游稳定行身份重复')
    if p['quantity_source']!=quantity_ref:raise MvpError('SOURCE_CHANGED','价税结果不属于此数量版本')
    if [(r['row_id'],r['scope'])for r in q['rows']]!=[(r['row_id'],r['scope'])for r in p['rows']]:
        raise MvpError('SOURCE_CHANGED','数量与价格行身份/顺序不符')
    if any(identity(qr)!=pr['quantity_row_sha256']for qr,pr in zip(q['rows'],p['rows'])):
        raise MvpError('SOURCE_CHANGED','价税引用数量行发生变化')
    task=Path(pricing_ref['path']).resolve().parent;job=load_json(task/'job.json')
    if (job.get('mode')!='price_tax'or job.get('step')!='exported'or job.get('pricing_source')!=pricing_ref
            or job['code']['sha256']!=p['code_sha256']or job['config']['quantity_source']!=quantity_ref
            or job['delivery']!=p['delivery']or len(job.get('business_files',[]))!=1):
        raise MvpError('SOURCE_CHANGED','价税交付与契约不符')
    path=Path(job['business_files'][0]).resolve(strict=True)
    sha=next((a['sha256']for a in job['artifacts']if Path(a['path']).resolve()==path),None)
    if not sha or digest(path)!=sha:raise MvpError('SOURCE_CHANGED','价税Excel发生变化')
    changes={}
    for row in p['rows']:
        inherited=row['inherited']['I'];ratio=row['pricing']['results'].get('purchase_ratio_round0')
        if inherited['value']==''and not inherited['formula']and ratio:changes['I'+str(row['row'])]=ratio['value']['numerator']
    compare(p['delivery']['path'],path,q['upstream']['sheet'],changes)
    return q,p,{'path':str(path),'sha256':sha,'job_path':str(task/'job.json'),'job_sha256':digest(task/'job.json'),
                'quantity_source':quantity_ref,'pricing_source':pricing_ref}


class WeightEvidence(Evidence):
    def __init__(self,path,batch_id,quantity_ref,pricing_ref):
        super().__init__(path,schema='arrival-carton-weight-evidence/1')
        d=self.data
        if d.get('batch_id')!=batch_id or d.get('quantity_source_sha256')!=quantity_ref['sha256']or d.get('pricing_source_sha256')!=pricing_ref['sha256']:
            raise MvpError('SOURCE_CHANGED','箱重依据须绑定同批次数量及价税版本')
        if d.get('coverage')not in {'partial','complete'}:raise MvpError('CONFIG_INVALID','须明确商品行是部分还是完整批次')
        if len(self.sources)!=1:raise MvpError('CONFIG_INVALID','箱重只绑定一个明确的本批版本')
        self.source=next(iter(self.sources.values()))
        if self.source['role']not in {'japanese_batch','reviewed_basics'}:raise MvpError('SOURCE_FORBIDDEN','箱重只用本批日方原始或明确保存资料')
        if d.get('weight_unit')not in {'KG','G'}or d.get('dimension_unit')not in {None,'CM','MM','M'}:
            raise MvpError('CONFIG_INVALID','重量及尺寸单位须明确，不按表头容积重量猜计费重')
        self.book=read_book(self.source['path'])
        matches=[s for s in self.book['sheets']if s['name']==d.get('sheet')]
        if len(matches)!=1:raise MvpError('CONFIG_INVALID','箱重工作表无法唯一定位')
        self.sheet=matches[0];self.rows={r['row']:r for r in self.sheet['rows']};self.columns=d.get('columns',{})
        expected={'carton','count','total_weight'};optional={'unit_weight','width','height','depth','volume'}
        if not expected<=set(self.columns)or set(self.columns)-expected-optional:
            raise MvpError('CONFIG_INVALID','箱重字段映射缺项或包含未知字段')
        if d.get('dimension_unit')and not {'width','height','depth'}<=set(self.columns):raise MvpError('CONFIG_INVALID','尺寸映射须完整')
        if not d.get('dimension_unit')and set(self.columns)&{'width','height','depth','volume'}:raise MvpError('CONFIG_INVALID','尺寸列须明确单位')
        cols=[m['column']for m in self.columns.values()]
        if len(set(cols))!=len(cols)or any(not re.fullmatch('[A-Z]{1,3}',c)for c in cols):raise MvpError('CONFIG_INVALID','映射列重复或无效')
        header=self.rows.get(d.get('header_row'),{})
        for mapping in self.columns.values():
            if not mapping.get('header')or header.get('values',{}).get(mapping['column'])!=mapping['header']or mapping['column']in header.get('formulas',{}):
                raise MvpError('FIELD_MAPPING_AMBIGUOUS','箱重实际表头与已审计字段不符')
        def stated_unit(text,kind):
            text=unicodedata.normalize('NFKC',text).upper()
            if kind=='weight':
                if re.search(r'KG|キログラム|千克|公斤',text):return 'KG'
                if re.search(r'(^|[^A-Z])G([^A-Z]|$)|グラム|克',text):return 'G'
            else:
                if 'CM'in text or '厘米'in text:return 'CM'
                if 'MM'in text or '毫米'in text:return 'MM'
                if re.search(r'(^|[^A-Z])M([^A-Z0-9]|$)',text)or text=='米':return 'M'
        for kind,keys in [('weight',['total_weight']),('dimension',['width','height','depth']if d.get('dimension_unit')else[])]:
            if not keys:continue
            declared=d[kind+'_unit'];known={stated_unit(self.columns[k]['header'],kind)for k in keys}
            if known-{None,declared}:raise MvpError('CONFIG_INVALID','已审计单位与实际原表单位冲突')
            if None in known:
                refs=self.refs(d.get(kind+'_unit_evidence',[]))
                if not refs or any(r['source_id']!=self.source['source_id']for r in refs)or {stated_unit(r['value'],kind)for r in refs}!={declared}:
                    raise MvpError('CONFIG_INVALID','单位缺实际表头或原始单位说明坐标')
        if 'unit_weight'in self.columns and stated_unit(self.columns['unit_weight']['header'],'weight')not in {None,d['weight_unit']}:
            raise MvpError('CONFIG_INVALID','单箱重和总重不能混用不同单位')
        if 'volume'in self.columns and not re.search(r'M3|立方米',unicodedata.normalize('NFKC',self.columns['volume']['header']).upper()):
            raise MvpError('CONFIG_INVALID','已有体积须明确为m³，不能冒充计费重量')
        self.start,self.end=d['detail_rows']
        if not all(isinstance(x,int)and not isinstance(x,bool)for x in [self.start,self.end])or not(d['header_row']<self.start<=self.end):
            raise MvpError('CONFIG_INVALID','箱重明细范围不合法')
        summaries=d.get('summary_rows',[])
        if len(set(summaries))!=len(summaries)or any(not isinstance(n,int)or n<=d['header_row']or self.start<=n<=self.end for n in summaries):
            raise MvpError('CONFIG_INVALID','箱重汇总行不得混入明细')
        if any(n not in self.rows for n in summaries):raise MvpError('CONFIG_INVALID','登记的汇总行不存在')
        self.summaries=summaries
        self.notes=d.get('note_rows',[])
        if len(set(self.notes))!=len(self.notes)or any(not isinstance(n,int)or n not in self.rows or n<=d['header_row']or self.start<=n<=self.end or n in summaries for n in self.notes):
            raise MvpError('CONFIG_INVALID','备注行范围不合法')
        auxiliary=d.get('auxiliary_rows',[]);self.auxiliary={x['row']:x for x in auxiliary}
        if len(self.auxiliary)!=len(auxiliary)or any(n not in self.rows or self.start<=n<=self.end or n in summaries or n in self.notes or n<=d['header_row']for n in self.auxiliary):
            raise MvpError('CONFIG_INVALID','辅助汇总行范围不合法')

    def proof(self,row,key):
        col=self.columns[key]['column'];r=self.rows[row]
        return {'path':self.source['path'],'source_id':self.source['source_id'],'source_sha256':self.source['sha256'],
                'source_version':self.source['version'],'sheet':self.sheet['name'],'row':row,'column':col,
                'value':r['values'].get(col,''),'formula':r['formulas'].get(col),'type':r['types'].get(col)}

    def group_facts(self):
        groups=[];issues=[];excluded=[]
        for n,r in sorted(self.rows.items()):
            if n<=self.data['header_row']:continue
            proofs={k:self.proof(n,k)for k in self.columns}
            active=any(x['value']!=''or x['formula']for x in proofs.values())
            if not active:continue
            if n in self.summaries:
                excluded.append({'row':n,'reason':'declared_summary_not_detail','evidence':proofs});continue
            if n in self.auxiliary:
                spec=self.auxiliary[n];references=spec.get('references',{});checked=[]
                if not references or not spec.get('reason'):raise MvpError('CONFIG_INVALID','辅助行须有原始引用及说明')
                for col in set(r['values'])|set(r['formulas']):
                    value=r['values'].get(col,'');formula=r['formulas'].get(col)
                    if number(value)is None and not formula:continue
                    target=references.get(col,'');m=re.fullmatch(r'([A-Z]+)([0-9]+)',target)
                    allowed={self.columns[k]['column']for k in ['count','total_weight','volume']if k in self.columns}
                    if not m or int(m[2])not in self.summaries or m[1]not in allowed or re.sub(r'[\s$=]','',formula or'')!=target:
                        raise MvpError('CONFIG_INVALID','辅助数字只能直接引用已登记主汇总，不能隐藏箱重明细')
                    expected=number(self.rows[int(m[2])]['values'].get(m[1]))
                    if expected is None or number(value)!=expected:raise MvpError('INPUT_INVALID','辅助汇总缓存与原始引用不符')
                    checked.append({'column':col,'formula':formula,'value':value,'summary_reference':target})
                if set(references)!={x['column']for x in checked}:raise MvpError('CONFIG_INVALID','辅助引用坐标不完整')
                excluded.append({'row':n,'reason':spec['reason'],'evidence':proofs,'checked_summary_references':checked});continue
            if n in self.notes:
                try:has_carton=bool(expand(proofs['carton']['value']))
                except ValueError:has_carton=False
                if has_carton or any(number(p['value'])is not None or p['formula']for p in proofs.values()):
                    raise MvpError('CONFIG_INVALID','数字/箱号/公式不能按备注排除')
                excluded.append({'row':n,'reason':'declared_non_numeric_note','evidence':proofs});continue
            if not self.start<=n<=self.end:
                issues.append({'code':'WEIGHT_UNCLASSIFIED_SOURCE_ROW','field':'source','row':n,'evidence':proofs});continue
            raw={k:p['value']for k,p in proofs.items()};problems=[]
            for key,p in proofs.items():
                if p['type']in {'b','e'}:
                    field={'total_weight':'weight','carton':'identity','unit_weight':'unit_weight','count':'count'}.get(key,'volume')
                    problems.append({'code':'WEIGHT_CELL_TYPE_INVALID','field':field,'evidence':p})
                formula=p['formula']
                if not formula:continue
                normalized=re.sub(r'[\s$=]','',formula).upper()
                factors=['unit_weight','count']if key=='total_weight'else['count','width','height','depth']if key=='volume'else[]
                expected='*'.join(self.columns[k]['column']+str(n)for k in factors)if all(k in self.columns for k in factors)else''
                if key=='volume':expected+='/'+{'CM':'1000000','MM':'1000000000','M':'1'}[self.data['dimension_unit']]
                independent=all(not proofs[k]['formula']and number(raw[k])is not None for k in factors)
                field={'total_weight':'weight','carton':'identity','unit_weight':'unit_weight','count':'count'}.get(key,'volume')
                if not factors or not independent or normalized!=expected:
                    problems.append({'code':'WEIGHT_FORMULA_UNSUPPORTED','field':field,'evidence':p})
                elif p['value']=='':problems.append({'code':'WEIGHT_FORMULA_CACHE_MISSING','field':field,'evidence':p})
            groups.append({'id':identity([self.source['sha256'],self.sheet['name'],n]),'row':n,'sheet':self.sheet['name'],
                           'carton_raw':raw['carton'],'raw':raw,'evidence':proofs,'issues':problems,
                           'weight_unit':self.data['weight_unit'],'dimension_unit':self.data.get('dimension_unit')})
        if not groups:issues.append({'code':'WEIGHT_DETAILS_EMPTY','field':'source'})
        return groups,issues,excluded

    def audit_summaries(self,inventory):
        output=[];issues=[]
        factor={'KG':1,'G':1000}[self.data['weight_unit']]
        for n in self.summaries:
            for key,metric in [('count','count'),('total_weight','weight_kg'),('volume','volume_m3')]:
                if key not in self.columns:continue
                p=self.proof(n,key);observed=number(p['value']);total=inventory[metric]
                expected=number(total['value'])if metric=='count'else frac(total['value'])
                if key=='total_weight'and expected is not None:expected*=factor
                formula_ok=not p['formula']or re.sub(r'[\s$=]','',p['formula']).upper()==f"SUM({p['column']}{self.start}:{p['column']}{self.end})"
                ok=total['complete']and expected is not None and observed==expected and formula_ok
                output.append({'field':metric,'evidence':p,'expected':exact(expected)if expected is not None else None,
                               'state':'source_checked'if ok else'pending'})
                if not ok:issues.append({'code':'WEIGHT_SUMMARY_UNRESOLVED','field':metric,'row':n})
        return output,issues


def carton_cell(sheet,n):
    rows={r['row']:r for r in sheet['rows']};source=n;merge=None
    if rows[n]['values'].get('A','')==''and 'A'not in rows[n]['formulas']:
        for label in sheet['merges']:
            m=re.fullmatch(r'A([0-9]+):A([0-9]+)',label)
            if m and int(m[1])<=n<=int(m[2]):source=int(m[1]);merge=label;break
    raw=rows[source]
    return raw['values'].get('A',''),{'source_row':source,'column':'A','value':raw['values'].get('A',''),
                                     'formula':raw['formulas'].get('A'),'type':raw.get('types',{}).get('A'),'merged_range':merge,'inherited_to_row':n if merge else None}


def item_fact(qrow,prow,sheet,delivery):
    value,proof=carton_cell(sheet,qrow['row']);issues=[]
    if norm(value)!=norm(qrow['scope']['carton']):issues.append({'code':'CARTON_SCOPE_MISMATCH','field':'carton'})
    if proof['formula']:issues.append({'code':'CARTON_FORMULA_UNSUPPORTED','field':'carton'})
    if proof['type']in {'b','e'}:issues.append({'code':'CARTON_CELL_TYPE_INVALID','field':'carton'})
    return {'row_id':qrow['row_id'],'row':qrow['row'],'sheet':qrow['sheet'],'scope':qrow['scope'],'carton_raw':value,
            'quantity_row_sha256':identity(qrow),'pricing_row_sha256':identity(prow),'issues':issues,
            'evidence':{**proof,'path':delivery['path'],'sha256':delivery['sha256']}}
