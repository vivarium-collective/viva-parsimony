"""Test that nascent-RNA specs are serialized into the recipe chromosome block."""
import json
from pathlib import Path
from viva_parsimony import Chromosome, Capsule, Ingredient, build_pack


def test_rnas_serialized_into_recipe(tmp_path):
    chrom = Chromosome(beads=1000, rna_segment="rna_segment", rna_angstrom_per_nt=2.0,
                       rnas=[{"root_coordinate": 100000, "root_domain": 0, "length_nt": 850, "is_mRNA": True}])
    ing = [Ingredient(id="rna_segment", count=0, sphere_radius=8.0)]
    res = build_pack(ing, Capsule(half_len=400, radius=120), chrom, out_dir=tmp_path, name="t")
    cb = json.loads(Path(res["recipe_path"]).read_text())["chromosome"]
    assert cb["rna_segment"] == "rna_segment"
    assert cb["rnas"][0]["length_nt"] == 850
    assert cb["rna_angstrom_per_nt"] == 2.0


def test_default_chromosome_recipe_unchanged(tmp_path):
    """A default Chromosome must not add rnas/rna_segment/rna_angstrom_per_nt keys."""
    chrom = Chromosome(beads=1000)
    ing = [Ingredient(id="rna_segment", count=0, sphere_radius=8.0)]
    res = build_pack(ing, Capsule(half_len=400, radius=120), chrom, out_dir=tmp_path, name="t")
    cb = json.loads(Path(res["recipe_path"]).read_text())["chromosome"]
    assert "rnas" not in cb
    assert "rna_segment" not in cb
    assert "rna_angstrom_per_nt" not in cb
