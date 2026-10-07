import sys; sys.path.insert(0, '/tmp/claude-0/-home-user-taste-skill/d46f1633-345d-5b87-803e-a453b1fd4c0a/scratchpad/kit'); from proto_kit import *
import numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
core = dd.sym(dd.nave_half(False))
center = core ^ dd.rect(-7.75, 7.75, -1, 100)
F = Manifold.batch_boolean([dd.tower(-1), dd.tower(1), dd.extrude_y(center, 0, 23.5), dd.pinnacle(0, 1.3, 1.6, 55, 63, 70)], OpType.Add)
S = front_silhouette(F)
print(S.bounds(), S.area(), S.num_contour(), S.num_vert())
for p in S.to_polygons():
    p=np.asarray(p); print(len(p))
np.save('sil_pts.npy', np.array(S.to_polygons()[0]))
fig,ax=plt.subplots(figsize=(4,10))
for p in S.to_polygons():
    p=np.vstack([p,p[:1]]); ax.plot(p[:,0],p[:,1],'k-',lw=0.6)
ax.set_aspect('equal'); fig.savefig('sketch/sil.png',dpi=120)
# print right tower vertices x>0 sorted by z
p=np.asarray(S.to_polygons()[0]); q=p[p[:,0]>0]; 
for v in q[np.argsort(q[:,1])]: print(np.round(v,2))
