"""Freeze a committed Codex candidate with pinned external source dependencies.

No installation, calculation, business-state migration or external delivery.
"""
import argparse
import hashlib
import io
import json
import os
import platform
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile


def sha(p):
    with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def save(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def archive(source,destination):
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(source.rglob('*')):
            if p.is_file() and not any(x in {'__pycache__','node_modules','.git'} for x in p.relative_to(source).parts):
                entry=zipfile.ZipInfo(p.relative_to(source).as_posix(),date_time=(2026,11,9,0,0,0))
                entry.compress_type=zipfile.ZIP_DEFLATED;z.writestr(entry,p.read_bytes())


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',required=True);p.add_argument('--output',required=True)
    p.add_argument('--profile',required=True);a=p.parse_args()
    workspace=Path(a.workspace).resolve();repo=Path(__file__).resolve().parents[1];out=Path(a.output).resolve()
    if out.exists():raise SystemExit('冻结目录已存在，不覆盖；请使用新版本目录')
    if not out.is_relative_to(workspace):raise SystemExit('冻结目录须位于指定项目工作区内')
    dirty=subprocess.run(['git','status','--porcelain','--','business-interaction','material-query-adapter'],cwd=repo,check=True,capture_output=True,text=True).stdout
    if dirty.strip():raise SystemExit('候选源码未提交，不能冻结')
    commit=subprocess.run(['git','rev-parse','HEAD'],cwd=repo,check=True,capture_output=True,text=True).stdout.strip()
    snapshot=out/'frozen-workspace';snapshot.mkdir(parents=True)
    raw=subprocess.run(['git','archive','--format=tar',commit],cwd=repo,check=True,capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:tar.extractall(snapshot/repo.name,filter='data')
    external=json.loads((repo/'business-interaction/external-source-manifest.json').read_text(encoding='utf-8'))
    for name,item in external['files'].items():
        source=workspace/name;target=snapshot/name
        if sha(source)!=item['sha256']:raise SystemExit('外部依赖源码漂移：'+name)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        if sha(target)!=item['sha256']:raise SystemExit('冻结复制摘要不符：'+name)
    # The conservative stop state is data, not scraper source; preserve its exact version.
    stop=workspace/'reports/fast-material-batch-20261106/state.json'
    if stop.exists():
        target=snapshot/stop.relative_to(workspace);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(stop,target)
    files={p.relative_to(snapshot).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(snapshot.rglob('*')) if p.is_file()}
    canonical=json.dumps({k:v['sha256'] for k,v in files.items()},sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
    manifest={'schema':'codex-phase1-frozen-source/1','commit':commit,'tree_sha256':hashlib.sha256(canonical).hexdigest(),'files':files}
    save(out/'source-manifest.json',manifest)
    candidate=out/'japan-arrival-customs-trial'
    origin=snapshot/repo.name/'business-interaction/workbuddy/japan-arrival-customs-trial'
    shutil.copytree(origin,candidate)
    # Both the tree and local Skill package carry the full executable source.
    shutil.copytree(snapshot,candidate/'rt/src')
    shutil.copyfile(out/'source-manifest.json',candidate/'rt/source-manifest.json')
    profile=json.loads(Path(a.profile).read_text(encoding='utf-8'))
    pinned={}
    for name in ['input_file','database']:
        if profile.get(name):pinned[profile[name]]=sha(profile[name])
    for name in ['sources','image_caches']:
        for item in profile.get(name,[]):
            path=item['path'] if isinstance(item,dict) else item;pinned[path]=sha(path)
    for name in ['purchase_sources','history_sources']:
        for item in profile.get('quantity_review',{}).get(name,[]):pinned[item['path']]=sha(item['path'])
    data={'schema':'codex-local-fixed-data/1','files':pinned,'data_bundled':False,
          'note':'Private business assets remain in original/fixed local paths; verify these hashes before reproducing.'}
    save(out/'data-manifest.json',data);save(candidate/'data-manifest.json',data)
    environment={'python':sys.executable,'python_version':platform.python_version(),'node':profile['node'],
                 'node_version':subprocess.run([profile['node'],'--version'],capture_output=True,text=True,check=True).stdout.strip(),
                 'python_packages':{n:importlib.metadata.version(n) for n in ['openpyxl','Pillow','requests']},
                 'artifact_node_modules':str(Path(profile['node']).parent.parent/'node_modules'),
                 'note':'Bundled runtime libraries remain local dependencies; no runtime installation is performed.'}
    save(out/'environment.json',environment);save(candidate/'environment.json',environment)
    runtime={'python':sys.executable,'node':profile['node'],'entry':str(candidate/'rt/src'/repo.name/'business-interaction/run.py'),
        'source_root':str(candidate/'rt/src'),'source_manifest':str(candidate/'rt/source-manifest.json'),
        'source_manifest_sha256':sha(candidate/'rt/source-manifest.json'),'session':None,
        'output_base':str(out/'isolated-runs'),'preparation_defaults':{k:profile[k] for k in ['database','sources','image_caches','node']},
        'installed':False,'formal_output':False,'target':'Codex isolated tests; no WorkBuddy installation'}
    runtime['preparation_defaults'].update(download_images=True,material_review={'allow_online':False})
    save(candidate/'runtime.json',runtime)
    save(candidate/'test-profiles/KMT20261002.prepare.json',profile)
    sop=origin/'references/business-preparation-sop.md';shutil.copyfile(sop,out/'第一阶段业务SOP.md')
    (out/'使用说明.md').write_text('\n'.join([
        '# Codex第一阶段冻结候选','',
        '仅供Codex隔离真实业务测试，不安装或覆盖正式Skill。完整源码、Skill调用包、业务SOP和逐文件SHA清单均在本目录。',
        '提交：'+commit,'',
        '候选Skill的runtime.json绑定其rt/src完整源码；scripts/operate.py每次调用前核验源码清单，漂移即停止。',
        '依赖Python/Node及Artifact Tool采用本机已验证运行库，具体路径和版本见environment.json；压缩包不包含运行库。',
        '业务输入、资料库与历史数据不打入源码/Skill包；data-manifest.json逐份登记本机原件或固定快照位置及SHA，复现前核对。',
        'KMT20261002完整来源配置在test-profiles/KMT20261002.prepare.json；复现时为output指定新的隔离目录，不覆盖历史会话。',
        '其他批次上传原件后由宿主明确配置适用的采购/历史范围；不能把KMT20261002的日期截面或单位确认套给其他批次。',
        '默认图片下载开启；默认网站缓存模式不等于全量联网完成。实际联网须现有访问检查及授权，停站状态不得清空绕过。',
        '本次有限实测嵌图4张；网站受历史429停站影响，未完成全量联网核证。缺项均留原因，不能称完整补齐。',
        '回传继续upload→展示范围→明确confirm；current不重建批次。计算、正式双表及正式外发规则保持原门禁。',
    ])+'\n',encoding='utf-8')
    sourcezip=out/'完整源码.zip';archive(snapshot,sourcezip)
    skillzip=out/'Codex第一阶段候选Skill.zip';archive(candidate,skillzip)
    packagefiles={p.relative_to(candidate).as_posix():sha(p) for p in sorted(candidate.rglob('*')) if p.is_file()}
    save(out/'skill-manifest.json',{'files':packagefiles,'runtime_entry':runtime['entry'],'installed':False})
    result={'commit':commit,'source_tree_sha256':manifest['tree_sha256'],'source_files':len(files),
        'source_archive':str(sourcezip),'source_archive_sha256':sha(sourcezip),'skill_archive':str(skillzip),'skill_archive_sha256':sha(skillzip),
        'skill_directory':str(candidate),'sop_version':'phase1-codex-20261109-final','sop_sha256':sha(sop),
        'source_manifest_sha256':sha(out/'source-manifest.json'),'data_manifest_sha256':sha(out/'data-manifest.json'),
        'installed':False,'formal_output':False}
    save(out/'freeze-result.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
