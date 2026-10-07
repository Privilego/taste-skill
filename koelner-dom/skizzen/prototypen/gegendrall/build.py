#!/usr/bin/env python3
"""Kölner Dom · GEGENDRALL

Die beiden Westtürme drehen sich spiegelbildlich gegeneinander: unten (bis zur
Dachlinie) stehen ihre Rippen kerzengerade wie Strebepfeiler, darüber beginnen
sie sich zu winden, immer stärker, bis zur Kreuzblume. Langhaus, Querhaus und
Chor bleiben ruhig und massiv wie ein Sockel.

Alle Maße intern in Metern (Dom-Koordinaten), am Ende auf mm skaliert.
Aufruf:  python3 build.py [render|norender] [palette]
"""
import math
import os
import sys

sys.path.insert(0, '/tmp/claude-0/-home-user-taste-skill/d46f1633-345d-5b87-803e-a453b1fd4c0a/scratchpad/kit')
from proto_kit import *  # noqa: E402,F401,F403
from manifold3d import Mesh  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
H_MM = 200.0                 # Turmspitze in mm
P = dict(
    NS=16,                   # Rippen pro Turm (8 Haupt- + 8 Nebenrippen)
    T=180.0,                 # Verdrehung an der Spitze (Grad)
    Z0=64.0,                 # ab hier dreht sich der Turm (Dachfirst)
    POW=1.7,                 # >1: Drall nimmt nach oben zu (Flamme)
    G0=76.0, G1=126.0,       # Farbverlauf dunkel -> Gold (m, Dom-Höhe)
)

# Hüllkurve der Westtürme: (z, Rippenradius a [m]) ; Form s: 0 = Quadrat, 1 = Achteck
A_KN = [(0, 11.5), (33, 11.5), (33.6, 10.9), (63, 10.9), (66, 9.2), (111, 8.1),
        (146.0, 2.25), (148.4, 1.3), (151.2, 2.45), (157.4, 0.0)]
S_KN = [(0, 0.0), (63, 0.0), (66, 1.0), (200, 1.0)]
D_KN = [(0, 0.09), (63, 0.09), (66, 0.30), (146, 0.34), (148.3, 0.2), (151.2, 0.30), (157.4, 0.3)]
WL_KN = [(0, 6.5), (63, 6.5), (66, 1.0), (200, 1.0)]    # halbe Rippenbreite (Grad)
WF_KN = [(0, 1.8), (63, 1.8), (66, 1.6), (200, 1.6)]    # halbe Kehlenbreite (Grad)
MI_KN = [(0, 1.0), (63, 1.0), (66, 0.96), (200, 0.96)]  # Nebenrippen relativ


def interp(kn, z):
    zz, vv = zip(*kn)
    return float(np.interp(z, zz, vv))


def ring(a, s, d, phi, NS, wl, wf, minor=1.0):
    """Sternquerschnitt: NS Rippen (jede zweite um Faktor minor kürzer), dazwischen Kehlen der Tiefe d."""
    pts = []
    half = 180.0 / NS
    for k in range(NS):
        c = k * 360.0 / NS
        f = 1.0 if k % 2 == 0 else minor
        for off, flute in ((-wl, 0), (0, 0), (wl, 0), (half - wf, 1), (half + wf, 1)):
            th = math.radians(c + off)
            rs = a / max(abs(math.cos(th)), abs(math.sin(th)))
            rho = (1 - s) * rs + s * a
            r = rho * (1 - d) if flute else rho * f
            pts.append((r * math.cos(th + phi), r * math.sin(th + phi)))
    return np.array(pts)


def loft(zs, ring_fn, apex=None):
    """Ringe gleicher Punktzahl übereinander, unten Deckel, oben Spitze (apex z) oder Deckel."""
    rings = [ring_fn(z) for z in zs]
    K = len(rings[0])
    V = [np.array([[0.0, 0.0, zs[0]]])]
    for z, r in zip(zs, rings):
        V.append(np.column_stack([r, np.full(K, z)]))
    top_c = len(zs) * K + 1
    V.append(np.array([[0.0, 0.0, apex if apex is not None else zs[-1]]]))
    V = np.vstack(V).astype(np.float32)
    F = []
    j = np.arange(K)
    jn = (j + 1) % K
    F.append(np.column_stack([np.zeros(K), 1 + jn, 1 + j]))
    for i in range(len(zs) - 1):
        b, t = 1 + i * K, 1 + (i + 1) * K
        F.append(np.column_stack([b + j, b + jn, t + jn]))
        F.append(np.column_stack([b + j, t + jn, t + j]))
    b = 1 + (len(zs) - 1) * K
    F.append(np.column_stack([b + j, b + jn, np.full(K, top_c)]))
    F = np.vstack(F).astype(np.uint32)
    m = Manifold(Mesh(vert_properties=V, tri_verts=F))
    assert m.status().name == 'NoError', m.status()
    return m


