import sys; sys.path.insert(0, '/tmp/claude-0/-home-user-taste-skill/d46f1633-345d-5b87-803e-a453b1fd4c0a/scratchpad/kit'); from proto_kit import *
import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path
core = dd.sym(dd.nave_half(False))
center = core ^ dd.rect(-7.75, 7.75, -1, 100)
F = Manifold.batch_boolean([dd.tower(-1), dd.tower(1), dd.extrude_y(center, 0, 23.5), dd.pinnacle(0, 1.3, 1.6, 55, 63, 70)], OpType.Add)
S = front_silhouette(F)
S = S + dd.rect(-8.4, 8.4, 0, 46) + dd.sym(dd.rect(7.75, 9.0, 0, 63))
S = S + dd.rect(-30.75, 30.75, -300, 0.01)
TOW = S ^ dd.rect(7.75, 100, -400, 400)
CEN = S ^ dd.rect(-7.75, 7.75, -400, 400)

def frame(kx, kz, C, w):
    # Turm rechts: um Innenkante skaliert
    t = TOW.translate((-7.75, 0)).scale((kx, kz)).translate((C / 2, 0))
    c = CEN.scale((C / 15.5, kz))
    Si = t + t.mirror((1, 0)) + c.offset(0.01, JoinType.Miter)
    hole = Si.offset(-w, JoinType.Miter, 2.0)
    J = 46.07 * kz
    legs = dd.rect(C / 2, C / 2 + w, -500, J + 1) + dd.rect(-C / 2 - w, -C / 2, -500, J + 1)
    b = (Si - hole) + (legs ^ Si)
    return b ^ dd.rect(-500, 500, 0, 500)

def draw(ax, frames):
    n = len(frames)
    for i, b in reversed(list(enumerate(frames))):
        g = 0.12 + 0.55 * i / max(1, n - 1)
        verts, codes = [], []
        for p in b.to_polygons():
            p = np.asarray(p); verts += list(p) + [p[0]]; codes += [Path.MOVETO] + [Path.LINETO] * (len(p) - 1) + [Path.CLOSEPOLY]
        ax.add_patch(PathPatch(Path(verts, codes), fc=(g, g, g), ec='none'))
    ax.set_xlim(-65, 65); ax.set_ylim(-5, 215); ax.set_aspect('equal'); ax.axis('off')

H = 157.4
cf = {}
# V1: gleichmäßig
ks = np.linspace(0.55, 1.27, 6); C = 15.5 * 0.55 * 1.15
cf['V1 gleich'] = [frame(k, k, C, 2.6) for k in ks]
# V2: kx wächst schneller
kz = np.linspace(0.6, 1.27, 6); kx = np.linspace(0.6, 1.55, 6); C = 15.5 * 0.6 * 1.1
cf['V2 breiter'] = [frame(a, b, C, 2.6) for a, b in zip(kx, kz)]
# V3: 5 Rahmen, größere Schritte
kz = np.linspace(0.5, 1.27, 5); kx = np.linspace(0.5, 1.45, 5); C = 15.5 * 0.5 * 1.15
cf['V3 fuenf'] = [frame(a, b, C, 2.8) for a, b in zip(kx, kz)]
# V4: 7 Rahmen, dünner
kz = np.linspace(0.55, 1.27, 7); kx = np.linspace(0.55, 1.6, 7); C = 15.5 * 0.55 * 1.1
cf['V4 sieben'] = [frame(a, b, C, 2.2) for a, b in zip(kx, kz)]
fig, axs = plt.subplots(1, len(cf), figsize=(5 * len(cf), 8))
for ax, (n, fr) in zip(axs, cf.items()):
    draw(ax, fr); ax.set_title(n)
    print(n, [round(f.bounds()[2]*2) for f in fr], [round(f.bounds()[3]) for f in fr])
fig.savefig('sketch/vergleich2.png', dpi=80, bbox_inches='tight')
