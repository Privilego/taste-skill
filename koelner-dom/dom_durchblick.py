#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kölner Dom · DURCHBLICK
=======================

Parametrischer Generator für ein 3D-druckbares Deko-Objekt.

Idee: Der Dom wird nicht als Modell nachgebaut, sondern in sein gotisches
Gerippe zerlegt. Jede Lamelle ist ein Querschnitt durch den Dom, genau dort,
wo im echten Bau ein Strebepfeiler steht. Alle Spitzbögen liegen exakt
hintereinander: Wer durchs Hauptportal schaut, blickt durch das ganze
Langhaus bis in den Chor. Um die Apsis fächern die Lamellen strahlenförmig
auf, wie das Strebewerk des echten Chors.

Alle Öffnungen sind „FDM-Spitzbögen“: Überhänge höchstens 45°, also ohne
Stützstrukturen druckbar. Die Gotik ist gewissermaßen die Ur-Architektur
des 3D-Drucks.

Ausgabe (Ordner ./out):
  dom_durchblick_einfarbig.stl   - ein Körper, für 1 Filament
  dom_durchblick_A.stl           - Teil für Filament 1 (unten, dunkel)
  dom_durchblick_B.stl           - Teil für Filament 2 (oben, Gold + Inschrift)
  preview/dom.bin, preview/meta.json - Daten für die 3D-Vorschau

