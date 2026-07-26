import json

from pbg_parsimony.api import _public_structure
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
