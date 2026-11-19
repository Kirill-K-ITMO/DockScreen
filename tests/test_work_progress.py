import io
import time

import pytest
from rich.console import Console

import src.ui.progress as ui


def terminal(buffer, interactive=True):
    return Console(file=buffer, force_terminal=interactive, force_interactive=interactive,
        color_system='standard' if interactive else None, width=80, height=25,
        _environ={'TERM': 'xterm-256color'})


@pytest.mark.parametrize('description', ['Docking', 'Ligand preparation'])
def test_rotation_continues_while_work_waits_without_advancing_counter(monkeypatch, description):
    monkeypatch.delenv('DOCKSCREEN_NO_ANIMATION', raising=False)
    buffer = io.StringIO()
    monkeypatch.setattr(ui, 'console', terminal(buffer))
    with ui.WorkProgress(description, 3) as progress:
        first = progress.frame().renderable.renderables[0].plain
        time.sleep(.45)
        second = progress.frame().renderable.renderables[0].plain
        assert first != second
        assert progress.progress.tasks[0].completed == 0
        progress.advance()
        progress.update(description=description + ': cached 0; failed 0')
        assert progress.progress.tasks[0].completed == 1
    assert buffer.getvalue().count('Abstract molecule') > 2
    assert progress._live is None


def test_redirected_progress_preserves_counts_without_animation(monkeypatch):
    buffer = io.StringIO()
    monkeypatch.setattr(ui, 'console', terminal(buffer, interactive=False))
    with ui.WorkProgress('Docking', 2) as progress:
        progress.update(completed=1)
        progress.advance()
    text = buffer.getvalue()
    assert 'Docking' in text and '2/2' in text
    assert 'Abstract molecule' not in text and '\x1b' not in text


def test_disabled_motion_and_interrupt_cleanup(monkeypatch):
    monkeypatch.setenv('DOCKSCREEN_NO_ANIMATION', '1')
    monkeypatch.setattr(ui, 'console', terminal(io.StringIO()))
    progress = ui.WorkProgress('Docking', 2)
    with pytest.raises(KeyboardInterrupt):
        with progress:
            before = progress.frame().renderable.renderables[0].plain
            time.sleep(.05)
            assert progress.frame().renderable.renderables[0].plain == before
            assert progress._live.auto_refresh is False
            raise KeyboardInterrupt
    assert progress._live is None
    assert not ui.console._live_stack
    assert progress.progress.tasks[0].completed == 0
