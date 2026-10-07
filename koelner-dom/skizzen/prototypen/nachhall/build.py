"""NACHHALL - die Westfassade des Kölner Doms als Echo.

Sechs Umriss-Rahmen der Westfassade (Türme + Mittelgiebel), jeder ein dünnes senkrechtes Band.
Von vorn nach hinten werden sie größer und rücken nach hinten - wie Schallwellen der Decke Pitter.
Die Turm-Innenkanten aller Rahmen liegen exakt hintereinander: dort sitzt eine von vorn
unsichtbare Wand (mit Spitzbogen-Arkaden, von der Seite wie ein Langhaus), die alle Rahmen
verbindet. Außen halten kleine Spitzbögen die Turmkanten, an den Helm-Kreuzungen verdeckte Kiele.
Der vorderste Rahmen ist ein eigenes Teil (Gold, liegend gedruckt) und steckt in einer Fuge im Sockel.

    python3 build.py            -> Geometrie + Vorschau + Checks
    python3 build.py render     -> zusätzlich Renderings
"""
import sys
import os
import json
import time

sys.path.insert(0, '/tmp/claude-0/-home-user-taste-skill/d46f1633-345d-5b87-803e-a453b1fd4c0a/scratchpad/kit')
from proto_kit import *  # noqa: F401,F403
import numpy as np

OUT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- Parameter (mm)
N = 6                                   # Anzahl Rahmen
KZ = np.linspace(0.60, 1.27, N)         # Höhenmaßstab mm/m  (Turm 157,4 m -> 94 ... 200 mm)
KX = np.linspace(0.60, 1.55, N)         # Breitenmaßstab der Türme: das Echo wird nach hinten breiter
C = 15.5 * 0.60 * 1.10                  # lichte Breite zwischen den Türmen (für alle Rahmen gleich)
WB = np.linspace(3.2, 2.2, N)           # Bandbreite in der Ansicht: vorn kräftig, hinten verklingend
W_BAND = 2.6
T = 2.0                                 # Plattenstärke
D = 10.0                                # Abstand der Rahmen in der Tiefe
PLINTH = 5.0                            # Sockelhöhe
Z_ARCH = (30.0, 62.0, 94.0)      # Höhen der kleinen Spitzbögen zwischen den Außenkanten
ARCH_ANGLE = 55.0                       # Steigung der Bogenschenkel
ARCH_BAR = 1.4                          # Querschnitt der Bogenschenkel
GAP0 = 0.15                             # Spiel zwischen Front-Rahmen (eigenes Teil) und Rest
SLOT = 3.0                              # Tiefe der Steckfuge im Sockel
KEEL_H = 4.0                            # Höhe der verdeckten Kiel-Stege an den Helm-Kreuzungen


# ---------------------------------------------------------------- Silhouette (Meter)
# Halbprofil eines Westturms (Abstand von der Turmachse, Höhe) in Metern - bewusst vereinfacht:
# drei Geschosse mit Rücksprüngen, Oktogon mit Fialenkranz, Helm, Kreuzblume.
TOWER_HALF = [(11.5, 0), (11.5, 33), (10.9, 33), (10.9, 63), (9.4, 63), (9.4, 103), (8.4, 116),
              (7.4, 111.6), (0.6, 147.4), (0.9, 148.8), (2.0, 151.5), (0.45, 154.0), (0.0, 157.4)]


def tower_outline(sx):
    right = [(dd.XT * sx + u, z) for (u, z) in TOWER_HALF]
    left = [(dd.XT * sx - u, z) for (u, z) in reversed(TOWER_HALF[:-1])]
    return dd.poly(right + left)


