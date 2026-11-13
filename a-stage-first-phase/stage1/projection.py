"""Reuse the verified private 11->16 projection implementation, never rederive it."""
from pathlib import Path
import importlib.util,sys,shutil
from .support import Rejected,load,save,digest

def project(config,destination):
    required={'source','source_sha256','converter_file','converter_sha256','layout_data','layout_data_sha256','layout_base','layout_base_sha256'}
    if set(config)!=required:raise Rejected('原表转换须显式指定已验证实现及其输入摘要')
    for name in ['source','converter','layout_data','layout_base']:
        key='converter_file' if name=='converter' else name
        p=Path(config[key]).resolve(strict=True)
        if digest(p)!=config[name+'_sha256']:raise Rejected('原表或既有转换资产版本变化：'+name)
    destination=Path(destination).resolve()
    if destination.exists():raise Rejected('不覆盖旧转换或原件')
    destination.mkdir(parents=True)
    original=load(config['layout_data']);target=destination/'input/business-source.xlsx'
    original.update(source=str(Path(config['source']).resolve()),source_sha256=config['source_sha256'],output=str(target))
    save(destination/'layout-data.json',original)
    shutil.copyfile(config['layout_base'],destination/'layout-base.xlsx')
    code=Path(config['converter_file']).resolve();sys.path.insert(0,str(code.parent))
    spec=importlib.util.spec_from_file_location('stage1_verified_projection',code)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.SOURCE=Path(config['source']).resolve();module.REPORT=destination
    result=module.project_layout()  # Existing mapping, formula/cache and weight checks.
    if Path(result)!=target:raise Rejected('既有转换返回位置不符')
    check=load(destination/'normalization-check.json')
    if check.get('rows')!=1275 or check.get('source_sha256')!=config['source_sha256']:
        raise Rejected('本候选仅覆盖已验证KMT20261101的1275行，不泛化新布局')
    return target,check
