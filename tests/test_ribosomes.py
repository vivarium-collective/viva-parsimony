"""Test that ribosome placements are serialized into the recipe chromosome block."""
import json
from pathlib import Path
from viva_parsimony import Chromosome, Capsule, Ingredient, build_pack


def test_ribosomes_serialized_into_recipe(tmp_path):
    chrom = Chromosome(beads=1000, ribosome_marker="70S_ribosome",
                       ribosomes=[{"mRNA_index": 20, "pos_on_mRNA": 0, "peptide_length": 0}])
    ing = [Ingredient(id="70S_ribosome", count=0, sphere_radius=15.0)]
    res = build_pack(ing, Capsule(half_len=400, radius=120), chrom,
                     out_dir=tmp_path, name="t")
    recipe = json.loads(Path(res["recipe_path"]).read_text())
    chrom_block = recipe["chromosome"]
    assert chrom_block["ribosome_marker"] == "70S_ribosome"
    assert chrom_block["ribosomes"][0]["mRNA_index"] == 20


def test_default_chromosome_no_ribosomes(tmp_path):
    """A default Chromosome must not add ribosomes/ribosome_marker keys."""
    chrom = Chromosome(beads=1000)
    ing = [Ingredient(id="sphere", count=0, sphere_radius=8.0)]
    res = build_pack(ing, Capsule(half_len=400, radius=120), chrom,
                     out_dir=tmp_path, name="t")
    cb = json.loads(Path(res["recipe_path"]).read_text())["chromosome"]
    assert "ribosomes" not in cb
    assert "ribosome_marker" not in cb
