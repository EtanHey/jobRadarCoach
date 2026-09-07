"""Install only the pinned official Linux Codex binary during image build."""
import base64
import hashlib
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
from urllib.request import urlopen

VERSION = "0.153.4"
ARTIFACTS = {
    "arm64": (
        "arm64", "aarch64-unknown-linux-musl",
        "QKdjYLYV4hXIuUQDP3P6F4NXuWFoKo9WUoV4nAREIx55kiUyi8UsYdsVobkeXir5n/maEQgYMCKLHVma4rNPiw==",
    ),
    "amd64": (
        "x64", "x86_64-unknown-linux-musl",
        "x1EcwBlY3AObM1VTUHNM2AzAJQsyreGdagpF+qFiYi/Oa30VBktvvG0C6tLtCzqW6hjZNWkGZQWmeVk7MuJKWg==",
    ),
}
MAX_ARCHIVE_BYTES = 200_000_000
MAX_BINARY_BYTES = 400_000_000


def install(architecture: str, destination: Path) -> None:
    if architecture not in ARTIFACTS:
        raise ValueError("Codex image supports linux/arm64 and linux/amd64 only")
    package_arch, target, integrity = ARTIFACTS[architecture]
    url = f"https://registry.npmjs.org/@openai/codex/-/codex-{VERSION}-linux-{package_arch}.tgz"
    with tempfile.TemporaryDirectory(prefix="codex-install-") as temporary:
        archive_path = Path(temporary) / "codex.tgz"
        digest = hashlib.sha512()
        total = 0
        # Fixed HTTPS npm origin, allowlisted architecture/version; SHA-512 verified below.
        with urlopen(url, timeout=60) as response, archive_path.open("wb") as archive:  # skipcq: BAN-B310
            while chunk := response.read(1_048_576):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError("Codex archive exceeds size limit")
                digest.update(chunk)
                archive.write(chunk)
        if digest.digest() != base64.b64decode(integrity, validate=True):
            raise ValueError("Codex archive integrity mismatch")
        with tarfile.open(archive_path, "r:gz") as archive:
            member = archive.getmember(f"package/vendor/{target}/bin/codex")
            if not member.isfile() or not 0 < member.size <= MAX_BINARY_BYTES:
                raise ValueError("Codex binary is not a bounded regular file")
            with archive.extractfile(member) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1_048_576)
        destination.chmod(0o755)


if __name__ == "__main__":
    install(sys.argv[1], Path("/usr/local/bin/codex"))