def facade_silhouette():
    core = dd.sym(dd.nave_half(False))
    center = core ^ dd.rect(-7.75, 7.75, -1, 100)
    Fc = Manifold.batch_boolean([dd.extrude_y(center, 0, 23.5), dd.pinnacle(0, 1.3, 1.6, 55, 63, 70)], OpType.Add)
    S = front_silhouette(Fc) + tower_outline(-1) + tower_outline(1)
    S = S + dd.sym(dd.rect(7.75, 9.0, 0, 63))               # Innenkante bis 63 m gerade
    S = S + dd.rect(-30.75, 30.75, -300, 0.01)              # nach unten offen
    return S


S_M = facade_silhouette()
TOW = S_M ^ dd.rect(7.75, 100, -400, 400)
CEN = S_M ^ dd.rect(-7.75, 7.75, -400, 400)
J_M = 46.07                                                # Kehle Turm/Giebel in m


def silhouette_mm(kx, kz):
    t = TOW.translate((-7.75, 0)).scale((kx, kz)).translate((C / 2, 0))
    c = CEN.scale((C / 15.5, kz))
    return t + t.mirror((1, 0)) + c.offset(0.01, JoinType.Miter)


def frame_band(kx, kz, w=W_BAND):
    Si = silhouette_mm(kx, kz)
    hole = Si.offset(-w, JoinType.Miter, 12.0)
    J = J_M * kz
    legs = dd.rect(C / 2, C / 2 + w, -500, J + 1) + dd.rect(-C / 2 - w, -C / 2, -500, J + 1)
    b = (Si - hole) + (legs ^ Si)
    return b ^ dd.rect(-500, 500, 0, 500)


# ---------------------------------------------------------------- Raster-Helfer (2D, x/z)
def rasterize(cs, res=0.04, slope_deg=50.0, pad=1.0):
    """Even-odd-Raster einer CrossSection. Zeilenabstand so, dass 1 px seitlich pro Zeile = slope_deg."""
    from matplotlib.path import Path
    x0, z0, x1, z1 = cs.bounds()
    dz = res * np.tan(np.radians(slope_deg))
    xs = np.arange(x0 - pad, x1 + pad, res)
    zs = np.arange(max(0.0, z0 - pad) + dz / 2, z1 + pad, dz)
    X, Z = np.meshgrid(xs, zs)
    pts = np.c_[X.ravel(), Z.ravel()]
    inside = np.zeros(len(pts), bool)
    for p in cs.to_polygons():
        inside ^= Path(np.asarray(p)).contains_points(pts)
    return xs, zs, inside.reshape(Z.shape)


def vectorize(mask, xs, zs, grow=0.0):
    from matplotlib import pyplot as plt
    if not mask.any():
        return CrossSection()
    fig = plt.figure()
    cs = plt.contourf(xs, zs, mask.astype(float), levels=[0.5, 2.0])
    loops = []
    for path in cs.get_paths():
        for poly in path.to_polygons():
            if len(poly) >= 3:
                loops.append(np.asarray(poly))
    plt.close(fig)
    if not loops:
        return CrossSection()
    out = CrossSection(loops, FillRule.EvenOdd)
    return out.offset(grow, JoinType.Miter) if grow else out


def gussets(band, res=0.04, slope_deg=50.0):
    """Unterseiten im Band, die flacher als ~45° sind, bekommen Keile.
    Von oben nach unten: nicht gestützte Pixel werden eine Zeile tiefer, um 1 px Richtung
    nächstem Material versetzt, ergänzt -> 50°-Keil bis zur nächsten Wand."""
    xs, zs, M = rasterize(band, res, slope_deg)
    Mf = M.copy()
    add = np.zeros_like(M)
    n = M.shape[1]
    idx = np.arange(n)
    for r in range(M.shape[0] - 2, 0, -1):
        above = Mf[r + 1]
        cur = Mf[r]
        sup = cur.copy()
        sup[1:] |= cur[:-1]
        sup[:-1] |= cur[1:]
        U = above & ~sup
        if not U.any():
            continue
        last_left = np.maximum.accumulate(np.where(cur, idx, -10 ** 6))
        next_right = np.minimum.accumulate(np.where(cur, idx, 10 ** 6)[::-1])[::-1]
        u = np.nonzero(U)[0]
        q = np.where((idx - last_left)[u] <= (next_right - idx)[u], u - 1, u + 1)
        q = np.clip(q, 0, n - 1)
        cur = cur.copy()
        cur[q] = True
        Mf[r] = cur
        add[r, q] = True
    if not add.any():
        return band, 0.0
    G = vectorize(add, xs, zs, grow=0.03)
    return band + G, float(add.sum() * res * (zs[1] - zs[0]))


