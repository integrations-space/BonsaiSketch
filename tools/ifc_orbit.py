"""Turntable MP4 of an IFC model: flat colours, z-buffer, no GPU.

    python3 tools/ifc_orbit.py model.ifc orbit.mp4 [frames]

Visual QA a machine can start and only a person can finish: the frames
come from the delivered IFC's own tessellated geometry -- never from
the tool that made the model -- so anything that looks wrong in the
video is wrong in the model. Colours follow the same class palette
autobuild styles elements with; glazing stays transparent so the
interior reads through it, and the camera orbits at a gentle elevation
so massing reads the way concept sketches draw it.

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
    'IfcWindow': ((.61, .80, .92), .5),
}
SKY_TOP = np.array([0.639, 0.745, 0.855])
SKY_BOTTOM = np.array([0.97, 0.97, 0.96])
GROUND = np.array([0.878, 0.867, 0.827])

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
    bucket = glass if alpha > 0 else opaque
    bucket.append((verts, faces, np.array(colour), alpha))

everything = np.vstack([v for v, _f, _c, _a in opaque + glass])
low, high = everything.min(axis=0), everything.max(axis=0)
centre = (low + high) / 2.0
radius = float(np.linalg.norm((high - low)[:2])) * 0.62 + 6.0

WIDTH, HEIGHT, FRAMES, FPS = 960, 540, FRAME_COUNT, 30
FOCAL = 1.35  # ~35 mm feel
LIGHT = np.array([0.45, 0.3, 0.84])
LIGHT = LIGHT / np.linalg.norm(LIGHT)

row_gradient = np.linspace(0.0, 1.0, HEIGHT)[:, None]
background = (SKY_TOP[None, None, :] * (1 - row_gradient[..., None])
              + SKY_BOTTOM[None, None, :] * row_gradient[..., None])
background = np.repeat(background, WIDTH, axis=1)

# The ground: a lawn of small tiles just below the carport slab, small
# enough that only tiles genuinely behind the camera are culled.
G, TILE = 60.0, 5.0
ground_verts, ground_faces = [], []
steps = int(2 * G / TILE)
for iy in range(steps):
    for ix in range(steps):
        x0 = centre[0] - G + ix * TILE
        y0 = centre[1] - G + iy * TILE
        base = len(ground_verts)
        ground_verts += [[x0, y0, -0.21], [x0 + TILE, y0, -0.21],
                         [x0 + TILE, y0 + TILE, -0.21], [x0, y0 + TILE, -0.21]]
        ground_faces += [[base, base + 1, base + 2], [base, base + 2, base + 3]]
ground_verts = np.array(ground_verts)
ground_faces = np.array(ground_faces)


def rasterise(frame, zbuf, pts, faces, colour, shade_only=None, alpha=0.0):
    for tri in faces:
        p = pts[tri]  # 3 x (x_px, y_px, depth) with camera-space normal shade
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
        mask = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not mask.any():
            continue
        depth = w0 * p[0, 2] + w1 * p[1, 2] + w2 * p[2, 2]
        window = zbuf[y0:y1 + 1, x0:x1 + 1]
        closer = mask & (depth < window - (1e-4 if alpha else 0.0))
        if not closer.any():
            continue
        shaded = colour * (0.55 + 0.45 * shade_only[0]) if shade_only else colour
        target = frame[y0:y1 + 1, x0:x1 + 1]
        if alpha:
            target[closer] = target[closer] * alpha + shaded * (1 - alpha)
        else:
            window[closer] = depth[closer]
            target[closer] = shaded


def project(verts, eye, forward, right, up):
    rel = verts - eye
    cx = rel @ right
    cy = rel @ up
    cz = rel @ forward
    with np.errstate(divide="ignore", invalid="ignore"):
        sx = (cx / cz) * FOCAL * HEIGHT + WIDTH / 2.0
        sy = HEIGHT / 2.0 - (cy / cz) * FOCAL * HEIGHT
    return np.stack([sx, sy, cz], axis=1)


writer = imageio.get_writer(OUT_PATH, fps=FPS, codec="libx264", quality=8,
                            macro_block_size=None)
for index in range(FRAMES):
    angle = 2.0 * math.pi * index / FRAMES - math.radians(35)
    eye = np.array([centre[0] + radius * math.cos(angle),
                    centre[1] + radius * math.sin(angle),
                    3.4])
    look = np.array([centre[0], centre[1], 1.5])
    forward = look - eye
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, np.array([0.0, 0.0, 1.0]))
    right = right / np.linalg.norm(right)
    up = np.cross(right, forward)

    frame = background.copy()
    zbuf = np.full((HEIGHT, WIDTH), np.inf)

    pts = project(ground_verts, eye, forward, right, up)
    rasterise(frame, zbuf, pts, ground_faces, GROUND, shade_only=[1.0])

    for verts, faces, colour, _alpha in opaque:
        pts = project(verts, eye, forward, right, up)
        for tri in faces:
            v = verts[tri]
            normal = np.cross(v[1] - v[0], v[2] - v[0])
            length = np.linalg.norm(normal)
            if length < 1e-12:
                continue
            shade = abs(float(normal @ LIGHT) / length)
            rasterise(frame, zbuf, pts, tri[None, :], colour,
                      shade_only=[shade])
    for verts, faces, colour, alpha in glass:
        pts = project(verts, eye, forward, right, up)
        for tri in faces:
            v = verts[tri]
            normal = np.cross(v[1] - v[0], v[2] - v[0])
            length = np.linalg.norm(normal)
            if length < 1e-12:
                continue
            shade = abs(float(normal @ LIGHT) / length)
            rasterise(frame, zbuf, pts, tri[None, :], colour,
                      shade_only=[shade], alpha=alpha)

    writer.append_data((np.clip(frame, 0, 1) * 255).astype(np.uint8))
    if index % 30 == 0:
        print("frame", index)
writer.close()
print("wrote", OUT_PATH)
