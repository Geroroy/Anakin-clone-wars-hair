"""
hair_pipeline.py - Blender(bpy) pipeline for restyling the `hair_anakin_01_mesh.fbx` hair-card asset.

Run with the `bpy` python module (pip install bpy) or inside Blender:

    python3 tools/hair_pipeline.py --style styles/anakin_ahsoka.json --out output --render
    python3 tools/hair_pipeline.py --style none --render            # just re-render the original

What it does
  1. imports the FBX (armature `Reference`, scalp cap `hair_cap`, hair cards `HairPlanes_M`)
  2. builds Principled materials from the reference textures (strip atlas albedo/alpha + normal for the
     cards, scalp albedo + normal/flow for the cap)
  3. optionally restyles every hair card with a parametric, region-based deformation
     (length, sweep direction, wave, volume lift, nape curl) - roots never move, skin weights untouched
  4. exports the result as FBX (+ .blend) and renders front / 3-4 / side / back previews

The style preset is a JSON file - see styles/anakin_ahsoka.json and PROMPT.md for the meaning of
every parameter.
"""
import argparse
import json
import math
import os
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_FBX = os.path.join(ROOT, "source", "hair_anakin_01_mesh.fbx")
TEX = os.path.join(ROOT, "reference", "textures")
TEXTURES = {
    "cards_albedo": os.path.join(TEX, "hair_strips_albedo_alpha_1024x512.webp"),
    "cards_normal": os.path.join(TEX, "hair_strips_normal_1024x512.webp"),
    "cap_albedo": os.path.join(TEX, "hair_scalp_albedo_1500.webp"),
    "cap_normal": os.path.join(TEX, "hair_scalp_flow_or_id_2000.webp"),
}

CARDS_NAME = "HairPlanes_M"
CAP_NAME = "hair_cap"

# Character frame after import (Blender Z-up): face looks down -Y, character's LEFT is +X.
# Measured from the armature: Head bone at z=1.634, ears at z~1.66-1.74, forehead at y~-0.10.
HEAD_CENTER = Vector((0.0, -0.04, 1.70))
HEAD_RADII = Vector((0.080, 0.098, 0.112))  # ellipsoid used as a collision proxy / preview head


# --------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------
def log(*a):
    print("[hair_pipeline]", *a)
    sys.stdout.flush()


def smoothstep(a, b, x):
    if a == b:
        return 1.0 if x >= b else 0.0
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def load_image(path, non_color=False):
    img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    img.alpha_mode = "STRAIGHT"
    return img


def build_material(name, albedo, normal, use_alpha, flip_v, color_tint=(1, 1, 1, 1), tint_mix=0.0,
                   roughness=0.6, use_normal=False, specular=0.08):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = roughness
    # thin stacked cards at grazing angles go white with a normal dielectric Fresnel - keep spec low
    bsdf.inputs["Specular IOR Level"].default_value = specular
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVChannel0"
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.0, -1.0 if flip_v else 1.0, 1.0)
    mapping.inputs["Location"].default_value = (0.0, 1.0 if flip_v else 0.0, 0.0)
    nt.links.new(uv.outputs["UV"], mapping.inputs["Vector"])

    tex_a = nt.nodes.new("ShaderNodeTexImage")
    tex_a.image = load_image(albedo)
    tex_a.extension = "EXTEND"
    nt.links.new(mapping.outputs["Vector"], tex_a.inputs["Vector"])

    # optional colour tint (hair dye) mixed over the albedo
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MIX"
    mix.inputs["Factor"].default_value = tint_mix
    nt.links.new(tex_a.outputs["Color"], mix.inputs[6])
    mix.inputs[7].default_value = color_tint
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])

    if use_alpha:
        nt.links.new(tex_a.outputs["Alpha"], bsdf.inputs["Alpha"])
        mat.surface_render_method = "DITHERED"
        mat.use_backface_culling = False

    if use_normal and normal and os.path.exists(normal):
        tex_n = nt.nodes.new("ShaderNodeTexImage")
        tex_n.image = load_image(normal, non_color=True)
        nt.links.new(mapping.outputs["Vector"], tex_n.inputs["Vector"])
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.uv_map = "UVChannel0"
        nmap.inputs["Strength"].default_value = 0.35
        nt.links.new(tex_n.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def island_components(bm):
    """Connected vertex islands of a bmesh -> list[list[BMVert]] (one per hair card)."""
    seen = set()
    islands = []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, comp = [v], []
        while stack:
            x = stack.pop()
            if x.index in seen:
                continue
            seen.add(x.index)
            comp.append(x)
            for e in x.link_edges:
                o = e.other_vert(x)
                if o.index not in seen:
                    stack.append(o)
        islands.append(comp)
    return islands


# --------------------------------------------------------------------------------------------
# scene
# --------------------------------------------------------------------------------------------
def import_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=SRC_FBX)
    cards = bpy.data.objects[CARDS_NAME]
    cap = bpy.data.objects[CAP_NAME]
    return cards, cap