def support_trim(cs, res=0.04, slope_deg=50.0, from_ground=True, max_seed=1.0):
    """Nur den Teil behalten, der von unten mit <= 40° Überhang erreichbar ist.
    from_ground=True: Start am Boden z=0. Sonst: Start am tiefsten Punkt, aber nur wenn er
    spitz ist (unterste Pixelzeile <= max_seed mm breit) - dann ist es ein Kiel, der sich
    beim Druck wie eine kurze Brücke zwischen zwei Rahmen verhält."""
    if cs.is_empty():
        return cs
    xs, zs, M = rasterize(cs, res, slope_deg)
    K = np.zeros_like(M)
    if from_ground:
        seed = zs < 0.3
    else:
        rows = np.nonzero(M.any(1))[0]
        if not len(rows) or M[rows[0]].sum() * res > max_seed:
            return CrossSection()
        seed = np.zeros(len(zs), bool)
        seed[rows[0]] = True
    K[seed] = M[seed]
    for r in range(1, M.shape[0]):
        if seed[r]:
            continue
        prev = K[r - 1]
        if not prev.any():
            continue
        d = prev.copy()
        d[1:] |= prev[:-1]
        d[:-1] |= prev[1:]
        K[r] = M[r] & d
    return vectorize(K, xs, zs)


# ---------------------------------------------------------------- Aufbau
def cached_band(i):
    """Band + Keile, auf Platte zwischengespeichert (die Keil-Rasterung dauert ein paar Sekunden)."""
    import pickle
    import hashlib
    key = hashlib.md5(repr((round(KX[i], 5), round(KZ[i], 5), round(WB[i], 4), round(C, 5), 'v4')).encode()).hexdigest()[:12]
    p = os.path.join(OUT, 'cache', f'band_{key}.pkl')
    if os.path.exists(p):
        with open(p, 'rb') as fh:
            polys = pickle.load(fh)
        return CrossSection([np.asarray(q) for q in polys], FillRule.EvenOdd), None
    b = frame_band(KX[i], KZ[i], WB[i])
    b, g = gussets(b)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as fh:
        pickle.dump([np.asarray(q) for q in b.to_polygons()], fh)
    return b, g


def foot(cs):
    """0,5 mm in den Sockel hinein verlängern."""
    return cs + (cs ^ dd.rect(-500, 500, 0, 0.6)).translate((0, -0.5))


def yz_prism(cs_yz, x0, x1):
    """2D-Profil in (y, z) entlang x von x0 bis x1 extrudieren."""
    m = Manifold.extrude(cs_yz, x1 - x0)          # (a, b, c) mit c entlang Extrusion
    return m.transform(np.array([[0, 0, 1, x0], [1, 0, 0, 0], [0, 1, 0, 0]], dtype=float))


