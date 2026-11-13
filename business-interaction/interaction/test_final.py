"""Explicit local flow-test final projection. Never creates business approvals."""
from pathlib import Path
from copy import deepcopy
from fractions import Fraction
import json,re,subprocess,zipfile,xml.etree.ElementTree as ET
from . import load,save,key,digest,Rejected
from .calculation_view import CalculationView,scalar
from .stage2_math import calculate,number
from arrival_core.colored_operations import execution
from arrival_core.logistics import read_weights,reconcile_logistics
from arrival_core import _p0_frozen as p0

POLICY='pending-reference-flow-test/20261113'
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
CUSTOMS=['箱号','品番','Items & Descriptions','原产地','盒数参考','单个总数','取整单个价JPY','品牌','品名','品类','是否盲盒','标签','材质','尺寸','规格','金额JPY','箱数CTNs','单箱重KG','箱组总重KG']
INTERNAL=['箱号','产地','商品编码','JC','商品','规格','日文品名','盒数参考','原Qty','日方原价JPY','原金额JPY','品类','材质','每盒原Qty数','关税率参考','每原Qty增值税JPY','每原Qty关税JPY','每盒税金JPY','YD编码','备注','本行税金JPY']

def project(facts,values):
    """Reuse exact stage-two and accepted ROUND0 execution; references stay references."""
    customs=[];internal=[];colors={'customs':{},'internal':{}};trace=[]
    def mark(kind,col,row,color='yellow'):colors[kind][col+str(row)]=color
    for f in facts:
        n=f['source_row'];v=values[n-1];r=calculate(f,total=v[10]);out=len(internal)+4
        if any(v[i]!=f[k]for i,k in [(11,'quantity'),(12,'price'),(13,'amount')]):raise Rejected('原数量/价格/金额与绑定不符：'+str(n))
        if r['rounded_price']is None or number(v[13])!=number(v[11])*number(v[12]):raise Rejected('原算术来源不完整：'+str(n))
        for i,j in [(21,3),(22,7),(23,8),(24,13),(25,14)]:
            a,b=number(v[i]),number(r['values'][j])
            if (a is None)!=(b is None)or a is not None and abs(a-b)>Fraction(1,10**7):raise Rejected('已保存计算结果与重算不符：'+str(n))
        q,u,s=number(v[11]),number(v[12]),number(v[10]);factor=s/q
        e=execution({'authority':{'quantity':str(q),'amount':str(number(v[13]))},'packaging':{'declaration_factor':str(factor)}})
        b=r['values'][3];perbox=r['values'][5];duty,vat=r['values'][9:11]
        c=[v[0],str(v[2]),v[9],{'JP':'Japan','CN':'China','VN':'Vietnam'}.get(v[1],v[1]),scalar(b),scalar(s),e['price'],None,v[14],v[14],None,None,v[15],None,None,scalar(e['amount']),None,None,None]
        i=[v[0],v[1],str(v[2]),str(v[3])if v[3]is not None else None,v[5],v[6],v[9],scalar(b),v[11],v[12],v[13],v[14],v[15],scalar(perbox),scalar(duty),scalar(r['values'][12]),scalar(r['values'][11]),scalar(r['values'][13]),v[17],None,scalar(r['values'][14])]
        if '缺独立盒规，参考盒数待核'in r['errors']and'整盒'in str(f['identity'].get('spec')or''):
            for col in ['H','N','R']:mark('internal',col,out)
            mark('customs','E',out)
        if not v[6]:mark('internal','F',out)
        if v[7]is None:mark('internal','E',out)
        for kind,cols in [('internal',['L','M']),('customs',['I','J','M'])]:
            for col in cols:
                idx=ord(col)-65
                if (i if kind=='internal'else c)[idx]in(None,''):mark(kind,col,out,'red')
        for col in ['O','P','Q','R','U']:mark('internal',col,out,'yellow'if i[ord(col)-65]is not None else'red')
        if e['rounded']:
            for col in ['G','P']:mark('customs',col,out)
        if any('冲突'in error or'不能整除'in error for error in r['errors']):
            for col in ['H','R']:mark('internal',col,out,'red')
            mark('customs','E',out,'red')
        customs.append(c);internal.append(i)
        trace.append({'source_row':n,'result_row':out,'identity':f['identity'],'exact_factor':str(factor),'exact_boxes':str(b)if b is not None else None,'errors':r['errors'],'execution':{k:str(value)if isinstance(value,Fraction)else value for k,value in e.items()},'professional_approval':False})
    # Public fields exclude internal full names and YD; suppress accidental text collisions.
    private={str(f['identity'][k])for f in facts for k in ['name','yd']if f['identity'].get(k)}
    privacy=re.compile('|'.join(re.escape(token)for token in sorted(private,key=len,reverse=True)if len(token)>=4))if private else None
    for row,c in enumerate(customs,4):
        for col,value in enumerate(c):
            if isinstance(value,str)and privacy and privacy.search(value):
                c[col]=None;mark('customs',chr(65+col),row,'red')
    return {'customs':{'headers':CUSTOMS,'rows':customs},'internal':{'headers':INTERNAL,'rows':internal},'colors':colors,'trace':trace,
            'vat_rates':[scalar(number(f.get('vat_rate')))for f in facts],
            'totals':{'pieces':sum(number(v[5])for v in customs),'original_amount':sum(number(v[10])for v in internal),'rounded_amount':sum(number(v[15])for v in customs)}}

