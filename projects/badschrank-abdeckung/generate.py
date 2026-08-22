#!/usr/bin/env python3
"""
Parametrischer Generator fuer die Abdeckung der Siphon-Aussparung
im Badezimmer-Unterschrank (Einlegeboden mit U-foermigem Ausschnitt).

Alle Masse in Millimetern.

Koordinatensystem (Bauteil in Einbaulage):
    x = quer zur Aussparung (0 = Mitte)
    y = 0 an der Hinterkante des Bodens, +y nach vorne
    z = 0 = Oberflaeche des Einlegebodens, +z nach oben

Exportiert wird in Druckorientierung: sichtbare Deckflaeche liegt auf
dem Druckbett (z=0), Fuehrungsschuerze und Rippen zeigen nach oben.
Dadurch wird die Sichtseite glatt und es sind keine Stuetzen noetig.

Aufruf:
    python3 generate.py                       # Standardmasse
    python3 generate.py --width 74 --depth 216
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass

import numpy as np
import trimesh
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

# --------------------------------------------------------------------------
# Parameter
# --------------------------------------------------------------------------


@dataclass
class Params:
    # --- gemessene Masse der Aussparung -----------------------------------
    notch_width: float = 75.0      # Breite der Aussparung
    notch_depth: float = 218.0     # Hinterkante Boden bis Scheitel der Rundung
    board_thickness: float = 16.0  # Dicke des Einlegebodens (nur Kontrolle)

    # --- Abdeckung ---------------------------------------------------------
    plate_t: float = 3.0           # Dicke der Deckplatte
    lip: float = 12.0              # Auflagerand auf dem Boden (seitlich/vorne)
    chamfer: float = 1.2           # umlaufende Fase an der Oberseite
    clear: float = 0.4             # Spiel der Schuerze je Seite
    skirt_h: float = 6.0           # Hoehe der Fuehrungsschuerze
    skirt_w: float = 2.5           # Wandstaerke der Fuehrungsschuerze
    front_play: float = 3.0        # Schuerze endet so weit vor dem Bogen
    rib_w: float = 2.5             # Breite der Querrippen
    rib_positions: tuple = (60.0, 170.0)

    # --- zweiteilige Variante ---------------------------------------------
    split_y: float = 110.0         # Trennfuge (y)
    dt_root: float = 18.0          # Schwalbenschwanz: Breite an der Wurzel
    dt_tip: float = 26.0           # Schwalbenschwanz: Breite an der Spitze
    dt_len: float = 14.0           # Schwalbenschwanz: Laenge
    dt_clear: float = 0.20         # Fugenspiel

    # --- Testdruck ---------------------------------------------------------
    gauge_t: float = 2.5           # Dicke der Lehren
    gauge_rim: float = 6.0         # Randbreite der Lehren
    gauge_min: int = 71            # kleinste Stufe der Breitenlehre
    gauge_max: int = 79            # groesste Stufe der Breitenlehre
    gauge_step_len: float = 11.0   # Laenge einer Stufe
    arc_gauge_len: float = 60.0    # Laenge der Bogenlehre
    sample_len: float = 40.0       # Laenge der Profilprobe

    @property
    def radius(self) -> float:
        return self.notch_width / 2.0


# --------------------------------------------------------------------------
# 2D-Grundformen
# --------------------------------------------------------------------------


def tongue_pts(halfw: float, tip_y: float, y_rear: float = 0.0, n_arc: int = 96):
    """Zungenform: Rechteck mit halbkreisfoermigem Kopf, hinten offen.

    Der Bogenradius ist immer gleich der halben Breite, der Mittelpunkt
    liegt bei y = tip_y - halfw. Punktreihenfolge gegen den Uhrzeigersinn.
    """
    cy = tip_y - halfw
    if cy < y_rear - 1e-9:
        raise ValueError("tip_y zu klein fuer halfw")
    pts = [(halfw, y_rear), (halfw, cy)]
    for i in range(1, n_arc):
        a = math.pi * i / n_arc
        pts.append((halfw * math.cos(a), cy + halfw * math.sin(a)))
    pts += [(-halfw, cy), (-halfw, y_rear)]
    return pts


def poly(pts) -> Polygon:
    p = Polygon(pts)
    if not p.is_valid:
        p = p.buffer(0)
    return p


def extrude(pg: Polygon, z0: float, z1: float) -> trimesh.Trimesh:
    """Extrudiert ein Polygon; Innenringe werden ausgeschnitten."""
    outer = Polygon(pg.exterior)
    m = trimesh.creation.extrude_polygon(outer, height=z1 - z0, engine="earcut")
    m.apply_translation([0.0, 0.0, z0])
    if len(pg.interiors):
        cuts = []
        for ring in pg.interiors:
            c = trimesh.creation.extrude_polygon(Polygon(ring),
                                                 height=z1 - z0 + 2.0,
                                                 engine="earcut")
            c.apply_translation([0.0, 0.0, z0 - 1.0])
            cuts.append(c)
        m = trimesh.boolean.difference([m] + cuts)
    return m


def loft(pts_a, za: float, pts_b, zb: float) -> trimesh.Trimesh:
    """Verbindet zwei gleich lange Punktlisten (Fase / Konus)."""
    import mapbox_earcut as earcut

    a = np.asarray(pts_a, dtype=np.float64)
    b = np.asarray(pts_b, dtype=np.float64)
    n = len(a)
    verts = np.vstack([
        np.column_stack([a, np.full(n, za)]),
        np.column_stack([b, np.full(n, zb)]),
    ])
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j])
        faces.append([i, n + j, n + i])
    ta = earcut.triangulate_float64(a, np.array([n])).reshape(-1, 3)
    tb = earcut.triangulate_float64(b, np.array([n])).reshape(-1, 3)
    faces += [list(t[::-1]) for t in ta]
    faces += [list(t + n) for t in tb]
    m = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)
    m.fix_normals()
    return m


def union(meshes):
    meshes = [m for m in meshes if m is not None]
    if len(meshes) == 1:
        return meshes[0]
    return trimesh.boolean.union(meshes)


# --------------------------------------------------------------------------
# Abdeckung
# --------------------------------------------------------------------------


def cover(p: Params) -> trimesh.Trimesh:
    """Abdeckung in Einbaulage: Deckplatte z=0..plate_t, Schuerze z=-skirt_h..0."""
    # Deckplatte (Aussenkontur = Aussparung + umlaufender Auflagerand)
    outer = tongue_pts(p.radius + p.lip, p.notch_depth + p.lip, 0.0)
    inner_ch = tongue_pts(p.radius + p.lip - p.chamfer,
                          p.notch_depth + p.lip - p.chamfer, 0.0)

    plate = extrude(poly(outer), 0.0, p.plate_t - p.chamfer)
    fase = loft(outer, p.plate_t - p.chamfer, inner_ch, p.plate_t)

    # Fuehrungsschuerze (taucht in die Aussparung ein)
    sk_out = poly(tongue_pts(p.radius - p.clear,
                             p.notch_depth - p.front_play, 0.0))
    sk_in = poly(tongue_pts(p.radius - p.clear - p.skirt_w,
                            p.notch_depth - p.front_play - p.skirt_w, 0.0))
    skirt = extrude(sk_out.difference(sk_in), -p.skirt_h, 0.0)

    # Querrippen zur Versteifung, bleiben innerhalb der Schuerze
    ribs = []
    for y in p.rib_positions:
        r = box(-p.radius, y - p.rib_w / 2.0, p.radius, y + p.rib_w / 2.0)
        r = r.intersection(sk_out)
        if not r.is_empty:
            ribs.append(extrude(r, -p.skirt_h, 0.0))

    return union([plate, fase, skirt] + ribs)


def split_regions(p: Params):
    """Zwei Halbebenen mit Schwalbenschwanz-Fuge (2D-Polygone)."""
    big = 400.0
    ys = p.split_y
    seam = [
        (-big, ys),
        (-p.dt_root / 2.0, ys),
        (-p.dt_tip / 2.0, ys - p.dt_len),
        (p.dt_tip / 2.0, ys - p.dt_len),
        (p.dt_root / 2.0, ys),
        (big, ys),
    ]
    front = poly(seam + [(big, big), (-big, big)])
    rear = poly(seam + [(big, -big), (-big, -big)])
    return front, rear


def cover_split(p: Params):
    full = cover(p)
    front2d, rear2d = split_regions(p)
    # Spiel nur am hinteren Teil, damit die Fuge nicht klemmt
    rear2d = rear2d.buffer(-p.dt_clear, join_style=2)
    fr = extrude(front2d, -50.0, 50.0)
    re = extrude(rear2d, -50.0, 50.0)
    return (trimesh.boolean.intersection([full, fr]),
            trimesh.boolean.intersection([full, re]))


# --------------------------------------------------------------------------
# Ziffern (7-Segment) fuer die Beschriftung der Lehren
# --------------------------------------------------------------------------

_SEG = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcfgd",
}


def digit_polys(ch: str, h: float, w: float, s: float):
    segs = {
        "a": (0, h - s, w, h),
        "b": (w - s, h / 2, w, h),
        "c": (w - s, 0, w, h / 2),
        "d": (0, 0, w, s),
        "e": (0, 0, s, h / 2),
        "f": (0, h / 2, s, h),
        "g": (0, h / 2 - s / 2, w, h / 2 + s / 2),
    }
    return [box(*segs[k]) for k in _SEG[ch]]


def label(text: str, cx: float, cy: float, h: float = 5.0):
    """Zentrierte Ziffernfolge als 2D-Geometrie (Polygon/MultiPolygon)."""
    w, s, gap = 0.62 * h, 0.17 * h, 0.30 * h
    total = len(text) * w + (len(text) - 1) * gap
    x = cx - total / 2.0
    parts = []
    for ch in text:
        for pg in digit_polys(ch, h, w, s):
            parts.append(Polygon([(px + x, py + cy - h / 2.0)
                                  for px, py in pg.exterior.coords]))
        x += w + gap
    return unary_union(parts)


def extrude_any(geom, z0: float, z1: float):
    """Extrudiert Polygon oder MultiPolygon und liefert eine Mesh-Liste."""
    geoms = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    return [extrude(pg, z0, z1) for pg in geoms]


# --------------------------------------------------------------------------
# Testdruck-Lehren
# --------------------------------------------------------------------------


def width_gauge(p: Params) -> trimesh.Trimesh:
    """Stufenlehre: bestimmt die Breite der Aussparung auf 1 mm genau.

    Schmales Ende voran in die Aussparung stecken. Die Lehre rutscht
    hinein, bis eine Stufe zu breit ist - diese Zahl minus 1 ist die
    lichte Breite.
    """
    widths = list(range(p.gauge_min, p.gauge_max + 1))
    L = p.gauge_step_len
    right, left = [], []
    for i, w in enumerate(widths):
        hw, y0, y1 = w / 2.0, i * L, (i + 1) * L
        right += [(hw, y0), (hw, y1)]
        left += [(-hw, y0), (-hw, y1)]
    outer = poly(right + left[::-1])

    frame = outer.difference(outer.buffer(-p.gauge_rim, join_style=2))
    spine = box(-5.0, 0.0, 5.0, len(widths) * L)
    braces = [box(-40.0, y - 1.5, 40.0, y + 1.5).intersection(outer)
              for y in (L * len(widths) / 3.0, L * len(widths) * 2 / 3.0)]
    body = unary_union([frame, spine] + braces)

    mesh = extrude(body, 0.0, p.gauge_t)
    marks = []
    for i, w in enumerate(widths):
        marks += extrude_any(label(str(w), 0.0, i * L + L / 2.0),
                             p.gauge_t, p.gauge_t + 0.6)
    return union([mesh] + marks)


def arc_gauge(p: Params) -> trimesh.Trimesh:
    """Bogenlehre: prueft den Radius vorne und dient der Tiefenmessung.

    Vorne in die Aussparung legen bis der Bogen anliegt, dann von der
    Hinterkante der Lehre bis zur Hinterkante des Bodens messen und die
    aufgedruckte Laenge addieren.
    """
    outer = poly(tongue_pts(p.radius - 0.3, p.arc_gauge_len, 0.0))
    frame = outer.difference(outer.buffer(-p.gauge_rim, join_style=2))
    spine = box(-5.0, 0.0, 5.0, p.arc_gauge_len - p.radius + 3.0)
    body = unary_union([frame, spine])
    mesh = extrude(body, 0.0, p.gauge_t)
    marks = extrude_any(label(str(int(p.arc_gauge_len)), 0.0, 12.0),
                        p.gauge_t, p.gauge_t + 0.6)
    return union([mesh] + marks)


def profile_sample(p: Params) -> trimesh.Trimesh:
    """Kurzes Stueck des echten Deckelprofils: prueft Spiel, Rand und
    Schuerzenhoehe gegen die Bodenstaerke."""
    L = p.sample_len
    ho = p.radius + p.lip
    outer = [(ho, 0.0), (ho, L), (-ho, L), (-ho, 0.0)]
    inner = [(ho - p.chamfer, 0.0), (ho - p.chamfer, L - p.chamfer),
             (-ho + p.chamfer, L - p.chamfer), (-ho + p.chamfer, 0.0)]
    cut = box(-(p.radius - 14.0), 9.0, p.radius - 14.0, L - 9.0)

    plate = extrude(poly(outer).difference(cut), 0.0, p.plate_t - p.chamfer)
    fase = loft(outer, p.plate_t - p.chamfer, inner, p.plate_t)
    fase = trimesh.boolean.difference([fase, extrude(cut, -1.0, 10.0)])

    hs = p.radius - p.clear
    rails = [extrude(box(hs - p.skirt_w, 0.0, hs, L), -p.skirt_h, 0.0),
             extrude(box(-hs, 0.0, -hs + p.skirt_w, L), -p.skirt_h, 0.0)]
    return union([plate, fase] + rails)


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


def to_print(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Dreht die Abdeckung in Druckorientierung: Sichtseite auf dem Bett."""
    m = mesh.copy()
    m.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
    b = m.bounds
    m.apply_translation([-(b[0][0] + b[1][0]) / 2.0, -b[0][1], -b[0][2]])
    return m


