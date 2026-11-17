"""Shared offline branding for docking and database reports."""
import base64
from functools import lru_cache
from html import escape
from pathlib import Path
import re
from src.version import APP_NAME, __version__

@lru_cache(maxsize=1)
def logo_data_uri():
    path = Path(__file__).resolve().parents[2] / "assets" / "dockscreen-logo.svg"
    if not path.exists():
        return None
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode("ascii")

def brand_html(document):
    if 'id="dockscreen-brand"' in document:
        return document
    brand = escape(f"{APP_NAME} {__version__}")
    source = logo_data_uri()
    image = (f'<img src="{source}" alt="DockScreen" '
             'style="display:block;width:100%;max-width:440px;height:auto;margin:auto">') if source else ''
    banner = ('<header id="dockscreen-brand" style="background:white;color:#173e2a;'
              'border-radius:10px;padding:8px 16px;margin:12px 0 24px;text-align:center">'
              + image + f'<div style="font:14px system-ui">{brand}</div></header>')
    document = re.sub(r'(<title>)(.*?)(</title>)',
        lambda m: m[1] + (m[2] if APP_NAME in m[2] else APP_NAME + " | " + m[2]) + m[3],
        document, count=1, flags=re.S | re.I)
    return re.sub(r'(<body\b[^>]*>)',lambda m:m[1]+banner,document,count=1,flags=re.I)
