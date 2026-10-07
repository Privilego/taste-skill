#!/usr/bin/env python3
"""LICHTFUGE - der Koelner Dom als Licht in einem dunklen Monolithen.

Eine ruhige Stele, durch die die Westfassade des Doms als Oeffnung geschnitten ist.
Die Oeffnung ist in die Tiefe gestaffelt: mehrere Dom-Silhouetten, nach hinten kleiner,
wie die Archivolten eines gotischen Portals. Jede Stufe traegt eine goldene Kante
(Goldfuge), an den Seiten der Stele erscheinen diese Fugen als feine Goldlinien.

Gedruckt wird LIEGEND (Rueckseite aufs Bett): dann ist jede Stufe eine nach oben
zeigende Flaeche, es gibt keine Bruecken und keine Ueberhaenge, und die Farben sind
reine Lagenwechsel (wenige Filamentwechsel).

usage: python3 build.py [--views hero,front,...] [--palette name] [--stl]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, '/tmp/claude-0/-home-user-taste-skill/d46f1633-345d-5b87-803e-a453b1fd4c0a/scratchpad/kit')
from proto_kit import *  # noqa: E402,F401,F403
from manifold3d import CrossSection, FillRule, JoinType, Manifold, OpType  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- Parameter (mm)
P = dict(
    W0=110.0,      # Breite unten
    W1=98.0,       # Breite oben (leichte Verjuengung)
    HT=214.0,      # Hoehe der Stele
    D=44.0,        # Tiefe
    CF=3.0,        # Fase vorne
    CB=1.0,        # Fase hinten (liegt auf dem Bett)
    Z_FLOOR=28.0,  # Boden der scharfen (hinteren) Dom-Silhouette
    H_AP=156.0,    # Hoehe der scharfen Dom-Silhouette (Turm 157,4 m -> 156 mm)
    MODE='halo',   # 'halo': hinten scharf, nach vorne Hoehenlinien | 'scale': Perspektiv-Tunnel
    KITE=[2.3, 1.0],                      # Lichthof-Form: nach oben spitz (x2,3), nach unten flach
    HALO=[0.75, 0.85, 1.0, 1.15, 1.3],    # Ringbreiten von innen nach aussen (mm), nach aussen weiter
    ANCHOR=0.0,    # (nur MODE scale) Skalierzentrum
    STEPS=[1, 1, 1, 1, 1],                # (nur MODE scale) Skalierungen; Anzahl = Anzahl Ringe
    T_FRONT=12.5,  # Dicke der vorderen Platte (dunkel, ruhige Laibung)
    T_STEP=6.5,    # Dicke je Stufe
    GOLD=[0.8, 0.96, 1.12, 1.28, 1.44],   # Goldfuge je Stufe (mm), nach hinten dicker
    BACK_GOLD=True,  # hinterste Platte komplett gold (Rueckseite gold)
    CLOSE=0.5,     # morphologisches Schliessen der Silhouette (mm) gegen Mini-Spalten
)
LAYER, FIRST = 0.16, 0.2


def facade_silhouette():
    """Westfassade allein: zwei Tuerme + Mittelteil mit Giebel (Meter, x/z)."""
    core = dd.sym(dd.nave_half(False))
    center = core ^ dd.rect(-7.75, 7.75, -1, 100)
    F = Manifold.batch_boolean([dd.tower(-1), dd.tower(1), dd.extrude_y(center, 0, 23.5),
                                dd.pinnacle(0, 1.3, 1.6, 55, 63, 70)], OpType.Add)
    return front_silhouette(F)


def minkowski_convex(cs, kpts):
    """Minkowski-Summe Polygon (+) konvexes Polygon kpts: Vereinigung der Huellen je Kante."""
    kp = np.asarray(kpts, float)
    parts = [cs]
    for poly in cs.to_polygons():
        poly = np.asarray(poly, float)
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            pts = np.vstack([a + kp, b + kp])
            parts.append(CrossSection.hull_points([tuple(p) for p in pts]))
    return CrossSection.batch_boolean(parts, OpType.Add)


def kite(o, up, down):
    """gotischer Drachen: spitz nach oben (Lanzette), flach nach unten."""
    return [(0, up * o), (o, 0), (0, -down * o), (-o, 0)]


def snap_layers(z):
    """auf Lagengrenze runden (Druckhoehe)."""
    n = round((z - FIRST) / LAYER)
    return FIRST + n * LAYER


def build(p=P):
    s = p['H_AP'] / dd.H_REAL
    sil = facade_silhouette().scale((s, s)).translate((0, p['Z_FLOOR']))
    if p['CLOSE'] > 0:
        r = p['CLOSE']
        sil = sil.offset(r, JoinType.Round, circular_segments=16).offset(-r, JoinType.Miter, 2.0)
    anchor = (0.0, p['Z_FLOOR'] + p['ANCHOR'] * p['H_AP'])

    def scaled(k):
        return sil.translate((-anchor[0], -anchor[1])).scale((k, k)).translate(anchor)

    D, HT = p['D'], p['HT']
    # ---- Stele (konvexe Huelle -> Fasen an allen Vorder- und Hinterkanten)
    W0, W1, CF, CB = p['W0'], p['W1'], p['CF'], p['CB']

    def ring(y, inset):
        # Trapez in x/z, um 'inset' eingerueckt (Fase)
        pts = []
        for (x, z) in [(-W0 / 2, 0), (W0 / 2, 0), (W1 / 2, HT), (-W1 / 2, HT)]:
            pts.append((x, z))
        pts = np.array(pts)
        c = pts.mean(0)
        # Einrueckung senkrecht zu den Kanten: einfache Naeherung ueber Offset des Polygons
        cs = CrossSection([pts]).offset(-inset, JoinType.Miter, 4.0)
        poly = np.array(cs.to_polygons()[0])
        return [(x, y, z) for (x, z) in poly]

    verts = ring(0.0, CF) + ring(CF, 0.0) + ring(D - CB, 0.0) + ring(D, CB)
    stele = Manifold.hull_points(verts)

    # ---- gestaffelte Oeffnung: Platte 0 vorne (gross) ... Platte n hinten (klein)
    scales = [1.0] + list(p['STEPS'])
    t_front = p['T_FRONT']
    n = len(scales)
    # Plattengrenzen in y (vorne y=0)
    bounds = [0.0, t_front]
    for i in range(1, n):
        bounds.append(t_front + i * p['T_STEP'])
    bounds[-1] = D  # letzte Platte bis hinten
    # auf Lagengrenzen der liegenden Druckorientierung schnappen (Druck-z = D - y)
    bounds = [0.0] + [D - snap_layers(D - b) for b in bounds[1:-1]] + [D]
    eps = 0.01
    voids = []
    prev = None
    apertures = []
    if p.get('MODE', 'scale') == 'halo':
        # hinten die scharfe Silhouette, nach vorne Offsets (Hoehenlinien eines Lichtscheins)
        offs = np.cumsum([0.0] + list(p['HALO'])[::-1])[::-1]   # vorne groesster Offset
        assert len(offs) == n, (len(offs), n)
    for i, k in enumerate(scales):
        y0, y1 = bounds[i], bounds[i + 1]
        if p.get('MODE', 'scale') == 'halo' and p.get('KITE'):
            o = float(offs[i])
            cs = minkowski_convex(sil, kite(o, *p['KITE'])) if o > 0 else sil
        elif p.get('MODE', 'scale') == 'halo':
            o = float(offs[i])
            cs = sil.offset(o, JoinType.Round, circular_segments=48) if o > 0 else sil
            if p.get('HALO_SCALE', 0):
                f = 1.0 + p['HALO_SCALE'] * o
                cs = cs.translate((-anchor[0], -anchor[1])).scale((f, f)).translate(anchor)
        else:
            cs = scaled(k)
        if prev is not None:
            cs = cs ^ prev   # Enthaltensein erzwingen -> beim liegenden Druck nie Ueberhang
        prev = cs
        apertures.append(cs)
        voids.append(dd.extrude_y(cs, y0 - (1.0 if i == 0 else eps), y1 + (1.0 if i == n - 1 else eps)))
    void = Manifold.batch_boolean(voids, OpType.Add)
    body = stele - void

    # ---- Goldfugen: vorderste g mm jeder Stufe (= oberste Lagen beim liegenden Druck)
    slabs = []
    gold_y = []
    for i in range(1, n):
        y0 = bounds[i]
        g = p['GOLD'][i - 1]
        y1 = y0 + g
        if p['BACK_GOLD'] and i == n - 1:
            y1 = D + 1
        slabs.append(dd.box(-200, 200, y0, y1, -10, 400))
        gold_y.append((y0, min(y1, D)))
    G = Manifold.batch_boolean(slabs, OpType.Add)
    B = body ^ G
    A = body - G
    info = dict(bounds_y=[round(b, 3) for b in bounds], gold_y=[[round(a, 3), round(b, 3)] for a, b in gold_y],
                scales=scales, anchor=anchor, sil_bounds=[round(v, 1) for v in sil.bounds()],
                inner_bounds=[round(v, 1) for v in apertures[-1].bounds()])
    return body, A, B, info


def print_orient(m, D):
    """liegend: Rueckseite aufs Bett. (x, y, z) -> (x, z, D - y)."""
    return m.rotate((-90, 0, 0)).translate((0, 0, D))


def composite_glow(dark_png, bright_png, out_png, bg_dark, bg_bright, glow=(255, 190, 100), bloom=22, strength=1.0):
    """Zwei identische Renderings mit unterschiedlichem Hintergrund -> Maske der Durchsicht.
    Durchsicht-Pixel, die NICHT mit dem Bildrand verbunden sind = Oeffnung im Block.
    Dort wird warmes Licht eingesetzt (+ weicher Bloom), so wie eine LED/Kerze hinter der Stele."""
    from PIL import Image, ImageDraw, ImageFilter
    a = np.asarray(Image.open(dark_png).convert('RGB')).astype(np.float32)
    b = np.asarray(Image.open(bright_png).convert('RGB')).astype(np.float32)
    c0 = np.array([int(bg_dark[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    c1 = np.array([int(bg_bright[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    alpha = np.clip(np.abs(b - a).mean(-1) / max(1.0, float(np.abs(c1 - c0).mean())), 0, 1)
    m = Image.fromarray(((alpha > 0.3) * 255).astype(np.uint8)).copy()
    H, W = alpha.shape
    for xy in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1), (W // 2, 0), (W // 2, H - 1), (0, H // 2), (W - 1, H // 2)]:
        if m.getpixel(xy) == 255:
            ImageDraw.floodfill(m, xy, 128)
    hole = np.asarray(m) == 255
    hole = np.asarray(Image.fromarray((hole * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
    ha = np.clip((alpha - 0.05) / 0.6, 0, 1) * hole
    g = np.array(glow, np.float32)
    core = np.array([255, 240, 214], np.float32)
    inner = np.asarray(Image.fromarray((ha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5))).astype(np.float32) / 255
    t = np.clip((inner - 0.5) * 2.2, 0, 1)[..., None]
    # Lichtquelle hinter der Stele: Mitte unten heiss/hell, nach oben in warmes Gold auslaufend
    ys, xs = np.nonzero(hole)
    if len(ys):
        cy = ys.min() + 0.72 * (ys.max() - ys.min()); cx = xs.mean()
        yy, xx = np.mgrid[0:H, 0:W]
        rr = np.sqrt(((yy - cy) / (ys.max() - ys.min() + 1)) ** 2 + ((xx - cx) / (ys.max() - ys.min() + 1)) ** 2)
        q = np.clip(rr / 0.75, 0, 1)[..., None] ** 1.3
    else:
        q = np.zeros((H, W, 1), np.float32)
    amber = np.array([255, 178, 82], np.float32)
    lit = core * (1 - q) + amber * q
    light = g * (1 - t) + lit * t
    out = a * (1 - ha[..., None]) + light * ha[..., None]
    mm = Image.fromarray((ha * 255).astype(np.uint8))
    bl1 = np.asarray(mm.filter(ImageFilter.GaussianBlur(bloom))).astype(np.float32) / 255
    bl2 = np.asarray(mm.filter(ImageFilter.GaussianBlur(bloom * 4))).astype(np.float32) / 255
    bloomv = (0.6 * bl1 + 0.5 * bl2)[..., None] * g[None, None, :] * strength
    # Bloom hellt vor allem helle (goldene) Flaechen auf -> Licht faellt auf die Goldkanten
    lum = (a.mean(-1, keepdims=True) / 255.0)
    out = out + bloomv * (0.35 + 1.4 * lum) * (1 - ha[..., None])
    out = np.clip(out, 0, 255).astype(np.uint8)
    Image.fromarray(out).save(out_png)
    return out_png


PAL_MONOLITH = dict(a='#3e4043', b='#d4a645', mA=0.75, rA=0.5, mB=0.65, rB=0.25)  # Iron Gray Metallic / Gold Silk+

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--views', default='hero,front,side')
    ap.add_argument('--palette', default='monolith')
    ap.add_argument('--money', action='store_true')
    ap.add_argument('--stl', action='store_true')
    ap.add_argument('--tag', default='')
    ap.add_argument('--second', default='', help='zweite Palette fuer ein Hero-Bild')
    ap.add_argument('--params', default='{}', help='JSON-Overrides fuer P')
    ap.add_argument('--outdir', default=HERE)
    args = ap.parse_args()
    P = dict(P, **json.loads(args.params))
    HERE = args.outdir
    os.makedirs(HERE, exist_ok=True)

    body, A, B, info = build(P)
    pr = print_orient(body, P['D'])
    c_print = check(pr)
    c_stand = check(body)
    # Farbwechsel: Goldfugen -> je Fuge 2 Wechsel (A->B->A), letzte Fuge bis Rueckseite = 1
    swaps = 0
    for (y0, y1) in info['gold_y']:
        swaps += 1 if y1 >= P['D'] - 1e-6 else 2
    info.update(check_print=c_print, check_standing=c_stand, swaps=swaps,
                vol_A=round(A.volume() / 1000, 1), vol_B=round(B.volume() / 1000, 1))
    print(json.dumps(info, indent=1))
    with open(os.path.join(HERE, 'info.json'), 'w') as fh:
        json.dump(info, fh, indent=1)

    write_preview(HERE, A, B, None)
    pal = PAL_MONOLITH if args.palette == 'monolith' else args.palette
    V = {
        'hero': dict(name='hero', az=-35, el=14, zoom=1.0),
        'front': dict(name='front', az=0, el=4, zoom=1.0),
        'side': dict(name='side', az=-90, el=5, zoom=1.0),
        'back': dict(name='back', az=-150, el=24, zoom=1.0),
        'detail': dict(name='detail', az=-22, el=26, zoom=2.0, ty=0.62),
        'low': dict(name='low', az=-18, el=-2, zoom=1.05, ty=0.5),
    }
    views = [V[v] for v in args.views.split(',') if v in V]
    if args.tag:
        views = [dict(v, name=v['name'] + '_' + args.tag) for v in views]
    if views:
        print(render(HERE, views, palette=pal))
    if args.second:
        print(render(HERE, [dict(V['hero'], name='hero_' + args.second)], palette=args.second))
    if args.money:
        bgd, bgb = '#111113', '#f0f0f0'
        glow_views = [dict(name='money', az=0, el=1.5, zoom=1.12, ty=0.5),
                      dict(name='hero_glow', az=-30, el=9, zoom=1.08, ty=0.5)]
        for gv in glow_views:
            ex = {'BACKLIGHT': 5, 'EXPOSURE': 0.55}
            r1 = render(HERE, [dict(gv, name=gv['name'] + '_dark')], palette=pal, bg=bgd, extra=ex)[0]
            r2 = render(HERE, [dict(gv, name=gv['name'] + '_bright')], palette=pal, bg=bgb, extra=ex)[0]
            print(composite_glow(r1, r2, os.path.join(HERE, 'shots', gv['name'] + '.png'), bgd, bgb))
            os.remove(r2)
    if args.stl:
        os.makedirs(os.path.join(HERE, 'out'), exist_ok=True)
        from manifold3d import Mesh  # noqa
        import struct

        def stl(m, path):
            mesh = m.to_mesh()
            v = np.asarray(mesh.vert_properties[:, :3]); f = np.asarray(mesh.tri_verts)
            with open(path, 'wb') as fh:
                fh.write(b'\0' * 80 + struct.pack('<I', len(f)))
                for t in f:
                    a, b_, c = v[t]
                    nrm = np.cross(b_ - a, c - a); nrm = nrm / (np.linalg.norm(nrm) + 1e-12)
                    fh.write(struct.pack('<12fH', *nrm, *a, *b_, *c, 0))
        stl(print_orient(A, P['D']), os.path.join(HERE, 'out', 'lichtfuge_A_dunkel_liegend.stl'))
        stl(print_orient(B, P['D']), os.path.join(HERE, 'out', 'lichtfuge_B_gold_liegend.stl'))
        stl(pr, os.path.join(HERE, 'out', 'lichtfuge_einfarbig_liegend.stl'))
