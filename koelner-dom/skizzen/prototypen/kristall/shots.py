"""Finale Renderings für Domkristall (nach build.py ausführen)."""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from crystal_lib import render  # noqa: E402

BASALT_GOLD = dict(a='#3e4043', b='#d4a645', mA=0.6, rA=0.5, mB=0.8, rB=0.2)      # Iron Gray Metallic + Gold Silk+
BERGKRISTALL = dict(a='#3e4043', b='#aeb2b9', mA=0.6, rA=0.5, mB=0.92, rB=0.14)   # Iron Gray Metallic + Silver Silk+

if __name__ != '__main__':
    raise SystemExit
out = []
out += render(HERE, [dict(name='hero', az=-35, el=14, zoom=1.22),
                     dict(name='front', az=0, el=4, zoom=1.25),
                     dict(name='side', az=-90, el=5, zoom=1.2)],
              palette=BASALT_GOLD, bg='#1c1d20', extra={'BACKLIGHT': 2.5})
out += render(HERE, [dict(name='money', az=-22, el=3, zoom=1.38, ty=0.5, fov=22),
                     dict(name='money_b', az=-62, el=4, zoom=1.2, ty=0.45, fov=24)],
              palette=BASALT_GOLD, bg='#0b0c0e', extra={'BACKLIGHT': 12, 'EXPOSURE': 0.85})
tmp = render(HERE, [dict(name='hero_tmp', az=-35, el=14, zoom=1.22)], palette=BERGKRISTALL, bg='#1c1d20',
             extra={'BACKLIGHT': 2.5})
dst = os.path.join(HERE, 'shots', 'hero_bergkristall.png')
shutil.move(tmp[0], dst)
out.append(dst)
print('\n'.join(os.path.abspath(p) for p in out))
