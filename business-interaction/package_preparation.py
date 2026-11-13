"""Package the uninstalled local candidate, SOP, exact assets and honest receipts."""
from pathlib import Path
import sys,json,shutil,subprocess,hashlib
from interaction import load,save,digest,ROOT
W=ROOT.parents[1];R=W/'reports/first-phase-upgrade-20261106';request=load(R/'prepare-request.json')
destination=W/'outputs/日本到货第一阶段升级候选_20261106';destination.mkdir(exist_ok=True)
candidate=destination/'japan-arrival-customs-trial'
if candidate.exists():raise SystemExit('候选交付目录已存在，保留已有包；使用新版本目录')
shutil.copytree(ROOT/'workbuddy/japan-arrival-customs-trial',candidate)
save(candidate/'runtime.json',{'python':sys.executable,'node':request['node'],'entry':str(ROOT/'run.py'),'session':None,
    'output_base':str(W/'outputs/日本到货准备批次'),'preparation_defaults':{k:request[k] for k in ['database','sources','image_caches','node']},
    'installed':False,'workbuddy_native_verified':False})
assets=load(R/'assets.json')
for asset in assets['assets']:
    asset.update(version='sha256:'+asset['sha256'],validation='固定输入摘要已登记；执行验证见validation.json' if asset['status']=='reusable' else '仅追溯，不用于新批执行')
commit=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT.parent,text=True,capture_output=True,check=True).stdout.strip()
capabilities=[]
for relative,purpose,status,validation in [
    ('a01-native-copy','日方原始导入、字段识别及安全单元格编辑','reusable','真实原始表1275行、cache与箱重验证'),
    ('a03-confirmation','回传预览、明确范围保存确认','reusable','装饰零修改回传、合成人工保存恢复验证'),
    ('a04-calculation-input','既有计算输入适配','reusable','既有整合回归，不新增规则'),
    ('b00-business-basis','既有业务金额基准及双表衔接','reusable','business-loop 37项及catalogue-pack-loop 35项回归'),
    ('catalogue-pack-loop','资料库快照、包装单位与ROUND0衔接','reusable','35项完整回归；原模块未修改'),
    ('business-loop','实际价格更新、计算审核及双表','reusable','37项完整回归；原模块未修改'),
    ('material-query-adapter','jp_material_query v0.2.0只读适配','reusable','插件8接口/63测试、适配11测试历史回执；本轮1275离线及1行联网'),
    ('business-interaction','prepare、全量网站队列、图片、受控登记与宿主入口','generalized_candidate','8项规则测试、原始表全过程验证；仅已验证原表布局'),
]:
    folder=ROOT.parent/relative
    files={str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file() and p.suffix in {'.py','.md','.json','.mjs'} and '__pycache__' not in p.parts}
    capabilities.append({'path':str(folder),'purpose':purpose,'status':status,'base_commit':commit,
        'version_sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),'validation':validation,'files':files})
assets['capabilities']=capabilities;assets['source_version_note']='工作树以内容摘要为准；HEAD用于说明继承基线，不表示未提交修改已在该提交中。'
assets['needs_generalization']=[{'asset':'其他日方原表模板','status':'needs_generalization','current':'只支持已验证连续商品行布局，其他布局拒绝'},
    {'asset':'Colleize等站点CLI适配','status':'needs_generalization','current':'已有浏览器方法及访问记录；当前自动查询仅Anime Store'}]
assets['historical_validation_scripts']=[str(ROOT/n) for n in ['build_preparation_assets.py','validate_preparation.py','test_prepared_website.py']]
save(R/'assets.json',assets)
lines=['# 第一阶段可用资产','',
    '所有来源以清单中具体文件和摘要为准，运行时另外捕获固定快照。不递归扫描整个资料库。',
    'reusable=可复用；needs_generalization=需通用化；historical_only=仅供历史验证。generalized_candidate为已通用化到当前已验证原表布局的工作区候选。','',
    '|用途|状态|文件|SHA256|','|---|---|---|---|']
for a in assets['assets']:lines.append(f"|{a['role']}|{a['status']}|{a['path']}|{a['sha256']}|")
lines+=['','## 流程能力与验证状态','','版本为工作树内容摘要，完整文件摘要见assets.json。继承提交：'+commit+'。','','|用途|状态|验证|位置|','|---|---|---|---|']
for c in capabilities:lines.append(f"|{c['purpose']}|{c['status']}|{c['validation']}|{c['path']}|")
lines+=['','## 验证与适用范围','',
    '- 原始导入、A03、包装数量、ROUND0及双表模块继续复用；本轮修改限定business-interaction交付适配层。',
    '- 已支持原始kmt-raw-invoice-v1连续商品行，行数和批次名动态；其他原表布局明确报未支持。',
    '- 数据库取已登记来源路径的只读SQLite backup；采购表采用明确字段映射，重复表头按列号。',
    '- 主JAN/pcs/采购SKU双向关联保留来源；多盒码、多YD或版本冲突留人工。',
    '- 旧HD文件图片经来源URL及绘图锚点提取，并重新记录内容SHA；未盲信摘要已过期的旧磁盘缓存。',
    '- 最新网站规则为全部商品核对。本轮离线回归范围与有限联网回执分别记录，不能把队列1275行说成已全部在线查完。',
    '- 当前自动材质网站适配为Anime Store；Colleize的浏览器查询方法属于可用过程资产，尚未实现其CLI适配。',
    '- build_preparation_assets.py、validate_preparation.py、test_prepared_website.py是固定KMT样本验收脚本；新批业务入口使用run.py/operate.py，不重跑这些脚本。',
    '- 候选runtime指向本工作区入口及实际依赖，是本机调用包；未安装正式Skill，未验证WorkBuddy原生附件流程。']
(destination/'可用资产清单.md').write_text('\n'.join(lines),encoding='utf8')
shutil.copyfile(candidate/'references/preparation-sop.md',destination/'第一阶段SOP.md')
for name in ['assets.json','prepare-result.json','validation.json','website-offline.json','website-live-probe.json','website-failure.json','preservation.json','regression.json','验收说明.md']:
    p=R/name
    if p.exists():shutil.copyfile(p,destination/name)
files={str(p.relative_to(candidate)):digest(p) for p in candidate.rglob('*') if p.is_file()}
save(destination/'manifest.json',{'candidate':str(candidate),'runtime_entry':str(ROOT/'run.py'),'files':files,'installed':False,'formal_output':False,'workbuddy_native_verified':False})
print(json.dumps({'candidate':str(candidate),'sop':str(destination/'第一阶段SOP.md'),'assets':str(destination/'可用资产清单.md')},ensure_ascii=False))
