"""Replay the real saved batch only in a NEW directory; never prepare/approve it.

Requires the private input manifest. No real workbook/session is in GitHub.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, sys
from freeze_unified import sha, save

REPO=Path(__file__).resolve().parents[1]

def replay(manifest_file, output):
    manifest=json.loads(Path(manifest_file).read_text('utf8'))
    out=Path(output).resolve()
    if out.exists():raise ValueError('Replay output already exists; no overwrite permitted')
    source=Path(manifest['session'])
    source_config=json.loads(source.read_text('utf8'))
    # Do all source validation before copying/writing any new batch.
    for item in manifest['files']:
        if sha(item['path'])!=item['sha256']:raise ValueError('Private input SHA drift: '+item['path'])
    protected={str(p):sha(p) for p in source.parent.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    out.mkdir(parents=True)
    run=out/'run';shutil.copytree(source.parent,run,ignore=shutil.ignore_patterns('__pycache__'))
    back=run/'后台';public=run/'业务当前文件'
    config={**source_config,'root':str(back/'live-state'),'background':str(back),'business_directory':str(public),
            'isolation_note':'Developer-only replay copy; no operator approval or formal release.'}
    binding=json.loads(Path(manifest['binding']).read_text('utf8'))
    issued=out/'issued.xlsx';shutil.copyfile(manifest['issued_file'],issued)
    backend=back/'calculation-exports'/binding['backend_export']['export_id']/'issued.xlsx'
    backend.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(binding['backend_export']['file'],backend)
    binding.update(issued_file=str(issued),issued_sha256=sha(issued),backend_root=config['root'])
    binding['backend_export']={**binding['backend_export'],'file':str(backend),'sha256':sha(backend)}
    binding.pop('session',None);binding.pop('public_file',None)
    save(out/'binding.json',binding)
    config['native_view_binding']=str(out/'binding.json');save(out/'session.json',config)
    # Replace only the copied display/cache pointers. Original business state is untouched.
    export={**binding['backend_export']};save(back/'current-review-export.json',export)
    current=public/(config['batch_label']+'_计算审核.xlsx')
    shutil.copyfile(issued,current)
    save(back/'current-business-delivery.json',{'stage':'calculation','head':binding['head'],
            'business_files':[str(current)],'formal_output':False})
    save(back/'last-audit-display.json',{'head':binding['head'],'file':str(backend)})
    # Old receipts are retained in the copy, but may not short-circuit this new test.
    for name in ['last-original-layout-submission.json','last-stage-submission.json','current-review-submission.json']:
        p=back/name
        if p.exists():p.rename(back/('inherited-'+name))
    sys.path.insert(0,str(REPO/'business-interaction'))
    from interaction.original_view import OriginalView,publish_original
    view=OriginalView(out/'session.json')
    zero=view.preview(issued)
    assert zero['modified_cells']==0
    rebuilt=out/'rebuilt.xlsx'
    publish_original(manifest['source_workbook'],binding,rebuilt)
    assert sha(rebuilt)==sha(issued),'I-only reproduction differs from issued workbook'
    request={'action':'upload','file':str(issued),'reference':'TECHNICAL replay of unchanged real original-layout workbook; not operator approval'}
    result=view.operate(request)
    assert result['saved'] and result['confirmation_required'] is False
    first=Path(result['business_files'][0]);before=first.stat().st_mtime_ns
    again=view.operate(request)
    assert again['receipt_replayed'] and first.stat().st_mtime_ns==before
    current_result=view.operate({'action':'current'})
    assert current_result['business_files']==result['business_files']
    assert not (Path(config['root'])/'current-computation.json').exists()
    assert all(sha(p)==h for p,h in protected.items()),'Original session changed'
    from openpyxl import load_workbook
    w=load_workbook(first,read_only=True,data_only=False)
    try:assert w.worksheets[0].max_column==21
    finally:w.close()
    report={'candidate':subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(manifest.get('source_checkout',REPO)),text=True).strip(),
            'passed':7,'failed':0,'not_executed':0,'rows':len(binding['row_map']),'columns':21,
            'reproduced_sha256':sha(rebuilt),'current_file':str(first),'zero_change_preview':True,
            'auto_save_readback_idempotency':True,'original_session_unchanged':True,
            'technical_only_not_operator_approval':True,'formal_output':False}
    save(out/'result.json',report)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(replay(a.manifest,a.output),ensure_ascii=False))
