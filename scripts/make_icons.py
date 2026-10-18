"""Erzeugt App-Icons (PNG/SVG) und Themen-Fallback-Icons. Einmalig ausführen: python scripts/make_icons.py"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "frontend" / "icons"
BG, ACCENT, LINE = "#0f1115", "#5b9dff", "#e8eaef"

STROKE = 'fill="none" stroke="#f1f3f7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
TOPICS = {
    "top": '<path d="M4 5h13v14H6a2 2 0 0 1-2-2z"/><path d="M17 8h3v9a2 2 0 0 1-2 2"/><path d="M7 9h7M7 12h7M7 15h4"/>',
    "politik": '<path d="M3 21h18M4 10h16M12 3l8 5H4z"/><path d="M6 10v8M10 10v8M14 10v8M18 10v8"/>',
    "wirtschaft": '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 6-6"/><path d="M16 8h4v4"/>',
    "tech": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "ki": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "gaming": '<path d="M7 7h10a5 5 0 0 1 4.9 6l-.6 3a2.5 2.5 0 0 1-4.3 1.2L15 15H9l-2 2.2A2.5 2.5 0 0 1 2.7 16l-.6-3A5 5 0 0 1 7 7z"/><path d="M7 10v4M5 12h4"/><circle cx="16" cy="11" r=".6"/><circle cx="18" cy="13" r=".6"/>',
    "sport": '<circle cx="12" cy="12" r="9"/><path d="M12 7l4 3-1.5 4.5h-5L8 10z"/><path d="M12 3v4M16 10l4.5-1.5M14.5 14.5l2.5 4M9.5 14.5L7 18.5M8 10L3.5 8.5"/>',
    "wissenschaft": '<path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/><path d="M7 15h10"/>',
    "kultur": '<circle cx="12" cy="12" r="9"/><circle cx="8.5" cy="10" r="1.2"/><circle cx="12" cy="7.5" r="1.2"/><circle cx="15.5" cy="10" r="1.2"/><path d="M12 21a3 3 0 0 1 0-6h2"/>',
    "regional": '<path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
}

def svg(body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" {STROKE}>{body}</svg>\n'

APP_SVG = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="{BG}"/>
<rect x="14" y="16" width="36" height="7" rx="3.5" fill="{ACCENT}"/>
<rect x="14" y="29" width="28" height="5" rx="2.5" fill="{LINE}"/>
<rect x="14" y="39" width="32" height="5" rx="2.5" fill="{LINE}" opacity=".7"/>
<rect x="14" y="49" width="20" height="5" rx="2.5" fill="{LINE}" opacity=".45"/>
</svg>
'''

def png(size: int, maskable: bool) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    # maskable: Inhalt in der inneren 60 %-Sicherheitszone halten
    pad = size * (0.2 if maskable else 0.0)
    s = (size - 2 * pad) / 64
    def bar(x, y, w, h, color):
        d.rounded_rectangle([pad + x * s, pad + y * s, pad + (x + w) * s, pad + (y + h) * s], radius=h * s / 2, fill=color)
    bar(14, 16, 36, 7, ACCENT)
    bar(14, 29, 28, 5, LINE)
    bar(14, 39, 32, 5, "#a3a6ab")
    bar(14, 49, 20, 5, "#6b6e74")
    return img

def main():
    (OUT / "topics").mkdir(parents=True, exist_ok=True)
    for name, body in TOPICS.items():
        (OUT / "topics" / f"{name}.svg").write_text(svg(body), encoding="utf-8")
    (OUT / "icon.svg").write_text(APP_SVG, encoding="utf-8")
    png(192, False).save(OUT / "icon-192.png", optimize=True)
    png(512, False).save(OUT / "icon-512.png", optimize=True)
    png(512, True).save(OUT / "icon-maskable-512.png", optimize=True)
    print("Icons erzeugt in", OUT)

if __name__ == "__main__":
    main()
