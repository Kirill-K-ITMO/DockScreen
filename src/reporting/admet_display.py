"""Offline presentation controls only: never changes ADMET values or selection."""

DEFAULT_VISIBLE = ('DILI', 'ClinTox', 'Bioavailability_Ma')
LABELS = {
    'DILI': 'DILI — сигнал повреждения печени',
    'ClinTox': 'ClinTox — клиническая токсичность, модель',
    'Bioavailability_Ma': 'Bioavailability_Ma — биодоступность, модель',
    'hERG': 'hERG — блокирование канала, модель',
    'AMES': 'AMES — мутагенность, модель',
}

CSS = r'''
[hidden]{display:none!important}
.report-tabs{display:flex;gap:8px;padding:18px 20px 0;background:var(--bg-secondary)}
.report-tabs button,.admet-actions button{border:1px solid var(--border-color);border-radius:8px;padding:10px 18px;background:var(--bg-card);color:var(--text-primary);cursor:pointer;font:inherit}
.report-tabs [aria-selected="true"]{background:var(--accent-color);color:var(--bg-primary);font-weight:700}
.report-tabs button:focus-visible,.admet-actions button:focus-visible{outline:3px solid var(--accent-color);outline-offset:2px}
.admet-picker{padding:18px 20px;background:var(--bg-secondary);border-bottom:1px solid var(--border-color)}
.admet-picker p{margin:8px 0;line-height:1.55}.admet-picker summary{cursor:pointer;font-weight:650;padding:8px 0}
.admet-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}
.admet-picker input[type="search"]{padding:10px;border:1px solid var(--border-color);background:var(--bg-card);color:var(--text-primary);border-radius:8px;width:min(100%,480px)}
.admet-options{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:8px;max-height:280px;overflow:auto;margin-top:12px}
.admet-choice{display:flex;align-items:flex-start;gap:9px;padding:10px;border:1px solid var(--border-color);border-radius:8px;background:var(--bg-card);cursor:pointer}
.admet-choice input{margin-top:4px;accent-color:var(--accent-color)}.admet-choice small{display:block;color:var(--text-secondary);margin-top:3px}
.admet-note{color:var(--text-secondary);font-size:.9em}.admet-picker [role="status"]{font-weight:650}
'''

HTML = r'''
{% if admet is not none %}
<nav class="report-tabs" role="tablist" aria-label="Раздел отчёта">
  <button type="button" id="tab-docking" role="tab" aria-selected="true" aria-controls="report-table-panel" tabindex="0">Докинг</button>
  <button type="button" id="tab-admet" role="tab" aria-selected="false" aria-controls="report-table-panel" tabindex="-1">ADMET</button>
</nav>
<section class="admet-picker" id="admet-picker" hidden aria-label="Отображение ADMET">
  <p><strong>Выберите, какие показатели показать рядом с оценками докинга.</strong> Это меняет только столбцы — значения и отбор Парето остаются прежними.</p>
  <p id="admet-visible-count" role="status" aria-live="polite"></p>
  <details><summary>Выбрать показатели ADMET</summary>
    <div class="admet-actions"><button type="button" id="admet-basic">DILI · ClinTox · Bioavailability</button><button type="button" id="admet-all">Показать все</button><button type="button" id="admet-none">Скрыть все</button></div>
    <label for="admet-metric-search">Найти показатель</label><br><input type="search" id="admet-metric-search" placeholder="Название, ID или категория" autocomplete="off">
    <p id="admet-no-matches" hidden>Подходящие показатели не найдены. Измените запрос.</p>
    <div class="admet-options" id="admet-options">
    {% for key in admet_picker_keys %}{% set meta = admet.endpoints[key] %}
      <label class="admet-choice"><input type="checkbox" data-admet-choice="{{ key }}" {% if key in admet_default_visible %}checked{% endif %}>
        <span>{{ admet_labels.get(key, meta.get('name', key)) }}<small>{{ key }} · {{ meta.get('category', 'Другие') }} · {{ 'модельная оценка 0–1' if meta.get('type') == 'classification' else meta.get('units', 'единицы не указаны') }}</small></span>
      </label>
    {% endfor %}
    </div>
  </details>
  <p class="admet-note">DILI, ClinTox и другие классификаторы — не клинические вероятности. Bioavailability_Ma — не процент биодоступности. Пропуск показан знаком «—». CSV содержит полный набор показателей независимо от выбора здесь.</p>
</section>
<noscript><p>Для вкладок нужен JavaScript. Все значения доступны в CSV.</p><style>[data-admet-key],[data-admet-status]{display:table-cell!important}</style></noscript>
{% endif %}
'''

JS = r'''
(() => {
  const docking=document.getElementById('tab-docking'),admet=document.getElementById('tab-admet');
  if(!docking||!admet)return;
  const panel=document.getElementById('report-table-panel'),picker=document.getElementById('admet-picker');
  const choices=Array.from(document.querySelectorAll('[data-admet-choice]'));
  const cells=Array.from(document.querySelectorAll('[data-admet-key]'));
  const statuses=Array.from(document.querySelectorAll('[data-admet-status]'));
  const dockingOnly=Array.from(document.querySelectorAll('[data-docking-only]'));
  const count=document.getElementById('admet-visible-count');
  let mode='docking';
  function refresh(){
    const selected=new Set(choices.filter(c=>c.checked).map(c=>c.dataset.admetChoice));
    cells.forEach(c=>c.hidden=mode!=='admet'||!selected.has(c.dataset.admetKey));
    statuses.forEach(c=>c.hidden=mode!=='admet');
    dockingOnly.forEach(c=>c.hidden=mode==='admet');
    count.textContent=choices.length?`Показано показателей: ${selected.size} из ${choices.length}.`+(selected.size?'':' Выберите хотя бы один показатель; пока виден только статус ADMET.'):'Показатели ADMET недоступны. Подробности — в столбце статуса.';
  }
  function activate(next){
    mode=next;picker.hidden=mode!=='admet';
    for(const tab of [docking,admet]){const active=tab.id==='tab-'+mode;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;}
    panel.setAttribute('aria-labelledby','tab-'+mode);refresh();
  }
  docking.addEventListener('click',()=>activate('docking'));
  admet.addEventListener('click',()=>activate('admet'));
  for(const tab of [docking,admet])tab.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const next=event.key==='Home'?docking:event.key==='End'?admet:tab===docking?admet:docking;
    next.focus();activate(next===docking?'docking':'admet');
  });
  choices.forEach(c=>c.addEventListener('change',refresh));
  function choose(predicate){choices.forEach(c=>c.checked=predicate(c.dataset.admetChoice));refresh();}
  document.getElementById('admet-basic').addEventListener('click',()=>choose(k=>['DILI','ClinTox','Bioavailability_Ma'].includes(k)));
  document.getElementById('admet-all').addEventListener('click',()=>choose(()=>true));
  document.getElementById('admet-none').addEventListener('click',()=>choose(()=>false));
  document.getElementById('admet-metric-search').addEventListener('input',event=>{
    const query=event.target.value.trim().toLowerCase();let matches=0;
    for(const item of document.querySelectorAll('#admet-options .admet-choice')){item.hidden=!item.textContent.toLowerCase().includes(query);if(!item.hidden)matches++;}
    document.getElementById('admet-no-matches').hidden=matches>0;
  });
  activate('docking');
})();
'''
