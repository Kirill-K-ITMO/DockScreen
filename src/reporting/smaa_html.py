"""Read-only, self-contained SMAA HTML; renders saved numbers without analysis.

No scripts, remote resources, molecular preparation or ranking are run here.
The full, exact distributions remain in the adjacent results JSON/rank CSV.
"""
from html import escape
import json
import math


_CSS = '''
:root{color-scheme:light;--ink:#193c32;--muted:#60766a;--green:#2c6047;--line:#dbe5dc;--pale:#edf4eb;--paper:#fff;--bg:#f2f5ef}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif}header{background:#204b36;color:white;padding:32px max(20px,5vw)}header p{color:#dce8dd;margin:8px 0 0}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700}h1{font-size:clamp(26px,4vw,38px);line-height:1.2;margin:10px 0}h2{font-size:21px;margin:0 0 12px}h3{font-size:17px;margin:0 0 6px}main{max-width:1600px;margin:auto;padding:22px max(16px,3vw) 50px}section,.panel{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:24px;margin:0 0 20px}p{margin:8px 0 14px}a{color:#17624b;text-underline-offset:3px}header a{color:white}.muted,small{color:var(--muted)}.notice{background:#fff8df;border-left:4px solid #c8a847;padding:14px 18px;border-radius:8px}.empty{background:var(--pale);padding:18px;border-radius:10px}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin-bottom:20px}.stat{background:white;padding:16px;border:1px solid var(--line);border-radius:12px}.stat strong{display:block;font-size:25px;line-height:1.25;font-variant-numeric:tabular-nums}.stat span{font-size:13px;color:var(--muted)}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}th{background:var(--pale);white-space:nowrap}td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}.candidate-name{font-weight:700;overflow-wrap:anywhere;min-width:130px;max-width:230px}.candidate-id{font-size:11px;color:var(--muted)}tr.excluded{background:#faf9f3}.badge{font-size:11px;display:inline-block;padding:3px 7px;border-radius:5px;background:var(--pale)}.badge.excluded{background:#f3e8ce;color:#715b29}.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:14px}.chart{background:#f8fbf6;border:1px solid var(--line);border-radius:10px;padding:16px;min-width:0}.chart svg{display:block;width:100%;height:auto;max-height:210px}.chart p{font-size:12px;margin:6px 0}details{margin:8px 0}summary{cursor:pointer;color:#225e43;font-weight:650}pre,code{font-family:ui-monospace,Consolas,monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5ee;border-radius:8px;padding:14px;font-size:12px;max-height:420px;overflow:auto}.values{display:grid;grid-template-columns:minmax(100px,1fr) minmax(70px,auto);gap:4px 14px;margin:8px 0;font-size:12px}.values dt{overflow-wrap:anywhere}.values dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}.rank-list{font-size:12px;max-height:170px;overflow:auto;padding-left:24px}.nowrap{white-space:nowrap}.links{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:13px}footer{margin-top:20px;font-size:12px;color:var(--muted)}@media(max-width:600px){section,.panel{padding:16px}th,td{padding:9px}header{padding:24px 18px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
'''


def _h(value):
    return escape(str(value), quote=True)


def _finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def _number(value):
    if not _finite(value):
        return '<span class="muted">нет значения</span>'
    return f'<span title="Точное значение: {_h(repr(value))}">{_h(format(value, ".6g"))}</span>'


def _raw(value):
    return 'не задано' if value is None else str(value)


def _status(row):
    return {'front': 'Фронт Парето', 'dominated': 'Доминируется', 'excluded': 'Исключён'}.get(row.get('pareto_status'), 'Не указан')


def _distribution(row):
    """Bounded detail preview; full distributions are never discarded from outputs."""
    smaa = row.get('smaa') or {}
    distribution = smaa.get('rank_acceptability') or {}
    pairs = sorted(((int(k), v) for k, v in distribution.items()
                    if str(k).isdigit() and int(k) > 0 and _finite(v) and v > 0), key=lambda item: item[0])
    if not pairs:
        return '<p class="muted">Распределение мест отсутствует.</p>'
    parts = ['<p>Доли занятых мест (0–1):</p><ol class="rank-list">']
    for rank, value in pairs[:40]:
        parts.append(f'<li value="{rank}">Место {rank}: {_number(value)}</li>')
    parts.append('</ol>')
    if len(pairs) > 40:
        parts.append(f'<p class="muted">Первые 40 из {len(pairs)} ненулевых мест. Полное распределение — в <a href="rank_acceptability.csv">rank_acceptability.csv</a> и <a href="results.json">results.json</a>.</p>')
    parts.append('<p class="muted">В полном разреженном распределении отсутствующие места имеют нулевую долю. Ограничение предпросмотра не обнуляет остальные значения.</p>')
    return ''.join(parts)


