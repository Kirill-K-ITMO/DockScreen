"""Completed-work counters with a decorative molecule; no invented Vina progress."""
import os
import time

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn
from rich.text import Text

from src.ui.admet_progress import molecule_frame
from src.ui.console import console


class WorkProgress:
    def __init__(self, description, total=None):
        self.progress = Progress(TextColumn("{task.description}"),
            BarColumn(complete_style='green', finished_style='green'),
            MofNCompleteColumn(), TimeElapsedColumn(), console=console)
        self.task = self.progress.add_task(description, total=total)
        self._live = None
        self._started = time.monotonic()
        self._animate = os.environ.get('DOCKSCREEN_NO_ANIMATION') != '1'

    def frame(self):
        angle = (time.monotonic() - self._started) * .85 if self._animate else .55
        art = molecule_frame(angle, width=max(15, min(43, console.width - 8)))
        return Panel(Group(Text(art, style='green'),
            Text('Abstract molecule · decorative animation', style='dim'), self.progress),
            title='DockScreen · work in progress', border_style='green')

    def __enter__(self):
        self._started = time.monotonic()
        if console.is_terminal and console.is_interactive and not console.is_dumb_terminal:
            self._live = Live(get_renderable=self.frame, console=console,
                refresh_per_second=8, auto_refresh=self._animate, transient=False)
            self._live.start()
        else:
            self.progress.start()
        return self

    def update(self, **values):
        self.progress.update(self.task, **values)
        if self._live and not self._animate:
            self._live.refresh()

    def advance(self):
        self.progress.advance(self.task)
        if self._live and not self._animate:
            self._live.refresh()

    def __exit__(self, *error):
        if self._live:
            self._live.stop()
            self._live = None
        else:
            self.progress.stop()
        return False