def assign_materials(cards, cap, style):
    flip = style.get("texture_flip_v", False)
    tint = style.get("hair_tint_rgb", [1, 1, 1]) + [1.0]
    tint_mix = style.get("hair_tint_mix", 0.0)
    rough = style.get("roughness", 0.6)
    use_n = style.get("use_normal_maps", False)
    spec = style.get("specular", 0.08)
    m_cards = build_material("M_HairCards", TEXTURES["cards_albedo"], TEXTURES["cards_normal"], True, flip,
                             tint, tint_mix, rough, use_n, spec)
    m_cap = build_material("M_HairCap", TEXTURES["cap_albedo"], TEXTURES["cap_normal"], True, flip,
                           tint, tint_mix, min(1.0, rough + 0.1), use_n, spec)
    for o, m in ((cards, m_cards), (cap, m_cap)):
        o.data.materials.clear()
        o.data.materials.append(m)


# --------------------------------------------------------------------------------------------
# restyle
# --------------------------------------------------------------------------------------------
class Card:
    __slots__ = ("verts", "root", "tip", "length", "dirn", "s", "region", "outward", "root_dir")

    def __init__(self, verts, uv_v, capbvh, M):
        self.verts = verts
        co = np.array([(M @ v.co)[:] for v in verts])
        lo = co[uv_v <= uv_v.min() + 0.05]
        hi = co[uv_v >= uv_v.max() - 0.05]
        # the root row is the row nearest the scalp cap (for this asset it is UV v-min for 443/463 cards)
        d_lo = np.mean([capbvh.find_nearest(Vector(p))[3] for p in lo])
        d_hi = np.mean([capbvh.find_nearest(Vector(p))[3] for p in hi])
        root_is_lo = d_lo <= d_hi
        self.root = Vector((lo if root_is_lo else hi).mean(0))
        self.tip = Vector((hi if root_is_lo else lo).mean(0))
        self.length = (self.tip - self.root).length
        self.dirn = (self.tip - self.root).normalized() if self.length > 1e-6 else Vector((0, 0, -1))
        # normalised position along the card 0=root 1=tip, from the UV v coordinate
        vr = uv_v.max() - uv_v.min()
        s = (uv_v - uv_v.min()) / vr if vr > 1e-6 else np.zeros_like(uv_v)
        self.s = s if root_is_lo else 1.0 - s
        # outward direction from the head centre at the root (ellipsoid normal)
        rel = self.root - HEAD_CENTER
        n = Vector((rel.x / HEAD_RADII.x ** 2, rel.y / HEAD_RADII.y ** 2, rel.z / HEAD_RADII.z ** 2))
        self.outward = n.normalized()
        self.root_dir = rel


