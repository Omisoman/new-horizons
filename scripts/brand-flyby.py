#!/usr/bin/env python3
"""New Horizons header mark: a halftone planet, a probe on a swing-by arc, a horizon.
Pure SVG + CSS/SMIL (no JS). Generates dark + light variants and a static one.

    uv run python scripts/brand-flyby.py              # write assets/brand/newhorizons-flyby*.svg
    uv run python scripts/brand-flyby.py --check      # exit 1 if a committed file drifted
    uv run python scripts/brand-flyby.py --out DIR    # write elsewhere (tests)

The drawing is design/flyby.py's, unchanged (stdlib, seeded): the sidebar inlines
the dark file (Black and Gray themes) or the light one (White); README and docs use
the static one. Never edit the SVGs by hand — change this and re-run."""
import math, pathlib, random, sys

random.seed(7)
W, H = 400, 150
CX, CY, R = 200, 62, 44          # planet

def halftone():
    """Dots on a grid inside the planet; size follows a lighting term so the sphere reads as lit from the upper left."""
    out = []
    pitch = 5.2
    for gy in range(-R, R + 1, int(pitch)):
        for gx in range(-R, R + 1, int(pitch)):
            d = math.hypot(gx, gy)
            if d > R - 1.5: continue
            nz = math.sqrt(max(0.0, 1 - (d / R) ** 2))          # sphere normal z
            nx, ny = gx / R, gy / R
            light = max(0.0, (-0.55 * nx - 0.55 * ny + 0.63 * nz))  # lit from upper-left
            r = 0.5 + 2.0 * light ** 1.1
            # a lighter lobe on the lower right (a region, not a copy of anything real)
            if math.hypot(gx - 14, gy + 10) < 16: r *= 1.25
            out.append((CX + gx, CY + gy, r))
    return out

def stars(n=26):
    pts = []
    while len(pts) < n:
        x, y = random.uniform(6, W - 6), random.uniform(4, 96)
        if math.hypot(x - CX, y - CY) < R + 10: continue
        pts.append((x, y, random.choice([0.6, 0.8, 1.0, 1.2]), random.uniform(0, 6)))
    return pts

def svg(theme="dark", animate=True):
    fg = "#ffffff" if theme == "dark" else "#1b1b1b"
    dim = "#8a8b8e"
    hal = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.2f}"/>' for x, y, r in halftone())
    sts = "".join(
        f'<circle class="s" cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" style="--t:{t:.2f}s"/>' for x, y, r, t in stars())
    # swing-by arc: enters top-left, passes behind the planet's lower edge, exits right
    arc = f"M -20 28 C 90 20, 150 118, {CX} 112 S 330 70, 430 22"
    anim = ""
    if animate:
        anim = f"""
<style>
.nh *{{transform-box:fill-box}}
.nh .term{{animation:nh-rot 14s linear infinite;transform-origin:{CX}px {CY}px}}
@keyframes nh-rot{{to{{transform:rotate(360deg)}}}}
.nh .s{{animation:nh-tw 4.5s ease-in-out infinite;animation-delay:var(--t)}}
@keyframes nh-tw{{0%,100%{{opacity:.25}}50%{{opacity:1}}}}
.nh .trail{{stroke-dasharray:64 489;animation:nh-trail 12s linear infinite}}
@keyframes nh-trail{{from{{stroke-dashoffset:64}}to{{stroke-dashoffset:-489}}}}
.nh .ping{{animation:nh-ping 12s linear infinite;transform-origin:center}}
@keyframes nh-ping{{0%,52%{{opacity:0;transform:scale(.2)}}55%{{opacity:.9}}66%{{opacity:0;transform:scale(2.6)}}100%{{opacity:0}}}}
.nh .word{{animation:nh-in 1.6s ease-out both}}
@keyframes nh-in{{from{{opacity:0;letter-spacing:.9em}}to{{opacity:1;letter-spacing:.42em}}}}
@media (prefers-reduced-motion:reduce){{.nh .term,.nh .s,.nh .trail,.nh .ping,.nh .word{{animation:none}} .nh .s{{opacity:.7}} .nh .trail{{stroke-dasharray:none;stroke-opacity:.25}}}}
</style>"""
    motion = (f'<animateMotion dur="12s" repeatCount="indefinite" rotate="auto" path="{arc}" '
              f'keyPoints="0;1" keyTimes="0;1" calcMode="linear"/>') if animate else ""
    probe_static = "" if animate else f'transform="translate(300 70) rotate(-25)"'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="nh" role="img" aria-label="New Horizons">