def _histogram(row, candidate_count):
    """Draw one saved distribution, aggregating only for readable display."""
    distribution = (row.get('smaa') or {}).get('rank_acceptability') or {}
    pairs = [(int(k), float(v)) for k, v in distribution.items()
             if str(k).isdigit() and 1 <= int(k) <= candidate_count and _finite(v) and v > 0]
    if not pairs or candidate_count < 1:
        return ''
    width = max(1, math.ceil(candidate_count / 40))
    bins = {}
    for rank, value in pairs:
        start = ((rank - 1) // width) * width + 1
        bins[start] = bins.get(start, 0.) + value
    starts = list(range(1, candidate_count + 1, width))
    max_value = max(bins.values())
    slot = 340 / len(starts)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 210" role="img" aria-label="Распределение приемлемости рангов">',
             '<path d="M42 16V174H388" fill="none" stroke="#a3b8a4"/>',
             f'<text x="38" y="22" text-anchor="end" font-size="10" fill="#60766a">{max_value:.3g}</text>',
             '<text x="38" y="176" text-anchor="end" font-size="10" fill="#60766a">0</text>']
    for index, start in enumerate(starts):
        value = bins.get(start, 0.)
        if not value:
            continue
        end = min(candidate_count, start + width - 1)
        height = 145 * value / max_value
        caption = f'Место {start}' if start == end else f'Места {start}–{end}'
        parts.append(f'<rect x="{46 + index * slot:.3f}" y="{174-height:.3f}" width="{max(.5,slot-1):.3f}" height="{height:.3f}" rx="1" fill="#4c855b"><title>{_h(caption)}: {_h(repr(value))} доли</title></rect>')
    parts.extend([f'<text x="46" y="192" font-size="11" fill="#60766a">1</text>',
                  f'<text x="386" y="192" text-anchor="end" font-size="11" fill="#60766a">{candidate_count}</text>',
                  '<text x="215" y="207" text-anchor="middle" font-size="11" fill="#60766a">Место (меньше — лучше)</text></svg>'])
    if width > 1:
        parts.append(f'<p class="muted">Для рисунка доли объединены по {width} соседним местам; высота — сумма долей в группе. Полные значения не изменены.</p>')
    else:
        parts.append('<p class="muted">Высота столбца — доля сценарного распределения данного места. Масштаб высоты индивидуален для каждого графика.</p>')
    return ''.join(parts)


