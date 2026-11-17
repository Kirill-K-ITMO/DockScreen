"""Offline report branding and actual terminal rendering contracts."""
import base64
import io
from pathlib import Path
import re

import pytest
from rich.console import Console

from src.ui.branding import console_banner
from src.version import __version__

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('width', [38, 80, 120])
def test_console_header_keeps_ascii_art_unwrapped(width, monkeypatch):
    from src.ui import console as ui
    output = io.StringIO()
    terminal = Console(file=output, width=width, color_system=None)
    monkeypatch.setattr(ui, 'console', terminal)
    ui.print_app_header()
    banner = console_banner(__version__, width)
    assert banner.isascii()
    assert max(map(len, banner.splitlines())) <= width
    assert output.getvalue().startswith(banner + '\n')
    if width == 38:
        assert banner == f'DockScreen v{__version__}'
    else:
        assert f'MOLECULAR DOCKING / v{__version__}' in banner


def test_distributed_ascii_preview_matches_current_banner():
    assert (ROOT / 'assets/dockscreen-console.txt').read_text(encoding='ascii').rstrip('\r\n') == console_banner(__version__, 80)


def test_generated_report_contains_exact_offline_svg(tmp_path):
    from src.reporting.docking import ReportGenerator
    from src.docking.affinity import AffinityCalculator
    data = AffinityCalculator().process_docking_results({'row1': {'R': {'affinity': -9, 'smiles': 'CCO'}}})
    path = ReportGenerator(tmp_path).generate_html_report(data, smiles_dict={'row1': 'CCO'})
    document = Path(path).read_text(encoding='utf-8')
    assert document.count('id="dockscreen-brand"') == 1
    match = re.search(r'data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)', document)
    assert match
    svg = base64.b64decode(match[1])
    assert svg == (ROOT / 'assets/dockscreen-logo.svg').read_bytes()
    assert b'#173E2A' in svg and b'#238636' in svg
    assert not re.search(rb'(?:href|src)=["\']https?://', svg)
    assert f'DockScreen {__version__}' in document
