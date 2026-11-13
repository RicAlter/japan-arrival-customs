"""Clone saved stage-two state for an explicitly authorized pending flow test."""
from pathlib import Path
import argparse,json,shutil
from freeze_unified import sha,save
POLICY='pending-reference-flow-test/20261113'
def bind(manifest,output):
    m=json.loads(Path(manifest).read_text('utf8'));out=Path(output).resolve()
    if out.exists():raise ValueError('测试须使用新目录，不覆盖旧session')
    for p,h in m['files'].items():
        if sha(p)!=h:raise ValueError('测试输入SHA不符：'+p)
    original=Path(m['session']);config=json.loads(original.read_text('utf8'))
    if not config.get('calculation_view_binding'):raise ValueError('须从已保存第二阶段继续')
    if config['calculation_view_binding_sha256']!=sha(config['calculation_view_binding']):raise ValueError('已保存绑定变化')
    pointer=Path(config['background'])/'stage2/current.json';state=json.loads(pointer.read_text('utf8'))
    if sha(state['file'])!=state['sha256']or state['sha256']!=m['calculation_file_sha256']:raise ValueError('当前计算稿发生变化')
    out.mkdir(parents=True);saved=out/'saved-batch'
    shutil.copytree(Path(config['background']).parent,saved,ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(config['calculation_view_binding'],out/'binding.json')
    config.update(background=str(saved/'后台'),root=str(saved/'后台/live-state'),business_directory=str(out/'结果表'),calculation_view_binding=str(out/'binding.json'),flow_test_final={'policy':POLICY,'manifest':str(Path(manifest).resolve()),'manifest_sha256':sha(manifest)})
    save(out/'session.json',config)
    return {'session':str(out/'session.json'),'prepare_executed':False,'prior_session_changed':False,'formal_output':False}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(bind(a.manifest,a.output),ensure_ascii=False))