def classify(card):
    """Return region weights for a card from its root position: front / side_L / side_R / back / top."""
    rel = card.root - HEAD_CENTER
    # horizontal angle: 0 = front (-Y), +90 = character's left (+X), 180 = back
    ang = math.degrees(math.atan2(rel.x, -rel.y))  # -180..180, front = 0
    a = abs(ang)
    height = rel.z  # metres above head centre (~ +0.08 at crown, 0 at ear height)
    w = {}
    w["top"] = smoothstep(0.03, 0.08, height)
    w["front"] = (1 - smoothstep(35, 70, a)) * (1 - w["top"])
    w["back"] = smoothstep(110, 145, a) * (1 - w["top"])
    side = (1 - w["front"] - w["back"]) * (1 - w["top"])
    w["side_L"] = side if ang > 0 else 0.0
    w["side_R"] = side if ang <= 0 else 0.0
    w["nape"] = smoothstep(110, 145, a) * (1 - smoothstep(-0.07, -0.02, height))
    return w, ang, height


def region_value(style_regions, key, w, default=0.0):
    """Blend a per-region parameter with the card's region weights."""
    total, acc = 0.0, 0.0
    for r, wr in w.items():
        if r == "nape":
            continue
        val = style_regions.get(r, {}).get(key, default)
        acc += wr * val
        total += wr
    return acc / total if total > 1e-6 else default


