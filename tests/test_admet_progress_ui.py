"""Independent checks for Russian menus and honest isolated-worker progress."""
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from rich.console import Console


def test_ascii_molecule_rotates_without_scientific_inputs():
    from src.ui.admet_progress import molecule_frame
    assert molecule_frame(0).isascii()
    assert molecule_frame(0)!=molecule_frame(1.5)
    assert len(molecule_frame(0).splitlines())==11


@pytest.mark.parametrize('terminal',[False,True])
def test_redirected_console_has_real_counts_no_ansi_or_animation(monkeypatch,terminal):
    import src.ui.admet_progress as ui
    buffer=io.StringIO();console=Console(file=buffer,force_terminal=terminal,force_interactive=False,color_system=None,width=80)
    def prohibited(*args,**kwargs):raise AssertionError('Live animation in redirected output')
    monkeypatch.setattr(ui,'Live',prohibited)
    with ui.AdmetProgress(console=console) as view:
        view.update('loading_models')
        assert view.total is None and view.completed is None
        view.update('predicting',completed=2,total=4,cache_hits=1)
        view.update('complete',completed=4,total=4,cache_hits=1)
    text=buffer.getvalue()
    assert '\x1b' not in text and '%' not in text
    assert '2/4' in text and '4/4' in text and 'Cached' not in text
    assert 'cached: 1' in text and 'Loading ADMET models' in text


def test_panel_has_ascii_above_counter_and_elapsed():
    from src.ui.admet_progress import AdmetProgress
    buffer=io.StringIO();console=Console(file=buffer,force_terminal=False,color_system=None,width=76)
    panel=AdmetProgress(console=console,animate=False)
    panel.stage='predicting';panel.completed=24;panel.total=40;panel.cache_hits=8
    console.print(panel.frame())
    text=buffer.getvalue()
    assert text.index('Abstract molecule')<text.index('24/40')
    assert 'Cached: 8' in text and 'Elapsed:' in text
    with pytest.raises(ValueError):panel.update('predicting',completed=5,total=4)


@pytest.fixture
def stub_worker(tmp_path,monkeypatch):
    import src.admet.pipeline as pipeline
    worker=tmp_path/'worker.py'
    worker.write_text('''import sys,json,time,os
from pathlib import Path
request,response=map(Path,sys.argv[1:3])
data=json.loads(request.read_text(encoding='utf-8'))
assert '_progress_callback' not in data
path=request.parent/'progress.json'
def event(done):
 temporary=path.with_suffix('.tmp')
 temporary.write_text(json.dumps({'stage':'predicting','completed':done,'total':2,'failed':0,'smiles':'must not leak'}),encoding='utf-8')
 os.replace(temporary,path)
event(0)
time.sleep(.15)
event(1)
time.sleep(.15)
event(2)
response.write_text(json.dumps({'metadata':{'verified':True},'predictions':{}}),encoding='utf-8')
''',encoding='utf-8')
    monkeypatch.setattr(pipeline,'__file__',str(tmp_path/'pipeline.py'))
    processes=[];native=subprocess.Popen
    def launch(*args,**kwargs):
        process=native(*args,**kwargs);processes.append(process);return process
    monkeypatch.setattr(pipeline.subprocess,'Popen',launch)
    return pipeline,worker,processes


def test_invoke_progress_is_sanitized_and_response_unchanged(stub_worker,tmp_path):
    pipeline,_,processes=stub_worker;events=[]
    result=pipeline._invoke(sys.executable,{'action':'predict','smiles':['CCO','CCN'],
                               '_progress_callback':events.append},5,tmp_path)
    assert result=={'metadata':{'verified':True},'predictions':{}}
    assert events and events[-1]['completed']==2
    assert all(set(e)=={'stage','completed','total','failed'} for e in events)
    assert [e['completed'] for e in events]==sorted(e['completed'] for e in events)
    assert all(p.poll() is not None for p in processes)


def test_timeout_kills_and_reaps_worker(stub_worker,tmp_path):
    pipeline,worker,processes=stub_worker
    worker.write_text('import time\ntime.sleep(30)\n',encoding='utf-8')
    with pytest.raises(RuntimeError,match='timed out'):
        pipeline._invoke(sys.executable,{'action':'probe'},.05,tmp_path)
    assert processes and all(p.poll() is not None for p in processes)


def test_interrupt_from_callback_kills_and_reaps_worker(stub_worker,tmp_path):
    pipeline,_,processes=stub_worker
    def cancel(event):raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        pipeline._invoke(sys.executable,{'action':'predict','smiles':['CCO','CCN'],
                                         '_progress_callback':cancel},5,tmp_path)
    assert processes and all(p.poll() is not None for p in processes)


def test_worker_batches_report_only_finished_structures_and_preserve_values(tmp_path,monkeypatch):
    import src.admet.worker as worker
    events=[];calls=[]
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(set_num_threads=lambda count:None))
    class Index(list):is_unique=True
    class Model:
        def __init__(self,**options):assert options=={'drugbank_path':None,'num_workers':0}
        def predict(self,smiles):
            calls.append(list(smiles))
            return SimpleNamespace(index=Index(smiles),loc={item:{'DILI':.25,'zero':0.0} for item in smiles})
    monkeypatch.setitem(sys.modules,'admet_ai',SimpleNamespace(ADMETModel=Model))
    monkeypatch.setattr(worker,'write_progress',lambda path,stage,**counts:events.append({'stage':stage,**counts}))
    result=worker.predict({'smiles':['CCO','CCN','CCC'],'batch_size':2},{'metadata':{'version':'fake'}},tmp_path/'p.json')
    assert calls==[['CCO','CCN'],['CCC']]
    assert [e['completed'] for e in events if e['stage']=='predicting']==[0,2,3]
    assert all(v['values']=={'DILI':.25,'zero':0.0} for v in result['predictions'].values())
    assert not any('smiles' in e or 'values' in e for e in events)


def test_progress_file_has_no_structures(tmp_path):
    from src.admet.worker import write_progress
    path=tmp_path/'progress.json'
    write_progress(path,'predicting',completed=2,total=4,failed=1)
    assert json.loads(path.read_text())=={'stage':'predicting','completed':2,'total':4,'failed':1}
    assert not path.with_suffix('.tmp').exists()


def test_main_menu_is_english_and_selection_accepts_both_languages(tmp_path,monkeypatch):
    import src.ui.application as app
    from src.ui.docking_menu import parse_selection
    buffer=io.StringIO();console=Console(file=buffer,force_terminal=False,color_system=None,width=100)
    monkeypatch.setattr(app,'console',console)
    application=app.DockScreenApp.__new__(app.DockScreenApp);application.project_root=tmp_path
    application.show_menu();text=buffer.getvalue()
    assert 'main menu' in text and 'Settings' in text and 'Exit' in text
    assert 'главное меню' not in text and 'Настройки' not in text
    assert parse_selection('все',3)==parse_selection('all',3)==[0,1,2]


def test_live_terminal_refreshes_molecule_while_waiting_without_percentages(monkeypatch):
    monkeypatch.delenv('DOCKSCREEN_NO_ANIMATION',raising=False)
    import time
    from src.ui.admet_progress import AdmetProgress
    buffer=io.StringIO()
    console=Console(file=buffer,force_terminal=True,force_interactive=True,color_system='standard',width=76,height=24,_environ={'TERM':'xterm-256color'})
    with AdmetProgress(console=console) as panel:
        panel.update('loading_models')
        time.sleep(.45)
    assert buffer.getvalue().count('Abstract molecule')>2
