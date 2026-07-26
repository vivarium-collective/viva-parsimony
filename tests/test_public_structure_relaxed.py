import json
from dataclasses import dataclass

from pbg_parsimony.api import _public_structure, _publish_relaxed_pdb
from pbg_parsimony.structures import StructureRef


def test_relaxed_file_ref_reports_provenance(tmp_path):
    pdb = tmp_path / "gapdh__abc123.pdb"
    pdb.write_text("ATOM\n")
    (tmp_path / "gapdh__abc123.provenance.json").write_text(json.dumps(
        {"source": "alphafold", "id": "P0A9B2", "model_version": "v4", "relaxed": True, "seed": 0}))
    rec = _public_structure(StructureRef(kind="file", ref=str(pdb)))
    assert rec["db"] == "relaxed" and rec["id"] == "P0A9B2"
    assert rec["provenance"]["relaxed"] is True


def test_plain_file_ref_still_none(tmp_path):
    pdb = tmp_path / "plain.pdb"
    pdb.write_text("ATOM\n")
    assert _public_structure(StructureRef(kind="file", ref=str(pdb))) is None


@dataclass
class _FakeIngredient:
    """Minimal stand-in for api.Ingredient — only what _publish_relaxed_pdb reads."""
    id: str
    structure: StructureRef


def test_publish_relaxed_pdb_copies_into_struct_cache(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    pdb = src_dir / "gapdh__abc123.pdb"
    pdb.write_text("ATOM      1  N   MET A   1\n")
    (src_dir / "gapdh__abc123.provenance.json").write_text(json.dumps(
        {"source": "alphafold", "id": "P0A9B2", "model_version": "v4", "relaxed": True, "seed": 0}))

    ing = _FakeIngredient(id="gapdh", structure=StructureRef(kind="file", ref=str(pdb)))
    st = _public_structure(ing.structure)
    assert st["db"] == "relaxed"

    struct_cache = tmp_path / "out" / "structures"
    _publish_relaxed_pdb(ing, st, struct_cache)

    dest = struct_cache / "gapdh.pdb"
    assert dest.exists()
    assert dest.read_text() == pdb.read_text()
    assert st["url"] == "structures/gapdh.pdb"


def test_publish_relaxed_pdb_missing_source_leaves_no_url(tmp_path):
    ing = _FakeIngredient(id="gapdh", structure=StructureRef(kind="file", ref=str(tmp_path / "gone.pdb")))
    st = {"db": "relaxed", "id": "P0A9B2", "provenance": {}}
    struct_cache = tmp_path / "out" / "structures"
    _publish_relaxed_pdb(ing, st, struct_cache)
    assert "url" not in st
    assert not struct_cache.exists()


def test_publish_relaxed_pdb_noop_for_non_relaxed():
    ing = _FakeIngredient(id="x", structure=StructureRef(kind="alphafold", ref="P0A9B2"))
    st = {"db": "alphafold", "id": "P0A9B2"}
    _publish_relaxed_pdb(ing, st, None)  # struct_cache never touched
    assert "url" not in st
