"""Download hash-pinned Cairo DLLs and license/source notices for the installer.

Run with the embedded Python after project dependencies (zstandard) are present.
No system installation, DLL registration, conda environment or PATH edit occurs.
"""
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
import urllib.request
import zipfile

try:
    from compression.zstd import decompress
except ImportError:
    import zstandard

    def decompress(data):
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)) as stream:
            return stream.read()


def package_native(lockfile, downloads, python_dir):
    downloads, python_dir = Path(downloads), Path(python_dir)
    downloads.mkdir(parents=True, exist_ok=True)
    packages = json.loads(Path(lockfile).read_text(encoding="utf-8-sig"))

    def download(package):
        archive = downloads / package["fn"]
        if not archive.exists():
            urllib.request.urlretrieve(package["url"], archive)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != package["sha256"]:
                raise RuntimeError(f"Hash mismatch: {archive.name}")
        return package, archive

    def unpack(tar, package):
        for member in tar:
            if not member.isfile():
                continue
            path = PurePosixPath(member.name)
            if ".." in path.parts or path.is_absolute():
                raise RuntimeError("Unsafe native archive path")
            if path.parent.as_posix() == "Library/bin" and path.suffix.lower() == ".dll":
                target = python_dir / path.name
            elif path.parts[:2] == ("info", "licenses") or path.parts[:2] == ("info", "recipe") or path.as_posix() == "info/about.json":
                target = python_dir / "native-notices" / package["name"] / Path(*path.parts)
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            data = tar.extractfile(member).read()
            if target.exists() and target.read_bytes() != data:
                # Embedded Python supplies its own VC runtime; keep the newer
                # conda redistributable consistently across the application.
                if not target.name.lower().startswith(("vcruntime", "msvcp")):
                    raise RuntimeError(f"Conflicting native library: {target}")
            target.write_bytes(data)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for package, archive in pool.map(download, packages):
            print("NATIVE", archive.name, flush=True)
            if archive.suffix == ".conda":
                with zipfile.ZipFile(archive) as bundle:
                    for name in bundle.namelist():
                        if name.endswith(".tar.zst"):
                            with io.BytesIO(decompress(bundle.read(name))) as stream:
                                with tarfile.open(fileobj=stream, mode="r|") as tar:
                                    unpack(tar, package)
            else:
                with tarfile.open(archive, "r:bz2") as tar:
                    unpack(tar, package)
    (python_dir / "native-notices" / "packages.json").write_text(json.dumps(packages, indent=2), encoding="utf-8")


if __name__ == "__main__":
    package_native(*sys.argv[1:])
