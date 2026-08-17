"""Process-bigraph Step wrapping the parsimony packing engine.

The Step takes per-ingredient counts as input (e.g. from an upstream whole-cell
model) and a structural *spec* as config (which structures/colors/categories,
the cell geometry, the chromosome), and emits a packed 3D cell.
"""
from __future__ import annotations
import copy
import logging

from process_bigraph import Step

from viva_parsimony.api import Ingredient, Capsule, Chromosome, build_pack
from viva_parsimony.structures import StructureRef
from viva_parsimony.relax_cache import get_or_relax

log = logging.getLogger(__name__)


def _ref(d) -> StructureRef:
    return StructureRef(kind=d["kind"], ref=d["ref"])


def spec_to_ingredients(spec: dict, counts: dict | None = None) -> list[Ingredient]:
    """Build :class:`Ingredient` objects from a spec's ``ingredients`` list,
    overriding ``count`` from ``counts[id]`` when provided."""
    counts = counts or {}
    out = []
    for it in spec.get("ingredients", []):
        out.append(Ingredient(
            id=it["id"],
            count=int(counts.get(it["id"], it.get("count", 1))),
            structure=_ref(it["structure"]),
            color=tuple(it.get("color", (0.6, 0.6, 0.6))),
            region=it.get("region", "interior"),
            display_name=it.get("display_name", ""),
            category=it.get("category", ""),
            proxy_voxel_size=it.get("proxy_voxel_size"),
        ))
    return out


def spec_capsule(spec: dict) -> Capsule:
    cap = spec["capsule"]
    if "volume_fl" in cap:
        return Capsule.from_volume_fl(cap["volume_fl"], cap.get("radius_um", 0.5))
    return Capsule(half_len=cap["half_len"], radius=cap["radius"])


def spec_chromosome(spec: dict) -> Chromosome | None:
    c = spec.get("chromosome")
    if not c:
        return None
    seg = _ref(c["segment"]) if c.get("segment") else None
    kw = {k: c[k] for k in ("beads", "spacing", "bead_radius", "genome_csv", "supercoil")
          if k in c}
    return Chromosome(segment=seg, **kw)


class ParsimonyPackStep(Step):
    """Pack a 3D cell from molecular counts + a structural spec."""

    config_schema = {
        "spec": "any",
        "out_dir": {"_type": "string", "_default": "out/parsimony"},
        "name": {"_type": "string", "_default": "model"},
        "scale": {"_type": "float", "_default": 1.0},
        "proxy_lod": {"_type": "integer", "_default": 2},
    }

    def inputs(self):
        return {"counts": "any"}

    def outputs(self):
        return {"pack": "any"}

    def update(self, state, interval=None):
        spec = self.config["spec"]
        res = build_pack(
            spec_to_ingredients(spec, state.get("counts")),
            spec_capsule(spec),
            spec_chromosome(spec),
            out_dir=self.config["out_dir"], name=self.config["name"],
            scale=self.config["scale"], proxy_lod=self.config["proxy_lod"],
        )
        return {"pack": res}


RELAX_PARAM_KEYS = ("forcefield", "water_model", "padding_nm", "ionic_strength_M",
                    "temperature_K", "timestep_fs", "equil_ps", "minimize", "seed")

_RELAXABLE_KINDS = {"alphafold", "pdb", "cif"}


def relax_spec(spec: dict, *, relax: bool, cache_dir, relax_cfg: dict) -> dict:
    """Return a copy of ``spec`` with each ingredient's structure rewritten to
    its cached RELAXED file (opt-in). ``relax=False`` returns the spec
    unchanged (deep-copied; the original is never mutated). Only
    alphafold/pdb/cif structures are relaxed; ``file`` refs pass through.

    Any failure relaxing a single ingredient (network/fetch error, missing
    OpenMM, unparseable structure, etc.) is logged and that ingredient's
    original structure ref is left in place — matching the non-relax path's
    behavior of skipping a bad ingredient rather than aborting the whole
    pack (see ``build_pack``)."""
    out = copy.deepcopy(spec)
    if not relax:
        return out
    for ing in out.get("ingredients", []):
        structure = ing.get("structure")
        if not structure or structure.get("kind") not in _RELAXABLE_KINDS:
            continue
        try:
            p = get_or_relax(structure, cache_dir, relax_cfg, obj_id=ing["id"])
            ing["structure"] = {"kind": "file", "ref": str(p)}
        except Exception as exc:  # fetch fail / openmm missing / bad ref → build on raw
            log.warning("relax skipped for %s (%s); using unrelaxed structure", ing["id"], exc)
    return out


class StructureRelaxStep(Step):
    """Opt-in upstream Step: rewrite each ingredient's fetched structure to
    its cached water-relaxed structure before packing."""

    config_schema = {
        "relax": {"_type": "boolean", "_default": False},
        "cache_dir": {"_type": "string", "_default": "out/cache"},
        "forcefield": {"_type": "list[string]",
                       "_default": ["amber14-all.xml", "amber14/tip3pfb.xml"]},
        "water_model": {"_type": "string", "_default": "tip3p"},
        "padding_nm": {"_type": "float", "_default": 1.0},
        "ionic_strength_M": {"_type": "float", "_default": 0.15},
        "temperature_K": {"_type": "float", "_default": 300.0},
        "timestep_fs": {"_type": "float", "_default": 2.0},
        "equil_ps": {"_type": "float", "_default": 200.0},
        "minimize": {"_type": "boolean", "_default": True},
        "seed": {"_type": "integer", "_default": 0},
    }

    def inputs(self):
        return {"spec": "any"}

    def outputs(self):
        return {"spec": "any"}

    def update(self, state, interval=None):
        relax_cfg = {k: self.config[k] for k in RELAX_PARAM_KEYS}
        return {"spec": relax_spec(state["spec"], relax=self.config["relax"],
                                    cache_dir=self.config["cache_dir"], relax_cfg=relax_cfg)}


def register_parsimony(core):
    """Register the Steps so ``local:ParsimonyPackStep``/``local:StructureRelaxStep``
    resolve in composites."""
    core.register_link("ParsimonyPackStep", ParsimonyPackStep)
    core.register_link("StructureRelaxStep", StructureRelaxStep)
    return core