def inputs(service):
    setting=service.config.get('flow_test_final')
    if not setting or setting.get('policy')!=POLICY:raise Rejected('未配置独立流程测试副本')
    if digest(setting['manifest'])!=setting['manifest_sha256']:raise Rejected('流程测试来源清单变化')
    manifest=load(setting['manifest'])
    for file,sha in manifest['files'].items():
        if digest(file)!=sha:raise Rejected('流程测试原件/状态版本变化：'+file)
    view=CalculationView(service);state=view.current()
    if state['sha256']!=manifest['calculation_file_sha256']:raise Rejected('流程测试须重新绑定当前计算版本')
    return manifest,view,state

def restore_weight_caches(source,target,formulas=None):
    """Artifact authors the sheet; retain each original weight formula/cache exactly."""
    with zipfile.ZipFile(source)as z:original=ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
    with zipfile.ZipFile(target)as z:infos=z.infolist();parts={x.filename:z.read(x.filename)for x in infos}
    sheet=ET.fromstring(parts['xl/worksheets/sheet2.xml']);cells={c.get('r'):c for c in sheet.iter(NS+'c')}
    expanded={x['cell']:x['formula'].removeprefix('=')for x in formulas or []}
    for old in original.iter(NS+'c'):
        if old.find(NS+'f')is None:continue
        new=cells[old.get('r')]
        expected=expanded.get(old.get('r'),old.find(NS+'f').text)
        if expected is None or new.find(NS+'f')is None or new.find(NS+'f').text!=expected:raise Rejected('箱重原公式变化')
        new.remove(new.find(NS+'f'));new.insert(0,deepcopy(old.find(NS+'f')))
        cached=new.find(NS+'v')
        if cached is not None:new.remove(cached)
        value=old.find(NS+'v')
        if value is not None:ET.SubElement(new,NS+'v').text=value.text
        new.attrib.pop('t',None)
        if old.get('t'):new.set('t',old.get('t'))
    parts['xl/worksheets/sheet2.xml']=ET.tostring(sheet,encoding='utf8',xml_declaration=True)
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED)as z:
        for info in infos:z.writestr(info,parts[info.filename])

def current(service):
    _,_,state=inputs(service);result=load(service.background/'test-final/current.json')
    if result['calculation_sha256']!=state['sha256']:raise Rejected('最终测试表上游版本失效')
    for file,sha in result['output_sha256'].items():
        if digest(file)!=sha:raise Rejected('最终测试结果文件被改动')
    return result

