"""Turntable MP4 of an IFC model: flat colours, z-buffer, no GPU.

    python3 tools/ifc_orbit.py model.ifc orbit.mp4 [frames]

Visual QA a machine can start and only a person can finish: the frames
come from the delivered IFC's own tessellated geometry -- never from
the tool that made the model -- so anything that looks wrong in the
video is wrong in the model. Colours come from each element's own
assigned IfcMaterial where one is named (timber reads timber, dark
render reads dark), falling back to the class palette autobuild styles
elements with; glazing stays transparent so the interior reads through
it; the sun casts a flat projected shadow on the ground so the massing
sits instead of floating. The camera orbits at a gentle elevation so
massing reads the way concept sketches draw it.

Pure Python plus numpy and ifcopenshell for geometry; the encode needs
imageio and imageio-ffmpeg (pip install imageio imageio-ffmpeg), and
the script says so plainly when they are missing.
"""
import math
import sys

import numpy as np

try:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element
except ImportError as exc:
    sys.exit(f"ifcopenshell is required: {exc}")
try:
    import imageio.v2 as imageio
except ImportError:
    sys.exit("the encode needs imageio and imageio-ffmpeg: "
             "pip install imageio imageio-ffmpeg")

if len(sys.argv) < 3:
    sys.exit(__doc__.strip().splitlines()[2].strip())
IFC_PATH, OUT_PATH = sys.argv[1], sys.argv[2]
FRAME_COUNT = int(sys.argv[3]) if len(sys.argv) > 3 else 180

LOOK = {
    'IfcWall': ((.93, .91, .87), 0), 'IfcCurtainWall': ((.55, .73, .88), .55),
    'IfcSlab': ((.83, .81, .77), 0), 'IfcRoof': ((.37, .40, .43), 0),
    'IfcColumn': ((.79, .76, .71), 0), 'IfcDoor': ((.56, .38, .25), 0),
    'IfcWindow': ((.61, .80, .92), .5), 'IfcCovering': ((.85, .83, .80), 0),
}
#: Named materials override the class palette; matched by substring so
#: "Timber decking" and "Timber cladding" both read as timber.
MATERIALS = (
    ("dark timber", (0.36, 0.27, 0.20)),
    ("timber", (0.70, 0.53, 0.34)),
    ("wood", (0.70, 0.53, 0.34)),
    ("dark", (0.30, 0.32, 0.34)),
    ("charcoal", (0.30, 0.32, 0.34)),
    ("white", (0.95, 0.95, 0.93)),
    ("glass", (0.61, 0.80, 0.92)),
)
SKY_TOP = np.array([0.639, 0.745, 0.855])
SKY_BOTTOM = np.array([0.97, 0.97, 0.96])
GROUND = np.array([0.878, 0.867, 0.827])


def material_name(element):
    try:
        material = ifcopenshell.util.element.get_material(element)
    except Exception:
        return ""
    if material is None:
        return ""
    return (getattr(material, "Name", "") or "").lower()


model = ifcopenshell.open(IFC_PATH)
settings = ifcopenshell.geom.settings()
try:
    settings.set("use-world-coords", True)
except Exception:
    settings.set(settings.USE_WORLD_COORDS, True)

opaque, glass = [], []
for element in model.by_type("IfcElement"):
    if element.is_a("IfcOpeningElement"):
        continue
    try:
        shape = ifcopenshell.geom.create_shape(settings, element)
    except Exception as exc:
        print("skip", element.is_a(), exc)
        continue
    verts = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3)
    faces = np.array(shape.geometry.faces, dtype=int).reshape(-1, 3)
    colour, alpha = LOOK.get(element.is_a(), ((0.8, 0.8, 0.8), 0))
    named = material_name(element)
    for token, override in MATERIALS:
        if token in named:
            colour = override
            break
    bucket = glass if alpha > 0 else opaque
    bucket.append((verts, faces, np.array(colour), alpha))

