#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kölner Dom · FIALENWALD
=======================
Der ganze Dom besteht aus Hunderten schlanker Fialen (quadratische Schäfte mit
Pyramidenhelm) auf einem Raster. Jede Fiale ist genau so hoch wie der Dom an
ihrer Stelle (Höhenfeld aus dem Massenmodell). Von weitem: der Dom. Von nahem:
ein Wald aus Spitzen.

Statik: Benachbarte Fialen sind innen über Stege verbunden, die bis
(niedrigere Nachbarhöhe - FREI) reichen. Nach außen bleiben Fugen offen
(Riefen), so dass jede Fassade aus einzelnen Schäften besteht. Oben steht jede
Fiale FREI mm frei. Alles wächst senkrecht oder als Pyramide nach oben ->
keine Überhänge, keine Stützen.

Farbe: Helme (Körper B) in Gold, Schäfte (Körper A) dunkel; die Turmhelme
laufen zusätzlich über einen Lagenverlauf ins Gold aus.

Aufruf:  python3 build.py [--no-render] [--palette bronze] [--stl]
"""
import json
import os
import sys
import time

import numpy as np

KIT = '/tmp/claude-0/-home-user-taste-skill/d46f1633-345d-5b87-803e-a453b1fd4c0a/scratchpad/kit'
sys.path.insert(0, KIT)
from proto_kit import *  # noqa: E402,F401,F403
from PIL import Image, ImageDraw  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

P = dict(
    n_tower=6,        # Rasterweite = Turmachsabstand XT / n  (3.21 m -> 4.08 mm)
    height=200.0,     # Turmspitze über Sockel (mm)
    w=2.8,            # Fialenbreite (mm)
    w_needle=3.6,     # Breite der beiden Turmnadeln (mm)
    tip=10.0,         # Helmhöhe (mm) - schlank, ca. 3.5 x Breite
    tip_needle=16.0,  # Helmhöhe der Turmnadeln (mm)
    collar=0.0,       # goldener Kragen unter dem Helm (mm)
    free=20.0,        # frei stehende Länge jeder Fiale über den Stegen (mm)
    groove=2.0,       # Tiefe der Außenfugen (mm)
    t_min=1.0,        # Mindeststärke eines Stegs (mm)
    plinth=4.0,       # Sockelhöhe (mm)
    plinth_margin=3.0,
    win=0.2,          # Abtastfenster (Anteil der Rasterweite) für die Höhe
    cov=0.4,          # Mindestbedeckung einer Zelle
    peak_max=12.0,    # max. Überstand über den höchsten Nachbarn (mm)
    rhythm=True,      # Strebepfeiler-Reihen im Jochrhythmus
    portals=True,     # Portale als Spitzbogen-Durchbrüche in den vorderen Reihen
    grad=(150.0, 186.0),  # Lagenverlauf A -> Gold (mm über Platte)
)

# ---------------------------------------------------------------- Höhenfeld
RES = 19.25 / 6 / 13          # 13 Pixel pro Rasterzelle
NXH = 182                     # x-Pixel: -NXH..NXH  (Pixelzentren bei k*RES)
NY0, NY1 = -60, 560           # y-Pixel: Zentren bei 11.5 + k*RES


def heightfield(M, dz=0.2):
    xs = np.arange(-NXH, NXH + 1) * RES
    ys = 11.5 + np.arange(NY0, NY1 + 1) * RES
    nx, ny = len(xs), len(ys)
    hf = np.zeros((ny, nx), np.float32)
    x0, y0 = xs[0] - RES / 2, ys[0] - RES / 2
    for z in np.arange(dz / 2, dd.H_REAL + dz, dz):
        polys = M.slice(float(z)).to_polygons()
        if not polys:
            continue
        mask = np.zeros((ny, nx), bool)
        for c in polys:
            im = Image.new('1', (nx, ny), 0)
            ImageDraw.Draw(im).polygon([((x - x0) / RES, (y - y0) / RES) for x, y in c], fill=1)
            mask ^= np.array(im, bool)
        hf[mask] = z + dz / 2
    hf = np.maximum(hf, hf[:, ::-1])  # exakt symmetrisch zur Domachse
    return hf


def load_hf():
    f = os.path.join(HERE, 'hf2.npy')
    if os.path.exists(f):
        return np.load(f)
    hf = heightfield(massing())
    np.save(f, hf)
    return hf


# ---------------------------------------------------------------- Raster
CX = np.arange(-14, 15)       # Zellindex quer (0 = Domachse, ±6 = Turmachsen)
CY = np.arange(-3, 42)        # Zellindex längs (0 = Turmmitte, -3 = Westfassade)


def cell_heights(hf, p):
    n = 13
    pm = dd.XT / p['n_tower']
    r = int(round(p['win'] * n))
    H = np.zeros((len(CY), len(CX)))
    C = np.zeros_like(H)
    for j, cj in enumerate(CY):
        for i, ci in enumerate(CX):
            px = NXH + ci * n
            py = -NY0 + cj * n
            b = hf[max(py - r, 0):py + r + 1, max(px - r, 0):px + r + 1]
            H[j, i] = b.max() if b.size else 0
            b = hf[max(py - 6, 0):py + 7, max(px - 6, 0):px + 7]
            C[j, i] = (b > 0.5).mean() if b.size else 0
    H[C < p['cov']] = 0
    # Türme auch in y symmetrisch (nur Turmspalten)
    tc = np.abs(CX) >= 3
    t = H[0:7, tc].copy()
    H[0:7, tc] = np.maximum(t, t[::-1])
    return CX * pm, dd.YT + CY * pm, H, pm


def at(H, cx, cy, v):
    H[list(CY).index(cy), list(CX).index(cx)] = v


def stylize(xs, ys, H, pm, p):
    """Künstlerische Eingriffe auf dem Raster (Meter)."""
    H = H.copy()
    if p['rhythm']:
        # Strebepfeiler (Fialen 47/48 m) nur in jedem zweiten Joch voll,
        # dazwischen Höhe des Seitenschiffdachs -> gotischer Jochrhythmus
        for j, y in enumerate(ys):
            if 23.0 < y < 113.9 and not (59.0 < y < 94.0) and CY[j] % 2 == 1:
                for i, x in enumerate(xs):
                    if 13.5 < abs(x) < 30.0 and H[j, i] > 43:
                        H[j, i] = 37.0
    # Türme: klare Stufen (Ring 3: Turmkrone, Ring 2: Fialenkranz, Ring 1 + Nadel: Helm)
    for s_ in (-1, 1):
        for dj in range(-3, 4):
            for di in range(-3, 4):
                r = max(abs(di), abs(dj))
                corner = abs(di) == abs(dj) and r > 0
                v = {3: 95.0, 2: 108.0 if corner else 119.0, 1: 137.0 if corner else 146.0, 0: dd.H_REAL}[r]
                at(H, 6 * s_ + di, dj, v)
    return H


def lonely_peaks(H, keep, peak):
    """Fialen, die alle Nachbarn um mehr als `peak` überragen, kürzen."""
    for _ in range(4):
        P_ = np.pad(H, 1)
        nb = np.max([P_[1 + dy:P_.shape[0] - 1 + dy, 1 + dx:P_.shape[1] - 1 + dx]
                     for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))], axis=0)
        lim = np.where(keep, H, nb + peak)
        H = np.where(H > 0, np.minimum(H, lim), 0)
    return H


# ---------------------------------------------------------------- Portale & Fenster
def lancet_cut(xs, ys, w, T, face, c, half, z0, apex, rows, k=1.25):
    """Spitzbogen-Ausschnitt (max. 45° Überhang) durch die äußeren `rows` Fialenreihen.
    face: 'W' (Westfassade), 'N'/'S' = Seite -x/+x mit Spaltenindex.
    c: Mitte entlang der Fassade (mm)."""
    cs = dd.lancet(0.0, half, T + z0, T + apex, k=k)
    depth = (w + 2.0 + 0.6) if z0 > 0 else 0.0
    if depth > 0:   # Fensterbank als 45°-Schräge nach außen (keine grelle Stufe, kein Überhang)
        sill = dd.poly([(0.0, 0.0), (depth, 0.0), (0.0, -depth)])   # (Tiefe ab außen, z)
    if face == 'W':
        j0 = list(CY).index(-3)
        d0, d1 = ys[j0] - w / 2 - 2.0, ys[j0 + rows] - w / 2 + 0.02
        m = dd.extrude_y(cs, d0, d1).translate((c, 0, 0))
        if depth > 0:   # Keil: Profil (y,z) entlang x extrudiert
            wedge = Manifold.extrude(sill, 2 * half).rotate((90, 0, 90))
            bb = wedge.bounding_box()
            wedge = wedge.translate((c - half - bb[0], d0 - bb[1], T + z0 + 0.01 - bb[5]))
            m = m + wedge
        return m
    col, sgn = face
    i0 = list(CX).index(col)
    xo = xs[i0] + sgn * (w / 2 + 2.0)                 # außen
    xi = xs[i0 - sgn * rows] + sgn * (w / 2 - 0.02)   # Vorderkante der Reihe dahinter
    m = dd.extrude_y(cs, 0.0, abs(xo - xi)).rotate((0, 0, 90))   # Tiefe entlang -x
    bb = m.bounding_box()
    m = m.translate((min(xo, xi) - bb[0], c, 0))
    if depth > 0:
        wedge = Manifold.extrude(sill, 2 * half).rotate((90, 0, 0))   # Profil in (x,z), Länge entlang y
        if sgn > 0:   # Tiefe zeigt nach innen (-x)
            wedge = wedge.mirror((1, 0, 0))
        bb = wedge.bounding_box()
        xo_edge = bb[3] if sgn > 0 else bb[0]
        wedge = wedge.translate((xo - xo_edge, c - 0.5 * (bb[1] + bb[4]), T + z0 + 0.01 - bb[5]))
        m = m + wedge
    return m


def portal_cuts(xs, ys, sp, w, T, S):
    g = sp - w
    h3 = 1.5 * sp - g / 2            # 3 Fialen breit
    h4 = 2.0 * sp - g / 2            # 4 Fialen breit
    yT = ys[list(CY).index(0)]       # Turmmitte
    cuts = [lancet_cut(xs, ys, w, T, 'W', 0.0, h3, -0.5, 42.0, 2)]                # Hauptportal
    for s in (-1, 1):
        xt = s * dd.XT * S
        # Turmfront: hohe Lanzettnische (1 Reihe tief) mit Portal darin (2 Reihen tief) -> Gewände
        cuts.append(lancet_cut(xs, ys, w, T, 'W', xt, h3, -0.5, 88.0, 1, k=1.6))
        cuts.append(lancet_cut(xs, ys, w, T, 'W', xt, h3 - sp, -0.5, 30.0, 2, k=1.25))
        # Turmseiten außen: dieselbe hohe Nische
        cuts.append(lancet_cut(xs, ys, w, T, (9 * s, s), yT, h3, -0.5, 88.0, 1, k=1.6))
        yq = 0.5 * (ys[list(CY).index(20)] + ys[list(CY).index(21)])
        cuts.append(lancet_cut(xs, ys, w, T, (13 * s, s), yq, h4, -0.5, 32.0, 2))  # Querhausportal
    return Manifold.batch_boolean(cuts, OpType.Add)


# ---------------------------------------------------------------- Geometrie
def box(x0, x1, y0, y1, z0, z1):
    return Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def build(p=P):
    t0 = time.time()
    hf = load_hf()
    xs_m, ys_m, Hm, pm = cell_heights(hf, p)
    Hm = stylize(xs_m, ys_m, Hm, pm, p)
    S = p['height'] / dd.H_REAL
    pin = Hm > 0
    H = Hm * S
    needle = np.zeros_like(pin)
    needle[list(CY).index(0), [list(CX).index(6), list(CX).index(-6)]] = True
    H = lonely_peaks(H, needle, p['peak_max'])
    xs, ys = xs_m * S, ys_m * S
    w, T, free = p['w'], p['plinth'], p['free']
    sp = pm * S
    g = sp - w
    eps = 0.04
    B = np.where(pin, np.maximum(H - free, 0.0), 0.0)
    ny, nx = H.shape

    def Bv(j, i):
        if 0 <= j < ny and 0 <= i < nx and pin[j, i]:
            return B[j, i]
        return 0.0

    def cross(j0, i0):  # Kreuzungsfeld zwischen (j0,i0) und (j0+1,i0+1)
        return min(Bv(j0, i0), Bv(j0, i0 + 1), Bv(j0 + 1, i0), Bv(j0 + 1, i0 + 1))

    A_parts, B_parts = [], []
    gd = p['groove']
    gd2 = min(gd, (w - p['t_min']) / 2)
    for j in range(ny):
        for i in range(nx):
            if not pin[j, i]:
                continue
            x, y, h = xs[i], ys[j], H[j, i]
            wi = p['w_needle'] if needle[j, i] else w
            th = p['tip_needle'] if needle[j, i] else p['tip']
            zt = T + h - th
            zc = zt - p['collar']
            A_parts.append(box(x - wi / 2, x + wi / 2, y - wi / 2, y + wi / 2, 0, zc))
            B_parts.append(box(x - wi / 2, x + wi / 2, y - wi / 2, y + wi / 2, zc, zt))
            sq = CrossSection.square((wi, wi), center=True)
            B_parts.append(Manifold.extrude(sq, th, scale_top=(0, 0)).translate((x, y, zt)))
            # Stege zu den Nachbarn in +x und +y
            for (dj, di) in ((0, 1), (1, 0)):
                jj, ii = j + dj, i + di
                if not (jj < ny and ii < nx and pin[jj, ii]):
                    continue
                W = min(B[j, i], B[jj, ii])
                if W <= 0:
                    continue
                if di == 1:   # Steg zwischen x_i und x_i+1, Tiefe in y
                    lo, hi = cross(j - 1, i), cross(j, i)
                    a0, a1 = x + w / 2 - eps, xs[ii] - w / 2 + eps
                    c = y
                else:         # Steg zwischen y_j und y_j+1, Tiefe in x
                    lo, hi = cross(j, i - 1), cross(j, i)
                    a0, a1 = y + w / 2 - eps, ys[jj] - w / 2 + eps
                    c = x
                segs = []
                za = min(lo, hi, W)
                zb = min(max(lo, hi), W)
                if za > 0:
                    segs.append((c - w / 2, c + w / 2, 0, za))
                if zb > za:   # eine Seite liegt außen -> Fuge von dieser Seite
                    if lo < hi:
                        segs.append((c - w / 2 + gd, c + w / 2, za, zb))
                    else:
                        segs.append((c - w / 2, c + w / 2 - gd, za, zb))
                if W > zb:    # beide Seiten außen: nur der Kern, der auch darunter Steg ist
                    b0, b1 = c - w / 2 + gd2, c + w / 2 - gd2
                    if zb > za:
                        b0, b1 = (max(b0, c - w / 2 + gd), b1) if lo < hi else (b0, min(b1, c + w / 2 - gd))
                    if b1 - b0 >= p['t_min'] - 1e-6:
                        segs.append((b0, b1, zb, W))
                for (b0, b1, z0, z1) in segs:
                    zz0 = T + z0 - (eps if z0 > 0 else 0)
                    if di == 1:
                        A_parts.append(box(a0, a1, b0, b1, zz0, T + z1))
                    else:
                        A_parts.append(box(b0, b1, a0, a1, zz0, T + z1))
            Xc = cross(j, i)
            if Xc > 0:
                A_parts.append(box(x + w / 2 - eps, xs[i + 1] - w / 2 + eps,
                                   y + w / 2 - eps, ys[j + 1] - w / 2 + eps, T, T + Xc))
    # Sockel: echter Grundriss (glatt), zweistufig
    cells = CrossSection.batch_boolean([CrossSection.square((w, w), center=True).translate((xs[i], ys[j]))
                                        for j in range(ny) for i in range(nx) if pin[j, i]], OpType.Add)
    fp = plan_footprint(massing()).scale((S, S))
    d = 0.0
    while not (cells - fp.offset(d, JoinType.Round, circular_segments=64)).is_empty() and d < 8:
        d += 0.25            # so weit aufblasen, bis alle Fialen auf dem glatten Grundriss stehen
    fp = fp.offset(d + p['plinth_margin'], JoinType.Round, circular_segments=96)
    A_parts.append(Manifold.extrude(fp, T + 0.01))
    A_parts.append(Manifold.extrude(fp.offset(1.6, JoinType.Round, circular_segments=64), T - 1.6))
    A = Manifold.batch_boolean(A_parts, OpType.Add)
    Bm = Manifold.batch_boolean(B_parts, OpType.Add)
    if p['portals']:
        A = A - portal_cuts(xs, ys, sp, w, T, S)
    bb = (A + Bm).bounding_box()
    A = A.translate((-bb[0], -bb[1], 0))
    Bm = Bm.translate((-bb[0], -bb[1], 0))
    # Diagnose: frei stehende Länge je Fiale
    Pb = np.pad(np.where(pin, B, 0), 1)
    nbB = np.max([Pb[1 + dy:Pb.shape[0] - 1 + dy, 1 + dx:Pb.shape[1] - 1 + dx]
                  for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))], axis=0)
    F = np.where(pin, H - np.minimum(B, nbB), 0)
    info = dict(pins=int(pin.sum()), pitch_mm=round(sp, 3), gap_mm=round(g, 3),
                free_max=round(float(F.max()), 1), free_gt25=int((F > 25).sum()),
                hmax=round(float(H.max()) + T, 1), tip_min_z=round(float((H[pin]).min()) + T - p['tip'], 1),
                secs=round(time.time() - t0, 1))
    return A, Bm, info, dict(H=H, pin=pin, xs=xs, ys=ys, F=F)


def swaps(A, Bm, bands, layer=0.16, first=0.2):
    """Schätzung der Filamentwechsel: je Lage, in der beide Farben vorkommen, 1 Wechsel."""
    zmax = max(A.bounding_box()[5], Bm.bounding_box()[5])
    zb0, zb1 = Bm.bounding_box()[2], Bm.bounding_box()[5]
    edges = [0.0, first]
    while edges[-1] < zmax:
        edges.append(edges[-1] + layer)
    inband = lambda z: any(a < z < b for a, b in bands)  # noqa: E731
    n_mixed = 0
    full_gold_from = None
    for k in range(len(edges) - 1):
        zc = 0.5 * (edges[k] + edges[k + 1])
        hasB = zb0 < zc < zb1 or inband(zc)
        hasA = zc < A.bounding_box()[5] and not inband(zc)
        if hasA and hasB:
            n_mixed += 1
    return n_mixed


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-render', action='store_true')
    ap.add_argument('--views', default='')
    ap.add_argument('--palette', default='bronze')
    ap.add_argument('--bg', default=None)
    ap.add_argument('--out', default=HERE)
    ap.add_argument('--stl', action='store_true')
    ap.add_argument('--final', action='store_true', help='alle Abschlussbilder rendern')
    a = ap.parse_args()
    A, Bm, info, dbg = build(P)
    print(json.dumps(info))
    U = A + Bm
    print(json.dumps(check(U)))
    print('A teile', check(A)['teile'], 'B teile', check(Bm)['teile'])
    zmax = U.bounding_box()[5]
    bands = gradient_bands(P['plinth'] + P['grad'][0], P['plinth'] + P['grad'][1], zmax, run=2)
    print('farbwechsel ~', swaps(A, Bm, bands))
    write_preview(a.out, A, Bm, bands)
    if a.stl:
        sys.path.insert(0, '/home/user/taste-skill/koelner-dom')
        from dom_durchblick import write_stl
        os.makedirs(os.path.join(a.out, 'out'), exist_ok=True)
        # Lagenverlauf in die Geometrie einbacken: Band-Scheiben von A gehen an B (Gold)
        bb = U.bounding_box()
        slabs = Manifold.batch_boolean([box(bb[0] - 1, bb[3] + 1, bb[1] - 1, bb[4] + 1, z0, z1) for z0, z1 in bands],
                                       OpType.Add)
        A_stl = A - slabs
        B_stl = Bm + (A ^ slabs)
        print('STL: Baender', len(bands), 'A teile', len(A_stl.decompose()), 'B teile', len(B_stl.decompose()))
        write_stl(os.path.join(a.out, 'out', 'fialenwald_A.stl'), A_stl, 'fialenwald_A')
        write_stl(os.path.join(a.out, 'out', 'fialenwald_B_gold.stl'), B_stl, 'fialenwald_B')
    if a.final:
        final_shots(a.out)
    elif not a.no_render:
        views = json.loads(a.views) if a.views else None
        print(render(a.out, views, palette=a.palette, bg=a.bg))


MONEY_LIGHT = {"BG": "#1a1c20", "KEY": {"az": -60, "el": 12, "I": 6.0, "color": "#ffdcae"},
               "RIM": {"az": 20, "el": 30, "I": 1.5, "color": "#ffe9c8"},
               "FILL": {"az": -160, "el": 30, "I": 0.6, "color": "#9fb3d9"}, "ENV": 0.5, "EXPOSURE": 1.1}


def final_shots(out):
    import shutil
    sys.path.insert(0, os.path.join(HERE, 'money'))
    from shoot import shoot   # eigene Kopie des Renderers mit Streiflicht (money/money.html)
    print(render(out, [dict(name='hero', az=-35, el=14, zoom=1.0), dict(name='front', az=0, el=4, zoom=1.0),
                       dict(name='side', az=-90, el=5, zoom=1.0)], palette='bronze'))
    tmp = os.path.join(out, '_alt')
    shutil.copytree(os.path.join(out, 'out', 'preview'), os.path.join(tmp, 'out', 'preview'), dirs_exist_ok=True)
    p = render(tmp, [dict(name='hero_abendgold', az=-35, el=14, zoom=1.0)], palette='abendgold')
    shutil.copy(p[0], os.path.join(out, 'shots', 'hero_abendgold.png'))
    shutil.rmtree(tmp)
    print(shoot(out, [dict(name='money', az=-142, el=12, zoom=1.27, ty=0.46),
                      dict(name='detail', az=-158, el=11, zoom=1.75, ty=0.52, tz=0.05)], 'bronze', dict(MONEY_LIGHT)))


if __name__ == '__main__':
    main()
