"""Prototyping-Baukasten für Kölner-Dom-Varianten.

Import:
    import sys; sys.path.insert(0, '<scratchpad>/kit'); from proto_kit import *

Alles Wichtige:
    dd                      -> Modul dom_durchblick (massing(), tower(), nave_half(), lancet(), octagon(),
                               oct_prism(), pinnacle(), box(), extrude_y(), sym(), rect(), poly(), section(),
                               to_local(), to_world(), arch_rise(), H_REAL, XT, YT, Y_CROSS, Y_APSE ...)
                               Maße in METERN, x quer, y längs (Fassade y=0, Chor y≈144.6), z hoch.
    M = massing()           -> Massenmodell des Doms (Manifold, Meter)
    front_silhouette(M)     -> CrossSection in (x, z): Westansicht
    side_silhouette(M)      -> CrossSection in (y, z): Seitenansicht (Rhein)
    plan_footprint(M)       -> CrossSection in (x, y): Grundriss
    to_mm(m, height_mm=200) -> Manifold von Metern auf mm skalieren (Turm 157.4 m -> height_mm)
    gradient_bands(z_start, z_end, z_max, run=2) -> Lagen-Intervalle (mm) für Filament B
    check(m)                -> dict: Teile, Überhangfläche >45° (mm²), bbox, Volumen
    write_preview(dir, A, B=None, bands=None) -> schreibt dir/out/preview/{dom.bin,b.bin,meta.json}
    render(dir, views=None, palette='abendgold', bg=None, extra=None) -> PNG-Pfade in dir/shots
    PALETTES                -> Farbpaare (abendgold, bronze, kupfer, blau, gold_mono, silber_mono)
"""
import json
import math
import os
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, "/home/user/taste-skill/koelner-dom")
import dom_durchblick as dd  # noqa: E402
from manifold3d import CrossSection, FillRule, JoinType, Manifold, OpType  # noqa: E402,F401

SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDER_DIR = os.path.join(SP, "render")

PALETTES = {
    "abendgold": dict(a="#6a6d71", b="#d4a645", mA=0.55, rA=0.30, mB=0.6, rB=0.26),
    "bronze": dict(a="#4b4d50", b="#b58d45", mA=0.8, rA=0.45, mB=0.85, rB=0.40),
    "kupfer": dict(a="#4b4d50", b="#a25f3b", mA=0.8, rA=0.45, mB=0.85, rB=0.40),
    "blau": dict(a="#2f4669", b="#c9ccd1", mA=0.8, rA=0.42, mB=0.6, rB=0.24),
    "gold_mono": dict(a="#d4a645", b="#d4a645", mA=0.6, rA=0.26, mB=0.6, rB=0.26),
    "silber_mono": dict(a="#c9ccd1", b="#c9ccd1", mA=0.6, rA=0.24, mB=0.6, rB=0.24),
}

DEFAULT_VIEWS = [
    dict(name="hero", az=-35, el=14, zoom=1.0),
    dict(name="front", az=0, el=4, zoom=1.0),
    dict(name="side", az=-90, el=5, zoom=1.0),
    dict(name="back", az=-150, el=24, zoom=1.0),
]


def massing():
    return dd.massing()


def _clean(cs):
    return CrossSection(cs.to_polygons(), FillRule.Positive)


def front_silhouette(M=None):
    M = M if M is not None else dd.massing()
    return _clean(dd.to_local(M, (0, 0), 90).project())


def side_silhouette(M=None):
    M = M if M is not None else dd.massing()
    return _clean(dd.to_local(M, (0, 0), 180).project())


def plan_footprint(M=None):
    M = M if M is not None else dd.massing()
    return _clean(M.project())


def to_mm(m, height_mm=200.0):
    s = height_mm / dd.H_REAL
    return m.scale((s, s, s))


