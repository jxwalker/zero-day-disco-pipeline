"""Static overlay assets for the render: cover glow, spectrum and waveform gradients.
usage: make_assets.py WORK_DIR"""
import sys, os
from PIL import Image, ImageDraw, ImageFilter
work = sys.argv[1]


def grad(w, h, stops):
    im = Image.new('RGBA', (w, h))
    px = im.load()
    for x in range(w):
        t = x / (w - 1)
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0]:
                a, b = stops[i], stops[i + 1]
                u = (t - a[0]) / (b[0] - a[0] or 1)
                c = tuple(int(a[1][k] + (b[1][k] - a[1][k]) * u) for k in range(3)) + (255,)
                break
        for y in range(h):
            px[x, y] = c
    return im


PINK, YEL, CYAN, PURP = (255, 46, 151), (255, 225, 77), (0, 229, 255), (123, 44, 255)
grad(1000, 200, [(0, PINK), (0.3, YEL), (0.65, CYAN), (1, CYAN)]).save(os.path.join(work, 'specgrad.png'))
grad(1000, 80, [(0, CYAN), (0.5, PURP), (1, CYAN)]).save(os.path.join(work, 'wavegrad.png'))
# glow: soft pink rounded square behind the 640px cover (placed at 40,120 -> centre 540,620)
g = Image.new('RGBA', (1000, 1000), (0, 0, 0, 0))
d = ImageDraw.Draw(g)
d.rounded_rectangle([150, 150, 850, 850], radius=40, fill=PINK + (235,))
g = g.filter(ImageFilter.GaussianBlur(38))
d = ImageDraw.Draw(g)
d.rounded_rectangle([170, 170, 830, 830], radius=24, fill=PINK + (255,))
g.save(os.path.join(work, 'glow.png'))
print('assets ok')
