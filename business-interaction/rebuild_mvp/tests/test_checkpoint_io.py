import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from rebuild_mvp.service import save_json

class AtomicCheckpointIO(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'job.json';self.path.write_text('{"old":true}',encoding='utf8')
    def winerror(self,code):
        e=PermissionError('simulated native file sharing/access error');e.winerror=code;return e
    def test_transient_windows_lock_retries_same_payload_then_publishes(self):
        import os
        replace=os.replace;calls=[]
        def transient(src,dst):
            calls.append(Path(src).read_bytes())
            if len(calls)<3:raise self.winerror(5)
            replace(src,dst)
        with patch('rebuild_mvp.service.os.replace',side_effect=transient),patch('rebuild_mvp.service.time.sleep')as sleep:
            save_json(self.path,{'new':'中文','row':212})
        self.assertEqual(calls,[calls[0]]*3);self.assertEqual(sleep.call_count,2);self.assertEqual(json.loads(self.path.read_text(encoding='utf8')),{'new':'中文','row':212});self.assertFalse(self.path.with_suffix('.json.tmp').exists())
    def test_exhaustion_preserves_previous_checkpoint_and_recoverable_temp(self):
        with patch('rebuild_mvp.service.os.replace',side_effect=self.winerror(32))as replace,patch('rebuild_mvp.service.time.sleep')as sleep:
            with self.assertRaises(PermissionError):save_json(self.path,{'new':1})
        self.assertEqual(replace.call_count,8);self.assertEqual(sleep.call_count,7);self.assertEqual(json.loads(self.path.read_text()),{'old':True});self.assertEqual(json.loads(self.path.with_suffix('.json.tmp').read_text()),{'new':1})
    def test_unrelated_permission_failure_is_not_hidden(self):
        with patch('rebuild_mvp.service.os.replace',side_effect=PermissionError('permanent permission failure'))as replace,patch('rebuild_mvp.service.time.sleep')as sleep:
            with self.assertRaises(PermissionError):save_json(self.path,{'new':1})
        self.assertEqual(replace.call_count,1);sleep.assert_not_called();self.assertEqual(json.loads(self.path.read_text()),{'old':True})
    def test_other_os_errors_are_not_retried(self):
        with patch('rebuild_mvp.service.os.replace',side_effect=OSError('disk full'))as replace,patch('rebuild_mvp.service.time.sleep')as sleep:
            with self.assertRaises(OSError):save_json(self.path,{'new':1})
        self.assertEqual(replace.call_count,1);sleep.assert_not_called()

if __name__=='__main__':unittest.main()
