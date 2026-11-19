"""Offline docking/ADMET review; never re-runs prediction or docking in the browser."""
import base64
import hashlib
import json
import math
from pathlib import Path

from src.core.calculation_cache import atomic_write
from src.reporting.pareto import PARETO_JS


def _load(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _drawing(smiles):
    try:
        from rdkit import Chem
        from rdkit.Chem.Draw import rdMolDraw2D
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            return None
        drawer = rdMolDraw2D.MolDraw2DSVG(360, 230)
        drawer.DrawMolecule(molecule)
        drawer.FinishDrawing()
        return 'data:image/svg+xml;base64,' + base64.b64encode(drawer.GetDrawingText().encode()).decode()
    except Exception:
        return None


def build_combined_data(root, run_dir, *, include_images=True):
    root, run_dir = Path(root).resolve(), Path(run_dir).resolve()
    inputs = _load(run_dir / 'preparation.json', [])
    if not isinstance(inputs, list):
        raise ValueError('Expected screening preparation.json with original input rows')
    results = _load(run_dir / 'results.json', {})
    summary = _load(run_dir / 'summary.json', {})
    admet = _load(run_dir / 'admet.json', {})
    outcomes = _load(run_dir / 'task_outcomes.json', {})
    if len({str(r['row_id']) for r in inputs}) != len(inputs):
        raise ValueError('Screening preparation has duplicate row IDs')
    if admet:
        recorded_hashes = admet.get('metadata', {}).get('input_sha256', {})
        for name in ('preparation.json', 'results.json', 'summary.json'):
            source = run_dir / name
            actual = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None
            if actual is None or recorded_hashes.get(name) != actual:
                raise ValueError(f'ADMET provenance mismatch for {name}; rerun local ADMET enrichment before reporting')
        originals = {str(r['row_id']): r for r in inputs}
        seen = set()
        for row in admet.get('rows', []):
            row_id = str(row.get('row_id'))
            original = originals.get(row_id)
            if row_id in seen or original is None or row.get('smiles') != original['smiles'] or row.get('name') != original['name']:
                raise ValueError('ADMET row identity/SMILES mismatch; rerun local ADMET enrichment before reporting')
            seen.add(row_id)
    admet_rows = {str(r['row_id']): r for r in admet.get('rows', [])}
    endpoints = admet.get('endpoints', {})
    if isinstance(endpoints, list):
        endpoints = {e.get('name', e.get('endpoint')): e for e in endpoints}
    endpoints = dict(endpoints)
    for row in admet_rows.values():
        for key in row.get('values', {}):
            endpoints.setdefault(key, {'units': '', 'type': 'unknown'})
    targets = list(dict.fromkeys([*summary.get('receptors', []),
                                 *(t for by_target in results.values() for t in by_target)]))
    protocols, by_pair = {}, {}
    for label, by_target in results.items():
        for target, record in by_target.items():
            spec = dict(record.get('spec', {}))
            # Ligand-dependent fields must not split a single protocol into one group per molecule.
            spec.pop('ligand_sha', None)
            if not spec:
                spec = {'legacy_protocol': 'unknown; original protocol not recorded', 'scoring': record.get('scoring', 'unknown')}
            signature = json.dumps(spec, ensure_ascii=False, sort_keys=True, allow_nan=False)
            key = target + ':' + hashlib.sha256(signature.encode()).hexdigest()[:12]
            protocols.setdefault(key, {'id': key, 'target': target, 'spec': spec,
                                      'label': target + ' · ' + key.rsplit(':', 1)[1]})
            by_pair[(label, target)] = (key, record)
    for target in targets:
        if not any(p['target'] == target for p in protocols.values()):
            key = target + ':no-success'
            protocols[key] = {'id': key, 'target': target, 'label': target + ' · нет успешных расчётов', 'spec': {}}
    rows = []
    for entry in inputs:
        aid = admet_rows.get(str(entry['row_id']), {})
        docking = {}
        for target in targets:
            pair = by_pair.get((entry['label'], target))
            if pair:
                protocol, record = pair
                docking[target] = {'protocol': protocol, 'score': _number(record.get('affinity')),
                                   'evaluation_id': record.get('evaluation_id'), 'record': record, 'status': 'success'}
            else:
                outcome = outcomes.get(entry['label'], {}).get(target, {})
                docking[target] = {'protocol': None, 'score': None,
                                   'status': outcome.get('status', entry.get('status', 'docking_failed')),
                                   'error': outcome.get('error', entry.get('error', 'Нет результата докинга'))}
        rows.append({'id': str(entry['row_id']), 'row_id': entry['row_id'], 'label': entry['label'],
                     'name': entry['name'], 'smiles': entry['smiles'], 'image': _drawing(entry['smiles']) if include_images else None,
                     'admet_status': aid.get('status', 'not_run'), 'admet_error': aid.get('error'),
                     'structure_id': aid.get('structure_id'),
                     'values': {key: _number(value) for key, value in aid.get('values', {}).items()},
                     'docking': docking})
    source_files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [run_dir / n for n in ('preparation.json', 'results.json', 'summary.json', 'admet.json')]
                    if p.is_file()}
    payload = {'schema_version': 1, 'run_name': run_dir.name, 'rows': rows, 'protocols': list(protocols.values()),
            'endpoints': {'docking_score': {'units': 'kcal/mol', 'type': 'docking score',
                                          'description': 'Vina score — не экспериментальная активность'}, **endpoints},
            'admet_metadata': admet.get('metadata', {}), 'source_sha256': source_files,
            'summary': summary}
    from src.reporting.pareto_csv import default_criteria
    payload['default_criteria'] = default_criteria(payload)
    return payload