def build():
    t0 = time.time()
    bands = []
    for i in range(N):
        b, g = cached_band(i)
        bands.append(b)
        print(f'Rahmen {i}: kx={KX[i]:.3f} kz={KZ[i]:.3f} Band {WB[i]:.2f} mm  ({time.time() - t0:.1f}s)')
    ys = [i * D for i in range(N)]
    frames = [dd.extrude_y(foot(b), y, y + T) for b, y in zip(bands, ys)]

    # 1) verdeckte Innenwand: Überdeckung benachbarter Bänder in der Frontansicht
    walls = []
    ties = []
    for i in range(N - 1):
        ov = bands[i] ^ bands[i + 1]
        ov = ov.offset(-0.6, JoinType.Miter, 4.0).offset(0.6, JoinType.Miter, 4.0)
        comps = [c for c in ov.decompose() if c.area() > 6.0]
        keep = [c for c in comps if c.bounds()[1] < 0.5]
        # Kreuzungen der Turmhelme: verdeckte Kiel-Stege zwischen den Rahmen
        if i > 0:
            for c in comps:
                if c.bounds()[1] >= 0.5:
                    kc = support_trim(c, from_ground=False) ^ c.offset(-0.02, JoinType.Miter)
                    if not kc.is_empty():   # nur der untere, spitze Teil: ein schlanker Kiel
                        kb = kc.bounds()
                        kc = kc ^ dd.rect(-500, 500, kb[1] - 1, kb[1] + KEEL_H)
                    if kc.area() > 2.0:
                        ties.append(dd.extrude_y(kc, ys[i] + 0.1, ys[i + 1] + T - 0.1))
        if not keep:
            continue
        ov = CrossSection.batch_boolean(keep, OpType.Add)
        ov = foot((support_trim(ov) ^ ov.offset(-0.02, JoinType.Miter)) + (ov ^ dd.rect(-500, 500, 0, 0.6)))
        if ov.is_empty():
            continue
        top = ov.bounds()[3]
        y_start = ys[i] + T + GAP0 if i == 0 else ys[i] + 0.1
        wall = dd.extrude_y(ov, y_start, ys[i + 1] + T - 0.1)
        # Arkade: zwei Spitzbögen übereinander (Seitenansicht wie ein Langhaus-Joch)
        ya, yb = ys[i] + T + 1.1, ys[i + 1] - 1.1
        half = (yb - ya) / 2
        cy = (ya + yb) / 2
        z_split = 0.56 * top
        cut = dd.lancet(cy, half, 2.2, z_split - 1.8, k=1.6)
        if top - 4.5 - (z_split + 2.2) > 3 * half:
            cut = cut + dd.lancet(cy, half * 0.8, z_split + 2.2, top - 4.5, k=1.6)
        xw = C / 2 + max(WB) + 1.0
        wall = wall - yz_prism(cut, -xw, xw)
        print(f'  Innenwand {i}-{i + 1}: Höhe {top:.0f} mm')
        walls.append(wall)

    # 2) kleine Spitzbögen zwischen den Turm-Außenkanten (in gleicher Höhe für alle Rahmen)
    arches = []
    for i in range(1, N - 1):          # Rahmen 0 ist ein eigenes Teil, liegend gedruckt
        for z in Z_ARCH:
            xa = outer_band_x(bands[i], z)
            xb = outer_band_x(bands[i + 1], z)
            if xa is None or xb is None:
                continue
            ya, yb = ys[i] + T / 2, ys[i + 1] + T / 2
            span = np.hypot(yb - ya, xb - xa) / 2
            rise = span * np.tan(np.radians(ARCH_ANGLE))
            if outer_band_x(bands[i], z + rise + 2) is None or outer_band_x(bands[i + 1], z + rise + 2) is None:
                continue
            xm, ym = (xa + xb) / 2, (ya + yb) / 2
            s = ARCH_BAR
            def blk(x, y, zz):
                return dd.box(x - s / 2, x + s / 2, y - s / 2, y + s / 2, zz, zz + s)
            pa, pm, pb = blk(xa, ya, z), blk(xm, ym, z + rise), blk(xb, yb, z)
            ch = Manifold.batch_hull([pa, pm]) + Manifold.batch_hull([pm, pb])
            arches += [ch, ch.mirror((1, 0, 0))]

    print(f'  Kiel-Stege an Helm-Kreuzungen: {len(ties)}')
    echoes = Manifold.batch_boolean(frames[1:] + walls + ties + arches, OpType.Add).translate((0, 0, PLINTH))
    front = frames[0].translate((0, 0, PLINTH))

    # Sockel: Trapez (vorn schmal, hinten breit), obere Kante gefast
    xf = silhouette_mm(KX[0], KZ[0]).bounds()[2] + 6
    xb_ = silhouette_mm(KX[-1], KZ[-1]).bounds()[2] + 6
    y0, y1 = -7.0, ys[-1] + T + 7.0
    plinth = plinth_solid(xf, xb_, y0, y1, PLINTH, chamfer=1.6)
    # Domtreppe: drei Stufen vor der Westfassade
    for k, h in enumerate((PLINTH * 0.25, PLINTH * 0.5, PLINTH * 0.75)):
        yk = y0 - 2.2 * (3 - k)
        plinth = plinth + dd.box(-xf + 2.0, xf - 2.0, yk, y0 + 0.5, 0, h)
    # Steckfuge für den goldenen Front-Rahmen
    x0f = silhouette_mm(KX[0], KZ[0]).bounds()[2]
    slot = dd.box(-x0f - 0.6, x0f + 0.6, -GAP0, T + GAP0, PLINTH - SLOT, PLINTH + 1)
    plinth = plinth - slot
    foot_bar = dd.box(-x0f, x0f, 0, T, PLINTH - SLOT, PLINTH - 0.3)
    front = front + foot_bar
    print(f'Aufbau fertig ({time.time() - t0:.1f}s)')
    return dict(echoes=echoes + plinth, front=front, bands=bands, ys=ys)


