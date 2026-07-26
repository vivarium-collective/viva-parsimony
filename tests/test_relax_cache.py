"""Tests for the param-keyed relaxed-structure cache (no network, no OpenMM)."""
import json
from pathlib import Path

from pbg_parsimony import relax_cache as rc

CFG = {"forcefield": ["amber14-all.xml", "amber14/tip3pfb.xml"], "water_model": "tip3p",
       "padding_nm": 1.0, "ionic_strength_M": 0.15, "temperature_K": 300.0,
       "timestep_fs": 2.0, "equil_ps": 200.0, "seed": 0}


def _tiny_pdb(tmp_path) -> Path:
    """Write a minimal valid single-atom PDB and return its path."""
    p = tmp_path / "tiny.pdb"
    p.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "END\n"
    )
    return p


def test_hash_stable_and_param_sensitive():
    ref = {"kind": "alphafold", "ref": "P0A6F5"}
    h1 = rc.relax_params_hash(ref, CFG, model_version="v4")
    h2 = rc.relax_params_hash(ref, CFG, model_version="v4")
    h3 = rc.relax_params_hash(ref, {**CFG, "seed": 1}, model_version="v4")
    h4 = rc.relax_params_hash(ref, CFG, model_version="v6")
    assert h1 == h2 and h1 != h3 and h1 != h4


def test_get_or_relax_cache_hit_skips_relax(tmp_path, monkeypatch):
    ref = {"kind": "file", "ref": str(_tiny_pdb(tmp_path))}
    calls = {"n": 0}
    monkeypatch.setattr(rc, "relax_in_water", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {"seed": 0})
    monkeypatch.setattr(rc, "fetch", lambda ref, cd, slug=None: _tiny_pdb(tmp_path))
    p1 = rc.get_or_relax(ref, tmp_path / "cache", CFG, obj_id="x")   # miss → relaxes + writes provenance
    p2 = rc.get_or_relax(ref, tmp_path / "cache", CFG, obj_id="x")   # hit → no re-relax
    assert p1 == p2 and calls["n"] == 1
    assert (p1.with_suffix(".provenance.json")).is_file()
    # This mock never writes `target` itself, so the fallback-copy branch
    # fires; provenance must not misrepresent the cached file as relaxed.
    prov = json.loads(p1.with_suffix(".provenance.json").read_text())
    assert prov["relaxed"] is False


def test_relax_error_falls_back_to_raw(tmp_path, monkeypatch):
    from pbg_openmm.relax import RelaxError
    raw = _tiny_pdb(tmp_path)
    monkeypatch.setattr(rc, "fetch", lambda *a, **k: raw)
    monkeypatch.setattr(rc, "relax_in_water", lambda *a, **k: (_ for _ in ()).throw(RelaxError("boom")))
    out = rc.get_or_relax({"kind": "file", "ref": str(raw)}, tmp_path / "cache", CFG, obj_id="x")
    assert out == raw   # graceful fallback to the raw structure
    # Minor A: provenance is preserved beside the raw fallback file, marked un-relaxed.
    raw_prov = raw.with_suffix(".provenance.json")
    assert raw_prov.is_file()
    prov = json.loads(raw_prov.read_text())
    assert prov["relaxed"] is False
    assert prov["source"] == "file" and prov["id"] == str(raw)


def test_alphafold_model_version_reused_from_warm_cache_offline(tmp_path, monkeypatch):
    """Important 2: if the AlphaFold API call is unavailable (offline), a
    matching existing relaxed-cache sidecar's model_version is reused so the
    hash (and therefore the target path) is reproducible instead of
    resolving to model_version=None and MISSing an already-relaxed entry."""
    cache_dir = tmp_path / "cache"
    ref = {"kind": "alphafold", "ref": "P0A6F5"}
    obj_id = "gapdh"

    # Simulate a pre-existing warm-cache entry relaxed while online, with a
    # resolved model_version, under some prior hash.
    prior_hash = "deadbeef"
    relaxed_dir = cache_dir / "relaxed"
    relaxed_dir.mkdir(parents=True)
    sidecar = relaxed_dir / f"{obj_id}__{prior_hash}.provenance.json"
    sidecar.write_text(json.dumps({
        "source": "alphafold", "id": "P0A6F5", "model_version": "4",
        **CFG, "relaxed": True, "utc": "2026-01-01T00:00:00+00:00",
    }))

    def _boom(accession):
        raise OSError("network is unreachable (simulated offline)")
    monkeypatch.setattr(rc, "alphafold_pdb_url", _boom)

    # The path get_or_relax resolves to (before it exists/network is touched)
    # should match a hash built directly from the sidecar's model_version.
    expected_hash = rc.relax_params_hash(ref, CFG, model_version="4")
    expected_target = rc.relaxed_path(cache_dir, obj_id, expected_hash)

    # Pre-create that target so get_or_relax short-circuits on a cache hit
    # without needing fetch/relax_in_water mocked.
    expected_target.parent.mkdir(parents=True, exist_ok=True)
    expected_target.write_text("RELAXED")

    monkeypatch.setattr(rc, "relax_in_water", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("should not relax; expected a cache hit")))
    monkeypatch.setattr(rc, "fetch", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("should not fetch; expected a cache hit")))

    out = rc.get_or_relax(ref, cache_dir, CFG, obj_id=obj_id)
    assert out == expected_target