<defs>
  <clipPath id="nh-planet"><circle cx="{CX}" cy="{CY}" r="{R}"/></clipPath>
  <linearGradient id="nh-hz" x1="0" x2="1"><stop offset="0" stop-color="{fg}" stop-opacity="0"/><stop offset=".5" stop-color="{fg}" stop-opacity=".55"/><stop offset="1" stop-color="{fg}" stop-opacity="0"/></linearGradient>
  <radialGradient id="nh-glow" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="{fg}" stop-opacity=".16"/><stop offset="1" stop-color="{fg}" stop-opacity="0"/></radialGradient>
  <linearGradient id="nh-tr" x1="0" x2="1"><stop offset="0" stop-color="{fg}" stop-opacity="0"/><stop offset="1" stop-color="{fg}" stop-opacity=".9"/></linearGradient>
</defs>{anim}
<g fill="{fg}">{sts}</g>
<circle cx="{CX}" cy="{CY}" r="{R + 8}" fill="url(#nh-glow)"/>
<g clip-path="url(#nh-planet)">
  <g fill="{fg}">{hal}</g>
  <g class="term" opacity=".72"><path d="M {CX} {CY - R - 2} A {R + 2} {R + 2} 0 0 1 {CX} {CY + R + 2} L {CX - R - 2} {CY + R + 2} L {CX - R - 2} {CY - R - 2} Z" fill="#000" style="mix-blend-mode:multiply" opacity="0"/>
    <ellipse cx="{CX - 26}" cy="{CY}" rx="34" ry="{R + 2}" fill="{('#0a0a0a' if theme == 'dark' else '#ffffff')}" opacity=".55"/></g>
</g>
<circle cx="{CX}" cy="{CY}" r="{R}" fill="none" stroke="{fg}" stroke-opacity=".35" stroke-width=".8"/>
<path d="M 20 {CY + R + 22} Q {CX} {CY + R + 2} {W - 20} {CY + R + 22}" fill="none" stroke="url(#nh-hz)" stroke-width="1.2"/>
<path d="{arc}" fill="none" stroke="{fg}" stroke-opacity=".10" stroke-width=".7" stroke-dasharray="2 5"/>
<path class="trail" d="{arc}" fill="none" stroke="{fg}" stroke-opacity=".75" stroke-width="1.2" stroke-linecap="round"/>
<g {probe_static}>
  <g>
    <circle class="ping" r="7" fill="none" stroke="{fg}" stroke-width=".8" opacity="0"/>
    <path d="M -6 0 L 2 -3 L 6 0 L 2 3 Z" fill="{fg}"/>
    <rect x="-1.5" y="-7" width="3" height="14" fill="{fg}" opacity=".85"/>
    {motion}
  </g>
</g>
<text class="word" x="{CX}" y="{H - 14}" text-anchor="middle" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="15" font-weight="600" letter-spacing=".42em" fill="{fg}">NEW HORIZONS</text>
</svg>"""


FILES = {"newhorizons-flyby.svg": ("dark", True), "newhorizons-flyby-light.svg": ("light", True),
         "newhorizons-flyby-static.svg": ("dark", False)}


def render() -> dict[str, str]:
    """All three files, in the generator's order (the star field draws from one seeded
    stream, so the order is part of the output)."""
    random.seed(7)
    return {name: svg(theme, animate) for name, (theme, animate) in FILES.items()}


def main(argv: list[str]) -> int:
    out = pathlib.Path(argv[argv.index("--out") + 1]) if "--out" in argv else \
        pathlib.Path(__file__).resolve().parents[1] / "assets" / "brand"
    drift = []
    for name, text in render().items():
        path = out / name
        if path.exists() and path.read_text() == text:
            continue
        drift.append(name)
        if "--check" not in argv:
            out.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    for name in drift:
        print(f"{'drifted' if '--check' in argv else 'written'}: {out / name}")
    if not drift:
        print("flyby: all files up to date")
    return 1 if drift and "--check" in argv else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
