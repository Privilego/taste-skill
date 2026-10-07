#!/usr/bin/env python3
"""Kölner Dom · DOMKRISTALL
Der Dom als goldene Kristallstufe, die aus einem Feld dunkler Basaltsäulen wächst.
Gleiche Formensprache (Sechseck-Prismen), zwei Zustände: stumpf + dunkel = Stein,
spitz + gold = Kristall.

  A (dunkel) = Basaltsäulen-Sockel (+ verdeckter Kern unter dem Dom bis Z_CORE)
  B (Gold)   = Dom-Kristall (alles, was aus dem Stein herausragt)
Ein Körper, zwei Farben per AMS (Farbwechsel nur im Höhenband, in dem Säulen und Dom nebeneinander liegen).
Maße intern in Metern (Dom-Koordinaten, Boden Dom = 0), Ausgabe in mm.
Aufruf: python3 build.py   (SEED=7 SCALE=1.2 als Umgebungsvariablen)
"""
import json
import math
import os
import sys

import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.geometry.polygon import orient

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crystal_lib import *  # noqa: F401,F403,E402
from crystal_lib import crystal, union  # noqa: E402
from manifold3d import OpType  # noqa: E402

SEED = int(os.environ.get('SEED', 7))
S = float(os.environ.get('SCALE', 1.2))     # mm pro Dom-Meter
PLATE_MM = 2.4                               # Grundplatte unter den Säulen
P = PLATE_MM / S                             # in Dom-Metern
Z_CORE = 11.0                                # bis hier ist der (verdeckte) Dom-Fuß dunkel
XT, YT = 19.25, 11.5
Y_APSE = 113.9
EC = 70.0                                    # Mitte des Sockels (y)


def ring_pts(cx, cy, z, r, n, rot, rng, irr=0.06):
    a = rot + 2 * math.pi * np.arange(n) / n + rng.uniform(-0.06, 0.06, n)
    rr = r * (1 + irr * rng.uniform(-1, 1, n))
    return [(cx + math.cos(t) * q, cy + math.sin(t) * q, z) for t, q in zip(a, rr)]


# ------------------------------------------------------------------ Dom-Kristall
def facet_window(c, n, half, z0, z1, depth):
    """Spitzbogenfenster als geschliffene Vertiefung (5 Facetten, stützenfrei)."""
    nx, ny = n
    tx, ty = -ny, nx
    zs = z1 - 1.25 * half * 1.4
    outline = [(-half, z0), (half, z0), (half, zs), (0, z1), (-half, zs)]
    pts = []
    for (u, z) in outline:
        for off in (0.6, -0.05):
            pts.append((c[0] + u * tx + off * nx, c[1] + u * ty + off * ny, z))
    zc = z0 + 0.55 * (z1 - z0)
    pts.append((c[0] - depth * nx, c[1] - depth * ny, zc))
    return Manifold.hull_points(np.array(pts))


def windows():
    W = []
    for sx in (-1, 1):
        for y in [27.7, 35.1, 42.5, 49.9, 57.0, 99.8, 108.9]:
            W.append(facet_window((sx * 8.3, y), (sx, 0), 2.1, 31.0, 43.2, 1.3))
    for i in range(5):
        a = math.pi * (i + 0.5) / 5
        rr = 8.3 * math.cos(math.pi / 10)
        W.append(facet_window((rr * math.cos(a), Y_APSE + rr * math.sin(a)), (math.cos(a), math.sin(a)),
                              1.7, 31.0, 43.2, 1.2))
    # Querhaus-Giebel: großes Fenster
    for sx in (-1, 1):
        W.append(facet_window((sx * 41.5, 76.5), (sx, 0), 4.2, 28.0, 47.0, 1.6))
    return union(W)


