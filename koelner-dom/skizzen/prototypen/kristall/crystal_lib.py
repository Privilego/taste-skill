"""Kristall-Bausteine: facettierte Kristallspitzen und Felsbrocken (konvexe Hüllen)."""
import math
import sys

import numpy as np

sys.path.insert(0, '/tmp/claude-0/-home-user-taste-skill/d46f1633-345d-5b87-803e-a453b1fd4c0a/scratchpad/kit')
from proto_kit import *  # noqa: F401,F403,E402
from manifold3d import Manifold, OpType, CrossSection  # noqa: E402


def rot_tilt(tilt_deg, azim_deg):
    """Rotationsmatrix: +z wird um tilt in Richtung azim (xy-Ebene) gekippt."""
    t, a = math.radians(tilt_deg), math.radians(azim_deg)
    k = np.array([-math.sin(a), math.cos(a), 0.0])
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) * math.cos(t) + math.sin(t) * K + (1 - math.cos(t)) * np.outer(k, k)


def crystal(p, r, h_sh, h_tip, rng, n=6, tilt=0.0, azim=0.0, irr=0.18, apex_off=0.25,
            taper=0.92, depth=4.0, rot=None, sh_jit=0.35, aspect=1.0, flat=None):
    """Eine Kristallspitze.
    p: Fußpunkt (x, y, z) auf der Achse, r: Radius, h_sh: Höhe des Prismenendes (entlang Achse),
    h_tip: Höhe der Spitze. Prisma reicht depth unter den Fußpunkt (zum Verankern).
    aspect: Streckung in lokaler y-Richtung (tafelige Kristalle). flat: Spitze als Grat (Länge)."""
    rot = rng.uniform(0, 2 * math.pi) if rot is None else rot
    ang = rot + 2 * math.pi * np.arange(n) / n + rng.uniform(-0.18, 0.18, n) * (2 * math.pi / n)
    rad = r * (1 + irr * rng.uniform(-1, 1, n))
    cx, cy = np.cos(ang) * rad, np.sin(ang) * rad * aspect
    pts = []
    for x, y in zip(cx, cy):
        pts.append((x, y, -depth))
    zs = h_sh + sh_jit * r * rng.uniform(-1, 1, n)
    for x, y, z in zip(cx, cy, zs):
        pts.append((x * taper, y * taper, z))
    ao = rng.uniform(0, 2 * math.pi)
    ax, ay = apex_off * r * math.cos(ao), apex_off * r * math.sin(ao)
    if flat:
        pts.append((ax - flat / 2, ay, h_tip))
        pts.append((ax + flat / 2, ay, h_tip))
    else:
        pts.append((ax, ay, h_tip))
    P = np.array(pts) @ rot_tilt(tilt, azim).T + np.asarray(p, dtype=float)
    return Manifold.hull_points(P)


def mound(cx, cy, rx, ry, z0, h, rng, n=13, rings=((0.4, 0.82), (0.75, 0.55), (1.0, 0.22)),
          noise=0.16, rotdeg=0.0, lean=(0.0, 0.0)):
    """Facettierter Felsbrocken, breiteste Stelle unten (z0) -> überhangfrei."""
    pts = []
    c, s = math.cos(math.radians(rotdeg)), math.sin(math.radians(rotdeg))
    def put(u, v, z):
        pts.append((cx + c * u - s * v, cy + s * u + c * v, z))
    a0 = rng.uniform(0, 2 * math.pi)
    for i in range(n):
        a = a0 + 2 * math.pi * i / n + rng.uniform(-0.2, 0.2)
        f = 1 + noise * rng.uniform(-1, 0.6)
        put(rx * f * math.cos(a), ry * f * math.sin(a), z0)
    for (fz, fr) in rings:
        m = max(3, int(round(n * (fr + 0.15))))
        a0 = rng.uniform(0, 2 * math.pi)
        for i in range(m):
            a = a0 + 2 * math.pi * i / m + rng.uniform(-0.3, 0.3)
            f = fr * (1 + noise * rng.uniform(-1, 0.5))
            zz = z0 + h * fz * (1 + 0.12 * rng.uniform(-1, 1)) if fz < 1 else z0 + h * (1 - 0.08 * rng.uniform(0, 1))
            put(rx * f * math.cos(a) + lean[0] * h * fz, ry * f * math.sin(a) + lean[1] * h * fz, zz)
    return Manifold.hull_points(np.array(pts))


def union(parts):
    parts = [p for p in parts if p is not None and not p.is_empty()]
    return Manifold.batch_boolean(parts, OpType.Add)