def restyle(cards_obj, cap_obj, style):
    M = cards_obj.matrix_world
    Mi = M.inverted()
    mesh = cards_obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    uv_lay = bm.loops.layers.uv.active
    capbm = bmesh.new()
    capbm.from_object(cap_obj, bpy.context.evaluated_depsgraph_get())
    capbm.transform(cap_obj.matrix_world)
    capbvh = BVHTree.FromBMesh(capbm)

    regions = style["regions"]
    part_x = style.get("part_x", -0.03)            # x of the parting line (character's right = -X)
    part_width = style.get("part_width", 0.025)
    sweep_dir = Vector(style.get("sweep_dir", [1.0, 0.25, -0.1])).normalized()  # top hair target direction
    wave_freq = style.get("wave_freq", 1.2)
    wave_phase_seed = style.get("seed", 7)
    rng = np.random.default_rng(wave_phase_seed)
    g_len = style.get("length_scale", 1.0)
    collision_margin = style.get("collision_margin", 0.004)
    max_rise = style.get("max_rise", 0.025)          # no vertex may end more than this above where it was
    front_extra_rise = style.get("front_extra_rise", 0.06)
    max_out = style.get("max_out", 0.035)            # hair envelope: max distance from the scalp ellipsoid
    wave_coherence = style.get("wave_coherence", 5.0)  # waves per metre across the scalp
    wave_jitter = style.get("wave_jitter", 0.35)       # radians of random phase per card
    crown_z = max((cap_obj.matrix_world @ v.co).z for v in cap_obj.data.vertices) + style.get("crown_clearance", 0.012)

    islands = island_components(bm)
    stats = {"cards": len(islands), "moved": 0}
    for comp in islands:
        uv_v = np.array([np.mean([l[uv_lay].uv.y for l in v.link_loops]) for v in comp])
        card = Card(comp, uv_v, capbvh, M)
        if card.length < 0.005:
            continue
        w, ang, height = classify(card)

        length_scale = g_len * region_value(regions, "length", w, 1.0)
        lift = region_value(regions, "lift", w, 0.0)
        wave_amp = region_value(regions, "wave_amp", w, 0.0)
        sweep = region_value(regions, "sweep", w, 0.0)
        curl = regions.get("nape", {}).get("curl", 0.0) * w["nape"]
        droop = region_value(regions, "droop", w, 0.0)

        # parting: top cards on the far side of the part line sweep away from it, cards on the part
        # line itself get pushed sideways so the scalp shows through (like the references)
        part_side = 1.0 if card.root.x > part_x else -1.0
        part_dist = abs(card.root.x - part_x)
        part_f = w["top"] * (1 - smoothstep(0.0, part_width, part_dist))

        # target direction for sweeping: per-region sweep_dir blended by the region weights,
        # falling back to the global sweep_dir
        target = Vector((0, 0, 0))
        for r, wr in w.items():
            if r == "nape" or wr <= 0:
                continue
            d = regions.get(r, {}).get("sweep_dir")
            target += wr * (Vector(d).normalized() if d else sweep_dir)
        if target.length < 1e-6:
            target = Vector(sweep_dir)
        target.normalize()
        if part_side < 0 and (w["top"] > 0.5 or w["front"] > 0.5):
            # cards on the short side of the parting are combed the other way (back / down)
            target = Vector((-target.x, target.y, target.z))
        target = (target + 0.4 * card.outward).normalized()
        # wave phase follows the root position so neighbouring cards form one coherent S-wave
        # (a purely random phase gives a wind-blown, shredded look)
        phase = 2 * math.pi * (card.root.x * wave_coherence + card.root.y * wave_coherence * 0.5) \
            + rng.uniform(-wave_jitter, wave_jitter)
        side_axis = card.dirn.cross(card.outward)
        if side_axis.length < 1e-6:
            side_axis = Vector((1, 0, 0))
        side_axis.normalize()

        for v, s in zip(comp, card.s):
            p = M @ v.co
            off = p - card.root
            # 1) length: scale the offset from the root
            off = off * length_scale
            # 2) sweep: rotate the whole card frame (so the card never turns edge-on) toward the target
            #    direction; the rotation grows from the root (0) to the tip (full)
            k = sweep * smoothstep(0.0, 1.0, s)
            new_dir = (card.dirn * (1 - k) + target * k).normalized()
            off = card.dirn.rotation_difference(new_dir) @ off
            # 3) parting push (sideways away from the part line)
            off += Vector((part_side * part_f * 0.012 * s, 0, 0))
            # 4) wave: S-curve along the card, growing toward the tip
            if wave_amp > 0:
                off += card.outward * (wave_amp * math.sin(2 * math.pi * wave_freq * s + phase) * (0.25 + 0.75 * s))
                off += side_axis * (0.5 * wave_amp * math.cos(2 * math.pi * wave_freq * s + phase) * s)
            # 5) volume lift: push tips outward from the head
            off += card.outward * (lift * s * s)
            # 6) gravity droop: tips sink a little
            off += Vector((0, 0, -droop * s * s))
            # 7) nape curl: tips flick outward / upward at the back of the neck
            if curl > 0:
                off += (card.outward * 1.0 + Vector((0, 0.4, 0.3))) * (curl * s ** 3)
            newp = card.root + off
            # keep stray cards from standing up above the crown
            # (the fringe is allowed to rise further so it can be swept up off the forehead)
            newp.z = min(newp.z, p.z + max_rise + front_extra_rise * w["front"], crown_z)
            # collision with the head ellipsoid: keep every vertex outside the scalp
            rel = newp - HEAD_CENTER
            e = Vector((rel.x / HEAD_RADII.x, rel.y / HEAD_RADII.y, rel.z / HEAD_RADII.z))
            lo_e = 1.0 + collision_margin / HEAD_RADII.x
            hi_e = 1.0 + max_out / HEAD_RADII.x
            if s > 0.05 and (e.length < lo_e or e.length > hi_e):
                scale = (lo_e if e.length < lo_e else hi_e) / max(e.length, 1e-6)
                newp = HEAD_CENTER + Vector((rel.x * scale, rel.y * scale, rel.z * scale))
            v.co = Mi @ newp
        stats["moved"] += len(comp)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return stats


