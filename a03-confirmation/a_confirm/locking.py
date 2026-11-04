"""Process-lifetime mutex around an exclusively owned B2 Store directory."""
from contextlib import contextmanager
import os
from .support import Rejected, path


@contextmanager
def writer(root, batch_id):
    from arrival_core.excel_return import safe_id
    safe_id(batch_id,24)
    folder=path(root/'guards');folder.mkdir(parents=True,exist_ok=True)
    file=folder/(batch_id+'.lock');stream=file.open('a+b')
    acquired=False
    try:
        if file.stat().st_size==0:stream.write(b'0');stream.flush();os.fsync(stream.fileno())
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            acquired=True
        except OSError as exc:raise Rejected('本批A版本正在保存，请稍后重新读取') from exc
        # Only this candidate writes its private Store, always under this OS mutex.
        # OS releases it on process death; an empty legacy lock can then be recovered.
        target=(root/'batches'/batch_id/'.writer.lock').resolve()
        if not target.is_relative_to((root/'batches').resolve()):raise Rejected('候选写锁路径越出专用存储')
        stale=path(target)
        recovered=stale.exists()
        if recovered:stale.unlink()
        yield recovered
    finally:
        if acquired:
            stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        stream.close()
