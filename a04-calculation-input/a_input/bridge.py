"""Read A03 HEAD, project confirmed fields and preflight the frozen rc.5 model."""
from copy import deepcopy
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'a03-confirmation'))
from a_confirm.support import Rejected, bootstrap, key, load, digest
from a_confirm import model
from a_confirm.service import Service


def dependencies():
    lock = load(Path(__file__).resolve().parents[1] / 'dependency-lock.json')
    for name, expected in lock['files'].items():
        p = (REPO / name).resolve(strict=True)
        if not p.is_relative_to(REPO) or digest(p) != expected:
            raise Rejected('A-04冻结依赖变化：' + name)
    bootstrap()


def confirmed(field, fields):
    if not field or field.get('confirmed') is not True:
        return False
    if field.get('status') not in model.CONFIRMED or not field.get('confirmation', {}).get('reference'):
        return False
    if field.get('identity_context_hash') != model.identity_context(fields, field['row_id']):
        return False
    return True


def project(view, batch):
    """Internal projection of a validated A03 snapshot; never a caller approval API."""
    from arrival_core.core import validate, proof_valid, context, decimal, positive, pricing_basis
    from arrival_core.business_amount import current, approved
    from fractions import Fraction
    fields = view['fields']
    by_row = {}
    for f in fields.values():
        by_row.setdefault(f['row_id'], {})[f['field']] = f
    checks = {r['row_id']: r for r in view['calculated_cells']}
    ready, pending = [], []
    adopted = []
    for original in batch['rows']:
        row = deepcopy(original)
        rid = row['id']; fs = by_row.get(rid, {}); blockers = []
        accepted = {}
        for name, f in fs.items():
            if confirmed(f, fields):
                accepted[name] = deepcopy(f['value'])
        # Source/raw/authority remain observations. Only the sparse current A view
        # supplies business/product values, never raw historical candidate fields.
        for name in ('internal_name', 'category', 'channel', 'yd'):
            row['product'][name] = accepted.get(name, {}).get('value') or ''
        row['product']['customs_name'] = ''
        row['reviews']['product'] = None
        row['identity']['specification'] = accepted.get('specification', {}).get('value') or ''
        row['material'] = {'candidate': '', 'selected': None, 'candidates': []}
        row['tax'] = None
        row['reviews']['tax'] = None
        row['reviews']['material'] = None
        if 'product_code' in accepted:
            row['identity']['code'] = accepted['product_code']['value']
        price = fs.get('purchase_unit_price')
        box = fs.get('pieces_per_box')
        if price and 'purchase_unit_price' in accepted:
            proof = price.get('evidence', {})
            if (not price.get('adopted_basis_current') or proof.get('price_basis_hash') != view['price_basis_hash']
                    or proof.get('currency') != 'JPY' or not proof.get('source_ref')
                    or proof.get('source_kind') not in ('purchase_document', 'explicit_purchase_price_confirmation')):
                accepted.pop('purchase_unit_price')
        if box and 'pieces_per_box' in accepted:
            proof = box.get('evidence', {})
            if not box.get('adopted_basis_current') or proof.get('meaning') != 'pieces_per_box' or not proof.get('source_ref'):
                accepted.pop('pieces_per_box')
        # Quantity, amount and their actual units must come from the existing B2
        # confirmed ledger, not Qty observations or a purchase-price reference.
        record = current(original)
        basis_valid = bool(record and approved(original) and proof_valid(original['reviews'].get('price'))
                           and record.get('status') == 'business_amount_approved')
        if basis_valid:
            basis = pricing_basis(original)
            try:
                positive(basis['quantity']); decimal(basis['amount'])
                if decimal(basis['amount']) < 0 or basis['currency'] != 'JPY':
                    raise Rejected('数量金额币种无效')
                from arrival_core.operations_adapter import UNITS
                if basis['quantity_unit'] not in UNITS:
                    raise Rejected('Qty实际单位未核实')
                # Binding must hold after projecting current specification/code.
                if record['fact_hash'] != key(context(row)):
                    raise Rejected('确认数量金额不匹配当前规格/编码')
            except (KeyError, ValueError) as exc:
                basis_valid = False
                blockers.append('confirmed_basis_invalid:' + str(exc))
        if not basis_valid:
            blockers += ['business_quantity_unconfirmed', 'qty_actual_unit_unconfirmed', 'business_amount_unconfirmed']
            row.pop('business_amount', None)
            row['reviews']['price'] = None
        p = original.get('packaging')
        packaging_valid = bool(p and proof_valid(original['reviews'].get('packaging'))
                               and proof_valid(original['reviews'].get('identity')))
        if 'pieces_per_box' not in accepted:
            blockers.append('h_pieces_per_box_unconfirmed')
            packaging_valid = False
        if packaging_valid:
            try:
                from arrival_core.operations_adapter import UNITS
                h = positive(accepted['pieces_per_box']['value'])
                if h != h.to_integral_value() or positive(p['pieces_per_box']) != h:
                    raise Rejected('H盒规与已确认包装关系不同')
                if not basis_valid or p['source_unit'] != basis['quantity_unit']:
                    raise Rejected('包装来源单位与Qty实际单位不同')
                if p.get('context') != context(row):
                    raise Rejected('包装依据不匹配当前身份')
                if p['declaration_unit'] not in UNITS or p['internal_unit'] not in UNITS:
                    raise Rejected('申报/内部单位未核实')
                positive(p['declaration_factor'])
                if not p.get('source') or Fraction(positive(p['internal_quantity'])) / Fraction(positive(p['internal_boxes'])) != Fraction(h):
                    raise Rejected('包装数量关系缺少依据或不一致')
                if positive(p['internal_quantity']) != positive(basis['quantity']):
                    raise Rejected('现有rc.5输入要求内部数量等于业务数量')
            except (KeyError, ValueError) as exc:
                packaging_valid = False
                blockers.append('packaging_invalid:' + str(exc))
        if not packaging_valid:
            blockers.append('unit_conversion_unconfirmed')
            row['packaging'] = None
            row['reviews']['packaging'] = None
        check = checks.get(rid)
        # The >100 JPY check is independent of authority of amount/quantity.
        # A valid independent confirmed amount can support arithmetic while a
        # purchase reference remains pending; keep that issue visible, not approved.
        price_pending = check is None or check['status'] != 'within_100_jpy'
        issue = {'row_id': rid, 'source': deepcopy(original['source']),
                 'blockers': sorted(set(blockers)), 'confirmed_fields': accepted,
                 'price_reference_pending': price_pending,
                 'price_check': deepcopy(check), 'purchase_quantity': None,
                 'purchase_quantity_status': 'not_confirmed_by_arrival_qty',
                 'formal_missing': ['declaration_material', 'customs_name', 'classification_and_tax', 'weights_release']}
        adopted.append(issue)
        if blockers:
            pending.append(rid)
        else:
            ready.append(row)
    engine = None
    if ready:
        from arrival_core.core import new_batch
        engine = new_batch(ready, deepcopy(batch['sources']))
        engine.update(input_mode='a04_confirmed_arithmetic_preflight', execution_mode='preflight_only',
                      product_data_policy='single-person-v1')
        validate(engine)
    return {'schema': 'a04-computation-preflight/1', 'batch_id': view['batch_id'],
            'a_version': view['a_version'], 'a_hash': view['current_hash'],
            'row_count': len(batch['rows']), 'ready_row_count': len(ready), 'blocked_row_count': len(pending),
            'row_checks': adopted, 'rc5_input': engine,
            'rc5_schema_accepted': engine is not None, 'calculation_executed': False,
            'can_calculate_entire_batch': bool(ready) and not pending,
            'formal_output': False, 'professional_approvals_created': 0,
            'price_reference_counts': deepcopy(view['pricing_counts'])}