everything = np.vstack([v for v, _f, _c, _a in opaque + glass])
low, high = everything.min(axis=0), everything.max(axis=0)
centre = (low + high) / 2.0
radius = float(np.linalg.norm((high - low)[:2])) * 0.62 + 6.0
GROUND_Z = float(low[2]) - 0.01

WIDTH, HEIGHT, FRAMES, FPS = 960, 540, FRAME_COUNT, 30
FOCAL = 1.35  # ~35 mm feel
LIGHT = np.array([-0.42, -0.38, 0.82])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
#: The sun's travel: where LIGHT comes from, shadows go the other way.
SHADOW_DIR = -LIGHT

row_gradient = np.linspace(0.0, 1.0, HEIGHT)[:, None]
background = (SKY_TOP[None, None, :] * (1 - row_gradient[..., None])
              + SKY_BOTTOM[None, None, :] * row_gradient[..., None])
background = np.repeat(background, WIDTH, axis=1)

# The ground: a lawn of small tiles, small enough that only tiles
# genuinely behind the camera are culled.
G, TILE = 60.0, 5.0
ground_verts, ground_faces = [], []
steps = int(2 * G / TILE)
for iy in range(steps):
    for ix in range(steps):
        x0 = centre[0] - G + ix * TILE
        y0 = centre[1] - G + iy * TILE
        base = len(ground_verts)
        ground_verts += [[x0, y0, GROUND_Z], [x0 + TILE, y0, GROUND_Z],
                         [x0 + TILE, y0 + TILE, GROUND_Z], [x0, y0 + TILE, GROUND_Z]]
        ground_faces += [[base, base + 1, base + 2], [base, base + 2, base + 3]]
ground_verts = np.array(ground_verts)
ground_faces = np.array(ground_faces)


def shadow_of(verts):
    """Vertices dropped along the sun onto the ground plane."""
    t = (GROUND_Z - verts[:, 2]) / SHADOW_DIR[2]
    flat = verts + t[:, None] * SHADOW_DIR
    flat[:, 2] = GROUND_Z + 0.002
    return flat


def rasterise(frame, zbuf, pts, faces, colour, shade_only=None, alpha=0.0,
              mask=None, idbuf=None, element_id=0):
    for tri in faces:
        p = pts[tri]
        if np.any(p[:, 2] <= 0.1):
            continue
        xs, ys = p[:, 0], p[:, 1]
        x0, x1 = int(max(0, xs.min())), int(min(WIDTH - 1, xs.max()))
        y0, y1 = int(max(0, ys.min())), int(min(HEIGHT - 1, ys.max()))
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        d = ((xs[1] - xs[0]) * (ys[2] - ys[0]) - (xs[2] - xs[0]) * (ys[1] - ys[0]))
        if abs(d) < 1e-9:
            continue
        w0 = ((xs[1] - gx) * (ys[2] - gy) - (xs[2] - gx) * (ys[1] - gy)) / d
        w1 = ((xs[2] - gx) * (ys[0] - gy) - (xs[0] - gx) * (ys[2] - gy)) / d
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        if mask is not None:
            mask[y0:y1 + 1, x0:x1 + 1] |= inside
            continue
        depth = w0 * p[0, 2] + w1 * p[1, 2] + w2 * p[2, 2]
        window = zbuf[y0:y1 + 1, x0:x1 + 1]
        closer = inside & (depth < window - (1e-4 if alpha else 0.0))
        if not closer.any():
            continue
        if shade_only:
            a = shade_only[0]
            band = 1.0 if a > 0.62 else 0.86 if a > 0.28 else 0.72
            shaded = colour * band
        else:
            shaded = colour
        target = frame[y0:y1 + 1, x0:x1 + 1]
        if alpha:
            target[closer] = target[closer] * alpha + shaded * (1 - alpha)
            if idbuf is not None:
                idbuf[y0:y1 + 1, x0:x1 + 1][closer] = element_id
        else:
            window[closer] = depth[closer]
            target[closer] = shaded
            if idbuf is not None:
                idbuf[y0:y1 + 1, x0:x1 + 1][closer] = element_id


