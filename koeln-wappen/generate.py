#!/usr/bin/env python3
"""Kölner Stadtwappen – schwebendes Wandrelief für den 3D-Druck (Schwarz/Weiß).

Erzeugt 4 Druckplatten für ein 256-mm-Bett (Bambu X1C/P1S/A1).

Gestaltungsregel für den Druck: ALLES unterhalb von COLOR_Z ist schwarz,
ALLES oberhalb ist weiß. Pro Platte genügt also ein einziger Filamentwechsel
(Bambu Studio: Farbwechsel bei Schicht COLOR_Z) – kein Purge-Turm, keine
Farbschlieren, Farbkanten entstehen aus Geometrie statt aus Mischzonen.

Aufruf:  python3 generate.py          (schreibt nach ./out)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import CrossSection, FillRule, Manifold
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

# ---------------------------------------------------------------- Parameter
W = 430.0            # Schildbreite  [mm]
HT = 490.0           # Schildhöhe    [mm]
SIDE_Y = 245.0       # bis hier verlaufen die Seiten senkrecht, darunter Spitzbogen
GAP = 2.0            # bewusste Schattenfuge zwischen den Kacheln
CHIEF_Y = 330.0      # Schildhaupt (oben) / Feld (unten); hier liegt auch der Fugenversatz
FIELD_TOP = 328.0    # Oberkante der weißen Feldplatte (2 mm schwarze Fuge zum Schildhaupt)
SEAM_JOG_X = -28.0   # Versatz der senkrechten Fuge im oberen Feldband (weicht der Mittelflamme aus)

COLOR_Z = 18.2       # Farbwechselhöhe (passt zu 0,2 mm Erstschicht + 0,08/0,12/0,2/0,24 mm Schichten)
STANDOFF = 12.0      # 45°-Unterschnitt: Schild schwebt mit Schattenkante vor der Wand
EDGE_CHAMFER = 2.0   # 45°-Fase der Schildvorderkante (schwarz)

CONTOUR_IN = 8.0     # weiße Konturlinie: Abstand zur Schildkante
CONTOUR_W = 3.0      #                    Breite
CONTOUR_H = 1.6      #                    Höhe über COLOR_Z
FIELD_IN = 15.0      # weiße Feldplatte: Abstand zur Schildkante
FIELD_T = 2.4        #                   Stärke (deckend weiß)
FIELD_CHAMFER = 1.2  #                   45°-Fase an allen Kanten und Flammen

CROWN_BASE = 1.6     # Krone: senkrechter Sockel über COLOR_Z
CROWN_SLOPE = 0.8    # Krone: Dachneigung der facettierten Schlifffläche (Höhe/Einzug)
CROWN_FIT = 0.20     # Spiel Kronen-Zapfen in der Aussparung (je Seite)

HATCH = True         # heraldische Schraffur für Rot (senkrechte Rillen) im Schildhaupt
HATCH_PITCH = 4.0
HATCH_W = 1.0
HATCH_DEPTH = 0.6

KEY_T = 4.0          # Schwalbenschwanz-Schlüssel (Rückseite) Dicke
KEY_FIT = 0.20

STEP = 0.12          # Scheibenhöhe für Fasen/Dachflächen (= Schichthöhe)
BED = 256.0          # Druckbett
BED_MARGIN = 3.0
BED_EXCLUDE = [(0.0, 0.0, 18.0, 28.0)]  # X1C: Kalibrierzone vorne links (x0,y0,x1,y1)

OUT = Path(__file__).resolve().parent / "out"
MITRE = dict(join_style=2, mitre_limit=8.0)   # scharfe Facetten (Kronen)
ROUND = dict(join_style=1, quad_segs=6)        # Fasen ohne Gehrungsspitzen (Flammen)

# ---------------------------------------------------------------- 2D-Helfer


def polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def to_cs(g) -> CrossSection:
    rings = []
    for p in polys(g):
        rings.append(np.asarray(p.exterior.coords)[:-1])
        rings.extend(np.asarray(r.coords)[:-1] for r in p.interiors)
    return CrossSection(rings, FillRule.EvenOdd)


def prism(g, z0, z1) -> Manifold:
    if g.is_empty or z1 <= z0:
        return Manifold()
    return Manifold.extrude(to_cs(g), z1 - z0).translate((0, 0, z0))


def union(parts) -> Manifold:
    parts = [p for p in parts if not p.is_empty()]
    if not parts:
        return Manifold()
    return Manifold.batch_boolean(parts, __import__("manifold3d").OpType.Add)


def roofed(g, z0, base, slope, cap=None, join=MITRE) -> Manifold:
    """Senkrechter Sockel (base) + facettiertes Walmdach (Gehrungs-Offsets).

    slope = Höhe pro mm Einzug; cap begrenzt die Dachhöhe (=> Fase statt Dach).
    """
    parts = [prism(g, z0, z0 + base)]
    i = 0
    while True:
        h = (i + 1) * STEP
        if cap is not None and h > cap + 1e-9:
            break
        inner = g.buffer(-h / slope, **join)
        if inner.is_empty or inner.area < 0.05:
            break
        parts.append(prism(inner, z0 + base + i * STEP, z0 + base + h))
        i += 1
    return union(parts)


# ---------------------------------------------------------------- Wappen-Geometrie


def shield() -> Polygon:
    r = (W / 2) ** 2 + SIDE_Y**2
    r /= W
    cx = W / 2 - r
    pts = [(-W / 2, HT), (W / 2, HT), (W / 2, SIDE_Y)]
    a0 = 0.0
    a1 = math.atan2(-SIDE_Y, -cx)  # Winkel zur Spitze (0,0)
    for a in np.linspace(a0, a1, 90)[1:-1]:
        pts.append((cx + r * math.cos(a), SIDE_Y + r * math.sin(a)))
    pts.append((0.0, 0.0))
    right = pts[3:-1]
    pts += [(-x, y) for x, y in reversed(right)]
    pts.append((-W / 2, SIDE_Y))
    return Polygon(pts)


def flame(cx, y0, w=30.0, h=58.0) -> Polygon:
    """Stilisierte Kölner Flamme: runder Fuß, S-förmig züngelnde Spitze."""
    r = w / 2
    pts = []
    for a in np.linspace(math.pi, 2 * math.pi, 40):          # Fuß (Halbkreis)
        pts.append((r * math.cos(a), r + r * math.sin(a)))
    s = np.linspace(0, 1, 60)[1:]
    c = 0.55 * r * s**2 * np.sin(1.5 * math.pi * s)         # Mittellinie (Züngeln)
    f = r * (1 - s) ** 1.35                                   # halbe Breite
    y = r + s * (h - r)
    pts += list(zip(c + f, y))
    pts += list(zip((c - f)[::-1][1:], y[::-1][1:]))
    p = Polygon(pts).buffer(0)
    return affinity.translate(p, cx, y0)


def crown(cx, y0) -> Polygon:
    """Geometrische Krone: Reif + drei Lilienzacken mit Rauten-Perlen."""
    band = Polygon([(-40, 0), (40, 0), (43, 17), (-43, 17)])
    top = Polygon([(-43, 16), (43, 16), (47, 47), (31, 27), (20, 41), (10, 28),
                   (0, 60), (-10, 28), (-20, 41), (-31, 27), (-47, 47)])
    def rhomb(x, y, s):
        return Polygon([(x, y - s), (x + s * 0.75, y), (x, y + s), (x - s * 0.75, y)])
    gems = [rhomb(47, 53, 7.5), rhomb(-47, 53, 7.5), rhomb(0, 67, 9),
            rhomb(20, 46, 4.5), rhomb(-20, 46, 4.5)]
    necks = [LineString([(47, 45), (47, 47)]).buffer(2.4), LineString([(-47, 45), (-47, 47)]).buffer(2.4),
             LineString([(0, 57), (0, 60)]).buffer(2.6),
             LineString([(20, 38), (20, 43)]).buffer(1.6), LineString([(-20, 38), (-20, 43)]).buffer(1.6)]
    g = unary_union([band, top, *gems, *necks]).buffer(0.01, **MITRE).buffer(-0.01, **MITRE)
    return affinity.translate(g, cx, y0)


SHIELD = shield()

# Flammen 5 : 4 : 2 (Hauptsatzung der Stadt Köln)
ROWS = [(258.5, [-152, -76, 0, 76, 152]),
        (168.5, [-114, -38, 38, 114]),
        (80.0, [-45, 45])]
FLAMES = [flame(x, y) for y, xs in ROWS for x in xs]
CROWNS = [crown(x, 371.0) for x in (-135.0, 0.0, 135.0)]
assert all(isinstance(c, Polygon) for c in CROWNS), "Krone muss zusammenhängend sein"

# Kachelaufteilung (Fugenmitte bei x=0 / y=245, oben mit Versatz im Feldband)
h = GAP / 2
INF = 1000.0
TILE_REGIONS = {
    "oben_links": unary_union([box(-INF, CHIEF_Y + h, -h, INF),
                               box(-INF, SIDE_Y + h, SEAM_JOG_X - h, CHIEF_Y + h)]),
    "oben_rechts": unary_union([box(h, SIDE_Y + h, INF, INF),
                                box(SEAM_JOG_X + h, SIDE_Y + h, h, CHIEF_Y - h)]),
    "unten_links": box(-INF, -INF, -h, SIDE_Y - h),
    "unten_rechts": box(h, -INF, INF, SIDE_Y - h),
}

# Schwalbenschwanz-Schlüssel über den Fugen: (x, y, Winkel)
KEYS = [(-150, SIDE_Y, 90), (-65, SIDE_Y, 90), (65, SIDE_Y, 90), (150, SIDE_Y, 90),
        (0, 350, 0), (SEAM_JOG_X, 287, 0), (0, 195, 0), (0, 100, 0)]


def butterfly() -> Polygon:
    return Polygon([(-18, -11), (-4, -5), (4, -5), (18, -11), (18, 11), (4, 5), (-4, 5), (-18, 11)])


def key_at(x, y, ang, grow=0.0):
    g = butterfly()
    if grow:
        g = g.buffer(grow, **MITRE)
    return affinity.translate(affinity.rotate(g, ang, origin=(0, 0)), x, y)


# ---------------------------------------------------------------- Bauteile


def shield_body() -> Manifold:
    """Schwarzer Schildkörper als konvexe Hülle: Unterschnitt, Platte, Frontfase."""
    def ring(g, z):
        xy = np.asarray(g.exterior.coords)[:-1]
        return np.column_stack([xy, np.full(len(xy), z)])
    pts = np.vstack([ring(SHIELD.buffer(-STANDOFF, **MITRE), 0.0),
                     ring(SHIELD, STANDOFF),
                     ring(SHIELD, COLOR_Z - EDGE_CHAMFER),
                     ring(SHIELD.buffer(-EDGE_CHAMFER, **MITRE), COLOR_Z)])
    return Manifold.hull_points(pts)


def build_tile(name, region, body):
    tile2d = SHIELD.intersection(region)
    black = body ^ prism(region.intersection(SHIELD.buffer(5)), -1, COLOR_Z + 1)

    # Mittlere Krone liegt über der Fuge -> separater Zapfen, der beide Kacheln verriegelt
    cuts = [prism(CROWNS[1].buffer(CROWN_FIT, **MITRE), -1, COLOR_Z + 1)]
    cuts += [prism(key_at(*k, grow=KEY_FIT), -1, KEY_T + 0.3) for k in KEYS]
    if HATCH:
        chief = SHIELD.buffer(-FIELD_IN, **MITRE).intersection(box(-INF, CHIEF_Y + 4, INF, INF))
        chief = chief.difference(unary_union([c.buffer(4, **MITRE) for c in CROWNS]))
        lines = unary_union([box(x - HATCH_W / 2, -INF, x + HATCH_W / 2, INF)
                             for x in np.arange(-W / 2 + 2, W / 2, HATCH_PITCH)])
        cuts.append(prism(chief.intersection(lines), COLOR_Z - HATCH_DEPTH, COLOR_Z + 1))
    black = black - union(cuts)

    contour = SHIELD.buffer(-CONTOUR_IN, **MITRE).difference(
        SHIELD.buffer(-(CONTOUR_IN + CONTOUR_W), **MITRE)).intersection(tile2d)
    field = SHIELD.buffer(-FIELD_IN, **MITRE).intersection(box(-INF, -INF, INF, FIELD_TOP))
    field = field.difference(unary_union(FLAMES)).intersection(tile2d)
    crowns = [roofed(c, COLOR_Z, CROWN_BASE, CROWN_SLOPE)
              for c in (CROWNS[0], CROWNS[2]) if c.within(tile2d)]
    white = union([
        *crowns,
        roofed(contour, COLOR_Z, CONTOUR_H - 0.6, 1.0, cap=0.6, join=ROUND),
        roofed(field, COLOR_Z, FIELD_T - FIELD_CHAMFER, 1.0, cap=FIELD_CHAMFER, join=ROUND),
    ])
    return black, white


def build_crown(c: Polygon):
    black = prism(c, 0, COLOR_Z)
    white = roofed(c, COLOR_Z, CROWN_BASE, CROWN_SLOPE)
    return black, white


def build_key():
    return prism(butterfly(), 0, KEY_T), Manifold()


# ---------------------------------------------------------------- Ausgabe


def mesh(m: Manifold) -> trimesh.Trimesh:
    if m.is_empty():
        return trimesh.Trimesh()
    mm = m.to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=True)


def footprint(m: Manifold) -> Polygon:
    cs = m.project()
    return unary_union([Polygon(p).buffer(0) for p in cs.to_polygons() if len(p) >= 3]).buffer(0)


def plate_layout(parts):
    """Je Kachel eine Platte; Krone und Schlüssel werden in die Restflächen gelegt."""
    bed = box(BED_MARGIN, BED_MARGIN, BED - BED_MARGIN, BED - BED_MARGIN)
    excl = unary_union([box(*e) for e in BED_EXCLUDE]) if BED_EXCLUDE else Polygon()

    def poses(fp, angles, step):
        for ang in angles:
            r = affinity.rotate(fp, ang, origin=(0, 0))
            minx, miny, maxx, maxy = r.bounds
            for ty in np.arange(BED_MARGIN - miny, BED - BED_MARGIN - maxy + 1e-6, step):
                for tx in np.arange(BED_MARGIN - minx, BED - BED_MARGIN - maxx + 1e-6, step):
                    p = affinity.translate(r, tx, ty)
                    if bed.contains(p) and not p.intersects(excl):
                        yield ang, tx, ty, p

    def fit(fp, occupied, angles, step=3.0, spacing=5.0):
        for pose in poses(fp, angles, step):
            if occupied.is_empty or pose[3].distance(occupied) >= spacing:
                return pose
        return None

    tiles = [p for p in parts if p["kind"] == "tile"]
    crowns = [p for p in parts if p["kind"] == "crown"]
    keys = [p for p in parts if p["kind"] == "key"]
    plates = [None] * len(tiles)
    # 1) Kronen-Zapfen: Kachel-Pose und Kronen-Pose gemeinsam suchen (untere Kacheln zuerst)
    for c in crowns:
        for i in sorted(range(len(tiles)), key=lambda i: tiles[i]["fp"].area):
            if plates[i] is not None:
                continue
            for tp in poses(tiles[i]["fp"], (0, 90, 180, 270), 4.0):
                cp = fit(c["fp"], tp[3], range(0, 360, 15))
                if cp:
                    plates[i] = {"items": [(tiles[i], *tp[:3]), (c, *cp[:3])],
                                 "occ": unary_union([tp[3], cp[3]])}
                    break
            if plates[i] is not None:
                break
        else:
            raise SystemExit("Kein Platz für den Kronen-Zapfen")
    # 2) übrige Kacheln in die Ecke
    for i, t in enumerate(tiles):
        if plates[i] is None:
            tp = fit(t["fp"], Polygon(), (0, 90, 180, 270))
            assert tp, f"Kachel {t['name']} passt nicht aufs Bett"
            plates[i] = {"items": [(t, *tp[:3])], "occ": tp[3]}
    # 3) Schlüssel in die Lücken
    for k in keys:
        for pl in sorted(plates, key=lambda pl: pl["occ"].area):
            kp = fit(k["fp"], pl["occ"], (0, 45, 90, 135), 2.0)
            if kp:
                pl["items"].append((k, *kp[:3]))
                pl["occ"] = unary_union([pl["occ"], kp[3]])
                break
        else:
            raise SystemExit(f"Kein Platz für {k['name']}")
    return plates


def place(m: Manifold, ang, tx, ty) -> Manifold:
    return m.rotate((0, 0, ang)).translate((tx, ty, 0))


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / "teile").mkdir(exist_ok=True)
    body = shield_body()

    parts = []
    for name, region in TILE_REGIONS.items():
        b, w = build_tile(name, region, body)
        parts.append({"name": f"kachel_{name}", "kind": "tile", "black": b, "white": w})
    b, w = build_crown(CROWNS[1])
    parts.append({"name": "krone_mitte", "kind": "crown", "black": b.translate((0, -371, 0)),
                  "white": w.translate((0, -371, 0)), "home": (0.0, 371.0)})
    for i, k in enumerate(KEYS, 1):
        b, w = build_key()
        parts.append({"name": f"schluessel_{i}", "kind": "key", "black": b, "white": w, "home": k})

    report = {"parts": {}, "plates": []}
    for p in parts:
        both = p["black"] + p["white"]
        p["fp"] = footprint(both)
        bm, wm = mesh(p["black"]), mesh(p["white"])
        bb = both.bounding_box()
        report["parts"][p["name"]] = {
            "size_mm": [round(bb[3] - bb[0], 1), round(bb[4] - bb[1], 1), round(bb[5] - bb[2], 2)],
            "black_watertight": bool(bm.is_watertight) if len(bm.faces) else None,
            "white_watertight": bool(wm.is_watertight) if len(wm.faces) else None,
            "black_zmax": round(float(bm.bounds[1][2]), 3) if len(bm.faces) else None,
            "white_zmin": round(float(wm.bounds[0][2]), 3) if len(wm.faces) else None,
            "volume_cm3": round(both.volume() / 1000, 1),
        }
        bm.export(OUT / "teile" / f"{p['name']}_schwarz.stl")
        if len(wm.faces):
            wm.export(OUT / "teile" / f"{p['name']}_weiss.stl")

    plates = plate_layout(parts)
    for n, pl in enumerate(plates, 1):
        blacks = [place(it["black"], a, x, y) for it, a, x, y in pl["items"]]
        whites = [place(it["white"], a, x, y) for it, a, x, y in pl["items"] if not it["white"].is_empty()]
        bm, wm = mesh(union(blacks)), mesh(union(whites))
        bm.export(OUT / f"platte_{n}_schwarz.stl")
        wm.export(OUT / f"platte_{n}_weiss.stl")
        trimesh.util.concatenate([bm, wm]).export(OUT / f"platte_{n}_komplett.stl")
        report["plates"].append({"plate": n, "items": [
            {"name": it["name"], "rot": a, "x": round(x, 1), "y": round(y, 1)} for it, a, x, y in pl["items"]]})

    # Zusammengebautes Wappen (Vorschau / Kontrolle)
    asm_b = [p["black"] for p in parts if p["kind"] == "tile"]
    asm_w = [p["white"] for p in parts if p["kind"] == "tile"]
    for p in parts:
        if p["kind"] == "crown":
            asm_b.append(p["black"].translate((*p["home"], 0)))
            asm_w.append(p["white"].translate((*p["home"], 0)))
    mesh(union(asm_b)).export(OUT / "wappen_gesamt_schwarz.stl")
    mesh(union(asm_w)).export(OUT / "wappen_gesamt_weiss.stl")

    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
