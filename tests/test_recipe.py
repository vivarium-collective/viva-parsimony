"""Pure tests for recipe/pipeline authoring + geometry (no network/binary)."""
import math

from viva_parsimony.recipe import object_block, author_recipe, build_pipeline, LOD_VOXELS
from viva_parsimony.api import Capsule


def test_object_block_lods_and_proxy():
    o = object_block((0.1, 0.2, 0.3), ["meshes/x.lod0.obj", "meshes/x.lod1.obj"], proxy_voxel_size=12.0)
    assert o["type"] == "mesh"
    assert o["color"] == [0.1, 0.2, 0.3]
    assert [l["path"] for l in o["mesh_lods"]] == ["meshes/x.lod0.obj", "meshes/x.lod1.obj"]
    assert o["mesh_lods"][0]["voxel_size"] == LOD_VOXELS[0]
    assert o["proxy_voxel_size"] == 12.0


def test_author_recipe_capsule_and_regions():
    r = author_recipe(
        "m", {"a": object_block((0, 0, 0), ["meshes/a.lod0.obj"])},
        interior=[{"object": "a", "count": 10}],
        surface=[{"object": "lip", "count": 5}],
        capsule={"half_len": 7000, "radius": 4000},
    )
    cell = r["composition"]["cell"]
    assert cell["compartment"]["kind"] == "capsule"
    assert cell["compartment"]["a"] == [-7000, 0, 0]
    assert cell["compartment"]["radius"] == 4000
    assert cell["regions"]["interior"][0]["object"] == "a"
    assert cell["regions"]["surface"][0]["object"] == "lip"
    assert r["format_version"] == "2.1-parsimony"
    assert "chromosome" not in r


def test_pipeline_stages_order():
    p = build_pipeline("m", "m.json", surface_ids=["lip"],
                       has_chromosome=True, has_fiber_proteins=True)
    ids = [s["id"] for s in p["stages"]]
    assert ids == ["chromosome", "membrane", "fiber_proteins", "interior"]
    assert p["backend"] == "octree"
    interior = [s for s in p["stages"] if s["id"] == "interior"][0]
    assert interior["exclude"] == ["lip"] and interior["densify"] is True
    assert "chromosome" in interior["depends_on"]


def test_pipeline_minimal_no_chromosome_no_surface():
    p = build_pipeline("m", "m.json", surface_ids=[], has_chromosome=False, has_fiber_proteins=False)
    assert [s["id"] for s in p["stages"]] == ["interior"]


def test_capsule_from_volume():
    cap = Capsule.from_volume_fl(1.15, radius_um=0.5)
    assert cap.radius == 5000.0          # 0.5 µm cap radius in Å
    assert cap.half_len >= cap.radius     # clamped to at least a rod, not a sphere
    bigger = Capsule.from_volume_fl(5.0, radius_um=0.5)
    assert bigger.half_len > cap.half_len  # more volume → longer rod
