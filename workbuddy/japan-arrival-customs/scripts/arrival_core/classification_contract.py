"""Shared D2/D3 exact-text contract. Unknown values never become wildcards."""
from datetime import date, datetime, timezone
from .core import Rejected, digest
from .declaration_decisions import FACT_FIELDS, FINAL_FIELDS, validate_values

CONDITIONS = tuple(sorted(FACT_FIELDS | {'jurisdiction', 'origin_conditions', 'trade_conditions', 'tariff_schedule_version'}))
TARGET = ('declaration_material', 'classification_code', 'duty_rate', 'vat_rate', 'tariff_schedule_version')

def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None: raise ValueError()
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError) as exc:
        raise Rejected('事件时间必须包含时区') from exc

def day(value):
    if date.fromisoformat(value).isoformat() != value: raise Rejected('日期必须为YYYY-MM-DD')
    return value

def contract(decision):
    facts, final = decision['facts'], decision['human_final']
    conditions = {k: facts.get(k) if k in FACT_FIELDS else final.get(k) for k in CONDITIONS}
    if any(not isinstance(v, str) or not v.strip() for v in conditions.values()):
        raise Rejected('归类条件缺失；未知不能作为通配')
    if any(not isinstance(final.get(k), str) or not final[k].strip() for k in FINAL_FIELDS):
        raise Rejected('申报材质、税号、税率及有效条件须完整')
    validate_values({**facts, **final})
    if not final['valid_from'] <= final['applicability_date'] <= final['valid_through']:
        raise Rejected('税率适用日期不在有效期内')
    return conditions, {k: final[k] for k in TARGET}

def identity(record):
    context = record['decision']['context']
    if context.get('code'): return 'code:' + context['code']
    return 'no-code:' + record['batch_id'] + ':' + record['decision']['row_id']

def reference(record):
    return {k: record[k] for k in ('batch_id', 'decision_id', 'event_id', 'version', 'source_bundle')}

def signature(conditions, target):
    return digest({'contract': 'japan-arrival/classification-conditions-1', 'conditions': conditions, 'target': target})