def generate_combined_report(root, run_dir, output_file=None):
    """Create a standalone report for a completed screening run, preserving legacy HTML."""
    data = build_combined_data(root, run_dir)
    destination = Path(output_file) if output_file else Path(run_dir) / 'combined_report.html'
    serialized = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    html = HTML.replace('/*PARETO_ENGINE*/', PARETO_JS).replace('/*REPORT_CODE*/', REPORT_JS).replace('<!--REPORT_DATA-->', serialized)
    atomic_write(destination, html.encode('utf-8'))
    return destination


HTML = r'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DockScreen · Docking + ADMET</title><style>
:root{color-scheme:light;--ink:#15312f;--teal:#006d64;--muted:#61716d;--border:#d6e2dc}*{box-sizing:border-box}body{margin:0;background:#f3f6f1;color:var(--ink);font:15px system-ui,sans-serif}header{background:#153b36;color:white;padding:24px 4vw}header h1{font-size:25px;margin:0 0 8px}header p{margin:0;color:#c7ddd3}main{padding:20px 4vw;max-width:1700px;margin:auto}.card{background:white;border:1px solid var(--border);border-radius:12px;padding:18px;margin-bottom:18px}h2{font-size:19px;margin:0 0 14px}h3{font-size:16px;margin:12px 0}p{line-height:1.55}label{display:inline-flex;gap:6px;align-items:center;margin:4px 10px 4px 0}input,select,button{font:inherit;border:1px solid #b9cdc2;border-radius:6px;background:white;color:var(--ink);padding:6px}button{cursor:pointer;background:#edf5ef}button.primary{background:var(--teal);color:white}input[type=number]{width:95px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid var(--border);padding:8px;text-align:left}th{background:#edf3ed;white-space:nowrap}td input,td select{max-width:130px}.scroll{overflow:auto;max-height:480px}.grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(280px,1fr);gap:18px}.muted{color:var(--muted)}.notice{background:#fff7dc;border:1px solid #e6d6a4;border-radius:8px;padding:10px}.front{color:#007563;font-weight:650}.excluded{color:#96622d}.row-selected{background:#e3f1eb}tr.candidate{cursor:pointer}#stats{font-size:18px;margin:12px 0}svg.plot{width:100%;height:370px;display:block}#detail img{max-width:100%;background:white}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#f4f7f2;padding:10px}.error{color:#a32828;font-weight:600}.small{font-size:12px}.endpoint-meta{max-width:220px}.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.plot circle{cursor:pointer}.plot text{font:11px system-ui}.number{text-align:right;font-variant-numeric:tabular-nums}summary{cursor:pointer}@media(max-width:900px){.grid{grid-template-columns:1fr}main{padding:12px}header{padding:20px}}
</style></head><body>
<header><h1>DockScreen · докинг и ADMET</h1><p>Исследовательский отбор кандидатов · локальный отчёт</p></header><main>
<section class="card"><h2 id="run-title">Отбор</h2><p>Выберите одну мишень и один протокол. Меняйте цели и пороги: расчёт ADMET повторно не запускается.</p><label>Рецептор / профиль / протокол <select id="protocol"></select></label><details><summary>Параметры выбранного протокола</summary><pre id="protocol-details"></pre></details>
<p class="notice">Докинг — расчётная оценка, а не экспериментальная активность. Классификационные ADMET-выходы — модельные оценки, не клинические вероятности риска; Bioavailability_Ma — не процент биодоступности. Индивидуальная неопределённость не оценена. Фронт Парето не доказывает, что кандидат станет лучшим лекарством.</p>
<details><summary>Модель, обработка структур и происхождение</summary><pre id="metadata"></pre></details></section>
<section class="card"><h2>Цели и ограничения</h2><p class="muted">Сначала применяются пороги, затем точное доминирование по всем целям. Равенство порогу проходит. Пропуск активного параметра исключает строку. «Справочно» не влияет на отбор. Для диапазона минимизируется расстояние до него; внутри диапазона цель равна нулю.</p>
<div class="scroll"><table id="criteria"><thead><tr><th>Параметр</th><th>Роль</th><th>Цель</th><th>Диапазон от</th><th>до</th><th>Порог ≥</th><th>Порог ≤</th><th>Сведения</th></tr></thead><tbody></tbody></table></div>
<p class="small muted">Начальный набор user-default-v3: докинг ≤ −7 ↓, DILI ≤ 0.5 ↓, ClinTox ≤ 0.5 ↓, hERG ≤ 0.5 ↓, Bioavailability_Ma ≥ 0.5 ↑ (модельная оценка, не проценты). В этой форме доступны только рассчитанные параметры. Полный автоматический набор требует всех пяти показателей. Пороги задают сценарий пользователя, не клинический стандарт.</p><div id="error" class="error" role="alert"></div><div id="stats" aria-live="polite"></div></section>
<div class="grid"><section class="card"><h2>Проекция выбранного фронта</h2><label>Ось X <select id="axis-x"></select></label><label>Ось Y <select id="axis-y"></select></label><p class="small muted">Здесь показаны исходные значения двух осей. Зелёный фронт рассчитан по всем выбранным целям; его проекция может выглядеть доминируемой. Серый — допустимый, янтарный — исключённый. Точки с пропуском оси не рисуются.</p><svg id="plot" class="plot" viewBox="0 0 700 370" role="img" aria-label="Диаграмма кандидатов"></svg><p id="plot-note" class="small muted"></p></section>
<section class="card" id="detail"><h2>Выбранный кандидат</h2><p class="muted">Нажмите строку или точку.</p></section></div>
<section class="card"><h2>Кандидаты</h2><label>Показать <select id="filter"><option value="all">Все строки</option><option value="front">Фронт Парето</option><option value="feasible">Допустимые</option><option value="excluded">Исключённые</option></select></label><label>Поиск <input id="search" type="search" placeholder="Имя, строка, SMILES"></label>
<div class="actions"><button id="select-front">Выбрать фронт</button><button id="clear-selected">Снять выбор</button><button class="primary" id="export-json">Экспорт выбранных + настройки JSON</button><button id="export-csv">Экспорт выбранных CSV</button><button id="export-settings">Экспорт настроек JSON</button><label>Загрузить настройки <input id="import-settings" type="file" accept="application/json,.json"></label></div><p id="selection-count" class="small"></p>
<div class="scroll"><table id="candidates"><thead></thead><tbody></tbody></table></div></section>
<section class="card small muted"><p>Успешный локальный расчёт — техническая проверка, не научная валидация. Профили и протоколы не усредняются. Выбор целей и порогов требует знаний о патологии, мишени, применимости модели и экспериментальной проверки. Общая метрика endpoint не является «точностью» отдельной молекулы.</p></section>
</main><script id="report-data" type="application/json"><!--REPORT_DATA--></script><script>/*PARETO_ENGINE*/
/*REPORT_CODE*/</script></body></html>'''


REPORT_JS = r'''
const DATA=JSON.parse(document.getElementById('report-data').textContent);
const $=id=>document.getElementById(id), make=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const keys=Object.keys(DATA.endpoints), selected=new Set();let current=[], decisions=[], focus=null, settings=[];
const numberText=n=>Pareto.finite(n)?Number(n.toPrecision(6)).toString():'—';
const option=(parent,value,text)=>{const e=make('option',text);e.value=value;parent.append(e);};
function inputNumber(v){const e=make('input');e.type='number';e.step='any';if(v!==null&&v!==undefined)e.value=v;return e;}
function readNumber(e){if(!e.value.trim())return null;const v=Number(e.value);if(!Number.isFinite(v))throw Error('Некорректное число');return v;}
function defaults(){const active=new Map((DATA.default_criteria||[]).map(s=>[s.key,s]));return keys.map(key=>active.has(key)?{...active.get(key)}:{key,role:'display',direction:'min',low:null,high:null,min:null,max:null});}
function buildCriteria(config){const body=$('criteria').tBodies[0];body.replaceChildren();for(const s of config){const row=make('tr');row.dataset.key=s.key;row.append(make('td',s.key));const role=make('select');[['display','Справочно'],['constraint','Только порог'],['objective','Цель + пороги']].forEach(([v,t])=>option(role,v,t));role.value=s.role;const direction=make('select');[['min','Минимум ↓'],['max','Максимум ↑'],['range','К диапазону']].forEach(([v,t])=>option(direction,v,t));direction.value=s.direction;const controls=[role,direction,...['low','high','min','max'].map(k=>inputNumber(s[k]))];for(const c of controls){const td=make('td');td.append(c);row.append(td);c.addEventListener('change',recompute);}const meta=DATA.endpoints[s.key]||{};const cell=make('td',[meta.units||meta.unit||'без единиц',meta.type||meta.task_type||'',meta.description||meta.warning||'',...(Array.isArray(meta.warnings)?meta.warnings:[])].filter(Boolean).join(' · '),'small endpoint-meta');cell.title=JSON.stringify(meta,null,2);row.append(cell);body.append(row);}}
function readCriteria(){return Array.from($('criteria').tBodies[0].rows).map(row=>{const c=row.querySelectorAll('select,input');const s={key:row.dataset.key,role:c[0].value,direction:c[1].value,low:readNumber(c[2]),high:readNumber(c[3]),min:readNumber(c[4]),max:readNumber(c[5])};if(s.role!=='display'&&s.min!==null&&s.max!==null&&s.min>s.max)throw Error(s.key+': нижний порог больше верхнего');if(s.role==='objective'&&s.direction==='range'&&(s.low===null||s.high===null||s.low>s.high))throw Error(s.key+': задайте целевой диапазон от / до');return s;});}
function getProtocol(){return DATA.protocols.find(p=>p.id===$('protocol').value);}
function recompute(){try{settings=readCriteria();const protocol=getProtocol();current=DATA.rows.map(r=>{const d=protocol?r.docking[protocol.target]:null;return {...r,values:{...r.values,docking_score:d&&d.protocol===protocol.id?d.score:null},eligible:!!(d&&d.protocol===protocol.id&&Pareto.finite(d.score)),error:d&&d.protocol&&protocol&&d.protocol!==protocol.id?'Несовместимый протокол докинга':(d&&d.error)||'Нет успешного докинга для выбранного протокола'};});decisions=Pareto.select(current,settings);$('error').textContent='';$('protocol-details').textContent=JSON.stringify(protocol||{},null,2);const valid=decisions.filter(r=>!r.reasons.length).length,front=decisions.filter(r=>r.front).length,objectives=settings.filter(s=>s.role==='objective').length;$('stats').textContent=`Строк: ${current.length} · допустимо: ${valid} · фронт: ${front} · целей: ${objectives}`+(objectives?'':' · Целей нет: все допустимые равноправны');renderTable();renderPlot();renderDetail();}catch(error){$('error').textContent=error.message;$('stats').textContent='Отбор не пересчитан: исправьте настройки';$('plot').replaceChildren();$('candidates').tBodies[0].replaceChildren();}}
function statusText(d){return d.reasons.length?'Исключён: '+d.reasons.join('; '):!settings.some(s=>s.role==='objective')?'Допустим; цели не выбраны':d.front?'Фронт Парето':'Доминируют строки: '+d.dominators.join(', ');}
function renderTable(){const head=$('candidates').tHead,body=$('candidates').tBodies[0];head.replaceChildren();body.replaceChildren();const cols=['Выбор','Строка','Имя','Докинг','ADMET','Статус отбора'];const h=make('tr');cols.forEach(t=>h.append(make('th',t)));head.append(h);const filter=$('filter').value,query=$('search').value.toLowerCase();for(let i=0;i<current.length;i++){const r=current[i],d=decisions[i];if(filter==='front'&&!d.front||filter==='feasible'&&d.reasons.length||filter==='excluded'&&!d.reasons.length)continue;if(query&&!`${r.id} ${r.name} ${r.smiles}`.toLowerCase().includes(query))continue;const tr=make('tr',undefined,'candidate'+(focus===r.id?' row-selected':''));tr.dataset.rowId=r.id;const check=make('input');check.type='checkbox';check.checked=selected.has(r.id);check.setAttribute('aria-label','Выбрать строку '+r.id);check.addEventListener('click',e=>e.stopPropagation());check.addEventListener('change',()=>{check.checked?selected.add(r.id):selected.delete(r.id);selectionCount();});const td=make('td');td.append(check);tr.append(td,make('td',r.id),make('td',r.name),make('td',numberText(r.values.docking_score),'number'),make('td',r.admet_status),make('td',statusText(d),d.reasons.length?'excluded':d.front?'front':''));tr.addEventListener('click',()=>setFocus(r.id));body.append(tr);}selectionCount();}
function setFocus(id){focus=id;renderTable();renderPlot();renderDetail();}
function renderDetail(){const panel=$('detail');panel.replaceChildren(make('h2','Выбранный кандидат'));const index=current.findIndex(r=>r.id===focus);if(index<0){panel.append(make('p','Нажмите строку или точку.','muted'));return;}const r=current[index],d=decisions[index];panel.append(make('h3',`Строка ${r.id} · ${r.name}`));if(r.image){const im=make('img');im.src=r.image;im.alt='Структура исходного SMILES';panel.append(im);}panel.append(make('p',r.smiles,'small'),make('p',statusText(d)),make('p',`ADMET: ${r.admet_status}${r.admet_error?' · '+r.admet_error:''}`));if(d.dominators.length){const p=make('p','Перейти к доминирующей строке: ');for(const id of d.dominators){const b=make('button',id);b.addEventListener('click',()=>setFocus(id));p.append(b);}panel.append(p);}const table=make('table');for(const key of keys){const tr=make('tr');tr.append(make('td',key),make('td',numberText(r.values[key]),'number'));table.append(tr);}panel.append(table);const details=make('details'),summary=make('summary','Исходные параметры и идентификаторы');details.append(summary,make('pre',JSON.stringify({structure_id:r.structure_id,docking:r.docking},null,2)));panel.append(details);}
function svg(tag,attrs,text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
function renderPlot(){const plot=$('plot');plot.replaceChildren();const x=$('axis-x').value,y=$('axis-y').value;const points=current.map((r,i)=>({r,d:decisions[i],x:r.values[x],y:r.values[y]})).filter(p=>Pareto.finite(p.x)&&Pareto.finite(p.y));$('plot-note').textContent=`Показано ${points.length} из ${current.length} строк. Нажмите точку для структуры и причин отбора.`;if(!points.length){plot.append(svg('text',{x:40,y:100},'Нет численных значений для этих осей'));return;}let xmin=Math.min(...points.map(p=>p.x)),xmax=Math.max(...points.map(p=>p.x)),ymin=Math.min(...points.map(p=>p.y)),ymax=Math.max(...points.map(p=>p.y));if(xmin===xmax){xmin-=0.5;xmax+=0.5;}if(ymin===ymax){ymin-=0.5;ymax+=0.5;}const xx=v=>72+(v-xmin)/(xmax-xmin)*590,yy=v=>310-(v-ymin)/(ymax-ymin)*280;plot.append(svg('path',{d:'M72 24 V310 H675',fill:'none',stroke:'#80968a'}));for(let i=0;i<=4;i++){const vx=xmin+(xmax-xmin)*i/4,vy=ymin+(ymax-ymin)*i/4;plot.append(svg('text',{x:xx(vx),y:330,'text-anchor':'middle'},numberText(vx)),svg('text',{x:65,y:yy(vy)+4,'text-anchor':'end'},numberText(vy)));}plot.append(svg('text',{x:370,y:359,'text-anchor':'middle'},x),svg('text',{x:10,y:17},y));for(const p of points){const c=svg('circle',{cx:xx(p.x),cy:yy(p.y),r:focus===p.r.id?8:5,fill:p.d.reasons.length?'#c6954e':p.d.front?'#008674':'#aab7af',stroke:focus===p.r.id?'#102e29':'white','stroke-width':2,tabindex:0,'aria-label':`Строка ${p.r.id}: ${p.r.name}`});c.append(svg('title',{},`${p.r.name} (строка ${p.r.id})\n${x}: ${p.x}\n${y}: ${p.y}\n${statusText(p.d)}`));c.addEventListener('click',()=>setFocus(p.r.id));c.addEventListener('keydown',e=>{if(e.key==='Enter')setFocus(p.r.id);});plot.append(c);}}
function selectionCount(){$('selection-count').textContent=`Выбрано строк: ${selected.size}. Экспорт сохраняет оригинальные имена, SMILES, параметры отбора и хэши исходных файлов.`;}
function config(){return {schema_version:1,protocol_id:$('protocol').value,criteria:settings,axis_x:$('axis-x').value,axis_y:$('axis-y').value,run_name:DATA.run_name,source_sha256:DATA.source_sha256,threshold_note:'User-defined model-score bounds, not clinical standards; Bioavailability_Ma is not a percentage'};}
function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const a=make('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function csvCell(value){let s=value===null||value===undefined?'':String(value);if(typeof value==='string'&&(s.startsWith("'")||/^[\s\x00-\x1f\x7f\ufeff]*[=+\-@]/.test(s)))s="'"+s;return '"'+s.replaceAll('"','""')+'"';}
function chosen(){return current.filter(r=>selected.has(r.id));}
$('export-json').addEventListener('click',()=>{if($('error').textContent)return;download('dockscreen-selection.json',JSON.stringify({settings:config(),admet_metadata:DATA.admet_metadata,endpoints:DATA.endpoints,candidates:chosen().map(r=>({...r,image:undefined,selection:decisions.find(d=>d.id===r.id)}))},null,2),'application/json');});
$('export-csv').addEventListener('click',()=>{if($('error').textContent)return;const cols=['row_id','name','smiles','admet_status','selection_status','protocol_id',...keys];const lines=[cols.map(csvCell).join(',')];for(const r of chosen()){const d=decisions.find(d=>d.id===r.id);lines.push([r.row_id,r.name,r.smiles,r.admet_status,statusText(d),$('protocol').value,...keys.map(k=>r.values[k])].map(csvCell).join(','));}download('dockscreen-selection.csv','\ufeff'+lines.join('\r\n')+'\r\n','text/csv;charset=utf-8');download('dockscreen-selection.settings.json',JSON.stringify({...config(),csv_safety:'Formula-like text cells have an added apostrophe; original strings are in selection JSON'},null,2),'application/json');});
$('export-settings').addEventListener('click',()=>{if(!$('error').textContent)download('dockscreen-settings.json',JSON.stringify(config(),null,2),'application/json');});
$('import-settings').addEventListener('change',async e=>{try{const value=JSON.parse(await e.target.files[0].text()),s=value.settings||value;if(s.schema_version!==1||!DATA.protocols.some(p=>p.id===s.protocol_id))throw Error('Настройки относятся к другому протоколу');if(JSON.stringify(s.source_sha256)!==JSON.stringify(DATA.source_sha256))throw Error('Хэши исходных файлов не совпадают');if(!Array.isArray(s.criteria)||s.criteria.length!==keys.length||new Set(s.criteria.map(x=>x.key)).size!==keys.length||s.criteria.some(x=>!keys.includes(x.key)||!['display','constraint','objective'].includes(x.role)||!['min','max','range'].includes(x.direction)||['low','high','min','max'].some(k=>x[k]!==null&&!Pareto.finite(x[k]))))throw Error('Некорректные критерии');$('protocol').value=s.protocol_id;buildCriteria(s.criteria);if(keys.includes(s.axis_x))$('axis-x').value=s.axis_x;if(keys.includes(s.axis_y))$('axis-y').value=s.axis_y;recompute();}catch(error){$('error').textContent='Импорт: '+error.message;}});
$('select-front').addEventListener('click',()=>{if($('error').textContent)return;selected.clear();decisions.filter(d=>d.front).forEach(d=>selected.add(d.id));renderTable();});$('clear-selected').addEventListener('click',()=>{selected.clear();renderTable();});
for(const id of ['filter','search'])$(id).addEventListener('input',renderTable);for(const id of ['axis-x','axis-y'])$(id).addEventListener('change',renderPlot);$('protocol').addEventListener('change',()=>{selected.clear();recompute();});
for(const p of DATA.protocols)option($('protocol'),p.id,p.label);for(const key of keys){option($('axis-x'),key,key);option($('axis-y'),key,key);}$('axis-x').value='docking_score';$('axis-y').value=keys.includes('DILI')?'DILI':keys[Math.min(1,keys.length-1)];$('run-title').textContent='Запуск: '+DATA.run_name;$('metadata').textContent=JSON.stringify({admet:DATA.admet_metadata,endpoints:DATA.endpoints,source_sha256:DATA.source_sha256},null,2);buildCriteria(defaults());recompute();
'''