def render_smaa_html(document, *, include_pareto=True):
    """Render saved SMAA results. This function never changes results or settings.

    The HTML belongs beside results.json/candidates.csv/rank_acceptability.csv.
    All scientific and identity strings are escaped; only static relative links
    are emitted. Display rounding does not affect stored values or selections.
    """
    rows = document.get('rows') or []
    configuration = document.get('configuration') or {}
    counts = document.get('counts') or {}
    protocol = document.get('protocol') or {}
    ranked = [r for r in rows if isinstance(r.get('smaa'), dict)]
    ordered = sorted(ranked, key=lambda row: ((row['smaa'].get('expected_rank')
                     if _finite(row['smaa'].get('expected_rank')) else math.inf), str(row.get('id'))))
    excluded = [r for r in rows if not isinstance(r.get('smaa'), dict)]
    candidate_count = len(ranked)
    title = 'Парето + SMAA' if include_pareto else 'SMAA — анализ предпочтений'
    actual = configuration.get('completed_scenarios', configuration.get('iterations', 0) if ranked else 0)
    requested_n = configuration.get('requested_top_n')
    effective_n = configuration.get('effective_top_n', min(candidate_count, requested_n) if type(requested_n) is int else candidate_count)
    parts = ['<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
             f'<title>DockScreen · {_h(title)}</title><style>{_CSS}</style></head><body>',
             f'<header><div class="eyebrow">DockScreen · сохранённые результаты</div><h1>{_h(title)}</h1>',
             '<p>Чувствительность выбора к предпочтениям · без референсных соединений</p></header><main>',
             '<div class="stats">']
    stats = [('Исходных строк', counts.get('total', len(rows))), ('Участвуют в SMAA', candidate_count)]
    if include_pareto:
        stats.append(('На фронте Парето', counts.get('front', sum(r.get('pareto_status') == 'front' for r in rows))))
    stats.extend([('Выполнено сценариев', actual), ('Применённый топ-N', effective_n)])
    for label, value in stats:
        parts.append(f'<div class="stat"><strong>{_h(value)}</strong><span>{_h(label)}</span></div>')
    parts.extend(['</div><section><h2>Как читать этот отчёт</h2>',
                  f'<p>Мишень: <b>{_h(protocol.get("target", "не указана"))}</b>. Протокол: <code>{_h(protocol.get("id", "не указан"))}</code>.</p>',
                  f'<p>Запрошено сценариев: {_h(configuration.get("iterations", "не указано"))}; выполнено: {_h(actual)}. Seed: <b>{_h(configuration.get("seed", "не указан"))}</b>. Запрошен топ-{_h(requested_n)}; применён топ-{_h(effective_n)} из {_h(candidate_count)} кандидатов.</p>',
                  '<p class="notice"><b>Доли 0–1 относятся к сценариям предпочтений.</b> Это не вероятность экспериментального успеха, клинической безопасности или истинного превосходства молекулы. Докинг не равен измеренной активности. ADMET-классификаторы не дают индивидуальную точность предсказания; Bioavailability_Ma не является процентом биодоступности.</p>',
                  '<p>Свойства фиксированы: изменяются только веса целей. Все прошедшие ограничения строки участвуют в ранжировании. Ожидаемое место — среднее по распределению мест, меньше предпочтительнее. Например, доля топ-N 0.65 означает 65% сценарного вклада в топ-N, а не 65% шанса стать лекарством.</p>',
                  '<p>Равные итоговые оценки поровну делят занятые места, включая границу топ-N. Порядок строк не даёт преимущества. Это симметричное распределение мест, а не присвоение всем связанным кандидатам общего первого ранга. Квантили — обратная дискретная функция распределения рангов.</p>',
                  '<p class="muted">Показанные числа округлены; наведите указатель для точного значения. CSV/JSON сохраняют исходную точность. Отчёт только показывает сохранённые результаты и не пересчитывает докинг, ADMET, ограничения или ранги.</p>',
                  '<div class="links"><a href="candidates.csv">Метрики CSV</a><a href="rank_acceptability.csv">Все распределения рангов</a><a href="results.json">Полные результаты JSON</a><a href="settings.json">Настройки SMAA</a><a href="criteria.csv">Применённые критерии</a></div></section>'])
    if not ranked:
        parts.append('<section><h2>Допустимый набор пуст</h2><p class="empty">Ни одна строка не участвует в ранжировании. Места и доли не назначены: исключение не означает последнее место или нулевое качество. Причины приведены ниже. Ограничения автоматически не ослаблялись.</p></section>')
    else:
        parts.append('<section><h2>Распределения мест: первые пять по ожидаемому рангу</h2><p class="muted">Это порядок просмотра по сохранённому ожидаемому месту, не новый метод выбора победителя. Графики показывают весь допустимый набор мест.</p><div class="charts">')
        for row in ordered[:5]:
            smaa = row['smaa']
            parts.extend([f'<article class="chart"><h3>{_h(row.get("name", ""))}</h3><small>ID {_h(row.get("id", ""))}</small>',
                          f'<p>Ожидаемое место: {_number(smaa.get("expected_rank"))} · топ-{_h(effective_n)}: {_number(smaa.get("top_n_acceptability"))}</p>',
                          _histogram(row, candidate_count), '</article>'])
        parts.append('</div></section>')
    parts.append('<section><h2>Все исходные строки</h2><p>Участники показаны по ожидаемому месту; ниже — не участвующие строки с причинами. SMILES, выбранные свойства и распределение мест доступны в раскрывающихся строках.</p><div class="scroll"><table><thead><tr>')
    headings = ['ID / название', f'Доля топ-{effective_n}', 'Доля первого места', 'Ожидаемое место', 'Медиана', 'Квантили мест']
    if include_pareto:
        headings.append('Статус Парето')
    headings.append('Пояснения и исходные значения')
    parts.extend(f'<th>{_h(label)}</th>' for label in headings)
    parts.append('</tr></thead><tbody>')
    quantiles = configuration.get('rank_quantiles', [.05, .95])
    for row in [*ordered, *excluded]:
        smaa = row.get('smaa') or {}
        present = bool(smaa)
        reasons = row.get('exclusion_reasons') or []
        parts.append(f'<tr class="{"ranked" if present else "excluded"}" data-row-id="{_h(row.get("id", ""))}"><td><div class="candidate-name">{_h(row.get("name", ""))}</div><div class="candidate-id">ID {_h(row.get("id", ""))} · строка {_h(row.get("row_id", ""))}</div></td>')
        for key in ('top_n_acceptability', 'first_rank_acceptability', 'expected_rank', 'median_rank'):
            parts.append(f'<td class="num">{_number(smaa.get(key)) if present else "—"}</td>')
        if present:
            parts.append(f'<td class="num" title="Квантили q={_h(quantiles)}">{_number(smaa.get("rank_quantile_low", smaa.get("rank_p05")))} … {_number(smaa.get("rank_quantile_high", smaa.get("rank_p95")))}</td>')
        else:
            parts.append('<td class="num">—</td>')
        if include_pareto:
            parts.append(f'<td><span class="badge{ " excluded" if not present else ""}">{_h(_status(row))}</span></td>')
        parts.append('<td>')
        if not present:
            parts.append('<p><b>Не участвует.</b> ' + _h('; '.join(str(reason) for reason in reasons) or 'Причина не сохранена') + '</p>')
        parts.append('<details><summary>SMILES, свойства и ранги</summary><p><b>SMILES</b></p><pre>' + _h(row.get('smiles', '')) + '</pre><dl class="values">')
        for key, value in (row.get('values') or {}).items():
            parts.append(f'<dt>{_h(key)}</dt><dd>{_number(value)}</dd>')
        parts.append('</dl>')
        if present:
            parts.append(_distribution(row))
            parts.append(f'<p class="muted">Monte Carlo SE доли топ-N: {_number(smaa.get("top_n_mc_se"))}; первого места: {_number(smaa.get("first_rank_mc_se"))}. Это погрешность интегрирования выбранных предпочтений, не ошибка предсказания свойств.</p>')
        parts.append('</details></td></tr>')
    parts.append('</tbody></table></div></section><section><h2>Критерии и фиксированные шкалы</h2><p>CSV задаёт допустимые границы и цели. Равенство границе допускается; пропуск активного значения исключает строку. JSON фиксирует шкалы и предпочтения. Изменение видимости в отчёте не меняет настройки.</p><div class="scroll"><table><thead><tr><th>Параметр</th><th>Роль</th><th>Цель</th><th>Не ниже</th><th>Не выше</th><th>Целевой диапазон</th></tr></thead><tbody>')
    directions = {'min': 'Минимум ↓', 'max': 'Максимум ↑', 'range': 'К диапазону'}
    roles = {'objective': 'Сравнивать', 'constraint': 'Только ограничение', 'display': 'Не учитывать'}
    for criterion in document.get('criteria') or []:
        parts.append('<tr>' + ''.join(f'<td>{_h(value)}</td>' for value in [criterion.get('key', ''), roles.get(criterion.get('role'), criterion.get('role', '')), directions.get(criterion.get('direction'), '—') if criterion.get('role') == 'objective' else '—', _raw(criterion.get('min')), _raw(criterion.get('max')), f'{_raw(criterion.get("low"))} … {_raw(criterion.get("high"))}' if criterion.get('direction') == 'range' else '—']) + '</tr>')
    parts.append('</tbody></table></div><p>Желательность линейна между worst (0) и best (1), за якорями насыщается до 0/1. Для диапазона сначала вычисляется расстояние до него, равное нулю внутри. Насыщение может превратить строгое исходное доминирование в равенство желательностей.</p><div class="scroll"><table><thead><tr><th>Цель</th><th>worst → 0</th><th>best → 1</th><th>alpha</th><th>Происхождение якорей</th></tr></thead><tbody>')
    for scale in document.get('scales') or configuration.get('scales') or []:
        origin = json.dumps(scale.get('origin') or {}, ensure_ascii=False, sort_keys=True)
        parts.append('<tr><td>' + _h(scale.get('key', '')) + '</td><td>' + _number(scale.get('worst')) + '</td><td>' + _number(scale.get('best')) + '</td><td>' + _number(scale.get('alpha')) + '</td><td><details><summary>Источник шкалы</summary><pre>' + _h(origin) + '</pre></details></td></tr>')
    parts.append('</tbody></table></div><p>Веса: <b>' + _h(configuration.get('weight_distribution', 'Dirichlet')) + '</b>; alpha=' + _h(configuration.get('alpha', [])) + '. При всех alpha=1 распределение равномерно по симплексу — это выбранное допущение, зависящее от целей и шкал. Аддитивная сумма допускает компенсацию свойств внутри допустимого набора; пересекающиеся показатели не являются независимыми свидетельствами. Индивидуальная неопределённость свойств не моделируется.</p></section>')
    provenance = {key: value for key, value in document.items() if key not in ('rows', 'admet_metadata')}
    if not include_pareto:
        provenance = {**provenance, 'counts': {key: value for key, value in counts.items() if key != 'front'}}
    parts.append('<section><details><summary>Протокол, версии и контрольные суммы</summary><pre>' + _h(json.dumps(provenance, ensure_ascii=False, sort_keys=True, indent=2)) + '</pre></details><p class="muted">Воспроизведение требует тех же входных данных, порядка целей, настроек и версий вычислительной среды. Метаданные моделей ADMET находятся в metadata.json / results.json. <a href="metadata.json">Метаданные анализа</a>.</p></section><footer>DockScreen · самостоятельный отчёт без внешних ресурсов. Полные значения и исключения сохранены в соседних CSV/JSON; округление и порядок просмотра не влияют на вычисления.</footer></main></body></html>')
    return ''.join(parts)
