import tempfile
from pathlib import Path
import unittest
import hashlib
from freeze_candidate import preserve_runtime_bytes


class FreezeBytesTests(unittest.TestCase):
    def test_preserve_guarded_CRLF_bytes_but_exclude_unrelated_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);committed=root/'commit';working=root/'working';committed.mkdir();working.mkdir()
            (committed/'engine.py').write_bytes(b'original\n')
            (working/'engine.py').write_bytes(b'original\r\n')
            (committed/'unrelated.md').write_bytes(b'old\n')
            (working/'unrelated.md').write_bytes(b'not part of this commit\r\n')
            result=preserve_runtime_bytes(committed,working)
            self.assertEqual((committed/'engine.py').read_bytes(),(working/'engine.py').read_bytes())
            self.assertEqual((committed/'unrelated.md').read_bytes(),b'old\n')
            self.assertEqual(result['checkout_EOL_bytes_preserved'],['engine.py'])
            self.assertEqual(result['unrelated_worktree_edits_excluded'],['unrelated.md'])

    def test_copy_an_existing_dirty_dependency_only_if_its_guard_hash_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);committed=root/'commit';working=root/'working';committed.mkdir();working.mkdir()
            (committed/'pinned.md').write_bytes(b'old git documentation\n')
            live=b'existing guarded documentation, not changed by this task\r\n'
            (working/'pinned.md').write_bytes(live)
            expected=hashlib.sha256(live).hexdigest()
            result=preserve_runtime_bytes(committed,working,{'pinned.md':expected})
            self.assertEqual((committed/'pinned.md').read_bytes(),live)
            self.assertEqual(result['required_guarded_worktree_snapshots'],{'pinned.md':expected})