# --------------------------------------------------------------------------------------------
# render / export
# --------------------------------------------------------------------------------------------
def add_preview_head(style):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=1.0, location=HEAD_CENTER)
    head = bpy.context.active_object
    head.name = "PreviewHead"
    head.scale = (HEAD_RADII.x - 0.004, HEAD_RADII.y - 0.004, HEAD_RADII.z - 0.004)
    bpy.ops.object.shade_smooth()
    m = bpy.data.materials.new("M_PreviewHead")
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.42, 0.35, 1)
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.6
    head.data.materials.append(m)
    # neck
    bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=0.16, location=(0, -0.03, 1.56))
    neck = bpy.context.active_object
    neck.name = "PreviewNeck"
    neck.data.materials.append(m)
    return head


def setup_render(res, samples):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.cycles.transparent_max_bounces = 24
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Filmic" if "Filmic" in [i.name for i in sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "AgX"
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.35, 0.37, 0.40, 1)
    bg.inputs["Strength"].default_value = 1.0
    sc.world = world
    # key / fill lights
    for name, loc, energy in (("Key", (0.6, -0.9, 2.4), 60), ("Fill", (-0.9, -0.6, 2.0), 25), ("Rim", (0.2, 0.9, 2.3), 40)):
        bpy.ops.object.light_add(type="AREA", location=loc)
        L = bpy.context.active_object
        L.name = name
        L.data.energy = energy
        L.data.size = 0.8
        direction = HEAD_CENTER - Vector(loc)
        L.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 85
    cam = bpy.data.objects.new("Cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    return cam


def render_views(cam, out_dir, prefix):
    os.makedirs(out_dir, exist_ok=True)
    views = {
        "front": (0.0, -0.95, 0.03),
        "three_quarter": (0.65, -0.70, 0.05),
        "side_L": (0.95, 0.0, 0.03),
        "back": (0.0, 0.95, 0.03),
    }
    target = HEAD_CENTER + Vector((0, 0, 0.03))
    files = []
    for name, off in views.items():
        cam.location = target + Vector(off)
        cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
        path = os.path.join(out_dir, f"{prefix}_{name}.png")
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        files.append(path)
        log("rendered", path)
    return files


def export(cards, cap, out_dir, name):
    os.makedirs(out_dir, exist_ok=True)
    for o in bpy.data.objects:
        o.select_set(o.name in (CARDS_NAME, CAP_NAME, "Reference"))
    fbx_path = os.path.join(out_dir, name + ".fbx")
    bpy.ops.export_scene.fbx(filepath=fbx_path, use_selection=True, add_leaf_bones=False, path_mode="COPY",
                             embed_textures=False, mesh_smooth_type="FACE", apply_scale_options="FBX_SCALE_ALL")
    log("exported", fbx_path)
    blend_path = os.path.join(out_dir, name + ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, copy=True)
    log("saved", blend_path)
    return fbx_path


# --------------------------------------------------------------------------------------------
def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", default=os.path.join(ROOT, "styles", "anakin_ahsoka.json"),
                    help="style preset json, or 'none' to keep the original hairstyle")
    ap.add_argument("--out", default=os.path.join(ROOT, "output"))
    ap.add_argument("--renders", default=os.path.join(ROOT, "renders"))
    ap.add_argument("--name", default=None, help="output file stem")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--res", type=int, default=900)
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--flip-v", dest="flip_v", default=None, choices=["0", "1"],
                    help="override texture_flip_v from the style")
    args = ap.parse_args(argv)

    if args.style == "none":
        style = {"name": "original", "regions": {}}
        do_restyle = False
    else:
        with open(args.style) as f:
            style = json.load(f)
        do_restyle = True
    if args.flip_v is not None:
        style["texture_flip_v"] = args.flip_v == "1"
    name = args.name or ("hair_anakin_01_" + style.get("name", "restyled"))

    cards, cap = import_scene()
    assign_materials(cards, cap, style)
    if do_restyle:
        stats = restyle(cards, cap, style)
        log("restyled", stats)
    if not args.no_export:
        export(cards, cap, args.out, name)
    if args.render:
        add_preview_head(style)
        cam = setup_render(args.res, args.samples)
        render_views(cam, args.renders, name)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    main(argv)