def tower_crystal(sx, rng):
    """Ein großer Kristall pro Turm (Prisma + lange Endspitze) mit Nebenkristallen."""
    xc, yc = sx * XT, YT
    out = []
    rot = math.pi / 6
    pts = (ring_pts(xc, yc, -6, 12.2, 6, rot, rng) + ring_pts(xc, yc, 58, 11.6, 6, rot, rng)
           + ring_pts(xc, yc, 97 + rng.uniform(-1, 1), 10.0, 6, rot, rng, irr=0.1))
    pts.append((xc + sx * 0.6, yc + 0.4, 157.4))
    out.append(Manifold.hull_points(np.array(pts)))
    # Eck-Nebenkristalle wachsen schräg aus den Turmflanken (= Eckfialen)
    for su in (-1, 1):
        for sv in (-1, 1):
            az = math.degrees(math.atan2(sv * 1.0, su * 1.0))
            out.append(crystal((xc + su * 7.0, yc + sv * 7.0, 50 + rng.uniform(-3, 3)), 2.6, 12 + rng.uniform(-2, 2),
                               27 + rng.uniform(-3, 3), rng, tilt=13, azim=az, apex_off=0.3, depth=8))
    # Kranz kleiner Spitzen am Helmansatz
    for k in range(6):
        a = 2 * math.pi * k / 6 + rot
        out.append(crystal((xc + 6.0 * math.cos(a), yc + 6.0 * math.sin(a), 96), 2.0,
                           9 + rng.uniform(-2, 2), 20 + rng.uniform(-2, 3), rng, tilt=14,
                           azim=math.degrees(a), apex_off=0.3, depth=8))
    return out


def facade_center():
    pts = [(-7.8, 2, -6), (7.8, 2, -6), (-7.8, 23, -6), (7.8, 23, -6), (-7.8, 2, 45), (7.8, 2, 45),
           (-7.8, 23, 45), (7.8, 23, 45), (0, 0.5, 67), (0, 23, 61), (0, -1.5, 30), (0, -1.0, -6)]
    return Manifold.hull_points(np.array(pts, float))


def dom_crystal(rng):
    Pm = []
    for sx in (-1, 1):
        Pm += tower_crystal(sx, rng)
    Pm.append(facade_center())
    Pm.append(crystal((0, 1.4, 56), 1.5, 10, 19, rng, apex_off=0.2, depth=4))
    # Langhaus + Chor: liegender Kristall, Chorhaupt = Endflächen
    sec = [(-8.3, -6), (8.3, -6), (8.3, 45), (5.4, 52.6), (0, 61), (-5.4, 52.6), (-8.3, 45)]
    pts = [(x, y, z) for (x, z) in sec for y in (20.0, Y_APSE)]
    nseg = 5
    for i in range(nseg + 1):
        a = math.pi * i / nseg
        for z in (-6, 45):
            pts.append((8.3 * math.cos(a), Y_APSE + 8.3 * math.sin(a), z))
    pts.append((0, Y_APSE + 2.0, 61))
    Pm.append(Manifold.hull_points(np.array(pts, float)))
    # Seitenschiffe / Chorumgang
    low = [(-23.6, -6), (23.6, -6), (23.6, 21), (8.3, 29), (-8.3, 29), (-23.6, 21)]
    pts = [(x, y, z) for (x, z) in low for y in (22.0, Y_APSE)]
    for i in range(nseg + 1):
        a = math.pi * i / nseg
        for (rr, z) in ((23.6, -6), (23.6, 21), (8.3, 29)):
            pts.append((rr * math.cos(a), Y_APSE + rr * math.sin(a), z))
    Pm.append(Manifold.hull_points(np.array(pts, float)))
    # Strebepfeiler-Kristalle (Fialenwald), fächern wie eine Druse nach außen
    for y in [24.0, 31.4, 38.8, 46.2, 53.6, 95.0, 104.5]:
        for sx in (-1, 1):
            Pm.append(crystal((sx * 25.5, y, 4), 3.2, 30 + rng.uniform(-3, 3), 42 + rng.uniform(-3, 4), rng,
                              tilt=13 + rng.uniform(-3, 3), azim=90 - sx * 90 + rng.uniform(-6, 6),
                              apex_off=0.3, depth=12))
    for i in range(0, 6):
        a = math.pi * (i + 0.5) / 6
        Pm.append(crystal((25.5 * math.cos(a), Y_APSE + 25.5 * math.sin(a), 4), 3.2, 30 + rng.uniform(-3, 3),
                          42 + rng.uniform(-3, 4), rng, tilt=14, azim=math.degrees(a), apex_off=0.3, depth=12))
    # Querhaus: liegender Kristall quer, Giebel als flache Endspitzen
    ty0 = 76.5
    pts = []
    for (v, z) in sec:
        for x in (-41.5, 41.5):
            pts.append((x, ty0 + v, z))
    pts += [(-44.0, ty0, 30), (44.0, ty0, 30)]
    Pm.append(Manifold.hull_points(np.array(pts, float)))
    low = [(-15.5, -6), (15.5, -6), (15.5, 21), (8.3, 27), (-8.3, 27), (-15.5, 21)]
    pts = [(x, ty0 + v, z) for (v, z) in low for x in (-39, 39)]
    Pm.append(Manifold.hull_points(np.array(pts, float)))
    for sx in (-1, 1):
        for yy in (65.5, 87.5):
            Pm.append(crystal((sx * 40.5, yy, 0), 3.4, 56 + rng.uniform(-2, 2), 72 + rng.uniform(-2, 2), rng,
                              tilt=3, azim=90 - sx * 90, apex_off=0.25, depth=8))
    # Vierungsturm: schlanker Kristall
    Pm.append(crystal((0, 76.5, 40), 4.6, 32, 69, rng, n=6, tilt=0, apex_off=0.04, irr=0.06, depth=4))
    return union(Pm) - windows()


