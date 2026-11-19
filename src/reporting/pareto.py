"""Exact non-dominance with inclusive constraints; browser engine is self-contained."""
import math


def select_pareto(rows, settings):
    """Rows have id/values/eligible; settings have key, role and optional bounds."""
    result = []
    active = [s for s in settings if s.get('role') in ('objective', 'constraint')]
    for row in rows:
        reasons, vector = [], []
        if row.get('eligible') is False:
            reasons.append(row.get('error') or 'Нет успешного докинга для выбранного протокола')
        for setting in active:
            key = setting['key']
            value = row.get('values', {}).get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                reasons.append(f'{key}: нет численного значения')
                continue
            if setting.get('min') is not None and value < setting['min']:
                reasons.append(f'{key}: ниже нижнего порога')
            if setting.get('max') is not None and value > setting['max']:
                reasons.append(f'{key}: выше верхнего порога')
            if setting['role'] == 'objective':
                direction = setting.get('direction', 'min')
                if direction == 'range':
                    low, high = setting.get('low'), setting.get('high')
                    if low is None or high is None or not math.isfinite(low) or not math.isfinite(high) or low > high:
                        raise ValueError(f'{key}: invalid target range')
                    vector.append(max(low - value, 0, value - high))
                elif direction in ('min', 'max'):
                    vector.append(value if direction == 'min' else -value)
                else:
                    raise ValueError(f'{key}: invalid direction')
        result.append({'id': row['id'], 'reasons': reasons, 'vector': vector, 'dominators': [], 'front': False})
    feasible = [r for r in result if not r['reasons']]
    for candidate in feasible:
        candidate['dominators'] = [other['id'] for other in feasible if
            all(a <= b for a, b in zip(other['vector'], candidate['vector'])) and
            any(a < b for a, b in zip(other['vector'], candidate['vector']))]
        candidate['front'] = bool(candidate['vector']) and not candidate['dominators']
    return result


PARETO_JS = r'''
const Pareto = (() => {
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  function select(rows, settings) {
    const active = settings.filter(s => ['objective','constraint'].includes(s.role));
    const result = rows.map(row => {
      const reasons = [], vector = [];
      if(row.eligible === false) reasons.push(row.error || 'Нет успешного докинга для выбранного протокола');
      for(const s of active) {
        const v = row.values[s.key];
        if(!finite(v)) { reasons.push(s.key+': нет численного значения'); continue; }
        if(s.min !== null && s.min !== undefined && v < s.min) reasons.push(s.key+': ниже нижнего порога');
        if(s.max !== null && s.max !== undefined && v > s.max) reasons.push(s.key+': выше верхнего порога');
        if(s.role === 'objective') {
          if(s.direction === 'range') {
            if(!finite(s.low) || !finite(s.high) || s.low > s.high) throw Error(s.key+': задайте корректный целевой диапазон');
            vector.push(Math.max(s.low-v,0,v-s.high));
          } else if(['min','max'].includes(s.direction)) vector.push(s.direction==='max' ? -v : v);
          else throw Error(s.key+': неизвестное направление');
        }
      }
      return {id:row.id,reasons,vector,dominators:[],front:false};
    });
    const feasible = result.filter(r=>!r.reasons.length);
    for(const r of feasible) {
      r.dominators=feasible.filter(o=>o.vector.every((v,i)=>v<=r.vector[i]) && o.vector.some((v,i)=>v<r.vector[i])).map(o=>o.id);
      r.front=r.vector.length>0 && !r.dominators.length;
    }
    return result;
  }
  return {select,finite};
})();
if(typeof module !== 'undefined') module.exports = Pareto;
'''