def outer_band_x(band, z):
    """x-Mitte des äußersten rechten Bandstücks auf Höhe z."""
    from shapely.geometry import LineString
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    polys = [Polygon(p) for p in band.to_polygons()]
    # Even-odd-Fläche rekonstruieren
    geom = None
    for p in sorted(polys, key=lambda q: -q.area):
        geom = p if geom is None else geom.symmetric_difference(p)
    ln = LineString([(0, z), (500, z)])
    it = geom.intersection(ln)
    if it.is_empty:
        return None
    segs = list(getattr(it, 'geoms', [it]))
    segs = [s for s in segs if s.length > 0.5]
    if not segs:
        return None
    s = max(segs, key=lambda s: s.bounds[2])
    return 0.5 * (s.bounds[0] + s.bounds[2])


def plinth_solid(xf, xb, y0, y1, h, chamfer=1.5):
    """Trapez-Sockel (vorn schmal, hinten breit), obere Kante gefast."""
    def trap(off):
        return dd.poly([(-xf + off, y0 + off), (xf - off, y0 + off), (xb - off, y1 - off), (-xb + off, y1 - off)])
    lower = Manifold.extrude(trap(0), h - chamfer)
    upper = Manifold.extrude(trap(0), chamfer, scale_top=(1, 1))
    # Fase: Hülle aus unterer Kontur bei h-chamfer und eingerückter Kontur bei h
    a = Manifold.extrude(trap(0), 0.01).translate((0, 0, h - chamfer - 0.01))
    b = Manifold.extrude(trap(chamfer), 0.01).translate((0, 0, h - 0.01))
    top = Manifold.batch_hull([a, b])
    del upper
    return lower + top


