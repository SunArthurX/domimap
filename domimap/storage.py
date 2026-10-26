"""Small connection-ownership primitives shared by the two local SQLite stores."""
import os
from functools import wraps


def synchronized(method):
    """Serialize the complete operation, not just individual SQLite statements."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


def read_snapshot(method):
    """Keep multi-statement reads consistent, including nested reads in a write transaction."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            owns_transaction = not self.db.in_transaction
            if owns_transaction:
                self.db.execute("BEGIN")
            try:
                result = method(self, *args, **kwargs)
                if owns_transaction:
                    self.db.commit()
                return result
            except BaseException:
                if owns_transaction:
                    self.db.rollback()
                raise
    return call


def sync_directory(path):
    """Persist directory entries on POSIX; Windows has no directory fsync in this API."""
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
