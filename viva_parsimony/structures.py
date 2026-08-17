"""Resolve molecular structures to local files: RCSB PDB/mmCIF or AlphaFold DB.

Organism-agnostic. Callers pass a ``StructureRef`` describing where a structure
comes from; :func:`fetch` downloads (and caches) it to a local file that
:func:`viva_parsimony.engine.mesh_file` can mesh.
"""
from __future__ import annotations
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StructureRef:
    """A structure source. ``kind`` is one of:
    - ``"pdb"`` / ``"cif"``: an RCSB id in ``ref`` (use ``cif`` for large
      assemblies that lack a legacy .pdb, e.g. the ribosome).
    - ``"alphafold"``: a UniProt accession in ``ref`` (latest model version).
    - ``"file"``: a local path in ``ref`` (used verbatim).
    """
    kind: str
    ref: str


def alphafold_pdb_url(accession: str) -> str:
    """Resolve the current AlphaFold DB model URL for a UniProt accession via
    the AlphaFold API (robust to the model-version bumps, e.g. v4 → v6)."""
    api = f"https://alphafold.ebi.ac.uk/api/prediction/{accession}"
    data = json.loads(urllib.request.urlopen(api, timeout=60).read())
    entry = data[0] if isinstance(data, list) else data
    return entry["pdbUrl"]


def fetch(ref: StructureRef, cache_dir: str | Path, slug: str | None = None) -> Path:
    """Download ``ref`` into ``cache_dir`` (cached) and return the local path.
    ``slug`` overrides the output basename (defaults to the id/accession)."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if ref.kind == "file":
        return Path(ref.ref)
    slug = (slug or ref.ref).lower().replace("-", "_")
    if ref.kind in ("pdb", "cif"):
        ext = ref.kind
        url = f"https://files.rcsb.org/download/{ref.ref}.{ext}"
        out = cache_dir / f"{slug}.{ext}"
    elif ref.kind == "alphafold":
        url = alphafold_pdb_url(ref.ref)
        out = cache_dir / f"{slug}.pdb"
    else:
        raise ValueError(f"unknown structure kind {ref.kind!r}")
    if out.exists() and out.stat().st_size > 0:
        return out
    urllib.request.urlretrieve(url, out)
    return out
