import sys; sys.path.insert(0, '/tmp/claude-0/-home-user-taste-skill/d46f1633-345d-5b87-803e-a453b1fd4c0a/scratchpad/kit'); from proto_kit import *
import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path
core = dd.sym(dd.nave_half(False))
center = core ^ dd.rect(-7.75, 7.75, -1, 100)
F = Manifold.batch_boolean([dd.tower(-1), dd.tower(1), dd.extrude_y(center, 0, 23.5), dd.pinnacle(0, 1.3, 1.6, 55, 63, 70)], OpType.Add)
S = front_silhouette(F)
S = S + dd.rect(-8.4, 8.4, 30, 47)   # Kerbe an der Turminnenseite schließen
S = S + dd.rect(-30.75, 30.75, -300, 0.01)  # nach unten verlängern (offener Rahmen)

def band(k, zc_m, zc_mm, w, legs=True):
    """Silhouette in mm: Punkt (0, zc_m) -> (0, zc_mm), Maßstab k mm/m."""
    Si = S.translate((0, -zc_m)).scale((k, k)).translate((0, zc_mm))
    hole = Si.offset(-w, JoinType.Miter, 2.0)
    b = Si - hole
    if legs:
        for sx in (-1, 1):
            x0 = sx * 7.75 * k
            b = b + (Si ^ dd.rect(min(x0, x0 + sx * w), max(x0, x0 + sx * w), -500, zc_mm + (46 - zc_m) * k + 1))
    return b ^ dd.rect(-500, 500, 0, 500)

def draw(ax, frames):
    n = len(frames)
    for i, b in reversed(list(enumerate(frames))):
        g = 0.15 + 0.5 * i / max(1, n - 1)
        verts, codes = [], []
        for p in b.to_polygons():
            p = np.asarray(p); verts += list(p) + [p[0]]; codes += [Path.MOVETO] + [Path.LINETO] * (len(p) - 1) + [Path.CLOSEPOLY]
        ax.add_patch(PathPatch(Path(verts, codes), fc=(g, g, g), ec='none'))
    ax.set_xlim(-130, 130); ax.set_ylim(-5, 225); ax.set_aspect('equal'); ax.axis('off')

H = 157.4
cfgs = {}
# A: Skalierung um Fußpunkt Mitte
ks = np.linspace(0.45, 1.0, 6) * 200 / H
cfgs['A_fuss'] = [band(k, 0, 0, 3.0) for k in ks]
# B: Zentrum Giebel (60 m), kleinster Rahmen steht auf dem Boden
k0 = 0.62 * 200 / H; zc = 60 * k0
kN = (205 - zc) / (H - 60)
cfgs['B_giebel'] = [band(k, 60, zc, 3.0) for k in np.linspace(k0, kN, 6)]
# C: Zentrum Portal (25 m)
k0 = 0.5 * 200 / H; zc = 25 * k0; kN = (205 - zc) / (H - 25)
cfgs['C_portal'] = [band(k, 25, zc, 3.0) for k in np.linspace(k0, kN, 6)]
# D: Zentrum 40 m, geometrisch
k0 = 0.42 * 200 / H; zc = 40 * k0; kN = (205 - zc) / (H - 40)
cfgs['D_geo'] = [band(k, 40, zc, 3.0) for k in np.geomspace(k0, kN, 7)]
fig, axs = plt.subplots(1, len(cfgs), figsize=(5 * len(cfgs), 5))
for ax, (n, fr) in zip(axs, cfgs.items()):
    draw(ax, fr); ax.set_title(n)
    print(n, [round(f.bounds()[2]*2) for f in fr], [round(f.bounds()[3]) for f in fr])
fig.savefig('sketch/vergleich.png', dpi=110, bbox_inches='tight')
fig, axs = plt.subplots(1, 4, figsize=(16, 9))
for ax, (n, fr) in zip(axs, cfgs.items()):
    draw(ax, fr); ax.set_title(n); ax.set_xlim(-65, 65)
fig.savefig('sketch/vergleich_gross.png', dpi=80, bbox_inches='tight')
