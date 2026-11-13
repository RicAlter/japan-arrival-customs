import importlib.util,json,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,TOOLS/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
freeze=module('freeze_unified');check=module('check_candidate')

class FreezeTests(unittest.TestCase):
    def fixture(self,root):
        root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
        files={'business-loop/dependency-lock.json':json.dumps({'files':{}}),'catalogue-pack-loop/reuse-lock.json':json.dumps({'files':{}}),'repro/guarded-text-snapshots.json':'{}','business-interaction/workbuddy/japan-arrival-customs-trial/SKILL.md':'example\n','.gitignore':'ignored/\n','text.txt':'git bytes\n'}
        for name,value in files.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value,encoding='utf8')
        subprocess.run(['git','-c','core.autocrlf=false','add','.'],cwd=root,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','maintenance.auto=false','-c','gc.auto=0','commit','-qm','fixture'],cwd=root,check=True)
    def test_clean_freeze_uses_git_bytes_and_excludes_ignored_files(self):
        with tempfile.TemporaryDirectory()as t:
            root=Path(t)/'repo';self.fixture(root);(root/'ignored').mkdir();(root/'ignored/private.xlsx').write_bytes(b'private')
            with patch.object(freeze,'REPO',root):freeze.freeze(Path(t)/'package')
            manifest=json.loads((Path(t)/'package/source-manifest.json').read_text('utf8'))
            self.assertEqual(manifest['source_basis'],'git_archive_HEAD');self.assertFalse(manifest['working_copy_changes'])
            expected=subprocess.check_output(['git','show','HEAD:text.txt'],cwd=root)
            self.assertEqual((Path(t)/'package/src/text.txt').read_bytes(),expected);self.assertNotIn('ignored/private.xlsx',manifest['files'])
    def test_dirty_default_rejects_before_creating_package(self):
        with tempfile.TemporaryDirectory()as t:
            root=Path(t)/'repo';self.fixture(root);(root/'text.txt').write_text('changed')
            with patch.object(freeze,'REPO',root),self.assertRaises(ValueError):freeze.freeze(Path(t)/'package')
            self.assertFalse((Path(t)/'package').exists())
    def test_explicit_dirty_preview_cannot_claim_git_archive(self):
        with tempfile.TemporaryDirectory()as t:
            root=Path(t)/'repo';self.fixture(root);(root/'extra.txt').write_text('preview')
            with patch.object(freeze,'REPO',root):freeze.freeze(Path(t)/'package',True)
            manifest=json.loads((Path(t)/'package/source-manifest.json').read_text('utf8'))
            self.assertTrue(manifest['working_copy_changes']);self.assertEqual(manifest['source_basis'],'working_copy_unverified_preview')

class BranchTests(unittest.TestCase):
    def test_canonical_branch_portable(self):self.assertEqual(check.branch_errors('codex/unified','codex/unified','h'),[])
    def test_isolated_branch_needs_explicit_existing_governance(self):self.assertTrue(check.branch_errors('codex/task','codex/unified','h'))
    def proof(self,**changes):
        p=dict(task_id='TASK',head='h',branch='codex/task',path=str(check.ROOT));p.update(changes)
        return SimpleNamespace(returncode=0,stdout=json.dumps(dict(status='passed',observed=dict(task_worktree=p))))
    def test_matching_task_proof_accepted(self):
        with patch.object(Path,'is_file',return_value=True),patch.object(check.subprocess,'run',return_value=self.proof()):self.assertEqual(check.branch_errors('codex/task','codex/unified','h','existing','TASK'),[])
    def test_other_task_head_or_worktree_rejected(self):
        for changes in [dict(head='old'),dict(task_id='OTHER'),dict(path=str(check.ROOT.parent)),dict(branch='codex/other')]:
            with self.subTest(changes=changes),patch.object(Path,'is_file',return_value=True),patch.object(check.subprocess,'run',return_value=self.proof(**changes)):self.assertTrue(check.branch_errors('codex/task','codex/unified','h','existing','TASK'))
    def test_governance_rejection_not_bypassed(self):
        with patch.object(Path,'is_file',return_value=True),patch.object(check.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='{"status":"conflict","errors":["BASELINE_DRIFT"]}')):self.assertTrue(check.branch_errors('codex/task','codex/unified','h','existing','TASK'))

if __name__=='__main__':unittest.main()