def zsamples(z0, z1, dz, knots):
    zs = set(np.round(np.arange(z0, z1, dz), 4))
    zs |= {round(k, 4) for k in knots if z0 <= k < z1}
    return np.array(sorted(zs))


def west_tower(sign):
    """sign=-1: Nordturm (links, von Westen gesehen). Drall gespiegelt für den anderen Turm."""
    NS, T, Z0, POW = (P[k] for k in ('NS', 'T', 'Z0', 'POW'))
    ztip = A_KN[-1][0]
    knots = [k[0] for k in A_KN + S_KN + D_KN + WL_KN + WF_KN + MI_KN]

    def fn(z):
        u = max(0.0, (z - Z0) / (ztip - Z0))
        phi = math.radians(T) * u ** POW
        return ring(interp(A_KN, z), interp(S_KN, z), interp(D_KN, z), phi, NS, interp(WL_KN, z), interp(WF_KN, z), interp(MI_KN, z))

    zs = zsamples(0.0, ztip - 0.25, 0.35, knots)
    m = loft(zs, fn, apex=ztip)
    m = m.translate((-dd.XT, dd.YT, 0))
    return m if sign < 0 else m.mirror((1, 0, 0))


def crossing_spire():
    NS = 8
    A = [(45, 4.6), (72, 4.6), (73, 4.2), (106, 0.6), (109, 0.0)]
    D = [(45, 0.18), (109, 0.25)]

    def fn(z):
        return ring(interp(A, z), 1.0, interp(D, z), math.radians(22.5), NS, 4.0, 5.0)
    zs = zsamples(45.0, 108.8, 0.5, [k[0] for k in A])
    return loft(zs, fn, apex=109.0).translate((0, dd.Y_CROSS, 0))


def niche(px, py, beta, half, zb, apex, depth=1.0, k=1.6):
    """Spitzbogennische in einer senkrechten Wand. (px, py) Punkt auf der Wand, beta = Richtung der Außennormalen (Grad)."""
    m = dd.extrude_y(dd.lancet(0, half, zb, apex, k), -depth, 3.0)
    return m.rotate((0, 0, beta - 90)).translate((px, py, 0))


def fin(px, py, beta, w, d, z1):
    """Strebepfeiler: steht an der Wand, Oberkante 45° zur Wand hin ansteigend."""
    prof = dd.poly([(-1.0, 0), (d, 0), (d, z1), (-1.0, z1 + d + 1.0)])     # (n, z)
    m = Manifold.extrude(prof, w).translate((0, 0, -w / 2))                 # n=x, z=y, Breite=z
    m = m.rotate((90, 0, 0))                                                # -> n=x, Höhe=z, Breite=y
    return m.rotate((0, 0, beta)).translate((px, py, 0))


NAVE_BAYS = np.linspace(dd.Y_NAVE0, 61.0, 6)      # Strebepfeiler-Achsen Langhaus
CHOIR_BAYS = np.linspace(92.0, dd.Y_APSE, 4)


def body():
    core = dd.sym(dd.nave_half(False))
    center = core ^ dd.rect(-7.75, 7.75, -1, 100)
    parts = [
        dd.extrude_y(center, 0, dd.Y_NAVE0 + 0.5),
        dd.extrude_y(core, dd.Y_NAVE0, dd.Y_APSE + 0.6),
        dd.pinnacle(0, 1.3, 1.6, 55, 63, 70),
    ]
    tr = dd.sym(dd.transept_half())
    trm = Manifold.extrude(tr, 2 * dd.TR_HALF).rotate((90, 0, 0)).translate((0, dd.TR_HALF, 0))
    parts.append(trm.rotate((0, 0, -90)).translate((0, dd.Y_CROSS, 0)))
    parts.append(Manifold.revolve(dd.nave_half(False), 10, 180).translate((0, dd.Y_APSE, 0)))
    B = Manifold.batch_boolean(parts, OpType.Add)

    cuts = [dd.extrude_y(dd.lancet(0, 4.0, -1, 27, 1.6), -1, 1.4),          # Hauptportal
            dd.extrude_y(dd.lancet(0, 4.6, 30.5, 54, 1.6), -1, 1.0)]        # großes Westfenster
    fins = []
    # Langhaus + Chor: Fenster je Joch (Seitenschiff + Obergaden), Strebepfeiler dazwischen
    for sx in (-1, 1):
        beta = 0 if sx > 0 else 180
        for bays in (NAVE_BAYS, CHOIR_BAYS):
            for y0, y1 in zip(bays[:-1], bays[1:]):
                yc = 0.5 * (y0 + y1)
                cuts.append(niche(sx * 23.6, yc, beta, 2.1, 4.0, 19.5))
                cuts.append(niche(sx * 8.3, yc, beta, 2.0, 30.0, 42.5, depth=0.9))
            for y in bays:
                if abs(y - 61.0) < 0.1 or abs(y - 92.0) < 0.1:
                    continue
                fins.append(fin(sx * 23.6, y, beta, 1.7, 3.2, 21.0))
        # Querhaus-Stirnseite: Portal + Fenster
        cuts.append(niche(sx * dd.TR_HALF, dd.Y_CROSS, beta, 3.2, -1, 21, depth=1.4))
        cuts.append(niche(sx * dd.TR_HALF, dd.Y_CROSS, beta, 4.0, 25.0, 44.0, depth=1.0))
        for yy in (65.54, 87.19):
            fins.append(dd.pinnacle(sx * 41.6, yy, 3.4, 0, 60, 74))
    # Chorhaupt: 10 Polygonseiten
    for i in range(10):
        a = 9 + 18 * i
        ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
        r_out, r_in = 23.6 * math.cos(math.radians(9)), 8.3 * math.cos(math.radians(9))
        cuts.append(niche(r_out * ca, dd.Y_APSE + r_out * sa, a, 1.9, 4.0, 19.5))
        cuts.append(niche(r_in * ca, dd.Y_APSE + r_in * sa, a, 0.9, 30.0, 41.5, depth=0.8))
        if i > 0:
            b = 18 * i
            fins.append(fin(23.6 * math.cos(math.radians(b)), dd.Y_APSE + 23.6 * math.sin(math.radians(b)), b, 1.7, 3.2, 21.0))
    B = B - Manifold.batch_boolean(cuts, OpType.Add)
    return Manifold.batch_boolean([B, crossing_spire()] + fins, OpType.Add)