# ------------------------------------------------------------------ Basaltsäulen-Sockel
def hexagon(cx, cy, r, rng, jit=0.25):
    a = np.arange(6) * math.pi / 3 + math.pi / 6
    rr = r + rng.uniform(-jit, jit, 6) * 0.5
    return np.stack([cx + rr * np.cos(a), cy + rr * np.sin(a)], 1)


def basalt_field(rng, dom):
    low = dom.trim_by_plane((0, 0, -1), -10.0)
    fp = unary_union([Polygon(p) for p in low.project().to_polygons() if len(p) >= 3])
    fp_s = fp.buffer(0.0)
    W = 7.4                         # Säulen-Schlüsselweite (m) ~ 9 mm
    GAP = 0.65                      # Fuge ~ 0,8 mm
    pitch = W + GAP
    r = W / math.sqrt(3)            # Umkreisradius
    # Grenze des Feldes: Dom-Grundriss + Rand, leicht unregelmäßig
    region = fp.buffer(19.0, join_style=2).buffer(-5).simplify(2.0)
    cols, tops, centers = [], [], []
    ph = rng.uniform(0, 2 * math.pi, 3)
    dx, dy = pitch, pitch * math.sqrt(3) / 2
    j = 0
    y = -30.0
    while y < 170:
        x0 = -70 + (dx / 2 if j % 2 else 0)
        x = x0
        while x < 70:
            pt = Point(x, y)
            if region.contains(pt):
                d = fp_s.exterior.distance(pt) if not fp_s.contains(pt) else 0.0
                inside = fp_s.contains(pt) and fp_s.exterior.distance(pt) > r + 0.5
                if not inside:
                    # Höhe: am Dom hoch, nach außen abtreppend; vorne (Fassade) niedrig wie eine Treppe
                    ang = math.degrees(math.atan2(y - EC, x))
                    front = math.exp(-(((ang + 90 + 180) % 360 - 180) / 30) ** 2)
                    north = 0.5 + 0.5 * math.cos(math.radians(ang - 180))
                    smooth = (math.sin(0.11 * x + 0.05 * y + ph[0]) + math.sin(-0.04 * x + 0.09 * y + ph[1])
                              + 0.6 * math.sin(0.17 * x - 0.13 * y + ph[2])) / 2.6
                    hnear = 28 + 9 * north - 9 * front + 6 * smooth
                    h = 1.2 + hnear * max(0.0, 1 - d / 30.0) ** 1.3 + rng.uniform(-0.7, 0.7)
                    if rng.uniform() < 0.12:
                        h += rng.uniform(3, 6)              # einzelne vorstehende Säulen
                    e = region.exterior.distance(pt)
                    h = max(1.0, min(h, 1.4 + 1.25 * e))    # zum Rand hin abtreppen
                    poly = hexagon(x, y, r, rng)
                    cs = CrossSection([poly])
                    col = Manifold.extrude(cs, h + P + 4).translate((0, 0, -P))
                    # schräge Kopffläche (bis 12°) wie gebrochener Basalt
                    tl = rng.uniform(0, 12) if rng.uniform() < 0.6 else 0.0
                    az = rng.uniform(0, 2 * math.pi)
                    nrm = (math.sin(math.radians(tl)) * math.cos(az), math.sin(math.radians(tl)) * math.sin(az),
                           math.cos(math.radians(tl)))
                    col = col.trim_by_plane((-nrm[0], -nrm[1], -nrm[2]), -(nrm[0] * x + nrm[1] * y + nrm[2] * h))
                    cols.append(col)
                    centers.append((x, y, h))
            x += dx
        y += dy
        j += 1
    # Grundplatte unter allen Säulen (verbindet alles zu einem Körper)
    base_poly = unary_union([Polygon(hexagon(cx, cy, r + GAP * 0.6, rng, 0)) for (cx, cy, _) in centers] + [fp])
    base_poly = base_poly.buffer(0.3).buffer(-0.3)
    base = Manifold.extrude(CrossSection([np.array(orient(Polygon(base_poly.exterior)).exterior.coords)[:-1]]), P).translate((0, 0, -P))
    # verdeckter Kern unter dem Dom (dunkel bis Z_CORE)
    core = Manifold.extrude(CrossSection([np.array(orient(Polygon(fp.buffer(0.4).exterior)).exterior.coords)[:-1]]), Z_CORE + P).translate((0, 0, -P))
    return union(cols + [base]), core, centers


