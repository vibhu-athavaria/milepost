"""Source hash: a digest over a note's source set (SPEC section 5)."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from milepost.core.glob import expand_sources


@dataclass
class HashResult:
    value: str
    manifest: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _normalize(data: bytes) -> bytes:
    if b"\x00" in data:
        return data
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def compute_source_hash(root: Path, sources: list[str], ignore: list[str]) -> HashResult:
    paths = expand_sources(root, sources, ignore)
    manifest = {
        path: hashlib.sha256(_normalize((root / path).read_bytes())).hexdigest() for path in paths
    }
    manifest_text = "".join(f"{path}\t{digest}\n" for path, digest in manifest.items())
    value = "sha256:" + hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
    warnings = [] if manifest else [f"source set matches no files: {sources}"]
    return HashResult(value=value, manifest=manifest, warnings=warnings)