Benötigt: pip install numpy manifold3d matplotlib
"""
import argparse
import json
import math
import os
import struct

import numpy as np
from manifold3d import CrossSection, FillRule, JoinType, Manifold, OpType

H_REAL = 157.4  # Höhe der Westtürme in Metern

# --------------------------------------------------------------------------
# 2D-Helfer (alle Maße in Metern, Dom-Koordinaten)
#   x = quer (Nord-Süd), y = längs (West -> Ost, Fassade bei y = 0), z = Höhe
# --------------------------------------------------------------------------


def poly(pts):
    pts = np.asarray(pts, dtype=float)
    area = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    if area < 0:
        pts = pts[::-1]
    return CrossSection([pts])


def rect(x0, x1, z0, z1):
    return poly([(x0, z0), (x1, z0), (x1, z1), (x0, z1)])


def union2d(items):
    items = [i for i in items if not i.is_empty()]
    if not items:
        return CrossSection()
    return CrossSection.batch_boolean(items, OpType.Add)


def sym(cs):
    """An u = 0 spiegeln und vereinigen."""
    return cs + cs.mirror((1, 0))


def arch_rise(half, k):
    """Höhe vom Kämpfer bis zum Scheitel eines FDM-Spitzbogens."""
    r = 2 * k * half
    phi_apex = math.acos((r - half) / r)
    phi_end = min(phi_apex, math.radians(45))
    xe = (half - r) + r * math.cos(phi_end)
    return r * math.sin(phi_end) + xe


def lancet(cx, half, zb, apex, k=2.0, seg=10):
    """Spitzbogenfenster: unten zb, Scheitel bei apex.
    k = 1: gleichseitiger Bogen, k > 1: schlanke Lanzette.
    Ab 45° Tangente geht der Bogen in eine Gerade über -> stützenfrei druckbar."""
    r = 2 * k * half
    zs = apex - arch_rise(half, k)
    zs = max(zs, zb + 0.05)
    c = cx + half - r
    phi_apex = math.acos((r - half) / r)
    phi_end = min(phi_apex, math.radians(45))
    right = [(c + r * math.cos(p), zs + r * math.sin(p)) for p in np.linspace(0, phi_end, seg)]
    if phi_end < phi_apex:
        xe, ze = right[-1]
        top = (cx, ze + (xe - cx))
    else:
        top = right.pop()
        top = (cx, top[1])
    left = [(2 * cx - x, z) for (x, z) in reversed(right)]
    return poly([(cx - half, zb), (cx + half, zb)] + right + [top] + left)


class Opening:
    def __init__(self, cs, ground=False):
        self.cs = cs
        self.ground = ground


def L(cx, half, zb, apex, k=2.0, ground=False):
    if ground:
        zb = -5.0
    return Opening(lancet(cx, half, zb, apex, k), ground)


def place_openings(profile, cands, margin):
    """Behält nur Fenster, die mit Rand vollständig in die Lamelle passen
    und sich nicht gegenseitig berühren (gierig, in Listenreihenfolge)."""
    if profile.is_empty():
        return CrossSection()
    inner = profile.offset(-margin, JoinType.Miter, 2.0)
    above = rect(-1e3, 1e3, margin, 1e4)
    accepted = []
    acc_union = CrossSection()
    for o in cands:
        test = (o.cs ^ above) if o.ground else o.cs
        a = test.area()
        if a <= 1e-9:
            continue
        if (test - inner).area() > 1e-4 * a + 1e-7:
            continue
        if accepted and (o.cs.offset(margin * 0.98, JoinType.Miter, 2.0) ^ acc_union).area() > 1e-7:
            continue
        accepted.append(o.cs)
        acc_union = acc_union + o.cs
    return acc_union


# --------------------------------------------------------------------------
# 3D-Helfer
# --------------------------------------------------------------------------


def box(x0, x1, y0, y1, z0, z1):
    return Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def octagon(apothem):
    return CrossSection.circle(apothem / math.cos(math.pi / 8), 8).rotate(22.5)


def oct_prism(cx, cy, a, z0, z1, a_top=None):
    s = 1.0 if a_top is None else max(a_top / a, 0.0)
    return Manifold.extrude(octagon(a), z1 - z0, scale_top=(s, s)).translate((cx, cy, z0))


def pinnacle(cx, cy, w, z0, z1, z2):
    shaft = box(cx - w / 2, cx + w / 2, cy - w / 2, cy + w / 2, z0, z1)
    tip = Manifold.extrude(CrossSection.square((w, w), center=True), z2 - z1, scale_top=(0, 0))
    return shaft + tip.translate((cx, cy, z1))


def extrude_y(cs, y0, y1):
    """2D-Profil (x, z) entlang y von y0 bis y1 extrudieren."""
    return Manifold.extrude(cs, y1 - y0).rotate((90, 0, 0)).translate((0, y1, 0))


def to_local(M, p, theta):
    return M.translate((-p[0], -p[1], 0)).rotate((0, 0, 90 - theta)).rotate((-90, 0, 0))


def to_world(Lm, p, theta):
    return Lm.rotate((90, 0, 0)).rotate((0, 0, -(90 - theta))).translate((p[0], p[1], 0))


def section(M, p, theta):
    """Senkrechter Schnitt durch M. Ebene durch p, Normale (cos θ, sin θ).
    Liefert 2D-Profil in (u, z), u entlang (sin θ, -cos θ)."""
    return to_local(M, p, theta).slice(0.0)


def plate(cs2d, p, theta, t):
    if cs2d.is_empty():
        return Manifold()
    return to_world(Manifold.extrude(cs2d, t).translate((0, 0, -t / 2)), p, theta)


# --------------------------------------------------------------------------
# Massenmodell des Doms (stark vereinfacht, aber mit echten Proportionen)
# --------------------------------------------------------------------------

XT = 19.25      # Turmachsen
YT = 11.5       # Turmmitte (Tiefe)
Y_NAVE0 = 23.0
Y_TR0, Y_TR1 = 61.0, 92.0
Y_CROSS = 76.5  # Vierung
Y_APSE = 113.9  # Mittelpunkt des Chorhaupts
TR_HALF = 43.1  # Querhaus: 86,25 m breit


def nave_half(buttress=True):
    pcs = [rect(0, 8.3, 0, 45), poly([(0, 45), (8.3, 45), (0, 61.1)]),
           rect(0, 23.6, 0, 23), poly([(8.3, 23), (23.6, 23), (8.3, 28.5)])]
    if buttress:
        pcs += [
            # äußerer Strebepfeiler mit Fiale
            rect(23.6, 30.7, 0, 14), rect(23.6, 29.7, 14, 26), rect(24.6, 29.2, 26, 34),
            rect(25.6, 28.8, 34, 38), poly([(25.6, 38), (28.8, 38), (27.2, 47)]),
            # Zwischenpfeiler mit Fiale
            rect(14.4, 16.4, 20, 39), poly([(14.4, 39), (16.4, 39), (15.4, 48)]),
            # Strebebögen (als Scheiben, die Öffnungen kommen später)
            poly([(16.4, 24.0), (24.6, 22.0), (24.6, 34), (16.4, 38)]),
            poly([(8.0, 26), (14.4, 24), (14.4, 39.5), (8.3, 42.5)]),
        ]
    return union2d(pcs)


def transept_half():
    return union2d([rect(0, 8.3, 0, 45), poly([(0, 45), (8.3, 45), (0, 61.1)]),
                    rect(0, 15.5, 0, 23), poly([(8.3, 23), (15.5, 23), (8.3, 26.0)])])


def tower(sx):
    xc, yc = sx * XT, YT
    parts = [
        box(xc - 11.5, xc + 11.5, yc - 11.5, yc + 11.5, 0, 33),
        box(xc - 10.9, xc + 10.9, yc - 10.9, yc + 10.9, 33, 63),
        box(xc - 9.4, xc + 9.4, yc - 9.4, yc + 9.4, 63, 95),
        oct_prism(xc, yc, 7.8, 95, 111),
        oct_prism(xc, yc, 7.2, 111, 148, a_top=0.5),
        # Kreuzblume
        oct_prism(xc, yc, 0.6, 146.5, 150),
        oct_prism(xc, yc, 0.5, 150, 151.5, a_top=2.0),
        oct_prism(xc, yc, 2.0, 151.5, 154, a_top=0.45),
        oct_prism(xc, yc, 0.45, 154, H_REAL, a_top=0.0),
    ]
    for su in (-1, 1):
        for sv in (-1, 1):
            parts.append(pinnacle(xc + su * 9.6, yc + sv * 10.2, 2.2, 63, 71, 82))
            parts.append(pinnacle(xc + su * 8.2, yc + sv * 5.1, 2.0, 95, 103, 116))
        parts.append(pinnacle(xc + su * 8.4, yc, 1.8, 95, 103, 114))
        parts.append(pinnacle(xc, yc + su * 8.4, 1.8, 95, 103, 114))
    return Manifold.batch_boolean(parts, OpType.Add)


def massing():
    nave = sym(nave_half(True))
    core = sym(nave_half(False))
    center = core ^ rect(-7.75, 7.75, -1, 100)
    parts = [
        tower(-1), tower(1),
        extrude_y(center, 0, Y_NAVE0 + 0.5),
        pinnacle(0, 1.3, 1.6, 55, 63, 70),
        extrude_y(nave, Y_NAVE0, Y_TR0 + 0.5),
        extrude_y(core, Y_TR0 - 0.5, Y_TR1 + 0.5),
        extrude_y(nave, Y_TR1, Y_APSE + 0.6),
    ]
    # Querhaus
    tr = sym(transept_half())
    trm = Manifold.extrude(tr, 2 * TR_HALF).rotate((90, 0, 0)).translate((0, TR_HALF, 0))
    trm = trm.rotate((0, 0, -90)).translate((0, Y_CROSS, 0))
    parts.append(trm)
    for sx in (-1, 1):
        for yy in (65.54, 87.19):
            parts.append(pinnacle(sx * 41.6, yy, 3.0, 0, 60, 74))
        parts.append(pinnacle(sx * 42.2, Y_CROSS, 1.6, 55, 63, 69))
    # Vierungsturm
    parts.append(oct_prism(0, Y_CROSS, 4.3, 45, 72))
    parts.append(oct_prism(0, Y_CROSS, 4.3, 72, 109, a_top=0.15))
    # Chorhaupt: Querschnitt um die Apsis gedreht (10 Polygonseiten auf 180°)
    half = nave_half(True)
    apse = Manifold.revolve(half, 10, 180).translate((0, Y_APSE, 0))
    parts.append(apse)
    return Manifold.batch_boolean(parts, OpType.Add)


# --------------------------------------------------------------------------
# Fenster-Kandidaten
# --------------------------------------------------------------------------

def spire_rows(a0, z0, a1, z1, m_in, margin, k=2.0, gap=1.6, min_half=0.55):
    """Zwillings-Lanzetten, die nach oben im Turmhelm kleiner werden."""
    rows = []
    zb = z0 + 1.2
    while zb < z1:
        half = 2.0
        height = 0
        for _ in range(30):
            height = arch_rise(half, k) + 2.5 * half
            ztop = zb + height
            a = a0 + (a1 - a0) * (ztop - z0) / (z1 - z0)
            half = 0.5 * (half + (a - margin - m_in) / 2)
        if half < min_half:
            break
        rows.append((m_in + half, half, zb, zb + height))
        zb += height + gap
    return rows


def cands_nave():
    c = [L(0, 6.3, 0, 43.35, k=1.0, ground=True)]
    for s in (-1, 1):
        c.append(L(s * 11.35, 2.9, 0, 19.8, k=1.0, ground=True))
        c.append(L(s * 18.9, 2.8, 0, 19.8, k=1.0, ground=True))
        c.append(L(s * 20.5, 2.2, 26.0, 34.4, k=1.5))
        c.append(L(s * 11.35, 1.6, 29.6, 39.3, k=1.5))
    c.append(L(0, 2.0, 46.5, 55.0, k=1.5))
    return c


def cands_tower(front, margin, mullion):
    c = []
    if front:
        c.append(L(0, 3.6, 0, 26.0, k=1.5, ground=True))       # Hauptportal
        c.append(L(0, 4.4, 30.0, 50.5, k=1.5))                 # Westfenster
    else:
        c.append(L(0, 6.3, 0, 43.35, k=1.0, ground=True))      # Mittelschiff
    c.append(L(0, 2.0, 46.5, 55.0, k=1.5))                     # Giebel
    rows = spire_rows(7.2, 111, 0.5, 148, mullion, margin)
    for sx in (-1, 1):
        xc = sx * XT
        if front:
            c.append(L(xc, 3.4, 0, 24.0, k=2.0, ground=True))  # Turmportale
        else:
            for su in (-1, 1):
                c.append(L(xc + su * 5.0, 3.2, 0, 24.5, k=2.0, ground=True))
        for su in (-1, 1):
            c.append(L(xc + su * 4.4, 2.7, 36, 57.2))
            c.append(L(xc + su * 4.0, 2.5, 66, 88.6))
            c.append(L(xc + su * 2.6, 1.4, 97.5, 108.2))
            for (uc, h, zb, ap) in rows:
                c.append(L(xc + su * uc, h, zb, ap))
    return c


def cands_transept(margin, mullion):
    c = cands_nave()
    for s in (-1, 1):
        for xc in (27.4, 32.9, 38.4):
            c.append(L(s * xc, 2.0, 0, 38.0, k=2.0, ground=True))
        for xc in (27.4, 32.9, 38.4):
            c.append(L(s * xc, 1.6, 0, 17.0, k=2.0, ground=True))
        c.append(L(s * 1.7, 0.9, 62.5, 70.0))
        for (uc, h, zb, ap) in spire_rows(4.3, 72, 0.15, 109, mullion, margin):
            c.append(L(s * uc, h, zb, ap))
    return c


def bay_cands(u_fins, t, margin, rows, u_lo=-1e9, u_hi=1e9):
    """Fenster in Längswänden: je eines zwischen zwei Lamellen."""
    c = []
    u_fins = sorted(u_fins)
    for a, b in zip(u_fins[:-1], u_fins[1:]):
        uc = 0.5 * (a + b)
        if not (u_lo <= uc <= u_hi):
            continue
        half = (b - a - t) / 2 - margin
        if half < 0.5:
            continue
        for (zb, apex, ground) in rows:
            c.append(L(uc, half, zb, apex, k=2.0, ground=ground))
    return c


# --------------------------------------------------------------------------
# Zusammenbau
# --------------------------------------------------------------------------

def build(args):
    S = args.height / H_REAL                 # mm pro Meter
    t = args.fin / S                         # Lamellenstärke in m
    margin = args.frame / S                  # Mindeststeg in m
    mullion = t / 2 + 0.5                    # Mittelpfosten neben Längswand
    M = massing()

    plates = []

    # ---- Querlamellen ----
    y_tower = [1.3, 6.4, 11.5, 16.6, 21.7]
    y_nave = list(np.linspace(21.7, Y_CROSS, 11)[1:])
    y_choir = list(np.linspace(Y_CROSS, Y_APSE, 8)[1:])
    fins_y = y_tower + y_nave + y_choir
    for y in fins_y:
        prof = section(M, (0, y), 90)
        if y < 1.5:
            cands = cands_tower(True, margin, mullion)
        elif y < Y_NAVE0:
            cands = cands_tower(False, margin, mullion)
        elif Y_TR0 < y < Y_TR1:
            cands = cands_transept(margin, mullion)
        else:
            cands = cands_nave()
        holes = place_openings(prof, cands, margin)
        plates.append(plate(prof - holes, (0, y), 90, t))

    # ---- Strahlenlamellen um das Chorhaupt ----
    phis = [18 * k for k in range(1, 10)]
    clip_pos = rect(0, 1e3, -10, 1e3)
    for phi in phis:
        th = 90 + phi
        prof = section(M, (0, Y_APSE), th) ^ clip_pos
        full = sym(prof)
        holes = place_openings(full, cands_nave(), margin)
        plates.append(plate((full - holes) ^ clip_pos.translate((-t / 2, 0)), (0, Y_APSE), th, t))

    # ---- Längswände (u = y) ----
    def spine(x, y0, y1, rows, z_min=None, fins=None):
        fy = [f for f in (fins or fins_y) if y0 - 1e-3 <= f <= y1 + 1e-3]
        prof = section(M, (x, 0), 180) ^ rect(y0 - t / 2, y1 + t / 2, -10 if z_min is None else z_min, 1e3)
        if z_min is not None:
            # Unterkante als Spitzbögen zwischen den Lamellen -> kein Überhang
            for a, b in zip(fy[:-1], fy[1:]):
                hb = (b - a - t) / 2
                prof = prof - lancet((a + b) / 2, hb, z_min - 5, z_min + arch_rise(hb, 1.0) + 0.6, k=1.0)
        holes = place_openings(prof, bay_cands(fy, t, margin, rows), margin)
        plates.append(plate(prof - holes, (x, 0), 180, t))

    nave_rows = [(0, 20.5, True), (27.5, 41.5, False), (46.5, 56.0, False)]
    tower_rows = [(0, 17.0, True), (36, 57.2, False), (66, 88.6, False), (97.5, 108.2, False)]
    zb = 112.5
    while zb < 140:
        tower_rows.append((zb, zb + 5.2, False))
        zb += 6.8
    for s in (-1, 1):
        spine(s * 7.4, 1.3, Y_APSE, nave_rows)
        spine(s * 23.0, y_tower[-1], y_nave[6], [(3.0, 18.5, False)])
        spine(s * 23.0, y_choir[0], Y_APSE, [(3.0, 18.5, False)])
        spine(s * XT, y_tower[0], y_tower[-1], tower_rows)
        spine(s * 42.4, y_nave[7], y_choir[1], [(0, 14.0, True), (19.0, 42.0, False), (46.5, 56.0, False)])
    cross_rows = [(62.5, 70.0, False)] + [(zb, zb + 4.0, False) for zb in np.arange(73.0, 95.0, 5.4)]
    spine(0.0, y_nave[8], y_choir[0], cross_rows, z_min=44.6)

    # ---- Polygonale Außenwand des Chorhaupts ----
    R = 23.0
    for k in range(10):
        a0, a1 = math.radians(18 * k), math.radians(18 * (k + 1))
        p0 = np.array([R * math.cos(a0), Y_APSE + R * math.sin(a0)])
        p1 = np.array([R * math.cos(a1), Y_APSE + R * math.sin(a1)])
        pm = 0.5 * (p0 + p1)
        d = (p1 - p0) / np.linalg.norm(p1 - p0)
        th = math.degrees(math.atan2(d[0], -d[1]))
        Lh = np.linalg.norm(p1 - p0) / 2
        prof = section(M, pm, th) ^ rect(-Lh - t / 2, Lh + t / 2, -10, 1e3)
        holes = place_openings(prof, bay_cands([-Lh, Lh], t, margin, [(3.0, 18.5, False)]), margin)
        plates.append(plate(prof - holes, pm, th, t))

    body = Manifold.batch_boolean([p for p in plates if not p.is_empty()], OpType.Add)

    # ---- Sockel „Domplatte“ mit Inschrift ----
    layer, first = args.layer, args.first_layer
    plinth_mm = first + layer * args.plinth_layers
    foot = CrossSection(body.project().to_polygons(), FillRule.Positive)
    foot = foot.offset(4.0, JoinType.Round).offset(-2.0, JoinType.Round)
    plaza = rect(-32.8, 32.8, -15.0, 6.0)  # (x, y) – hier als Grundriss
    foot = (foot + plaza).offset(1.0, JoinType.Round).offset(-1.0, JoinType.Round)

    # in Millimeter umrechnen
    body = body.scale((S, S, S)).translate((0, 0, plinth_mm))
    foot = foot.scale((S, S))
    steps = 3
    base_h = plinth_mm - steps * layer
    plinth = Manifold.extrude(foot, base_h)
    for i in range(steps):
        inset = (i + 1) * layer * 1.0
        plinth = plinth + Manifold.extrude(foot.offset(-inset, JoinType.Round), layer).translate((0, 0, base_h + i * layer))

    text = inscription(args.text, S, plinth_mm, layer, args.inlay_layers)
    solid = body + plinth

    # ---- Farbverlauf: Lagenmuster ----
    bands, n_layers, swaps = band_pattern(args, plinth_mm, args.height)
    bb = solid.bounding_box()
    slabs = [box(bb[0] - 1, bb[3] + 1, bb[1] - 1, bb[4] + 1, z0, z1) for (z0, z1) in bands]
    slab_b = Manifold.batch_boolean(slabs, OpType.Add) if slabs else Manifold()
    part_b = (body ^ slab_b) + text
    part_a = solid - slab_b - text
    return dict(solid=solid + text, body=solid, text=text, a=part_a, b=part_b, S=S, plinth_mm=plinth_mm,
                bands=bands, n_layers=n_layers, swaps=swaps, n_plates=len(plates))


def inscription(txt, S, plinth_mm, layer, inlay_layers):
    """Goldene Inschrift, bündig in der Domplatte eingelegt."""
    if not txt:
        return Manifold()
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    tp = TextPath((0, 0), txt, size=10, prop=FontProperties(family="DejaVu Serif"))
    polys = [np.asarray(p) for p in tp.to_polygons() if len(p) >= 3]
    cs = CrossSection(polys, FillRule.EvenOdd)
    x0, y0, x1, y1 = cs.bounds()
    h_mm = 4.2
    sc = h_mm / (y1 - y0)
    cs = cs.translate((-(x0 + x1) / 2, -(y0 + y1) / 2)).scale((sc, sc))
    cs = cs.translate((0, -9.0 * S))
    depth = layer * inlay_layers
    return Manifold.extrude(cs, depth).translate((0, 0, plinth_mm - depth))


def band_pattern(args, z_base, height):
    """Liefert die z-Intervalle für Filament B.
    Unten Filament A, oben B. Dazwischen verteilt eine Fehlerdiffusion feine
    Linien von B (je `run` Lagen dick): erst vereinzelt, dann immer dichter,
    bis alles in B übergeht. run = 1 ergibt einen echten Lage-für-Lage-Verlauf."""
    layer, first = args.layer, args.first_layer
    z_top = z_base + height + 1.0
    edges = [0.0, first]
    while edges[-1] < z_top:
        edges.append(edges[-1] + layer)
    n = len(edges) - 1
    zs, ze = z_base + args.grad_start * height, z_base + args.grad_end * height
    R = max(1, args.run)
    isB = np.zeros(n, dtype=bool)
    acc = 0.0
    for i in range(0, n, R):
        j = min(i + R, n)
        zc = 0.5 * (edges[i] + edges[j])
        f = min(max((zc - zs) / (ze - zs), 0.0), 1.0) ** args.gamma
        acc += f
        if acc >= 0.5:
            isB[i:j] = True
            acc -= 1.0
    bands = []
    k = 0
    while k < n:
        if isB[k]:
            s0 = k
            while k < n and isB[k]:
                k += 1
            bands.append((edges[s0], edges[k]))
        else:
            k += 1
    swaps = int(np.sum(isB[1:] != isB[:-1]))
    return bands, n, swaps


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

def mesh_arrays(m):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties[:, :3], dtype=np.float32)
    f = np.asarray(mesh.tri_verts, dtype=np.uint32)
    return v, f


def write_stl(path, m, name):
    v, f = mesh_arrays(m)
    tri = v[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.where(ln == 0, 1, ln)
    rec = np.zeros(len(f), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"] = n
    rec["v"] = tri
    with open(path, "wb") as fh:
        hdr = name.encode("ascii", "replace")[:80]
        fh.write(hdr + b" " * (80 - len(hdr)))
        fh.write(struct.pack("<I", len(f)))
        fh.write(rec.tobytes())
    return len(f)


def write_preview(path, m):
    v, f = mesh_arrays(m)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<II", len(v), len(f)))
        fh.write(v.astype("<f4").tobytes())
        fh.write(f.astype("<u4").tobytes())


def main():
    ap = argparse.ArgumentParser(description="Kölner Dom · DURCHBLICK – Generator")
    ap.add_argument("--height", type=float, default=200.0, help="Turmhöhe in mm ohne Sockel (Standard 200)")
    ap.add_argument("--fin", type=float, default=1.6, help="Lamellenstärke in mm (Standard 1.6)")
    ap.add_argument("--frame", type=float, default=1.2, help="Mindeststeg um Fenster in mm (Standard 1.2)")
    ap.add_argument("--layer", type=float, default=0.16, help="Schichthöhe in mm (Standard 0.16)")
    ap.add_argument("--first-layer", type=float, default=0.2, help="Erste Schicht in mm (Standard 0.2)")
    ap.add_argument("--plinth-layers", type=int, default=18, help="Sockelhöhe in Schichten nach der ersten")
    ap.add_argument("--inlay-layers", type=int, default=4, help="Tiefe der Inschrift in Schichten")
    ap.add_argument("--text", default="1248 · 1880", help="Inschrift auf der Domplatte ('' = keine)")
    ap.add_argument("--grad-start", type=float, default=0.36, help="Beginn des Verlaufs (Anteil der Höhe)")
    ap.add_argument("--grad-end", type=float, default=0.84, help="Ende des Verlaufs (Anteil der Höhe)")
    ap.add_argument("--run", type=int, default=2, help="Lagen pro Goldlinie im Verlauf (1 = Lage für Lage)")
    ap.add_argument("--gamma", type=float, default=1.0, help="Kurve des Verlaufs")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
    ap.add_argument("--suffix", default="", help="Zusatz für Dateinamen")
    args = ap.parse_args()

    r = build(args)
    os.makedirs(os.path.join(args.out, "preview"), exist_ok=True)
    sfx = args.suffix
    n1 = write_stl(os.path.join(args.out, f"dom_durchblick_einfarbig{sfx}.stl"), r["solid"], "Koelner Dom DURCHBLICK")
    na = write_stl(os.path.join(args.out, f"dom_durchblick_A{sfx}.stl"), r["a"], "Koelner Dom DURCHBLICK Filament A")
    nb = write_stl(os.path.join(args.out, f"dom_durchblick_B{sfx}.stl"), r["b"], "Koelner Dom DURCHBLICK Filament B")
    write_preview(os.path.join(args.out, "preview", f"dom{sfx}.bin"), r["body"])
    write_preview(os.path.join(args.out, "preview", f"text{sfx}.bin"), r["text"])
    parts = r["solid"].decompose()
    print("zusammenhängende Teile:", len(parts))
    bb = r["solid"].bounding_box()
    meta = dict(
        bbox_mm=[round(x, 2) for x in bb],
        plinth_mm=round(r["plinth_mm"], 3),
        layer=args.layer, first_layer=args.first_layer,
        run=args.run, grad_start=args.grad_start, grad_end=args.grad_end, gamma=args.gamma,
        bands=[[round(a, 3), round(b, 3)] for a, b in r["bands"]],
        n_layers=r["n_layers"], swaps=r["swaps"],
        volume_cm3=round(r["solid"].volume() / 1000, 1),
        volume_a_cm3=round(r["a"].volume() / 1000, 1),
        volume_b_cm3=round(r["b"].volume() / 1000, 1),
        triangles=dict(einfarbig=n1, A=na, B=nb),
        plates=r["n_plates"],
    )
    with open(os.path.join(args.out, "preview", f"meta{sfx}.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    print(json.dumps({k: v for k, v in meta.items() if k != "bands"}, indent=1))


if __name__ == "__main__":
    main()