def front_plot(bands, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path
    fig, ax = plt.subplots(figsize=(6, 10))
    n = len(bands)
    for i, b in reversed(list(enumerate(bands))):
        g = 0.12 + 0.55 * i / max(1, n - 1)
        verts, codes = [], []
        for p in b.to_polygons():
            p = np.asarray(p)
            verts += list(p) + [p[0]]
            codes += [Path.MOVETO] + [Path.LINETO] * (len(p) - 1) + [Path.CLOSEPOLY]
        ax.add_patch(PathPatch(Path(verts, codes), fc=(g, g, g), ec='none'))
    ax.set_xlim(-50, 50)
    ax.set_ylim(-2, 205)
    ax.set_aspect('equal')
    fig.savefig(path, dpi=110, bbox_inches='tight')
    plt.close(fig)


def overhang_plot(m, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties[:, :3])
    f = np.asarray(mesh.tri_verts)
    tri = v[f]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    a = np.linalg.norm(nrm, axis=1) / 2
    nrm = nrm / (2 * a[:, None] + 1e-12)
    down = (nrm[:, 2] < -0.72) & (tri[:, :, 2].min(1) > v[:, 2].min() + 0.05) & (a > 1e-3)
    c = tri[down].mean(1)
    fig, axs = plt.subplots(1, 2, figsize=(12, 10))
    axs[0].scatter(c[:, 0], c[:, 2], s=np.clip(a[down] * 20, 2, 80), c='r')
    axs[0].set_aspect('equal'); axs[0].set_title('Überhänge (x,z)')
    axs[1].scatter(c[:, 1], c[:, 2], s=np.clip(a[down] * 20, 2, 80), c='r')
    axs[1].set_aspect('equal'); axs[1].set_title('Überhänge (y,z)')
    fig.savefig(path, dpi=80)
    plt.close(fig)
    return c, a[down]


if __name__ == '__main__':
    R = build()
    model = R['echoes'] + R['front']
    os.makedirs(os.path.join(OUT, 'sketch'), exist_ok=True)
    front_plot(R['bands'], os.path.join(OUT, 'sketch', 'front2d.png'))
    ck = check(model)
    ck_e = check(R['echoes'])
    ck_f = check(R['front'])
    print('gesamt', json.dumps(ck))
    print('echo  ', json.dumps(ck_e))
    print('front ', json.dumps(ck_f))
    c, ar = overhang_plot(model, os.path.join(OUT, 'sketch', 'ueberhang.png'))
    for k in np.argsort(-ar)[:8]:
        print('  Überhang', np.round(c[k], 1), round(float(ar[k]), 2))
    with open(os.path.join(OUT, 'check.json'), 'w') as fh:
        json.dump(dict(gesamt=ck, echo=ck_e, front=ck_f), fh, indent=1)


def views_main():
    return [
        dict(name='hero', az=-35, el=14, zoom=1.0),
        dict(name='front', az=0, el=4, zoom=1.0),
        dict(name='side', az=-90, el=5, zoom=1.0),
        dict(name='back', az=-150, el=24, zoom=1.0),
    ]


def do_render(A, B=None, palette='abendgold', bands_z=(70, 185), tag='', views=None, echo=True):
    zmax = A.bounding_box()[5]
    bands = gradient_bands(bands_z[0], bands_z[1], zmax, run=2) if bands_z else []
    write_preview(OUT, A, B, bands)
    paths = render(OUT, views or views_main(), palette=palette)
    if echo:
        paths += render(OUT, [dict(name='echo', az=0, el=12, zoom=1.05, ty=0.5)], palette=palette,
                        bg='#1a1b1e', extra={'BACKLIGHT': 4})
    if tag:
        new = []
        for p in paths:
            q = p.replace('.png', f'_{tag}.png')
            os.replace(p, q)
            new.append(q)
        paths = new
    print('\n'.join(paths))
    return paths, len(bands)


ECHO_VIEW = dict(name='echo', az=0, el=9, zoom=1.0, ty=0.5, fov=16)


if __name__ == '__main__' and 'render' in sys.argv:
    A, B = R['echoes'], R['front']
    write_preview(OUT, A, B, [])
    out = render(OUT, views_main()[:3], palette='abendgold')
    out += render(OUT, [ECHO_VIEW], palette='abendgold', bg='#17181b', extra={'BACKLIGHT': 4})
    out += render(OUT, [dict(name='hero_bronze', az=-32, el=12, zoom=1.0)], palette='bronze', bg='#17181b',
                  extra={'BACKLIGHT': 3})
    out += render(OUT, [dict(name='detail', az=-58, el=6, zoom=1.7, ty=0.32)], palette='abendgold')
    print('\n'.join(out))
