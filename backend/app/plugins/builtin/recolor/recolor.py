"""Part-wise palette recolour in CIE Lab, pure numpy (the shim runs plugins isolated, so the Lab
helpers live here rather than being imported from `app`).

A part keeps its lightness detail (L minus the part's mean L); its mean L moves partway toward
the target colour's L and its a/b become the target's. Seams between parts are feathered a
couple of pixels; pixels outside every part are never touched."""

import itertools
import random

import numpy as np

# ---- colour ------------------------------------------------------------------------------

_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]], np.float32)  # fmt: skip
_M_INV = np.linalg.inv(_M).astype(np.float32)
_WHITE = np.array([0.95047, 1.0, 1.08883], np.float32)
_D = 6 / 29
_LIN = np.where(
    (c := np.arange(256, dtype=np.float64) / 255) <= 0.04045,
    c / 12.92,
    ((c + 0.055) / 1.055) ** 2.4,
).astype(np.float32)
_GAMMA_STEPS = 16384
_GAMMA = np.round(
    255
    * np.where(
        (g := np.linspace(0, 1, _GAMMA_STEPS + 1)) <= 0.0031308,
        12.92 * g,
        1.055 * g ** (1 / 2.4) - 0.055,
    )
).astype(np.uint8)


def rgb_to_lab(rgb):
    """uint8 RGB (..., 3) to float32 Lab (..., 3), D65."""
    xyz = _LIN[np.asarray(rgb, np.uint8)] @ _M.T / _WHITE
    f = np.where(xyz > _D**3, np.cbrt(xyz), xyz / (3 * _D * _D) + 4 / 29)
    lab = np.empty_like(f)
    lab[..., 0] = 116 * f[..., 1] - 16
    lab[..., 1] = 500 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200 * (f[..., 1] - f[..., 2])
    return lab


def lab_to_rgb(lab):
    """float Lab (..., 3) to uint8 RGB, out-of-gamut values clipped."""
    lab = np.asarray(lab, np.float32)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], axis=-1)
    xyz = np.where(f > _D, f**3, 3 * _D * _D * (f - 4 / 29)) * _WHITE
    lin = np.clip(xyz @ _M_INV.T, 0, 1)
    return _GAMMA[np.round(lin * _GAMMA_STEPS).astype(np.int32)]


def parse_hex(h):
    """'#rrggbb' or '#rgb' to an (r, g, b) tuple; ValueError otherwise."""
    if not isinstance(h, str) or not h.startswith("#") or len(h) not in (4, 7):
        raise ValueError(f"not a hex colour: {h!r}")
    body = h[1:] if len(h) == 7 else "".join(ch * 2 for ch in h[1:])
    return tuple(int(body[i : i + 2], 16) for i in (0, 2, 4))


def norm_hex(h):
    """'#rrggbb', lower case, for any colour `parse_hex` accepts."""
    r, g, b = parse_hex(h)
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_lab(h):
    return rgb_to_lab(np.array([parse_hex(h)], np.uint8))[0]


def parse_palette(value):
    """(name, distinct #rrggbb colours) of a palette param; ValueError in plain words."""
    value = value if isinstance(value, dict) else {}
    colors = value.get("colors")
    if not isinstance(colors, list) or not 2 <= len(colors) <= 8:
        raise ValueError("A palette needs 2 to 8 colours")
    # one entry per colour: "#ABC" and "#aabbcc" are the same swatch
    unique = list(dict.fromkeys(norm_hex(c) for c in colors))
    if len(unique) < 2:
        raise ValueError("A palette needs at least 2 different colours")
    name = value.get("name") if isinstance(value.get("name"), str) else ""
    return name.strip() or "Palette", unique


# ---- regions -----------------------------------------------------------------------------


def label_map(masks):
    """Int map of the masks' indices, -1 where no mask covers a pixel. Where masks overlap the
    smallest one wins (laces over the upper); equal areas go to the earlier mask."""
    if not masks:
        raise ValueError("no masks")
    labels = np.full(np.shape(masks[0]), -1, np.int32)
    areas = [int(np.count_nonzero(m)) for m in masks]
    for i in sorted(range(len(masks)), key=lambda i: (-areas[i], -i)):
        labels[np.asarray(masks[i], bool)] = i
    return labels


def _box_sum(x, r, axis):
    """Sum over a 2r+1 window along axis 0 or 1, edges replicated."""
    pad = [(0, 0)] * x.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(x, pad, mode="edge"), axis=axis, dtype=np.float32)
    n = x.shape[axis]
    if axis == 0:
        return c[2 * r + 1 : 2 * r + 1 + n] - c[:n]
    return c[:, 2 * r + 1 : 2 * r + 1 + n] - c[:, :n]


def box_blur(x, r):
    """Mean over a (2r+1)^2 square, edges replicated."""
    if r <= 0:
        return np.asarray(x, np.float32)
    x = np.asarray(x, np.float32)
    return _box_sum(_box_sum(x, r, 0), r, 1) / float((2 * r + 1) ** 2)


def _crop(labels, margin):
    """Slices of the bounding box of every labelled pixel, grown by `margin`."""
    ys, xs = np.nonzero(labels >= 0)
    if len(ys) == 0:
        return slice(0, 0), slice(0, 0)
    h, w = labels.shape
    return (slice(max(0, ys.min() - margin), min(h, ys.max() + 1 + margin)),
            slice(max(0, xs.min() - margin), min(w, xs.max() + 1 + margin)))  # fmt: skip


