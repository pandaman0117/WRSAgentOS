"""Cross-process ownership of one local node or Router instance."""

import os
import re
import tempfile
from pathlib import Path


class InstanceLock:
    def __init__(self, name):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", name):
            raise ValueError("invalid_instance_name")
        path = Path(tempfile.gettempdir()) / "wrs-agent-locks" / f"{name}.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        if path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("node_already_running") from None

    def close(self):
        self.file.close()