def centered(mesh: trimesh.Trimesh, dx=0.0, dy=0.0) -> trimesh.Trimesh:
    m = mesh.copy()
    b = m.bounds
    m.apply_translation([-(b[0][0] + b[1][0]) / 2.0 + dx, -b[0][1] + dy, -b[0][2]])
    return m


def test_plate(p: Params) -> trimesh.Trimesh:
    """Alle drei Lehren auf einer Platte, druckfertig angeordnet."""
    wg = centered(width_gauge(p), dx=-42.0, dy=0.0)
    ag = centered(arc_gauge(p), dx=42.0, dy=0.0)
    ps = centered(profile_sample(p), dx=0.0, dy=105.0)
    plate = trimesh.util.concatenate([wg, ag, ps])
    b = plate.bounds
    plate.apply_translation([-(b[0][0] + b[1][0]) / 2.0,
                             -(b[0][1] + b[1][1]) / 2.0, 0.0])
    return plate


# --------------------------------------------------------------------------
# Massskizze (SVG)
# --------------------------------------------------------------------------


def drawing(p: Params) -> str:
    """Bemasste Skizze (Draufsicht 1:2 + Schnitt 2:1) als SVG."""
    R, D, W = p.radius, p.notch_depth, p.notch_width
    ho, tip = R + p.lip, D + p.lip
    hs, tips = R - p.clear, D - p.front_play
    ox, oy = 95.0, 132.0
    bt = p.board_thickness

    def tongue_path(halfw, tip_y):
        cy = tip_y - halfw
        return (f"M {ox:.1f} {oy - halfw:.1f} L {ox + cy:.1f} {oy - halfw:.1f} "
                f"A {halfw:.1f} {halfw:.1f} 0 0 1 {ox + cy:.1f} {oy + halfw:.1f} "
                f"L {ox:.1f} {oy + halfw:.1f}")

    def dim_h(x0, x1, y, text):
        return (f'<path class="dim" d="M {x0:.1f} {y:.1f} L {x1:.1f} {y:.1f}"/>'
                f'<path class="dim" d="M {x0:.1f} {y - 3:.1f} L {x0:.1f} {y + 3:.1f}"/>'
                f'<path class="dim" d="M {x1:.1f} {y - 3:.1f} L {x1:.1f} {y + 3:.1f}"/>'
                f'<text class="dt" x="{(x0 + x1) / 2:.1f}" y="{y - 2.5:.1f}">{text}</text>')

    def dim_v(y0, y1, x, text):
        return (f'<path class="dim" d="M {x:.1f} {y0:.1f} L {x:.1f} {y1:.1f}"/>'
                f'<path class="dim" d="M {x - 3:.1f} {y0:.1f} L {x + 3:.1f} {y0:.1f}"/>'
                f'<path class="dim" d="M {x - 3:.1f} {y1:.1f} L {x + 3:.1f} {y1:.1f}"/>'
                f'<text class="dt" x="{x - 4:.1f}" y="{(y0 + y1) / 2 + 2:.1f}" '
                f'text-anchor="end">{text}</text>')

    # ---- Schnitt A-A, Massstab 2:1 ---------------------------------------
    sx, sy, sc, bw = 285.0, 275.0, 2.0, R + 26.0

    def S(x, y):
        return f"{sx + x * sc:.1f} {sy + y * sc:.1f}"

    sec = []
    for sgn in (-1, 1):
        a, b = sgn * R, sgn * bw
        sec.append(f'<path class="board" d="M {S(min(a, b), 0)} L {S(max(a, b), 0)} '
                   f'L {S(max(a, b), bt)} L {S(min(a, b), bt)} Z"/>')
    sec.append(f'<path class="cov" d="M {S(-ho, 0)} L {S(ho, 0)} '
               f'L {S(ho, -p.plate_t + p.chamfer)} L {S(ho - p.chamfer, -p.plate_t)} '
               f'L {S(-ho + p.chamfer, -p.plate_t)} L {S(-ho, -p.plate_t + p.chamfer)} Z"/>')
    for sgn in (-1, 1):
        a, b = sgn * (R - p.clear), sgn * (R - p.clear - p.skirt_w)
        sec.append(f'<path class="cov" d="M {S(min(a, b), 0)} L {S(max(a, b), 0)} '
                   f'L {S(max(a, b), p.skirt_h)} L {S(min(a, b), p.skirt_h)} Z"/>')

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="740"
     viewBox="0 0 560 370">