def adjacency(labels, n, dilate_px=3):
    """Pairs (i, j), i < j, of parts whose regions overlap once each is dilated `dilate_px`."""
    ys, xs = _crop(labels, dilate_px + 1)
    sub = labels[ys, xs]
    grown = [box_blur(sub == i, dilate_px) > 1e-6 for i in range(n)]
    return {(i, j) for i, j in itertools.combinations(range(n), 2) if (grown[i] & grown[j]).any()}


# ---- assignments -------------------------------------------------------------------------

ENUMERATE_UP_TO = 20_000  # colourings of the whole space; beyond this they are sampled
SAMPLES = 4_000


def _repeats(a, touching):
    return sum(a[i] == a[j] for i, j in touching)


def _greedy(rng, n_parts, n_colors, neighbours):
    """A random colouring that avoids neighbours' colours where it can."""
    a = [-1] * n_parts
    order = list(range(n_parts))
    rng.shuffle(order)
    for i in order:
        used = {a[j] for j in neighbours[i] if a[j] >= 0}
        free = [c for c in range(n_colors) if c not in used]
        a[i] = rng.choice(free or list(range(n_colors)))
    return tuple(a)


def assignments(n_parts, n_colors, touching, count, seed):
    """Up to `count` distinct colourings (a palette index per part), the same list for the same
    seed. When the palette can keep every touching pair apart only such colourings are given
    (so fewer may come back); otherwise those with the fewest touching repeats come first.
    Among equals, colourings that use more of the palette come first."""
    if n_parts <= 0 or n_colors <= 0 or count <= 0:
        return []
    rng = random.Random(seed)
    if n_colors**n_parts <= ENUMERATE_UP_TO:
        pool = list(itertools.product(range(n_colors), repeat=n_parts))
    else:
        neighbours = {i: set() for i in range(n_parts)}
        for i, j in touching:
            neighbours[i].add(j)
            neighbours[j].add(i)
        seen = set()
        pool = []
        for _ in range(SAMPLES):
            a = _greedy(rng, n_parts, n_colors, neighbours)
            if a not in seen:
                seen.add(a)
                pool.append(a)
    rng.shuffle(pool)
    pool.sort(key=lambda a: (_repeats(a, touching), -len(set(a))))
    if pool and _repeats(pool[0], touching) == 0:
        pool = [a for a in pool if _repeats(a, touching) == 0]
    return pool[:count]


# ---- recolour ----------------------------------------------------------------------------


class Recolorer:
    """Precomputes the Lab picture and part weights once, so many colourings of the same picture
    are cheap. Work is done only on the pixels inside some part.

    A part's own pixels are fully its colour, so thin parts (laces) and edges against the
    background recolour completely. Where two parts meet, the smaller part's colour is feathered
    `feather_px` into the larger one, the same way round as the label map resolves overlaps."""

    def __init__(self, rgb, labels, feather_px=2):
        self.rgb = np.asarray(rgb, np.uint8)
        self.n = int(labels.max()) + 1 if labels.size else 0
        ys, xs = _crop(labels, feather_px + 1)
        self.ys, self.xs = ys, xs
        sub = labels[ys, xs]
        inside = sub >= 0
        self.idx = np.flatnonzero(inside)
        lab = rgb_to_lab(self.rgb[ys, xs]).reshape(-1, 3)[self.idx]
        self.lab = lab
        flat = sub.reshape(-1)[self.idx]
        own = [flat == i for i in range(self.n)]
        self.mean_l = [float(lab[own[i], 0].mean()) if own[i].any() else 0.0
                       for i in range(self.n)]  # fmt: skip
        areas = [int(o.sum()) for o in own]
        rank = np.empty(self.n + 1, np.int32)  # smallest part first; rank[-1] for no part
        rank[sorted(range(self.n), key=lambda i: (areas[i], i))] = np.arange(self.n)
        rank[self.n] = -1
        pixel_rank = rank[flat]
        blur = [box_blur(sub == i, feather_px).reshape(-1)[self.idx] for i in range(self.n)]
        # weight of a smaller neighbour's colour that a pixel takes (0 inside the smallest part)
        taken = np.zeros(len(self.idx), np.float32)
        for i in range(self.n):
            taken += np.where(pixel_rank > rank[i], blur[i], 0)
        self.weights = [np.where(own[i], 1 - taken, np.where(pixel_rank > rank[i], blur[i], 0))
                        .astype(np.float32) for i in range(self.n)]  # fmt: skip

    def apply(self, colors, l_pull=0.6):
        """A copy of the picture with part i in colour colors[i] (hex); other parts untouched."""
        out = self.rgb.copy()
        if not colors or len(self.idx) == 0:
            return out
        lab = self.lab
        new = lab.copy()
        for i, h in colors.items():
            if not 0 <= i < self.n:
                continue
            w = self.weights[i]
            t = hex_to_lab(h)
            new[:, 0] += w * (l_pull * (float(t[0]) - self.mean_l[i]))
            new[:, 1] += w * (float(t[1]) - lab[:, 1])
            new[:, 2] += w * (float(t[2]) - lab[:, 2])
        region = out[self.ys, self.xs].reshape(-1, 3)
        region[self.idx] = lab_to_rgb(new)
        out[self.ys, self.xs] = region.reshape(out[self.ys, self.xs].shape)
        return out


def recolor(rgb, labels, colors, feather_px=2, l_pull=0.6):
    """`rgb` with each part i in `colors` ({part index: hex}) recoloured; see the module doc."""
    return Recolorer(rgb, labels, feather_px).apply(colors, l_pull)