def project(verts, eye, forward, right, up):
    rel = verts - eye
    cx = rel @ right
    cy = rel @ up
    cz = rel @ forward
    with np.errstate(divide="ignore", invalid="ignore"):
        sx = (cx / cz) * FOCAL * HEIGHT + WIDTH / 2.0
        sy = HEIGHT / 2.0 - (cy / cz) * FOCAL * HEIGHT
    return np.stack([sx, sy, cz], axis=1)


def draw_frame(eye, look):
    forward = look - eye
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, np.array([0.0, 0.0, 1.0]))
    right = right / np.linalg.norm(right)
    up = np.cross(right, forward)

    frame = background.copy()
    zbuf = np.full((HEIGHT, WIDTH), np.inf)
    idbuf = np.zeros((HEIGHT, WIDTH), dtype=np.int32)

    pts = project(ground_verts, eye, forward, right, up)
    rasterise(frame, zbuf, pts, ground_faces, GROUND, shade_only=[1.0])
    grounded = np.isfinite(zbuf)

    # The sun's flat shadow, once per pixel however many casters overlap.
    shadow_mask = np.zeros((HEIGHT, WIDTH), dtype=bool)
    for verts, faces, _colour, _alpha in opaque + glass:
        pts = project(shadow_of(verts), eye, forward, right, up)
        rasterise(frame, zbuf, pts, faces, None, mask=shadow_mask)
    frame[shadow_mask & grounded] *= 0.80

    element_id = 1
    for bucket, blend in ((opaque, False), (glass, True)):
        for verts, faces, colour, alpha in bucket:
            element_id += 1
            pts = project(verts, eye, forward, right, up)
            for tri in faces:
                v = verts[tri]
                normal = np.cross(v[1] - v[0], v[2] - v[0])
                length = np.linalg.norm(normal)
                if length < 1e-12:
                    continue
                shade = abs(float(normal @ LIGHT) / length)
                rasterise(frame, zbuf, pts, tri[None, :], colour,
                          shade_only=[shade], alpha=alpha if blend else 0.0,
                          idbuf=idbuf, element_id=element_id)

    # The ink pass: a dark line wherever depth jumps or one element ends
    # and another begins -- the silhouette-and-crease language concept
    # sketches are drawn in.
    depth = np.where(np.isfinite(zbuf), zbuf, 1e6)
    edge = np.zeros((HEIGHT, WIDTH), dtype=bool)
    # Depth jumps ink only where an element is involved: bare ground at
    # grazing incidence has huge honest gradients that are not lines.
    element_here = idbuf > 0
    edge[:, 1:] |= ((np.abs(np.diff(depth, axis=1)) > 0.015 * depth[:, 1:])
                    & (element_here[:, 1:] | element_here[:, :-1]))
    edge[1:, :] |= ((np.abs(np.diff(depth, axis=0)) > 0.015 * depth[1:, :])
                    & (element_here[1:, :] | element_here[:-1, :]))
    edge[:, 1:] |= np.diff(idbuf, axis=1) != 0
    edge[1:, :] |= np.diff(idbuf, axis=0) != 0
    ink = np.array([0.16, 0.16, 0.18])
    frame[edge] = frame[edge] * 0.25 + ink * 0.75
    return frame


writer = imageio.get_writer(OUT_PATH, fps=FPS, codec="libx264", quality=8,
                            macro_block_size=None)
for index in range(FRAMES):
    angle = 2.0 * math.pi * index / FRAMES - math.radians(35)
    eye = np.array([centre[0] + radius * math.cos(angle),
                    centre[1] + radius * math.sin(angle),
                    3.4])
    look = np.array([centre[0], centre[1], 1.5])
    writer.append_data(
        (np.clip(draw_frame(eye, look), 0, 1) * 255).astype(np.uint8))
    if index % 30 == 0:
        print("frame", index)
writer.close()
print("wrote", OUT_PATH)