<style>
  text {{ font-family: "DejaVu Sans", Arial, Helvetica, sans-serif; fill: #111; }}
  .t  {{ font-size: 6px; }}
  .h  {{ font-size: 9.5px; font-weight: 700; }}
  .s  {{ font-size: 7.5px; font-weight: 700; }}
  .dt {{ font-size: 5.5px; fill: #b00; text-anchor: middle; }}
  .board {{ fill: #e9e9e9; stroke: #333; stroke-width: 0.7; }}
  .notch {{ fill: #fff; stroke: #111; stroke-width: 1.2; }}
  .cover {{ fill: none; stroke: #0a63c9; stroke-width: 1.1; stroke-dasharray: 5 2.5; }}
  .skirt {{ fill: none; stroke: #999; stroke-width: 0.6; stroke-dasharray: 2 2; }}
  .cov {{ fill: #cde1fa; stroke: #0a63c9; stroke-width: 0.8; }}
  .dim {{ stroke: #b00; stroke-width: 0.4; fill: none; }}
  .cl  {{ stroke: #b00; stroke-width: 0.3; stroke-dasharray: 7 2 1.5 2; }}
  .ld  {{ stroke: #555; stroke-width: 0.35; fill: none; }}
</style>

<text class="h" x="20" y="20">Abdeckung fuer die Siphon-Aussparung im Badschrank</text>
<text class="t" x="20" y="31">alle Masse in mm - schwarz: Aussparung im Boden - blau gestrichelt: Umriss der Abdeckung - grau: Fuehrungsschuerze auf der Unterseite</text>

<text class="s" x="20" y="52">Draufsicht 1:2</text>
<rect class="board" x="{ox:.1f}" y="{oy - 80:.1f}" width="245" height="160"/>
<path class="notch" d="{tongue_path(R, D)} Z"/>
<path class="cover" d="{tongue_path(ho, tip)}"/>
<path class="skirt" d="{tongue_path(hs, tips)}"/>
<path class="cl" d="M {ox - 40:.1f} {oy:.1f} L {ox + tip + 22:.1f} {oy:.1f}"/>

<path class="ld" d="M {ox:.1f} {oy - 86:.1f} L {ox:.1f} {oy - 80:.1f}"/>
<text class="t" x="{ox + 2:.1f}" y="{oy - 88:.1f}">Hinterkante Einlegeboden (Wandseite)</text>
<text class="t" x="{ox + 120:.1f}" y="{oy - 86:.1f}">Einlegeboden</text>
<text class="t" x="{ox + tip + 14:.1f}" y="{oy - 3:.1f}">Deckplatte</text>
<text class="t" x="{ox + tip + 14:.1f}" y="{oy + 5:.1f}">{2 * ho:.0f} mm breit</text>

{dim_v(oy - R, oy + R, ox - 14, f"W = {W:.1f}")}
{dim_h(ox, ox + D, oy + 96, f"T = {D:.1f}")}
{dim_h(ox + D, ox + tip, oy + 70, f"{p.lip:.0f}")}
{dim_h(ox, ox + tips, oy + 64, f"Schuerze {tips:.1f}")}

<text class="s" x="20" y="{sy - 34:.1f}">Schnitt A-A 2:1</text>
{''.join(sec)}
<path class="ld" d="M {sx - bw * sc - 6:.1f} {sy + 14:.1f} L {sx - bw * sc + 20:.1f} {sy + 14:.1f}"/>
<text class="t" x="{sx - bw * sc - 8:.1f}" y="{sy + 15:.1f}" text-anchor="end">Einlegeboden {bt:.0f} mm</text>
<path class="ld" d="M {sx - ho * sc - 6:.1f} {sy - 8:.1f} L {sx - ho * sc + 4:.1f} {sy - 4:.1f}"/>
<text class="t" x="{sx - ho * sc - 8:.1f}" y="{sy - 7:.1f}" text-anchor="end">Deckplatte {p.plate_t:.1f} mm, Fase {p.chamfer:.1f} mm</text>
<path class="ld" d="M {sx + (R - p.clear) * sc + 6:.1f} {sy + p.skirt_h * sc + 6:.1f} L {sx + (R - p.clear) * sc - 2:.1f} {sy + p.skirt_h * sc:.1f}"/>
<text class="t" x="{sx + (R - p.clear) * sc + 8:.1f}" y="{sy + p.skirt_h * sc + 8:.1f}">Schuerze {p.skirt_h:.0f} x {p.skirt_w:.1f} mm, Spiel {p.clear:.1f} je Seite</text>
<text class="t" x="{sx + R * sc + 6:.1f}" y="{sy - 14:.1f}">Auflagerand {p.lip:.0f} mm liegt auf dem Boden auf</text>
<text class="t" x="20" y="{sy + 52:.1f}">Die Schuerze taucht nur {p.skirt_h:.0f} mm ein - die Bodenstaerke ist deshalb unkritisch, solange der Boden dicker als {p.skirt_h:.0f} mm ist.</text>
</svg>
"""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--width", type=float, default=Params.notch_width,
                    help="lichte Breite der Aussparung (mm)")
    ap.add_argument("--depth", type=float, default=Params.notch_depth,
                    help="Tiefe ab Hinterkante Boden bis Scheitel (mm)")
    ap.add_argument("--board", type=float, default=Params.board_thickness,
                    help="Dicke des Einlegebodens (mm)")
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(__file__), "stl"))
    args = ap.parse_args()

    p = Params(notch_width=args.width, notch_depth=args.depth,
               board_thickness=args.board)
    p.split_y = round(p.notch_depth / 2.0, 1)
    p.rib_positions = (round(p.notch_depth * 0.27, 1), round(p.notch_depth * 0.78, 1))

    os.makedirs(args.outdir, exist_ok=True)
    parts = {}
    parts["abdeckung_1teilig"] = to_print(cover(p))
    front, rear = cover_split(p)
    parts["abdeckung_2teilig_vorne"] = to_print(front)
    parts["abdeckung_2teilig_hinten"] = to_print(rear)
    parts["testdruck_komplett"] = test_plate(p)
    parts["testdruck_breitenlehre"] = centered(width_gauge(p))
    parts["testdruck_bogenlehre"] = centered(arc_gauge(p))
    parts["testdruck_profilprobe"] = centered(profile_sample(p))

    print(f"Aussparung: {p.notch_width} x {p.notch_depth} mm, R{p.radius}")
    for name, mesh in parts.items():
        path = os.path.join(args.outdir, name + ".stl")
        mesh.export(path)
        e = mesh.extents
        print(f"  {name + '.stl':34s} {e[0]:6.1f} x {e[1]:6.1f} x {e[2]:5.1f} mm"
              f"  {mesh.volume / 1000:6.1f} cm3"
              f"  {'ok' if mesh.is_watertight else 'NICHT WASSERDICHT'}")

    svg = os.path.join(os.path.dirname(__file__), "massskizze.svg")
    with open(svg, "w") as fh:
        fh.write(drawing(p))
    print(f"  {'massskizze.svg':34s} geschrieben")


if __name__ == "__main__":
    main()
