"""Param-keyed cache for all-atom-relaxed protein structures.

Wraps :func:`pbg_openmm.relax.relax_in_water` so the 3D packing pipeline can
opt into water-relaxed structures without repeating an expensive OpenMM run
every time the same (structure, relax-params) pair is requested. Relaxation
is opt-in: this module (and `viva_parsimony` as a whole) must still import
cleanly when OpenMM/``pbg_openmm`` is not installed.

Cache key: a SHA1 over the canonical JSON of the structure reference, the
relax config, the (best-effort) AlphaFold model version, and the OpenMM
version — so a change to any of those produces a distinct cache entry.
"""
from __future__ import annotations

import json
import hashlib
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .structures import StructureRef, fetch, alphafold_pdb_url

try:
    from pbg_openmm.relax import relax_in_water, RelaxError
except Exception:  # pbg_openmm/openmm not available — relax is opt-in
    relax_in_water = None

    class RelaxError(Exception):
        pass


log = logging.getLogger(__name__)


def relax_params_hash(ref: Dict[str, Any], relax_cfg: Dict[str, Any], *,
                       model_version: Optional[str] = None) -> str:
    """Stable, param-sensitive cache key for a (structure, relax-config) pair.

    SHA1 hexdigest over a canonical (``sort_keys=True``) JSON encoding of the
    structure source/id, the AlphaFold model version (if resolved), every
    relax-config field, and the OpenMM version — deterministic, no timestamp.
    """
    try:
        import openmm
        openmm_version = openmm.version.version
    except Exception:
        openmm_version = "unknown"

    payload = {
        "source": ref["kind"],
        "id": ref["ref"],
        "model_version": model_version,
        **relax_cfg,
        "openmm_version": openmm_version,
    }
    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def relaxed_path(cache_dir: str | Path, obj_id: str, phash: str) -> Path:
    """Where the relaxed PDB for ``obj_id``/``phash`` lives under ``cache_dir``."""
    return Path(cache_dir) / "relaxed" / f"{obj_id}__{phash}.pdb"


def _cached_model_version(cache_dir: str | Path, obj_id: str, ref: Dict[str, Any],
                           relax_cfg: Dict[str, Any]) -> Optional[str]:
    """Reuse the ``model_version`` of an existing relaxed entry for this
    ``obj_id`` whose source/id and relax params match, so a warm cache is
    reproducible even when the live AlphaFold API call is unavailable
    (offline / network down) — avoids a spurious cache MISS on a structure
    that's already been relaxed under a fixed model version."""
    import glob
    for sc in glob.glob(str(Path(cache_dir) / "relaxed" / f"{obj_id}__*.provenance.json")):
        try:
            prov = json.loads(Path(sc).read_text())
        except Exception:
            continue
        if prov.get("source") == ref["kind"] and prov.get("id") == ref["ref"] \
                and all(prov.get(k) == v for k, v in relax_cfg.items()):
            return prov.get("model_version")
    return None


def get_or_relax(ref: Dict[str, Any], cache_dir: str | Path, relax_cfg: Dict[str, Any],
                  *, obj_id: str) -> Path:
    """Return a relaxed structure for ``ref``, relaxing (and caching) on miss.

    ``ref`` is a plain dict (an ingredient's structure reference), converted
    to a :class:`StructureRef` before fetching. On a cache hit, returns the
    existing relaxed path without touching the network or OpenMM. On a miss,
    fetches the raw structure, relaxes it, and writes both the relaxed PDB
    and a sibling ``<...>.provenance.json``. If relaxation fails
    (``RelaxError``), logs a warning and falls back to the raw fetched path.
    """
    model_version = None
    if ref["kind"] == "alphafold":
        model_version = _cached_model_version(cache_dir, obj_id, ref, relax_cfg)
        if model_version is None:
            try:
                url = alphafold_pdb_url(ref["ref"])
                m = re.search(r"_v(\d+)", url)
                model_version = m.group(0)[1:] if m else None
            except Exception:
                model_version = None

    phash = relax_params_hash(ref, relax_cfg, model_version=model_version)
    target = relaxed_path(cache_dir, obj_id, phash)
    if target.exists():
        return target

    src = fetch(StructureRef(kind=ref["kind"], ref=ref["ref"]), Path(cache_dir) / "structures", slug=obj_id)

    if relax_in_water is None:
        raise RuntimeError(
            "pbg_openmm is not installed; install pbg-openmm to relax structures "
            "(or pass a relax_cfg that skips relaxation)."
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        prov = relax_in_water(str(src), str(target), **relax_cfg)
        relaxed = True
        if not target.exists():
            # Defensive fallback: relax_in_water is contracted to write
            # pdb_out itself (or raise RelaxError). If that contract is ever
            # broken (future bug / alternate backend) and it returns without
            # writing target, we must not silently cache the raw structure
            # under a relaxed name with provenance claiming it was relaxed.
            log.warning(
                "relax_in_water for %s returned without writing the relaxed "
                "output to %s; caching the raw fetched structure instead "
                "(marked relaxed=False in provenance)", obj_id, target,
            )
            shutil.copyfile(src, target)
            relaxed = False
        provenance = {
            "source": ref["kind"],
            "id": ref["ref"],
            "model_version": model_version,
            **prov,
            "relaxed": relaxed,
            "utc": datetime.now(timezone.utc).isoformat(),
        }
        target.with_suffix(".provenance.json").write_text(json.dumps(provenance, indent=2))
        return target
    except RelaxError as exc:
        log.warning("relax_in_water failed for %s (%s); using raw fetched structure", obj_id, exc)
        if src.suffix.lower() in (".pdb", ".cif"):
            raw_prov = src.with_suffix(".provenance.json")
            raw_prov.write_text(json.dumps({
                "source": ref["kind"],
                "id": ref["ref"],
                "model_version": model_version,
                "relaxed": False,
                "utc": datetime.now(timezone.utc).isoformat(),
            }, indent=2))
        return src