class Bridge:
    def __init__(self, root):
        dependencies()
        root = Path(root).resolve(strict=True)
        if not (root / 'a03-service.json').is_file():
            raise Rejected('只接受已有A-03保存目录')
        self.service = Service(root)

    def prepare(self, batch_id):
        dependencies()
        view = self.service.read_current(batch_id)
        batch = self.service.store.load(batch_id)
        if key(batch) != view['current_hash']:
            raise Rejected('读取期间A版本变化，请重新读取')
        result = project(view, batch)
        result['input_fingerprint'] = key(result)
        if self.service.read_current(batch_id)['current_hash'] != view['current_hash']:
            raise Rejected('预检期间A版本变化，请重新读取')
        return result

    def current_input(self, prepared):
        """Mandatory consumer boundary: stale/tampered input never reaches rc.5."""
        dependencies()
        body = {k: v for k, v in prepared.items() if k != 'input_fingerprint'}
        if prepared.get('schema') != 'a04-computation-preflight/1' or key(body) != prepared.get('input_fingerprint'):
            raise Rejected('计算输入摘要不一致')
        fresh = self.prepare(prepared['batch_id'])
        if fresh != prepared:
            raise Rejected('A版本或确认依据已变化，旧计算输入失效')
        return deepcopy(fresh['rc5_input'])