def generate(service,request):
    if request.get('purpose')!='flow_test'or request.get('allow_pending')is not True or not str(request.get('reference')or'').strip():raise Rejected('流程测试须明确范围、保留未核项并记录本次用户依据')
    manifest,view,state=inputs(service);pointer=service.background/'test-final/current.json'
    if pointer.exists():return {**current(service),'receipt_replayed':True}
    from openpyxl import load_workbook
    w=load_workbook(state['file'],read_only=True,data_only=True);values=list(w.worksheets[0].values);weights=list(w.worksheets[1].values);weight_name=w.worksheets[1].title;w.close()
    wf=load_workbook(state['file'],read_only=True,data_only=False);weight_formulas=[{'cell':c.coordinate,'formula':c.value}for row in wf.worksheets[1]for c in row if c.data_type=='f'];wf.close()
    data=project(view.binding['rows'],values)
    weight_data=read_weights(state['file'],weight_name);logistics=reconcile_logistics([{'id':str(f['source_row']),'logistics':{'carton_raw':f['carton']}}for f in view.binding['rows']],weight_data)
    if not logistics['passed']:raise Rejected('箱号/箱重基础核对失败，不能作为流程测试结果')
    assigned=set()
    for row in data['customs']['rows']:
        entities=set(p0.expand(row[0])or[]);matches=[g for g in weight_data['groups']if entities and entities<=set(g['entities'])]
        if len(matches)==1:
            group=matches[0];group_key=tuple(sorted(group['entities']))
            if group_key not in assigned:
                row[16:19]=[scalar(number(group[k]))for k in ['count','unit_weight_observed','total_kg']];assigned.add(group_key)
    if len(assigned)!=len(weight_data['groups']):raise Rejected('最终测试表箱重组不能完整映射')
    base=service.background/'test-final'/key({'calculation':state['sha256'],'policy':POLICY,'reference':request['reference']})[:16];folder=base;attempt=1
    while folder.exists():folder=base.with_name(base.name+'-attempt'+str(attempt));attempt+=1
    folder.mkdir(parents=True,exist_ok=False)
    payload={k:v for k,v in data.items()if k!='trace'}
    payload.update(schema=POLICY,formal_output=False,reference=request['reference'],batch=service.config['batch_label'],weights={'name':weight_name,'rows':weights,'formulas':weight_formulas},output_dir=str(folder),artifact_node_modules=str(Path(service.config['node']).parent.parent/'node_modules'))
    payload['totals']={k:scalar(v)for k,v in data['totals'].items()};save(folder/'plan.json',payload)
    command=subprocess.run([service.config['node'],str(Path(__file__).resolve().parents[1]/'test-final-author.mjs'),str(folder/'plan.json')],capture_output=True,text=True,encoding='utf8')
    if command.returncode:raise Rejected('最终测试表生成失败：'+command.stderr[-2000:])
    files=[folder/(service.config['batch_label']+suffix)for suffix in ['_内部到货表_流程测试.xlsx','_海关报关单_流程测试.xlsx']]
    restore_weight_caches(state['file'],files[0],weight_formulas)
    from .test_final_verify import verify
    verification=verify(data,weights,weight_formulas,files,state['file'],logistics)
    inputs(service)
    public=[service._publish(f,f.name)for f in files]
    result={'stage':'test-final','test_only':True,'formal_output':False,'professional_approval':False,'calculation_confirmed':False,'policy':POLICY,'head':state['base_head'],'calculation_sha256':state['sha256'],'business_files':public,'output_sha256':{file:digest(file)for file in public},'rows':len(data['trace']),'retained_pending_rows':manifest['pending_rows'],'reference':request['reference'],'totals':payload['totals'],'rounding_difference_jpy':scalar(data['totals']['rounded_amount']-data['totals']['original_amount']),'logistics':logistics,'verification':verification,'receipt_replayed':False,'message':'本次流程测试双表已生成；未核项保留颜色，业务确认和正式外发状态未改变。'}
    save(folder/'trace.json',{'rows':data['trace'],'manifest':manifest,'approval_created':False});save(pointer,result)
    return result