def main():
    rng = np.random.default_rng(SEED)
    D = dom_crystal(rng).trim_by_plane((0, 0, 1), -P)
    rock, core, centers = basalt_field(rng, D)
    R = rock + (core ^ D)
    G = D - R
    to = lambda m: m.translate((0, 0, P)).scale((S, S, S)).translate((0, -EC * S, 0))
    solid = lambda m: Manifold.batch_boolean([q for q in m.decompose() if q.volume() > 1.0], OpType.Add)
    B, A = solid(to(G)), solid(to(R))
    full = to(D + rock)
    info = check(full)
    info['teile_A'], info['teile_B'] = len(A.decompose()), len(B.decompose())
    bbA, bbB = A.bounding_box(), B.bounding_box()
    info['A_z'], info['B_z'] = [round(bbA[2], 1), round(bbA[5], 1)], [round(bbB[2], 1), round(bbB[5], 1)]
    info['saeulen'] = len(centers)
    print(json.dumps(info))
    write_preview(HERE, A, B, None)
    os.makedirs(os.path.join(HERE, 'out'), exist_ok=True)
    write_stl(os.path.join(HERE, 'out', 'domkristall_A_basalt.stl'), A)
    write_stl(os.path.join(HERE, 'out', 'domkristall_B_kristall.stl'), B)
    return A, B, info


def write_stl(path, m):
    import struct
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties[:, :3], dtype=np.float32)
    f = np.asarray(mesh.tri_verts, dtype=np.int64)
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= (np.linalg.norm(n, axis=1)[:, None] + 1e-12)
    rec = np.zeros(len(f), dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
    rec['n'], rec['v'] = n, tri
    with open(path, 'wb') as fh:
        fh.write(b'Domkristall'.ljust(80, b' '))
        fh.write(struct.pack('<I', len(f)))
        fh.write(rec.tobytes())


if __name__ == '__main__':
    main()
