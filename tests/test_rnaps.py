"""Test that explicit RNAP placements are serialized into the recipe chromosome block."""
import json
from pathlib import Path
from viva_parsimony import Chromosome, Capsule, Ingredient, build_pack


def test_rnaps_serialized_into_recipe(tmp_path):
    chrom = Chromosome(beads=1000, rnap_marker="rna_polymerase",
                       rnaps=[{"coordinates": 100000, "domain_index": 0, "is_forward": True}])
    ing = [Ingredient(id="rna_polymerase", count=0, sphere_radius=30.0, region="fiber")]
    res = build_pack(ing, Capsule(half_len=400, radius=120), chrom,
                     out_dir=tmp_path, name="t")
    recipe = json.loads(Path(res["recipe_path"]).read_text())
    chrom_block = recipe["chromosome"]
    assert chrom_block["rnap_marker"] == "rna_polymerase"
    assert chrom_block["rnaps"][0]["coordinates"] == 100000
