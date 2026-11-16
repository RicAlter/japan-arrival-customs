"""R2/R3 immutable graph and explicit customs-only field licenses."""
from pathlib import Path
import re
from .service import MvpError,load_json,digest,HERE
from .storage import identity
from .quantity_sources import Evidence,norm,read_upstream
from .quantity_conversion import read_quantity_source
from .pricing_conversion import read_pricing_source
from .logistics_conversion import read_logistics_source

TEMPLATE=HERE/'dual_templates.json'
FIELDS={'customs_name':('C',{'海关申报品名','海关品名','对外品名','Items & Descriptions'}),
        'brand':('H',{'品牌','对外品牌'}),'public_name':('I',{'对外商品名','海关品名','申报品名'}),
        'category':('J',{'品类','商品品类'}),'label_required':('L',{'是否需要打标签','标签要求'}),
        'material':('M',{'材质','最终申报材质','申报材质'}),'size':('N',{'尺寸','商品尺寸'}),
        'specification':('O',{'规格','对外规格'})}


def graph(config):
    q=read_quantity_source(config['quantity_source']);p=read_pricing_source(config['pricing_source']);l=read_logistics_source(config['logistics_source'])
    if l['quantity_source']!=config['quantity_source']or l['pricing_source']!=config['pricing_source']or p['quantity_source']!=config['quantity_source']:
        raise MvpError('SOURCE_CHANGED','双表不能混用不同数量/价税/箱重版本')
    r2=read_upstream(config['review_task_root'],config['reviewed_source'])
    if r2!=q['upstream']or config['batch_id']!=r2['batch_id']:raise MvpError('SOURCE_CHANGED','R2保存版本/批次与R3不一致')
    identities=[(r['row_id'],r['row'],r['sheet'],r['scope'])for r in q['rows']]
    if not identities:raise MvpError('INPUT_INVALID','没有可投影的已保存商品行')
    for data in [p,l]:
        if identities!=[(r['row_id'],r['row'],r['sheet'],r['scope'])for r in data['rows']]:raise MvpError('SOURCE_CHANGED','上游出荷行身份/顺序不符')
    if len({r['row_id']for r in q['rows']})!=len(q['rows']):raise MvpError('SOURCE_CHANGED','上游行身份重复')
    for qr,pr,lr in zip(q['rows'],p['rows'],l['rows']):
        if lr['quantity_row_sha256']!=identity(qr)or lr['pricing_row_sha256']!=identity(pr):raise MvpError('SOURCE_CHANGED','箱重行未绑定此数量/价税行')
    task=Path(config['logistics_source']['path']).resolve().parent;job=load_json(task/'job.json')
    if job.get('step')!='exported'or job.get('mode')!='carton_weight'or job.get('logistics_source')!=config['logistics_source']or job['code']['sha256']!=l['code_sha256']or job['delivery']!=l['delivery']or len(job.get('business_files',[]))!=1:
        raise MvpError('SOURCE_CHANGED','箱重交付与契约不符')
    file=Path(job['business_files'][0]).resolve(strict=True);sha=next((x['sha256']for x in job['artifacts']if Path(x['path']).resolve()==file),None)
    if not sha or digest(file)!=sha or sha!=l['delivery']['sha256']:raise MvpError('SOURCE_CHANGED','箱重交付不再是原价税副本')
    return q,p,l,{'path':str(file),'sha256':sha,'job_path':str(task/'job.json'),'job_sha256':digest(task/'job.json'),'r2':r2}


class ProjectionEvidence(Evidence):
    def __init__(self,path,config):
        super().__init__(path,schema='arrival-projection-evidence/1')
        d=self.data;template=load_json(TEMPLATE)
        expected={'quantity_source_sha256':config['quantity_source']['sha256'],'pricing_source_sha256':config['pricing_source']['sha256'],'logistics_source_sha256':config['logistics_source']['sha256'],'reviewed_source_sha256':config['reviewed_source']['sha256']}
        if d.get('batch_id')!=config['batch_id']or any(d.get(k)!=v for k,v in expected.items()):raise MvpError('SOURCE_CHANGED','投影依据须绑定同批R2及全部R3版本')
        if d.get('internal_template')!=template['internal_id']or d.get('customs_template')!=template['customs_id']or d.get('template_sha256')!=digest(TEMPLATE):raise MvpError('CONFIG_INVALID','未绑定当前认可模板')
        if any(s['role']not in {'reviewed_basics','business_summary'}for s in self.sources.values()):raise MvpError('SOURCE_FORBIDDEN','海关资料只取明确业务主表/保存来源，不取旧成品或官方商品售价')
        if any(s['sha256']in template['layout_only_source_shas']for s in self.sources.values()):raise MvpError('SOURCE_FORBIDDEN','认可模板仅许可版式，不能改声明角色采用其历史业务数据')
        if sum(s['role']=='business_summary'for s in self.sources.values())>1:raise MvpError('CONFIG_INVALID','海关字段只绑定一个明确主表版本')
        self.versions.append({'path':str(TEMPLATE),'sha256':digest(TEMPLATE)})
        self.index={}
        for row in d.get('rows',[]):self.index.setdefault((row.get('sheet'),row.get('row')),[]).append(row)

    def public(self,row):
        found=self.index.get((row['sheet'],row['row']),[])
        if not found:return {},[]
        if len(found)!=1:return {},[{'code':'PUBLIC_IDENTITY_AMBIGUOUS','field':'public_fields'}]
        record=found[0]
        if set(record.get('scope',{}))!=set(row['scope'])or any(norm(record['scope'][k])!=norm(v)for k,v in row['scope'].items()):return {},[{'code':'PUBLIC_SCOPE_MISMATCH','field':'public_fields'}]
        result={};issues=[]
        for field,spec in record.get('fields',{}).items():
            try:
                if field not in FIELDS or spec.get('state')not in {'reviewed_reference','reviewed_value'}:raise MvpError('INPUT_INVALID','海关字段/采用状态未明确')
                refs=self.refs(spec['evidence']);headers=self.refs(spec['header_evidence']);ids=self.refs(spec['identity_evidence'])
                for ref in refs:
                    if ref['value']!=str(spec['value'])or not any(h['source_id']==ref['source_id']and h['sheet']==ref['sheet']and h['column']==ref['column']and h['row']<ref['row']and norm(h['value'])in {norm(x)for x in FIELDS[field][1]}for h in headers):raise MvpError('INPUT_INVALID','海关字段与原格/许可表头不符')
                    matching=[i for i in ids if i['source_id']==ref['source_id']and i['sheet']==ref['sheet']and i['row']==ref['row']]
                    if not matching or not all(i.get('field')in {'code','ja','specification'}and norm(i['value'])==norm(row['scope'].get(i['field'],''))for i in matching)or not any(i['field']in {'code','ja'}for i in matching):raise MvpError('INPUT_INVALID','海关字段缺同记录商品身份')
                    if norm(row['scope'].get('specification',''))and not any(i['field']=='specification'for i in matching):raise MvpError('INPUT_INVALID','海关字段缺具体SKU规格范围')
                if not str(spec['value']).strip():raise MvpError('INPUT_INVALID','海关字段原格为空')
                result[field]={**spec,'evidence':refs,'header_evidence':headers,'identity_evidence':ids,'professional_approved':False}
            except (MvpError,KeyError,TypeError)as exc:issues.append({'code':getattr(exc,'code','INPUT_INVALID'),'field':field,'message':str(exc)})
        return result,issues
