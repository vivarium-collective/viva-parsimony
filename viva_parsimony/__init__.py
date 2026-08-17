"""viva-parsimony — reusable process-bigraph packing of 3D cell models.

Wraps the `parsimony <https://github.com/prismofeverything/parsimony>`_ engine
(a cellPACK-style molecular packer): resolve structures (PDB / mmCIF /
AlphaFold) → author a recipe → pack a capsule cell with a supercoiled rod
nucleoid. Organism-agnostic; the caller (e.g. v2ecoli) supplies the molecules,
abundances, names and categories.

High-level entry point: :func:`viva_parsimony.build_pack`.
"""
from viva_parsimony.api import Ingredient, Capsule, Chromosome, build_pack
from viva_parsimony.structures import StructureRef
from viva_parsimony.engine import find_parsimony_bin, ParsimonyNotFound
from viva_parsimony.processes import ParsimonyPackStep, register_parsimony

__all__ = [
    "Ingredient", "Capsule", "Chromosome", "build_pack",
    "StructureRef", "find_parsimony_bin", "ParsimonyNotFound",
    "ParsimonyPackStep", "register_parsimony",
]
