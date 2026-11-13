"""Versioned per-row business pricing basis; source observations are immutable."""
from __future__ import annotations

import copy
from pathlib import Path

from .core import Rejected, context, decimal, positive, digest, now, changed, require_actor
from .storage import Store, atomic_json, check_sources

SCHEMA = 'japan-arrival/business-amount-1'
FIELDS = {'amount', 'currency', 'quantity', 'quantity_unit', 'reason'}

def current(row):
    ledger = row.get('business_amount')
    if not ledger:
        return None
    versions = ledger.get('versions', [])
    if ledger.get('schema') != SCHEMA or not versions or ledger.get('current_version') != len(versions):
        raise Rejected('最终金额版本链无效')
    previous = None
    for index, record in enumerate(versions, 1):
        if record.get('version') != index or record.get('previous_hash') != previous:
            raise Rejected('最终金额历史链无效')
        body = {k: v for k, v in record.items() if k != 'record_hash'}
        if digest(body) != record.get('record_hash'):
            raise Rejected('最终金额记录被修改')
        previous = record['record_hash']
    return versions[-1]

def approved(row):
    record = current(row)
    review = row['reviews']['price']
    return bool(record and record['fact_hash'] == digest(context(row)) and review
                and review.get('business_amount_hash') == record['record_hash'])

def effective_basis(row):
    record = current(row)
    if record and approved(row):
        return dict(record['values'], status='business_confirmed_in_batch', source=record['source'],
                    business_amount_version=record['version'])
    return row['authority']

def values_for(row, values):
    if not isinstance(values, dict) or set(values) != FIELDS:
        raise Rejected('最终金额须逐行明确金额、JPY币种、计价数量、单位和原因')
    if any(not isinstance(v, str) or not v.strip() for v in values.values()):
        raise Rejected('最终金额字段须完整文本，不能使用浮点数或空值')
    if decimal(values['amount']) < 0 or values['currency'] != 'JPY':
        raise Rejected('本期最终金额须为非负JPY金额')
    positive(values['quantity'])
    if values['quantity_unit'] in ('未知', '待确认', 'JPY', 'USD', 'CNY'):
        raise Rejected('计价单位尚未确认')
    return copy.deepcopy(values)

def authorize_amount(root, session, batch):
    """Only this domain may use host duties for an unsigned raw-input batch.

    This does not sign D08 for material/customs or upgrade the batch into D1.
    """
    from .business_setup import runtime
    from .return_auth import validate_session, authorize
    config = runtime(root)
    # A host configured for synthetic technical work can never create a business
    # amount approval merely because a malformed legacy batch omitted its mode.
    if config['execution_mode'] == 'synthetic_technical_test' and batch.get('execution_mode') != 'synthetic_technical_test':
        raise Rejected('合成权限只能确认明确标记的技术测试批次')
    if batch.get('execution_mode') == 'synthetic_technical_test' and config['execution_mode'] != 'synthetic_technical_test':
        raise Rejected('技术批次不能升级为业务金额批准')
    if batch.get('execution_mode') == 'preliminary_untrusted' and config['execution_mode'] != 'business':
        raise Rejected('合成权限不能用于真实原表初步批次')
    if batch.get('input_mode') == 'raw_invoice_preliminary' and not batch.get('input_contract', {}).get('approval'):
        validate_session(root, session, config['execution_mode'])
        permissions = {session.principal: [role for role in session.roles
                       if session.principal in (config['responsibilities'].get(role) or [])]}
        require_actor(session.principal, 'amount', permissions)
    else:
        authorize(root, session, batch, 'amount')
    return config

def apply_amount(row, values, *, session, reference, source_revision, authorization_hash):
    values = values_for(row, values)
    previous = current(row)
    old_basis = effective_basis(row)
    unit_changed = any(values[k] != old_basis[k] for k in ('quantity', 'quantity_unit'))
    # Every approved new version invalidates dependent monetary results.
    row['reviews']['price'] = None
    row['reviews']['tax'] = None
    row['tax'] = None
    if unit_changed:
        row['reviews']['packaging'] = None
        row['packaging'] = None
    ledger = row.setdefault('business_amount', {'schema': SCHEMA, 'versions': [], 'current_version': 0})
    record = {'version': len(ledger['versions']) + 1, 'previous_hash': previous['record_hash'] if previous else None,
              'values': values, 'fact_hash': digest(context(row)), 'source': copy.deepcopy(row['source']),
              'source_revision': source_revision, 'reference': reference, 'confirmed_at': now(),
              'execution': session.evidence(), 'authorization_hash': authorization_hash,
              'status': 'synthetic_technical_approved' if session.mode == 'synthetic_technical_test' else 'business_amount_approved'}
    record['record_hash'] = digest(record)
    ledger['versions'].append(record); ledger['current_version'] = record['version']
    row['reviews']['price'] = {'confirmed_by': session.principal, 'confirmed_at': record['confirmed_at'],
                              'reference': reference, 'business_amount_hash': record['record_hash']}
    row['disputes'] = [d for d in row['disputes'] if d.get('domain') != 'price']
    return record

