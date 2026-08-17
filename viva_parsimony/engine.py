"""Locate and drive the parsimony CLI (the Rust packing engine)."""
from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path


class ParsimonyNotFound(RuntimeError):
    """The parsimony binary could not be located."""


def find_parsimony_bin() -> str:
    """Locate the parsimony binary: ``$PARSIMONY_BIN``, else
    ``$PARSIMONY_HOME/target/release/parsimony``, else ``parsimony`` on PATH."""
    env = os.environ.get("PARSIMONY_BIN")
    if env and Path(env).exists():
        return env
    home = os.environ.get("PARSIMONY_HOME")
    if home:
        cand = Path(home) / "target" / "release" / "parsimony"
        if cand.exists():
            return str(cand)
    found = shutil.which("parsimony")
    if found:
        return found
    raise ParsimonyNotFound(
        "parsimony binary not found. Set PARSIMONY_BIN to the binary, or "
        "PARSIMONY_HOME to the parsimony repo (with target/release/parsimony built)."
    )


def mesh_file(structure_path: str | Path, out_dir: str | Path,
              lods: str = "16,8,4,2.5") -> str:
    """VdW-surface-mesh a PDB/mmCIF file into ``<out_dir>/<stem>.lod*.obj``.
    Returns the slug (the input file stem). Idempotent (the CLI skips meshes
    that already exist)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src = Path(structure_path).resolve()
    subprocess.run(
        [find_parsimony_bin(), "mesh", str(src), "--out-dir", str(out_dir), "--lods", lods],
        check=True,
    )
    return src.stem


def run_pipeline(pipeline_path: str | Path, out_pack: str | Path,
                 proxy_lod: int = 2) -> dict:
    """Run ``parsimony pipeline run <pipeline> --out <pack> --proxy-lod N``
    (octree backend). Returns ``{pack_path, stdout}``."""
    proc = subprocess.run(
        [find_parsimony_bin(), "pipeline", "run", str(pipeline_path),
         "--out", str(out_pack), "--proxy-lod", str(proxy_lod)],
        check=True, capture_output=True, text=True,
    )
    return {"pack_path": str(out_pack), "stdout": proc.stdout.strip()}
