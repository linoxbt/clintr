"""Generate Clintr's transparent, vector signal field for the landing page."""
from math import exp, pi, sin
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
target = ROOT / "web" / "signal-field.svg"
width = 940
height = 880

lines = [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 940 880" fill="none" role="img" aria-labelledby="title desc">',
    '<title id="title">Clintr signal field</title>',
    '<desc id="desc">A woven field of green, cyan, and violet lines converges into a narrow center, then opens outward.</desc>',
    '<defs>',
    '<linearGradient id="spectrum" x1="0" y1="0" x2="940" y2="880" gradientUnits="userSpaceOnUse"><stop stop-color="#49B6A0"/><stop offset=".39" stop-color="#B6F13E"/><stop offset=".7" stop-color="#9AD6D5"/><stop offset="1" stop-color="#8E84DF"/></linearGradient>',
    '<radialGradient id="halo"><stop stop-color="#B6F13E" stop-opacity=".24"/><stop offset=".65" stop-color="#B6F13E" stop-opacity=".05"/><stop offset="1" stop-color="#B6F13E" stop-opacity="0"/></radialGradient>',
    '<linearGradient id="fade" x1="0" y1="0" x2="940" y2="0" gradientUnits="userSpaceOnUse"><stop stop-color="white" stop-opacity="0"/><stop offset=".12" stop-color="white"/><stop offset=".87" stop-color="white"/><stop offset="1" stop-color="white" stop-opacity="0"/></linearGradient>',
    '<mask id="field-mask"><path fill="url(#fade)" d="M0 0h940v880H0z"/></mask>',
    '</defs>',
    '<ellipse cx="492" cy="435" rx="410" ry="370" fill="url(#halo)"/>',
    '<g mask="url(#field-mask)" stroke="url(#spectrum)" stroke-width="1.25">',
]

for index in range(57):
    offset = index - 28
    points = []
    for x in range(0, width + 1, 8):
        neck = exp(-((x - 478) / 190) ** 2)
        opening = 13.1 - 10.1 * neck
        ripple = (18 + 26 * neck) * sin(x / 103 + index * 0.14)
        torsion = 17 * sin(x / 172 + offset * 0.09) * neck
        y = height / 2 + offset * opening + ripple + torsion
        points.append(f"{x},{y:.1f}")
    opacity = 0.26 + 0.55 * (1 - abs(offset) / 29)
    lines.append(f'<polyline points="{" ".join(points)}" opacity="{opacity:.2f}"/>')

lines += [
    '</g>',
    '<circle cx="478" cy="439" r="4" fill="#83C447"/>',
    '<circle cx="478" cy="439" r="12" stroke="#83C447" stroke-opacity=".42"/>',
    '<path d="M478 0v880M0 439h940" stroke="#A4BDB0" stroke-opacity=".22" stroke-dasharray="3 9"/>',
    '</svg>',
]
target.write_text("\n".join(lines) + "\n")