def preview(root, batch_id, items, *, reference):
    store = Store(root); batch = store.load(batch_id); check_sources(batch)
    if not isinstance(reference, str) or not reference.strip():
        raise Rejected('最终金额须有来源依据')
    if not isinstance(items, dict) or not items:
        raise Rejected('最终金额须按稳定行ID提供明确逐行范围，不接受总额分摊')
    rows = {r['id']: r for r in batch['rows']}
    if set(items) - set(rows):
        raise Rejected('最终金额包含未知商品行')
    normalized = {rid: values_for(rows[rid], value) for rid, value in items.items()}
    differences = [{'row_id': rid, 'original': copy.deepcopy(rows[rid]['authority']),
                    'before': copy.deepcopy(effective_basis(rows[rid])), 'proposed': value,
                    'delta': str(decimal(value['amount']) - decimal(rows[rid]['authority']['amount'])),
                    'fact_hash': digest(context(rows[rid]))} for rid, value in sorted(normalized.items())]
    data = {'schema': SCHEMA, 'batch_id': batch_id, 'base_hash': digest(batch), 'items': normalized,
            'reference': reference, 'differences': differences, 'formal_output': False}
    key = digest(data); path = store.root / 'amount_previews' / (key + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        import json
        if json.loads(path.read_text(encoding='utf-8')) != data: raise Rejected('金额预览登记冲突')
    else: atomic_json(path, data)
    return {'preview_id': key, 'confirmation_hash': key, 'changes': differences, 'submitted': False, 'formal_output': False}

def commit(root, batch_id, preview_id, *, confirmed_hash, confirm, session, reference):
    import json
    from .excel_return import safe_id
    safe_id(preview_id)
    if confirm is not True or confirmed_hash != preview_id or not isinstance(reference, str) or not reference.strip():
        raise Rejected('须先展示金额差异并明确确认对应版本及依据')
    store = Store(root); batch = store.load(batch_id); check_sources(batch)
    config = authorize_amount(root, session, batch)
    data = json.loads((store.root / 'amount_previews' / (preview_id + '.json')).read_text(encoding='utf-8'))
    if digest(data) != preview_id or data['batch_id'] != batch_id or data.get('schema') != SCHEMA:
        raise Rejected('金额预览被修改或跨批次')
    transaction = digest({'preview_id': preview_id, 'principal': session.principal, 'mode': session.mode, 'reference': reference})
    if transaction in batch.get('amount_receipts', {}):
        return dict(batch['amount_receipts'][transaction], replayed=True)
    if digest(batch) != data['base_hash']:
        raise Rejected('金额预览已过期，不能覆盖并发新版本')
    rows = {r['id']: r for r in batch['rows']}
    for rid, values in data['items'].items():
        values_for(rows[rid], values)
        if values['quantity_unit'] not in config['quantity_units']:
            raise Rejected('金额计价单位不在可信环境已确认清单中')
    out = copy.deepcopy(batch)
    for row in out['rows']:
        if row['id'] in data['items']:
            apply_amount(row, data['items'][row['id']], session=session, reference=data['reference'] + '；确认：' + reference,
                         source_revision=batch['revision'], authorization_hash=digest(config))
    receipt = {'transaction_id': transaction, 'preview_id': preview_id, 'revision': batch['revision'] + 1,
               'saved_rows': sorted(data['items']), 'formal_output': False, 'd1_learning_eligible': False,
               'execution': session.evidence()}
    out.setdefault('amount_receipts', {})[transaction] = receipt
    out = changed(batch, out, session.principal, 'confirm_business_amount', sorted(data['items']),
                  {'reference': reference, 'preview_id': preview_id, 'execution': session.evidence()})
    store.save(out, expected_hash=digest(batch))
    return dict(receipt, replayed=False)
