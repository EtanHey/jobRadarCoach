"""Read a verifier source without blocking on named pipes or devices."""

import errno
import hashlib
import hmac
import os
from pathlib import Path
import stat


def read_verifier_source(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, "verifier source must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            return source.read()
    finally:
        os.close(descriptor)


def pinned_verifier_source(path: Path, expected_hash: str) -> tuple[bytes | None, str | None]:
    try:
        source = read_verifier_source(path)
    except OSError:
        return None, "verifier_missing" if not path.is_file() else "verifier_unavailable"
    if not hmac.compare_digest(hashlib.sha256(source).hexdigest(), expected_hash):
        return None, "verifier_hash_mismatch"
    return source, None