def tower_details(sx):
    xc, yc = sx * dd.XT, dd.YT
    add, cut = [], []
    # Kranz aus geraden Fialen auf der Turmplattform (63 m): hier beginnt der Drall
    for su in (-1, 1):
        for sv in (-1, 1):
            add.append(dd.pinnacle(xc + su * 9.0, yc + sv * 9.0, 2.6, 62, 73, 86))
    # Portal + hohe Fenster in der Westseite, Fenster in der Außenseite
    cut.append(niche(xc, 0.0, -90, 3.0, -1, 21, depth=1.6))
    cut.append(niche(xc, 0.6, -90, 1.4, 36, 58.5, depth=1.0))
    cut.append(niche(xc + sx * 10.9, yc, 0 if sx > 0 else 180, 1.4, 36, 58.5, depth=1.0))
    cut.append(niche(xc + sx * 11.5, yc, 0 if sx > 0 else 180, 1.4, 8, 28, depth=1.0))
    return add, cut


PLINTH = 2.4    # Sockelplatte (m) ~ 3 mm


def build():
    adds, cuts = [], []
    for sx in (-1, 1):
        a, c = tower_details(sx)
        adds += a
        cuts += c
    M = Manifold.batch_boolean([body(), west_tower(-1), west_tower(1)], OpType.Add)
    M = M - Manifold.batch_boolean(cuts, OpType.Add)
    M = Manifold.batch_boolean([M] + adds, OpType.Add)
    # Sockelplatte in Form des Grundrisses (lateinisches Kreuz)
    fp = plan_footprint(M).offset(3.6, JoinType.Miter, 2.0).offset(-3.6, JoinType.Miter, 2.0)
    fp = fp.offset(3.0, JoinType.Miter, 2.0).simplify(0.05)
    plate = Manifold.extrude(fp, PLINTH * 0.6) + Manifold.extrude(fp.offset(-0.7, JoinType.Miter, 2.0), PLINTH)
    M = M.translate((0, 0, PLINTH)) + plate
    return to_mm(M, H_MM * dd.H_REAL / (dd.H_REAL + PLINTH))


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'render'
    pal = sys.argv[2] if len(sys.argv) > 2 else 'bronze'
    A = build()
    c = check(A)
    print(c)
    zmax = A.bounding_box()[5]
    s = H_MM / (dd.H_REAL + PLINTH)
    bands = gradient_bands((P['G0'] + PLINTH) * s, (P['G1'] + PLINTH) * s, zmax, run=2)
    print('bands', len(bands))
    write_preview(HERE, A, None, bands)
    if mode == 'render':
        V = [dict(name='hero', az=-35, el=14, zoom=1.08, tx=0.15),
             dict(name='front', az=0, el=4, zoom=1.05),
             dict(name='side', az=-90, el=5, zoom=1.05),
             dict(name='back', az=-150, el=24, zoom=1.05)]
        print(render(HERE, V, palette=pal))
        print(render(HERE, [dict(name='hero_abendgold', az=-35, el=14, zoom=1.08, tx=0.15)], palette='abendgold'))
        print(render(HERE, [dict(name='money', az=-18, el=-14, zoom=1.7, ty=0.68, fov=44),
                            dict(name='money2', az=-38, el=-20, zoom=1.9, ty=0.72, tx=0.12, fov=48)],
                     palette=pal, bg='#17181b', extra={'BACKLIGHT': 4}))
