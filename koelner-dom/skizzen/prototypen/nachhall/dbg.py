import sys; sys.argv=['x','nogusset']
exec(open('build.py').read().split("if __name__ == '__main__':")[0])
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
b = frame_band(KX[0], KZ[0])
fig, axs = plt.subplots(1,3, figsize=(15,6))
for ax, (xl, zl) in zip(axs, [((-8, 12), (15, 45)), ((5, 25), (45, 75)), ((5, 20), (75, 100))]):
    for p in b.to_polygons():
        p = np.vstack([p, p[:1]]); ax.plot(p[:,0], p[:,1], 'k.-', lw=0.8, ms=3)
    ax.set_xlim(*xl); ax.set_ylim(*zl); ax.set_aspect('equal'); ax.grid(True)
fig.savefig('sketch/dbg_band0.png', dpi=80, bbox_inches='tight')
