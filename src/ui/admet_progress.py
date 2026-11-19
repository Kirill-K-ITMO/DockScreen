"""Honest ADMET progress with an ASCII decorative molecule in real terminals."""
import math
import os
from threading import RLock
import time

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, TextColumn, BarColumn
from rich.text import Text

STAGES = {
    'validation': 'Validating structures', 'checking_environment': 'Checking environment and models',
    'cache': 'Checking prediction cache', 'loading_models': 'Loading ADMET models',
    'predicting': 'Predicting properties', 'saving': 'Saving results',
    'complete': 'Calculation complete', 'failed': 'Calculation failed',
    'cancelled': 'Calculation interrupted',
}


def molecule_frame(angle, width=43, height=11):
    """Projection of a fixed abstract graph; never a user's candidate structure."""
    width=max(15,min(49,int(width)));height=max(7,int(height))
    points=[(-1.6,0,0,'C'),(-.8,1,.35,'C'),(.5,1,.1,'N'),(1.25,0,-.25,'C'),
            (.45,-1,.15,'C'),(-.85,-1,-.35,'C'),(2.4,.15,.7,'O'),(-2.6,.1,-.7,'O'),
            (.8,1.9,-.9,'H')]
    bonds=[(0,1),(1,2),(2,3),(3,4),(4,5),(5,0),(3,6),(0,7),(2,8)]
    grid=[[' ']*width for _ in range(height)];coords=[]
    for x,y,z,label in points:
        xx=x*math.cos(angle)+z*math.sin(angle)
        zz=-x*math.sin(angle)+z*math.cos(angle)
        yy=y*math.cos(angle*.35)-zz*math.sin(angle*.35)
        coords.append((round(width/2+xx*(width-5)/7),round(height/2-yy*(height-2)/5),label))
    for a,b in bonds:
        x0,y0,_=coords[a];x1,y1,_=coords[b]
        steps=max(abs(x1-x0),abs(y1-y0),1)
        char='-' if abs(x1-x0)>2*abs(y1-y0) else '|' if abs(y1-y0)>abs(x1-x0) else '\\' if (x1-x0)*(y1-y0)>0 else '/'
        for n in range(1,steps):
            x=round(x0+(x1-x0)*n/steps);y=round(y0+(y1-y0)*n/steps)
            if 0<=x<width and 0<=y<height:grid[y][x]=char
    for x,y,label in coords:
        if 0<=x<width and 0<=y<height:grid[y][x]=label
    return '\n'.join(''.join(row) for row in grid)


class AdmetProgress:
    def __init__(self, console=None, animate=True):
        if console is None:
            from src.ui.console import console
        self.console=console
        self.animate=animate and os.environ.get('DOCKSCREEN_NO_ANIMATION')!='1'
        self.stage='validation';self.completed=None;self.total=None
        self.cache_hits=0;self.failed=0;self.started=time.monotonic()
        self._live=None;self._lock=RLock();self._last_log=None;self._last_refresh=0
        self._progress=Progress(TextColumn('{task.description}'),BarColumn(complete_style='green',finished_style='green',pulse_style='cyan',style='grey23'),
            TextColumn('{task.fields[count_label]}'),console=self.console,auto_refresh=False,expand=True)
        self._task=self._progress.add_task('ADMET',total=None,count_label='waiting')

    def __enter__(self):
        if self.console.is_terminal and self.console.is_interactive:
            self._live=Live(get_renderable=self.frame,console=self.console,refresh_per_second=8,
                            auto_refresh=self.animate,transient=False)
            self._live.start()
        else:self._log()
        return self

    def frame(self):
        with self._lock:
            elapsed=time.monotonic()-self.started
            angle=elapsed*.85 if self.animate else .55
            art=molecule_frame(angle,width=max(15,min(43,self.console.width-8)))
            elapsed_label=f'{int(elapsed)//60:02d}:{int(elapsed)%60:02d}'
            unit='rows' if self.stage=='validation' else 'unique structures'
            count=(f'{self.completed}/{self.total} {unit}' if self.total is not None else 'progress not yet measurable')
            self._progress.tasks[0].total=self.total
            self._progress.update(self._task,completed=self.completed or 0,description='ADMET',count_label=count)
            return Panel(Group(Text(art,style='green'),Text('Abstract molecule · decorative animation',style='dim'),
                Text(STAGES.get(self.stage,self.stage),style='bold cyan'),self._progress,
                Text(f'Cached: {self.cache_hits}  |  Failed: {self.failed}  |  Elapsed: {elapsed_label}',style='dim')),
                title='ADMET · local predictions',border_style='red' if self.stage=='failed' else 'yellow' if self.stage=='cancelled' else 'green')

    def update(self, stage, completed=None, total=None, cache_hits=None, failed=None):
        if stage not in STAGES:raise ValueError('Unknown ADMET stage')
        if total is not None and (type(total) is not int or total<0):raise ValueError('Invalid structure count')
        if completed is not None and (type(completed) is not int or completed<0 or (total is not None and completed>total)):
            raise ValueError('Invalid ADMET progress')
        changed=stage!=self.stage
        with self._lock:
            self.stage=stage;self.completed=completed;self.total=total
            if cache_hits is not None:self.cache_hits=cache_hits
            if failed is not None:self.failed=failed
        if self._live:
            now=time.monotonic()
            if changed or now-self._last_refresh>=.12 or stage in ('complete','failed','cancelled'):
                self._live.refresh();self._last_refresh=now
        else:self._log()

    def _log(self):
        # Plain output for redirected logs, with at most ~20 updates per phase.
        bucket=(self.completed*20//max(1,self.total) if self.total and self.completed is not None else None)
        marker=(self.stage,bucket)
        if marker==self._last_log:return
        self._last_log=marker
        detail=f' {self.completed}/{self.total} structures' if self.total is not None else ''
        self.console.print(f'ADMET: {STAGES[self.stage]}{detail}; cached: {self.cache_hits}; failed: {self.failed}',markup=False)

    def __exit__(self,kind,error,tb):
        if kind is not None:
            self.stage='cancelled' if issubclass(kind,KeyboardInterrupt) else 'failed'
        if self._live:
            self._live.update(self.frame(),refresh=True);self._live.stop();self._live=None
        else:self._log()
        return False