def gradient_bands(z_start, z_end, z_max, run=2, layer=0.16, first=0.2, gamma=1.0):
    edges = [0.0, first]
    while edges[-1] < z_max + 1:
        edges.append(edges[-1] + layer)
    n = len(edges) - 1
    isB = np.zeros(n, dtype=bool)
    acc = 0.0
    for i in range(0, n, max(1, run)):
        j = min(i + run, n)
        zc = 0.5 * (edges[i] + edges[j])
        f = min(max((zc - z_start) / (z_end - z_start), 0.0), 1.0) ** gamma
        acc += f
        if acc >= 0.5:
            isB[i:j] = True
            acc -= 1.0
    bands, k = [], 0
    while k < n:
        if isB[k]:
            s = k
            while k < n and isB[k]:
                k += 1
            bands.append((edges[s], edges[k]))
        else:
            k += 1
    return bands


def _arrays(m):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties[:, :3], dtype=np.float32)
    f = np.asarray(mesh.tri_verts, dtype=np.uint32)
    return v, f


def check(m):
    v, f = _arrays(m)
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    a = np.linalg.norm(n, axis=1) / 2
    n = n / (2 * a[:, None] + 1e-12)
    zmin = float(v[:, 2].min()) if len(v) else 0.0
    down = (n[:, 2] < -0.72) & (tri[:, :, 2].min(1) > zmin + 0.05) & (a > 1e-3)
    bb = m.bounding_box()
    return dict(
        teile=len(m.decompose()),
        ueberhang_mm2=round(float(a[down].sum()), 2),
        bbox_mm=[round(x, 1) for x in bb],
        groesse_mm=[round(bb[3] - bb[0], 1), round(bb[4] - bb[1], 1), round(bb[5] - bb[2], 1)],
        volumen_cm3=round(m.volume() / 1000, 1),
        dreiecke=int(len(f)),
    )


def _write_bin(path, m):
    with open(path, "wb") as fh:
        if m is None or m.is_empty():
            fh.write(struct.pack("<II", 0, 0))
            return
        v, f = _arrays(m)
        fh.write(struct.pack("<II", len(v), len(f)))
        fh.write(v.astype("<f4").tobytes())
        fh.write(f.astype("<u4").tobytes())


def write_preview(outdir, A, B=None, bands=None, layer=0.16, first=0.2):
    """A, B: Manifolds in mm, z ab 0. A wird mit Lagenverlauf (bands) eingefärbt, B komplett in Farbe B."""
    p = os.path.join(outdir, "out", "preview")
    os.makedirs(p, exist_ok=True)
    zmax = A.bounding_box()[5]
    if B is not None and not B.is_empty():
        zmax = max(zmax, B.bounding_box()[5])
    edges = [0.0, first]
    while edges[-1] < zmax + 1:
        edges.append(edges[-1] + layer)
    _write_bin(os.path.join(p, "dom.bin"), A)
    _write_bin(os.path.join(p, "b.bin"), B)
    with open(os.path.join(p, "meta.json"), "w") as fh:
        json.dump(dict(bands=[[float(a), float(b)] for a, b in (bands or [])], n_layers=len(edges) - 1,
                       layer=layer, first_layer=first), fh)


def render(outdir, views=None, palette="abendgold", bg=None, extra=None):
    """views: Liste von dicts {name, az, el, zoom, ty (0..1 Zielhöhe), tx, tz, fov}.
    palette: Name aus PALETTES oder dict. extra: weitere window-Variablen (z. B. {'BACKLIGHT': 3})."""
    views = views or DEFAULT_VIEWS
    pal = PALETTES[palette] if isinstance(palette, str) else palette
    init = {"PALETTE": pal, "BG": bg or "#d9d6d0"}
    init.update(extra or {})
    shots = os.path.join(outdir, "shots")
    r = subprocess.run(["node", os.path.join(RENDER_DIR, "shoot2.mjs"), outdir, shots, json.dumps(views), json.dumps(init)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stdout + r.stderr)
    if "pageerror" in r.stdout:
        print(r.stdout)
    return [os.path.join(shots, v["name"] + ".png") for v in views]
