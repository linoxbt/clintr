"""Render Clintr's landing page and workspace as static Netlify documents."""
from pathlib import Path
from shutil import copy2

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OUT = ROOT / "public"
PAGES = ("overview", "jobs", "nodes", "activity", "settings")


def main():
    env = Environment(loader=FileSystemLoader(WEB / "templates"), autoescape=select_autoescape(["html"]))
    assets = OUT / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for name in ("app.js", "wallet.js", "wallet.bundle.js", "styles.css", "landing.css", "brand.css", "favicon.svg", "logo-mark.svg", "logo-dark.svg", "logo-light.svg", "signal-field.svg"):
        copy2(WEB / name, assets / name)
    for page in PAGES:
        doc = env.get_template(f"{page}.html").render(page=page, page_title=page.title(), hosted=True)
        target = OUT / "app" / page / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc)
    (OUT / "index.html").write_text(env.get_template("landing.html").render(hosted=True))


if __name__ == "__main__":
    main()
