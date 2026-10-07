#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kölner Dom · ZEITSCHICHTEN
==========================

Der Dom, wie er rund 300 Jahre lang (1560-1842) dastand - massiv, in Stein -,
und darüber, als goldenes Gitter, das, was erst 1842-1880 vollendet wurde.

  Stein  (Farbe A): Chor in voller Höhe, niedriges Lang- und Querhaus,
                    Südturm-Stumpf mit dem Domkran, Nordturm-Stummel, Domplatte.
  Gitter (Farbe B): Nordturm, oberer Südturm, Helme, Mittelschiff, Querhaus,
                    Vierungsturm - als selbsttragendes Rauten-Gitter (Streben >= 60°).

Ausgabe: out/zeitschichten_A.stl, out/zeitschichten_B.stl, out/zeitschichten_einfarbig.stl,
         out/preview/*, out/info.json
"""
import json
import math
import os
import struct
import sys

KIT = '/tmp/claude-0/-home-user-taste-skill/d46f1633-345d-5b87-803e-a453b1fd4c0a/scratchpad/kit'
sys.path.insert(0, KIT)
from proto_kit import *  # noqa: E402,F401,F403
import numpy as np  # noqa: E402
from manifold3d import CrossSection, FillRule, JoinType, Manifold, OpType  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- Maßstab
HMM = 200.0                 # Turmspitze über Domplatte (mm)
S = HMM / dd.H_REAL         # mm pro Meter (1.27)
T = 1.4 / S                 # Schalenstärke Gitter (m)
SW = 1.3 / S                # Strebenbreite (m)
WC = 2.2 / S                # Eckpfeiler (m)
WC2 = 2.7 / S               # Eckpfeiler Glockengeschoss (trägt die großen Fialen)
MB = 1.3 / S                # Gesims-Rand unten/oben (m)
CELL = 7.2 / S              # Ziel-Rautenbreite (m)
ASPECT = 2.4                # Rauten: Höhe / Breite  (Strebe ca. 64° steil)
XT, YT = dd.XT, dd.YT

Z_STUMP_S = 59.0            # Südturm-Stumpf (Kran obendrauf)
Z_STUMP_N = 8.0             # Nordturm-Stummel
Z_NAVE = 22.0               # Lang-/Querhaus-Stumpf
Y_CHOIR = 92.0              # ab hier: vollendeter Chor (1322)
SQ2 = math.sqrt(2.0)
BIG = 1e3


def U(ms):
    ms = [m for m in ms if m is not None and not m.is_empty()]
    return Manifold.batch_boolean(ms, OpType.Add) if ms else Manifold()


def U2(cs):
    cs = [c for c in cs if c is not None and not c.is_empty()]
    return CrossSection.batch_boolean(cs, OpType.Add) if cs else CrossSection()


def box(x0, x1, y0, y1, z0, z1):
    return dd.box(x0, x1, y0, y1, z0, z1)


# ---------------------------------------------------------------- Loft (Turm-Schalen)
def octo_pts(a, b):
    a = max(a, 0.02)
    sq = CrossSection.square((2 * a, 2 * a), center=True)
    if b < SQ2 * a - 1e-6:
        b = max(b, 0.02)
        sq = sq ^ CrossSection.square((2 * b, 2 * b), center=True).rotate(45)
    return np.asarray(sq.to_polygons()[0])


def loft(cx, cy, keys):
    parts = []
    for (z0, a0, b0), (z1, a1, b1) in zip(keys[:-1], keys[1:]):
        if z1 - z0 < 1e-6:
            continue
        p0, p1 = octo_pts(a0, b0), octo_pts(a1, b1)
        pts = np.vstack([np.c_[p0, np.full(len(p0), z0)], np.c_[p1, np.full(len(p1), z1)]])
        parts.append(Manifold.hull_points(pts))
    return U(parts).translate((cx, cy, 0))


def sqk(z, a):
    return (z, a, BIG)


def okk(z, a):
    return (z, a, a)


# ---------------------------------------------------------------- Gitter-Generator
def frame(phi):
    """Rahmen einer senkrechten Fläche: Tangente t, Normale n (horizontal)."""
    p = math.radians(phi)
    n = np.array([math.cos(p), math.sin(p), 0.0])
    t = np.array([-math.sin(p), math.cos(p), 0.0])
    return t, n


def cutter(polys, c, phi, r0, r1):
    """2D-Öffnung (u, z) als Prisma entlang der Flächennormale, Abstand r0..r1 vom Punkt c."""
    t, n = frame(phi)
    cs = CrossSection(polys, FillRule.Positive) if not isinstance(polys, CrossSection) else polys
    if cs.is_empty():
        return Manifold()
    m = Manifold.extrude(cs, r1 - r0)
    c = np.asarray(c, dtype=float) + r0 * n
    M = np.array([[t[0], 0, n[0], c[0]], [t[1], 0, n[1], c[1]], [t[2], 1, n[2], c[2]]], dtype=float)
    return m.transform(M)


def top_ok(poly, tol=0.93):
    """Oberkanten der Öffnung (Material darüber) müssen >= ~43° steil sein."""
    p = np.asarray(poly)
    # CCW sicherstellen
    ar = 0.5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])
    if ar < 0:
        p = p[::-1]
    q = np.roll(p, -1, axis=0)
    d = q - p
    for (dx, dz) in d:
        if dx < -1e-9:  # Oberkante (Inneres liegt darunter)
            if math.hypot(dx, dz) > 0.12 and abs(dz) < tol * abs(dx):
                return False
    return True


def lattice(region, z0, z1, u0, u1, N, aspect=ASPECT, s=SW, min_w=2.0 / S, densify=6):
    """Rautengitter-Öffnungen in einer (u, z)-Fläche.
    u0, u1: (Wert bei z0, Wert bei z1) -> lineare Ränder (für sich verjüngende Helmflächen).
    region: CrossSection, in die die Öffnungen geschnitten werden (bereits mit Rändern).
    Rückgabe: Liste von (CrossSection, zlo, zhi)."""
    he0 = (u1[0] - u0[0]) / 2
    he1 = (u1[1] - u0[1]) / 2
    uc0 = (u1[0] + u0[0]) / 2
    uc1 = (u1[1] + u0[1]) / 2
    if he0 <= 0:
        return []
    k = (he1 - he0) / (z1 - z0)

    def he(z):
        return he0 + k * (z - z0)

    def uc(z):
        return uc0 + (uc1 - uc0) * (z - z0) / (z1 - z0)

    def zeta(z):
        return (z - z0) / he0 if abs(k) < 1e-9 else math.log(max(he(z), 1e-6) / he0) / k

    def zinv(zt):
        return z0 + he0 * zt if abs(k) < 1e-9 else z0 + (he0 * math.exp(k * zt) - he0) / k

    Wn = 2.0 / N
    Hn = aspect * Wn
    zt_top = zeta(z1)
    nh = max(2, int(round(zt_top / (Hn / 2))))
    Hn = 2 * zt_top / nh
    out = []
    for j in range(nh + 1):
        zc = j * Hn / 2
        for i in range(N + 1):
            uc_n = -1 + (2 * i + (j % 2)) / N
            if uc_n > 1 + 1e-9:
                continue
            corners = [(uc_n - 1 / N, zc), (uc_n, zc - Hn / 2), (uc_n + 1 / N, zc), (uc_n, zc + Hn / 2)]
            pts = []
            for a, b in zip(corners, corners[1:] + corners[:1]):
                for f in np.linspace(0, 1, densify, endpoint=False):
                    pts.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            P = []
            for (un, zn) in pts:
                z = zinv(zn)
                P.append((uc(z) + un * he(z), z))
            cell = CrossSection([np.array(P)], FillRule.Positive)
            full = cell.offset(-s / 2, JoinType.Miter, 2.0)
            if full.is_empty():
                continue
            fa = full.area()
            b = full.bounds()
            if (b[2] - b[0]) < min_w:
                continue
            o = full ^ region
            if o.is_empty() or o.area() < 0.3 * fa:
                continue
            polys = o.to_polygons()
            if not all(top_ok(p) for p in polys):
                continue
            ob = o.bounds()
            out.append((o, ob[1], ob[3]))
    return out


def rect2(u0, u1, z0, z1):
    return dd.rect(u0, u1, z0, z1)


def trap2(z0, z1, u0, u1):
    return dd.poly([(u0[0], z0), (u1[0], z0), (u1[1], z1), (u0[1], z1)])


# ---------------------------------------------------------------- Türme
def tower_keys(z_start, inner=False):
    d = T if inner else 0.0
    zs = z_start - (1.0 if inner else 0.0)
    if z_start < 33:
        ks = [sqk(zs, 11.5 - d), sqk(33, 11.5 - d), sqk(33.7, 10.9 - d)]
    else:
        ks = [sqk(zs, 10.9 - d)]
    ks += [sqk(63, 10.9 - d), sqk(64.6, 9.4 - d), sqk(95, 9.4 - d),
           okk(101, 7.8 - d), okk(111, 7.8 - d), okk(111.7, 7.2 - d)]
    ks += [okk(145.0, spire_a(145.0) - d), okk(146.6, 0.05)] if inner else [okk(147, 2.0)]
    return ks


def spire_a(z):
    return 7.2 + (2.0 - 7.2) * (z - 111.7) / (147 - 111.7)


def pinnacle(cx, cy, w, z0, z1, z2):
    return dd.pinnacle(cx, cy, w, z0, z1, z2)


def finial(cx, cy, z0=147.0):
    return loft(cx, cy, [okk(z0 - 0.7, 1.25), okk(149.4, 1.25), okk(150.7, 2.25), okk(153.8, 0.5), okk(dd.H_REAL, 0.02)])


def tower_ghost(sx):
    """Gitter-Turm. sx=-1 Nord (ab Stummel), sx=+1 Süd (ab Stumpf, mit Kran-Bogen)."""
    cx, cy = sx * XT, YT
    zst = Z_STUMP_N if sx < 0 else Z_STUMP_S
    outer = loft(cx, cy, tower_keys(zst))
    inner = loft(cx, cy, tower_keys(zst, inner=True))
    solid = []
    cuts = []
    c = (cx, cy, 0.0)

    def sq_faces(a, z0, z1, phis, arch=None, Nfix=None, wc=WC):
        for phi in phis:
            u0, u1 = -a + wc, a - wc
            reg = rect2(u0, u1, z0, z1)
            arch_cs = None
            if arch is not None:
                zb, zsp_apex = arch
                arch_cs = dd.lancet(0.0, u1, zb, zsp_apex, k=1.0)
                reg = reg - arch_cs.offset(SW, JoinType.Miter, 2.0)
            N = Nfix or max(1, int(round((u1 - u0) / CELL)))
            for (o, zl, zh) in lattice(reg, z0, z1, (u0, u0), (u1, u1), N):
                cuts.append(cutter(o, c, phi, a - T - 0.3, a + 0.3))
            if arch_cs is not None:
                cuts.append(cutter(arch_cs, c, phi, a - T - 0.3, a + 0.3))

    # Fassadenseiten, die an das Mittelschiff grenzen, bleiben unten geschlossen
    inner_phi = 0 if sx < 0 else 180
    all4 = [0, 90, 180, 270]
    outer3 = [p for p in all4 if p != inner_phi]
    if sx < 0:
        sq_faces(11.5, zst + MB, 33 - MB, outer3)
        sq_faces(10.9, 33.7 + MB, 63 - MB, outer3)
    # L2: großer Spitzbogen (Kranfenster) + Gitter darüber
    sq_faces(9.4, 64.6 + MB, 95 - MB, all4, arch=(64.6 + MB, 86.0), wc=WC2)
    # Eckpfeiler (massiv, tragen die Fialen), Übergänge mit 45°-Schrägen
    secs = ([(zst, 33, 11.5, WC), (33.7, 63, 10.9, WC)] if sx < 0 else [(zst, 63, 10.9, WC)]) + [(64.6, 95, 9.4, WC2)]
    for su in (-1, 1):
        for sv in (-1, 1):
            def cb(a, z0, z1, w):
                x0, x1 = (cx + a - w, cx + a) if su > 0 else (cx - a, cx - a + w)
                y0, y1 = (cy + a - w, cy + a) if sv > 0 else (cy - a, cy - a + w)
                return box(x0, x1, y0, y1, z0, z1)
            for i, (z0, z1, a, w) in enumerate(secs):
                solid.append(cb(a, z0, z1, w))
                if i + 1 < len(secs):
                    n_ = secs[i + 1]
                    dz = max(n_[0] - z1, 1.08 * ((a - w) - (n_[2] - n_[3])))
                    solid.append(Manifold.batch_hull([cb(a, z1 - 0.05, z1, w), cb(n_[2], z1 + dz, z1 + dz + 0.05, n_[3])]))
    # Oktogon: je Seite eine Lanzette
    a3 = 7.8
    hw3 = (SQ2 - 1) * a3
    for k in range(8):
        phi = 45 * k
        lan = dd.lancet(0, hw3 - 0.9 / S * 1.0 - SW / 2, 101 + MB, 111 - MB, k=1.6)
        cuts.append(cutter(lan, c, phi, a3 - T - 0.3, a3 + 0.3))
    # Helm: sich verjüngendes Rautengitter auf 8 Flächen
    z0h, z1h = 111.7 + MB, 141.0
    for k in range(8):
        phi = 45 * k
        hwz0 = (SQ2 - 1) * spire_a(z0h) - 0.85 / S
        hwz1 = (SQ2 - 1) * spire_a(z1h) - 0.85 / S
        reg = trap2(z0h, z1h, (-hwz0, -hwz1), (hwz0, hwz1))
        for (o, zl, zh) in lattice(reg, z0h, z1h, (-hwz0, -hwz1), (hwz0, hwz1), 1, aspect=2.3, min_w=1.4 / S):
            cuts.append(cutter(o, c, phi, spire_a(zh) - T - 0.4, spire_a(zl) + 0.4))
    # Fialen-Kranz
    for su in (-1, 1):
        for sv in (-1, 1):
            solid.append(pinnacle(cx + su * (10.9 - WC / 2), cy + sv * (10.9 - WC / 2), WC, 63, 71, 82))
            solid.append(pinnacle(cx + su * (9.4 - WC2 / 2), cy + sv * (9.4 - WC2 / 2), WC2, 95, 105.0, 119.0))
    # Wimperge (Giebel) über dem Kranfenster-Geschoss
    for phi in all4:
        hw = 9.4 - WC2
        g = dd.poly([(-hw, 95 - 0.2), (hw, 95 - 0.2), (0, 95 + hw * 1.75)])
        gi = dd.lancet(0, 1.35, 96.6, 95 + hw * 1.75 - 3.4, k=1.5)
        for su in (-1, 1):
            gi = gi + dd.lancet(su * 3.35, 0.75, 96.6, 99.6, k=1.2)
        solid.append(cutter(g - gi, c, phi, 9.4 - T, 9.4))
    solid.append(finial(cx, cy))
    shell = outer - inner
    return shell, U(solid), U(cuts)


# ---------------------------------------------------------------- Mittelschiff / Querhaus / Vierung
NH = 8.3
Z_EAVE, Z_RIDGE = 45.0, 61.1
ROOF_K = (Z_RIDGE - Z_EAVE) / NH


def vessel_profile(h, z0, hr=NH):
    return dd.rect(-h, h, z0, Z_EAVE) + dd.poly([(-hr, Z_EAVE), (hr, Z_EAVE), (0, Z_EAVE + hr * ROOF_K)])


def x_roof(z):
    return (Z_RIDGE - z) / ROOF_K


def vessel_ghost():
    # Profil in (x, z), Längsrichtung y
    prof_f = vessel_profile(8.6, Z_STUMP_N)          # Fassadenbereich (überlappt Türme)
    prof_n = vessel_profile(NH, Z_NAVE - 1)
    inner_p = vessel_profile(NH, Z_STUMP_N - 1).offset(-T, JoinType.Miter, 2.0)
    outer = U([dd.extrude_y(prof_f, 0.0, 23.0), dd.extrude_y(prof_n, 22.5, Y_CHOIR)])
    inner = dd.extrude_y(inner_p, T, Y_CHOIR + 2) + Manifold.batch_hull([box(0, 7.8, T, 23.0, Z_STUMP_N + 0.1, 43.6),
                                                                         box(0, 7.0, T, 23.0, Z_STUMP_N + 0.1, 44.5)])
    # Querhaus: Profil in (y-76.5, z), Längsrichtung x
    tr_o = dd.extrude_y(vessel_profile(NH, Z_NAVE - 1), -43.1, 43.1).rotate((0, 0, -90)).translate((0, dd.Y_CROSS, 0))
    tr_i = dd.extrude_y(vessel_profile(NH, Z_NAVE - 2).offset(-T, JoinType.Miter, 2.0), -43.1 + T, 43.1 - T)
    tr_i = tr_i.rotate((0, 0, -90)).translate((0, dd.Y_CROSS, 0))
    # Vierungsturm
    vk_o = [okk(45, 4.3), okk(72, 4.3), okk(105, 0.75)]
    vk_i = [okk(44, 4.3 - T), okk(72, 4.3 - T), okk(101.5, 0.12)]
    v_o = loft(0, dd.Y_CROSS, vk_o) + dd.oct_prism(0, dd.Y_CROSS, 0.75, 104.9, 109.0, a_top=0.0)
    v_i = loft(0, dd.Y_CROSS, vk_i)
    shell = U([outer, tr_o, v_o]) - U([inner, tr_i, v_i])

    cuts, solid = [], []
    N_ = lambda w: max(1, int(round(w / CELL)))  # noqa: E731
    # Langhaus-Wände x = ±8.3 (u = y bzw. -y)
    y0, y1 = 23.0 + 1.2, 68.2 - 1.2
    zb, zt = Z_NAVE + Z_LEAN + MB, Z_EAVE - MB
    for phi, sgn in ((0, 1), (180, -1)):
        u0, u1 = (y0, y1) if sgn > 0 else (-y1, -y0)
        reg = rect2(u0, u1, zb, zt)
        for (o, zl, zh) in lattice(reg, zb, zt, (u0, u0), (u1, u1), N_(u1 - u0)):
            cuts.append(cutter(o, (0, 0, 0), phi, NH - T - 0.3, NH + 0.3))
        # Dach (projiziert auf (u, z))
        rb, rt = Z_EAVE + MB * 1.2, Z_RIDGE - MB * 1.6
        u0r, u1r = (1.2, y1) if sgn > 0 else (-y1, -1.2)
        reg = rect2(u0r, u1r, rb, rt)
        for (o, zl, zh) in lattice(reg, rb, rt, (u0r, u0r), (u1r, u1r), N_(u1r - u0r), aspect=1.9):
            cuts.append(cutter(o, (0, 0, 0), phi, max(0.05, x_roof(zh) - 1.25 * T - 0.25), x_roof(zl) + 0.3))
    # Querhaus-Wände y = 76.5 ± 8.3 (u entlang x)
    if True:
        xa, xb = 8.3 + 1.6, 43.1 - 1.2
        ranges = [(xa, xb), (-xb, -xa)]
        for phi in (90, 270):
            for (ua, ub) in ranges:
                # bei phi=90: t = (-1, 0) -> u = -x ; phi=270: t = (1, 0) -> u = x
                u0, u1 = (-ub, -ua) if phi == 90 else (ua, ub)
                reg = rect2(u0, u1, zb, zt)
                c = (0, dd.Y_CROSS, 0)
                for (o, zl, zh) in lattice(reg, zb, zt, (u0, u0), (u1, u1), N_(u1 - u0)):
                    cuts.append(cutter(o, c, phi, NH - T - 0.3, NH + 0.3))
                rb, rt = Z_EAVE + MB * 1.2, Z_RIDGE - MB * 1.6
                reg = rect2(u0, u1, rb, rt)
                for (o, zl, zh) in lattice(reg, rb, rt, (u0, u0), (u1, u1), N_(u1 - u0), aspect=1.9):
                    cuts.append(cutter(o, c, phi, max(0.05, x_roof(zh) - 1.25 * T - 0.25), x_roof(zl) + 0.3))
    # Querhaus-Giebel x = ±43.1 (u entlang y)
    for phi in (0, 180):
        c = (0, dd.Y_CROSS, 0)
        tw = [dd.lancet(-3.4, 2.9, Z_NAVE + 2.2, 41.5, k=2.0), dd.lancet(3.4, 2.9, Z_NAVE + 2.2, 41.5, k=2.0),
              dd.poly([(0, 43.0), (2.6, 47.5), (0, 52.0), (-2.6, 47.5)]), dd.lancet(0, 1.1, 53.5, 58.2, k=1.5)]
        for w in tw:
            cuts.append(cutter(w, c, phi, 43.1 - T - 0.3, 43.1 + 0.3))
    # Westgiebel y = 0 zwischen den Türmen (Normale -y)
    hw = 7.75 - 1.2
    # Westfenster: zwei Lanzetten, Raute, kleine Giebel-Lanzette (Maßwerk statt Raster)
    west = [dd.lancet(-3.1, 2.6, Z_STUMP_N + MB + 1.0, 41.0, k=2.0), dd.lancet(3.1, 2.6, Z_STUMP_N + MB + 1.0, 41.0, k=2.0),
            dd.poly([(0, 42.6), (2.5, 46.9), (0, 51.2), (-2.5, 46.9)]), dd.lancet(0, 1.1, 53.0, 58.0, k=1.5)]
    for w in west:
        cuts.append(cutter(w, (0, 0, 0), 270, -T - 0.3, 0.3))
    # Vierungsturm: Lanzetten
    hwv = (SQ2 - 1) * 4.3
    for k in range(8):
        lan = dd.lancet(0, hwv - 0.75 / S, 58.0, 70.5, k=1.6)
        cuts.append(cutter(lan, (0, dd.Y_CROSS, 0), 45 * k, 4.3 - T - 0.3, 4.3 + 0.3))
    # Querhaus-Fialen
    for sx in (-1, 1):
        for yy in (65.54, 87.19):
            solid.append(pinnacle(sx * 41.6, yy, 3.0, Z_NAVE + 3.6, 60, 74))
    return shell, U(solid), U(cuts)


# ---------------------------------------------------------------- Stein (Mittelalter)
Y_FINS_CHOIR = [92.54, 97.88, 103.22, 108.56, dd.Y_APSE]
Y_FINS_NAVE = [27.18, 32.66, 38.14, 43.62, 49.1, 54.58, 60.06]
REC = 0.75 / S              # Tiefe der Blendfenster im Stein (m)
Z_LEAN = 5.5                # Pultdach der Seitenschiffe (Höhe über Stumpf)


def fin_profile():
    """Strebewerk eines Jochs (u = x >= 8.3, z): Strebepfeiler, Fialen, zwei Strebebögen."""
    full = dd.nave_half(True) ^ dd.rect(8.3, 40, -1, 100)
    holes = dd.lancet(20.5, 2.2, 26.0, 34.4, k=1.5) + dd.lancet(11.35, 1.6, 29.6, 39.3, k=1.5)
    return full - holes


def recess(cs, c, phi, r):
    """Blendfenster: 2D-Lanzette (u, z) REC tief in die Wand bei Abstand r."""
    return cutter(cs, c, phi, r - REC, r + 0.5)


def stone():
    parts, cuts = [], []
    core = dd.nave_half(False)                       # Mittelschiff + Seitenschiff + Pultdach
    fin = fin_profile()
    # ---- Chor (1248-1322) in voller Höhe
    parts.append(dd.extrude_y(dd.sym(core), Y_CHOIR, dd.Y_APSE + 0.3))
    parts.append(Manifold.revolve(core, 10, 180).translate((0, dd.Y_APSE, 0)))
    for y in Y_FINS_CHOIR:
        parts.append(dd.extrude_y(dd.sym(fin), y - 1.0, y + 1.0))
    for k in range(1, 10):
        al = 18 * k
        parts.append(dd.plate(fin, (0, dd.Y_APSE), al + 90, 2.0))
    # Blendfenster Chor
    for y0, y1 in zip(Y_FINS_CHOIR[:-1], Y_FINS_CHOIR[1:]):
        yc = 0.5 * (y0 + y1)
        for phi, sg in ((0, 1), (180, -1)):
            cuts.append(recess(dd.lancet(sg * yc, 1.25, 30.0, 43.0, k=1.5), (0, 0, 0), phi, 8.3))
            cuts.append(recess(dd.lancet(sg * yc, 1.25, 3.5, 19.0, k=1.5), (0, 0, 0), phi, 23.6))
    for k in range(10):
        al = 9 + 18 * k
        ap_c = 8.3 * math.cos(math.radians(9))
        ap_a = 23.6 * math.cos(math.radians(9))
        cuts.append(recess(dd.lancet(0, 0.72, 30.0, 42.0, k=1.5), (0, dd.Y_APSE, 0), al, ap_c))
        cuts.append(recess(dd.lancet(0, 1.6, 3.5, 19.0, k=1.5), (0, dd.Y_APSE, 0), al, ap_a))
    # ---- Langhaus-Stumpf (Seitenschiffe mit Notdach) bis Z_NAVE
    lo = dd.sym(core ^ dd.rect(-1, 100, -1, Z_NAVE)) + dd.sym(dd.poly([(8.3, Z_NAVE), (23.6, Z_NAVE), (8.3, Z_NAVE + Z_LEAN)]))
    parts.append(dd.extrude_y(lo, 23.0, Y_CHOIR + 0.01))
    pier = dd.sym(dd.union2d([dd.rect(23.0, 30.7, 0, 14), dd.rect(23.0, 29.7, 14, Z_NAVE - 1.5),
                              dd.poly([(23.0, Z_NAVE - 1.5), (29.7, Z_NAVE - 1.5), (26.35, Z_NAVE + 4.5)])]))
    for y in Y_FINS_NAVE:
        parts.append(dd.extrude_y(pier, y - 1.0, y + 1.0))
    for y0, y1 in zip([23.0] + Y_FINS_NAVE[:-1], Y_FINS_NAVE):
        yc = 0.5 * (y0 + y1)
        for phi, sg in ((0, 1), (180, -1)):
            cuts.append(recess(dd.lancet(sg * yc, 1.25, 3.5, 18.0, k=1.5), (0, 0, 0), phi, 23.6))
    # ---- Querhaus-Stumpf
    tr = dd.sym(dd.transept_half() ^ dd.rect(-1, 100, -1, Z_NAVE))
    trm = dd.extrude_y(tr, -43.1, 43.1).rotate((0, 0, -90)).translate((0, dd.Y_CROSS, 0))
    parts.append(trm)
    for sx in (-1, 1):
        for yy in (65.54, 87.19):
            parts.append(box(sx * 41.6 - 1.5, sx * 41.6 + 1.5, yy - 1.5, yy + 1.5, 0, Z_NAVE + 3.6))
        for phi in ((0,) if sx > 0 else (180,)):
            cuts.append(recess(dd.lancet(0, 3.0, 0.0, 19.0, k=1.5), (0, dd.Y_CROSS, 0), phi, 43.1))
    for sx in (-1, 1):
        for xc in (32.9, 38.4):
            for phi in (90, 270):
                u = -sx * xc if phi == 90 else sx * xc
                cuts.append(recess(dd.lancet(u, 1.6, 3.5, 18.0, k=1.5), (0, dd.Y_CROSS, 0), phi, 15.5))
    # ---- Westbau: Mittelteil + Nordturm-Stummel + Südturm-Stumpf
    M = dd.massing()
    parts.append(M ^ box(-60, 7.75, -1, 23.01, -1, Z_STUMP_N))
    parts.append(dd.tower(1) ^ box(-60, 60, -1, 60, -1, Z_STUMP_S))
    xc, yc = XT, YT
    cS = (xc, yc, 0)
    # Westportal + Südportale (Blend), Fenster im 2. Geschoss
    cuts.append(recess(dd.lancet(0, 3.4, 0.0, 24.0, k=2.0), cS, 270, 11.5))
    for su in (-1, 1):
        cuts.append(recess(dd.lancet(su * 5.0, 3.0, 0.0, 24.0, k=2.0), cS, 0, 11.5))
        for phi in (0, 270, 90):
            cuts.append(recess(dd.lancet(su * 4.4, 2.7, 36.0, 56.8, k=2.0), cS, phi, 10.9))
    body = U(parts)
    return body - U(cuts)


def crane():
    """Stilisierter Domkran auf dem Südturm-Stumpf (x>0 = Süden)."""
    cx, cy, z0 = XT, YT, Z_STUMP_S
    parts = []
    # Kranhaus mit steilem Satteldach
    hx0, hx1, hy = cx - 6.0, cx + 0.5, 3.4
    parts.append(box(hx0, hx1, cy - hy, cy + hy, z0 - 0.5, z0 + 6.5))
    roof = Manifold.hull_points(np.array([[hx0, cy - hy, z0 + 6.5], [hx1, cy - hy, z0 + 6.5], [hx0, cy + hy, z0 + 6.5],
                                          [hx1, cy + hy, z0 + 6.5], [hx0, cy, z0 + 11.0], [hx1, cy, z0 + 11.0]]))
    parts.append(roof)

    def strut(p, q, w):
        p, q = np.asarray(p, float), np.asarray(q, float)
        h = w / 2
        pts = []
        for P in (p, q):
            for dx in (-h, h):
                for dy in (-h, h):
                    pts.append([P[0] + dx, P[1] + dy, P[2] - h])
                    pts.append([P[0] + dx, P[1] + dy, P[2] + h])
        return Manifold.hull_points(np.array(pts))

    mx = cx - 2.0
    parts.append(box(mx - 0.9, mx + 0.9, cy - 0.9, cy + 0.9, z0, z0 + 30.0))       # Mast
    ang = math.radians(48)
    p0 = np.array([mx, cy, z0 + 7.5])
    L = 24.0
    d = np.array([math.cos(ang), 0, math.sin(ang)])
    tip = p0 + L * d
    parts.append(strut(p0, tip, 1.8))                                                # Ausleger
    parts.append(strut((mx, cy, z0 + 30.0), p0 + 0.45 * L * d, 1.25))                # Abspannung
    return U(parts), tip


# ---------------------------------------------------------------- Domplatte + Inschrift
def plinth(foot_m, S, h_mm=4.0):
    foot = foot_m.scale((S, S))
    foot = foot.offset(10.0, JoinType.Round).offset(-7.5, JoinType.Round)
    plaza = dd.rect(-36 * S, 36 * S, -17 * S, 5 * S)
    foot = (foot + plaza).offset(1.5, JoinType.Round).offset(-1.5, JoinType.Round)
    base = Manifold.extrude(foot, h_mm - 0.48)
    for i in range(3):
        base = base + Manifold.extrude(foot.offset(-(i + 1) * 0.35, JoinType.Round), 0.16).translate((0, 0, h_mm - 0.48 + i * 0.16))
    return base


def text_cs(txt, h_mm):
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    tp = TextPath((0, 0), txt, size=10, prop=FontProperties(family="DejaVu Serif"))
    polys = [np.asarray(p) for p in tp.to_polygons() if len(p) >= 3]
    cs = CrossSection(polys, FillRule.EvenOdd)
    x0, y0, x1, y1 = cs.bounds()
    sc = h_mm / (y1 - y0)
    return cs.translate((-(x0 + x1) / 2, -(y0 + y1) / 2)).scale((sc, sc))


# ---------------------------------------------------------------- Export
def write_stl(path, m, name):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties[:, :3], dtype=np.float32)
    f = np.asarray(mesh.tri_verts, dtype=np.uint32)
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


def swap_layers(A, B, zmax, layer=0.16, first=0.2):
    z = first
    edges = [0.0, first]
    while edges[-1] < zmax:
        edges.append(edges[-1] + layer)
    both = 0
    for z0, z1 in zip(edges[:-1], edges[1:]):
        zc = 0.5 * (z0 + z1)
        a = A.slice(zc).area()
        b = B.slice(zc).area()
        if a > 1e-3 and b > 1e-3:
            both += 1
    return both, len(edges) - 1


def build():
    st = stone()
    cr, tip = crane()
    gN, sN, cN = tower_ghost(-1)
    gS, sS, cS = tower_ghost(1)
    gV, sV, cV = vessel_ghost()
    shell = U([gN, gS, gV])
    cuts = U([cN, cS, cV])
    ghost = (shell - cuts) + U([sN, sS, sV])
    A_m = st + cr
    ghost = ghost - A_m
    foot = CrossSection((A_m + ghost).project().to_polygons(), FillRule.Positive)
    h_pl = 4.0
    base = plinth(foot, S, h_pl)
    A = A_m.scale((S, S, S)).translate((0, 0, h_pl)) + base
    B = ghost.scale((S, S, S)).translate((0, 0, h_pl))
    # Inschrift: Jahreszahlen in Gold, eingelegt
    txt = text_cs("1248 · 1560   |   1842 · 1880", 4.0).translate((0, -10.5 * S))
    inlay = Manifold.extrude(txt, 0.64).translate((0, 0, h_pl - 0.64))
    A = clean(A - inlay)
    B = clean(B + inlay)
    return A, B


def clean(m, vmin=0.5):
    ps = [p for p in m.decompose() if p.volume() > vmin]
    return U(ps)


if __name__ == "__main__":
    import time
    t0 = time.time()
    A, B = build()
    print("build", round(time.time() - t0, 1), "s")
    out = os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    whole = A + B
    info = dict(gesamt=check(whole), A=check(A), B=check(B))
    nb, nl = swap_layers(A, B, whole.bounding_box()[5])
    info["lagen_beide_farben"] = nb
    info["lagen_gesamt"] = nl
    print(json.dumps(info, indent=1))
    write_stl(os.path.join(out, "zeitschichten_A.stl"), A, "Koelner Dom ZEITSCHICHTEN A Stein")
    write_stl(os.path.join(out, "zeitschichten_B.stl"), B, "Koelner Dom ZEITSCHICHTEN B Gold")
    write_stl(os.path.join(out, "zeitschichten_einfarbig.stl"), whole, "Koelner Dom ZEITSCHICHTEN")
    with open(os.path.join(out, "info.json"), "w") as fh:
        json.dump(info, fh, indent=1)
    write_preview(HERE, A, B)
    print("total", round(time.time() - t0, 1), "s")
