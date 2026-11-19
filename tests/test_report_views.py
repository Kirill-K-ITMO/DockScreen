"""Presentation safety and dossier completeness, with synthetic model values."""
import csv
import re
import shutil
import subprocess

from src.reporting.docking import ReportGenerator
from src.reporting.pareto_csv import _candidate_dossier, _html


def test_dossier_keeps_raw_smiles_zero_missing_and_safe_text():
    row={'row_id':7,'name':'<script>bad()</script>','smiles':'C"<x>&N',
         'values':{'docking_score':-8.,'DILI':0.,'ClinTox':None,'Bioavailability_Ma':.34567891,'hERG':.2},
         'admet_status':'success'}
    text=_candidate_dossier(row)
    assert '<script>bad()' not in text and '&lt;script&gt;' in text
    assert 'C&quot;&lt;x&gt;&amp;N' in text
    assert 'data-endpoint="DILI" title="Точное значение: 0.0">0<' in text
    assert 'data-endpoint="ClinTox" title="Значение не рассчитано или недоступно">нет значения<' in text
    assert 'Точное значение: 0.34567891' in text
    assert 'не %' in text and 'Другие сигналы токсичности' in text


def test_only_front_receives_dossiers_and_selection_is_not_changed():
    decision={'front':True,'dominators':[],'reasons':[]}
    a={'id':'1','row_id':1,'name':'A','smiles':'CCO','values':{'docking_score':-8,'DILI':.2,'ClinTox':.1,'Bioavailability_Ma':.8},'selection':decision}
    b={**a,'id':'2','row_id':2,'name':'B','selection':{'front':False,'dominators':['1'],'reasons':[]}}
    doc={'counts':{'total':2,'feasible':2,'front':1,'objectives':1},'protocol':{'target':'R'},
         'criteria':[{'key':'docking_score','role':'objective','direction':'min','min':None,'max':-7,'low':None,'high':None}],
         'endpoints':{'docking_score':{'units':'kcal/mol'}}}
    text=_html(doc,[a,b],['docking_score'])
    assert text.count('class="candidate-dossier"')==1 and 'data-row-id="1"' in text
    assert 'data-row-id="2"' not in text
    assert 'DILI · повреждение печени' in text and 'ClinTox · клиническая токсичность' in text
    assert 'не клинические вероятности' in text
    assert decision=={'front':True,'dominators':[],'reasons':[]}
    assert '<input' not in text and '<select' not in text


def test_admet_view_markup_safe_labels_complete_csv_and_script_syntax(tmp_path):
    name='=1+1</script><script>bad()</script>'
    evil='bad"><img src=x onerror=bad()>'
    endpoints={k:{'name':k,'type':'classification','units':'-'} for k in ('DILI','ClinTox','Bioavailability_Ma','hERG',evil)}
    values={'DILI':.2,'ClinTox':None,'Bioavailability_Ma':.9,'hERG':0.,evil:.1}
    results={'row':{'R':{'affinity':-8,'selection_row_id':1,'input_name':name,'smiles':'CCO'}}}
    context={'metadata':{},'source_sha256':{},'endpoints':endpoints,'by_label':{'row':{
        'row_id':1,'name':name,'smiles':'CCO','status':'success','values':values}}}
    reporter=ReportGenerator(tmp_path)
    html_path=reporter.generate_html_report(results,output_file=tmp_path/'view.html',admet=context)
    csv_path=reporter.generate_csv_report(results,output_file=tmp_path/'view.csv',admet=context)
    text=html_path.read_text(encoding='utf-8')
    assert 'id="tab-docking"' in text and 'id="tab-admet"' in text
    assert 'id="admet-metric-search"' in text and 'data-admet-choice="hERG"' in text
    assert 'data-admet-key="DILI" hidden' in text
    assert 'bad"><img' not in text and '</script><script>bad()' not in text
    rows=list(csv.DictReader(csv_path.open(encoding='utf-8-sig')))
    assert len([k for k in rows[0] if k.startswith('ADMET__')])==5
    assert rows[0]['ADMET__hERG']=='0.0' and rows[0]['ADMET__ClinTox']==''
    node=shutil.which('node')
    if node:
        js=tmp_path/'view.js'
        js.write_text('\n'.join(re.findall(r'<script>(.*?)</script>',text,re.S)),encoding='utf-8')
        subprocess.run([node,'--check',str(js)],check=True,capture_output=True)
