"""Semantic comparison permits ordinary Excel saves, never evaluates formulas."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import io
import re
import zipfile
import xml.etree.ElementTree as ET

from .support import Rejected, key


class InvalidReturn(Rejected):
    def __init__(self, message, positions=None):
        super().__init__(message)
        self.positions = positions or []


def xml_signature(raw):
    def visit(e):
        return (e.tag, tuple(sorted(e.attrib.items())), (e.text or '').strip(), tuple(visit(c) for c in e))
    return visit(ET.fromstring(raw))


def passive_links(data):
    """Fingerprint existing external-link records; never open their targets."""
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name.lower().startswith('xl/externallinks/') and name.endswith(('.xml', '.rels')):
                result[name] = xml_signature(z.read(name))
    return result


def read(data, *, trusted_external=None):
    from openpyxl import load_workbook
    from arrival_core import _p0_frozen as p0
    if len(data) > 64 * 1024 * 1024:
        raise InvalidReturn('Excel文件过大')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if len(infos) > 10000 or sum(i.file_size for i in infos) > 128 * 1024 * 1024:
                raise InvalidReturn('Excel解压范围超限')
            names = z.namelist()
            if len(names) != len(set(names)):
                raise InvalidReturn('Excel存在重复部件')
            for name in names:
                if any(t in name.lower() for t in ('vbaproject', 'embeddings/', 'connections.xml', 'querytables/')):
                    raise InvalidReturn('不接受宏、外部连接或嵌入对象')
                if name.endswith(('.xml', '.rels')):
                    raw = z.read(name)
                    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                        raise InvalidReturn('Excel包含不支持的XML声明')
                    if name.endswith('.rels'):
                        for rel in ET.fromstring(raw):
                            if rel.get('TargetMode') == 'External' and not name.lower().startswith('xl/externallinks/'):
                                raise InvalidReturn('不接受外部活动链接')
            links = passive_links(data)
            if links and (trusted_external is None or links != trusted_external):
                raise InvalidReturn('原外部链接被改写或新增，拒绝回传')
            if trusted_external and links != trusted_external:
                raise InvalidReturn('原外部链接被删除，拒绝回传')
        wb = load_workbook(io.BytesIO(data), data_only=False, keep_links=True)
        if len(wb.worksheets) != len(wb.sheetnames) or len(wb.sheetnames) > 20:
            wb.close(); raise InvalidReturn('工作表类型或数量不受支持')
        if any(w.max_row > 50000 or w.max_column > 192 for w in wb):
            wb.close(); raise InvalidReturn('Excel行列范围异常')
        parsed = p0.Book(data, 'a02-immutable-bytes.xlsx')
        return wb, parsed
    except InvalidReturn:
        raise
    except Exception as exc:
        raise InvalidReturn('无法安全读取Excel：' + type(exc).__name__) from exc


def scalar(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    return value


def blank(value):
    return value is None or value == ''


def number(value):
    if isinstance(value, bool) or blank(value):
        return None
    try:
        d = Decimal(str(value))
        return d if d.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def positive_integer(value):
    n = number(value)
    return int(n) if n is not None and 0 < n <= 1000000000 and n == n.to_integral_value() else None


def cell_value(cell):
    value = cell.value
    if blank(value):
        return ('blank', None)
    if cell.data_type == 'f':
        if not isinstance(value, str):
            raise InvalidReturn('暂不支持数组/数据表公式的回传', [cell.coordinate])
        return ('formula', value)
    if isinstance(value, bool):
        return ('bool', value)
    if cell.data_type == 'e':
        return ('error', value)
    if isinstance(value, (int, float, Decimal)):
        n = number(value)
        if n is None:
            raise InvalidReturn('非有限数值', [cell.coordinate])
        return ('number', n)
    if not isinstance(value, str):
        # Do not silently turn changed date number formats into changed facts.
        return ('typed', (type(value).__name__, str(value)))
    return ('text', value)


def shown(cell):
    typ, value = cell_value(cell)
    return {'type': typ, 'value': scalar(value)}


def cells(ws):
    # Bounded by read(); include comments on otherwise empty cells.
    return {c.coordinate: c for c in ws._cells.values()
            if c.value is not None or c.comment is not None or c.hyperlink is not None}


def names(wb):
    all_names = [('workbook', k, xml_signature(ET.tostring(v.to_tree())))
                 for k, v in wb.defined_names.items()]
    for ws in wb:
        all_names.extend((ws.title, k, xml_signature(ET.tostring(v.to_tree())))
                         for k, v in ws.defined_names.items())
    return sorted(all_names)


def allowed(reg, wb):
    targets = {}
    for f in reg['fields']:
        targets[(f['sheet'], f['cell'])] = {'field': f['field'], 'row_id': f['row_id'], 'base_status': f['status'], 'sources': f['sources']}
    for row in reg['row_map']:
        source = row['source']; coordinates = source['cells']
        for role, field in [('code', 'product_code'), ('origin', 'origin')]:
            c = coordinates.get(role)
            if not c:
                continue
            addr = c['cell']; sheet = source['sheet']
            if role == 'origin' and not blank(wb[sheet][addr].value):
                continue
            targets[(sheet, addr)] = {'field': field, 'row_id': row['row_id'], 'base_status': 'source_observation', 'sources': []}
    return targets


def compare(base, returned, reg):
    if base.sheetnames != returned.sheetnames:
        raise InvalidReturn('工作表新增、删除或顺序改变，拒绝回传')
    if names(base) != names(returned):
        raise InvalidReturn('原有命名区域被改变，拒绝回传')
    editable = allowed(reg, base); violations = []; edits = []
    skeletons = defaultdict(list)
    widths = {ws.title: ws.max_column for ws in base}
    for row in reg['row_map']:
        ws = base[row['source']['sheet']]; n = row['source_row']
        protected = []
        for col in range(1, widths[ws.title] + 1):
            c = ws.cell(n, col)
            if (ws.title, c.coordinate) in editable and c.data_type != 'f':
                continue
            value = shown(c)
            if c.data_type == 'f':
                from openpyxl.formula.translate import Translator
                try:
                    value = {'type': 'formula', 'value': Translator(c.value, origin=c.coordinate).translate_formula(c.column_letter+'1')}
                except Exception:
                    # An unnormalizable formula cannot certify distinct row identity.
                    value = {'type': 'formula', 'value': 'unresolved_relative_formula'}
            protected.append((c.coordinate.rstrip('0123456789'), value))
        skeletons[key(protected)].append(row['row_id'])
    ambiguous = {rid for ids in skeletons.values() if len(ids) > 1 for rid in ids}
    for ws in base:
        other = returned[ws.title]
        if ws.sheet_state != other.sheet_state or sorted(str(m) for m in ws.merged_cells.ranges) != sorted(str(m) for m in other.merged_cells.ranges):
            raise InvalidReturn('页签状态或合并范围被改变，拒绝回传', [ws.title])
        a, b = cells(ws), cells(other)
        for address in sorted(set(a) | set(b), key=lambda x: (int(re.search(r'\d+$', x)[0]), len(x.rstrip('0123456789')), x)):
            old = ws[address]; new = other[address]; location = ws.title + '!' + address
            old_comment = None if old.comment is None else (old.comment.text, old.comment.author)
            new_comment = None if new.comment is None else (new.comment.text, new.comment.author)
            old_link = None if old.hyperlink is None else (old.hyperlink.target, old.hyperlink.location)
            new_link = None if new.hyperlink is None else (new.hyperlink.target, new.hyperlink.location)
            if old_comment != new_comment or old_link != new_link:
                violations.append({'position': location, 'reason': '原批注/链接被改变'})
            if cell_value(old) == cell_value(new):
                continue
            field = editable.get((ws.title, address))
            if old.data_type == 'f' or new.data_type == 'f' or field is None:
                reason = '原公式受保护；H盒规更正请在对话说明' if old.data_type == 'f' and field and field['field'] == 'pieces_per_box' else '原公式/原始事实/物流或未授权单元格受保护'
                violations.append({'position': location, 'reason': reason, 'before': shown(old), 'after': shown(new)})
                continue
            reasons = []
            value = new.value; name = field['field']
            if field['row_id'] in ambiguous:
                reasons.append('只读内容重复，需明确原行范围；不能推断排序后对应')
            if name in ('internal_name', 'category', 'material_reference') and (blank(value) or not isinstance(value, str) or not value.strip()):
                reasons.append('基础信息留空或类型待核')
            if name == 'pieces_per_box' and positive_integer(value) is None:
                reasons.append('每盒件数需为有依据的正整数')
            if name == 'purchase_unit_price':
                reasons.append('采购价格币种、计价单位及来源须另行明确')
                if number(value) is None or number(value) < 0:
                    reasons.append('采购单价格式待核')
            if name == 'product_code':
                reasons.append('改码对应及身份范围须明确确认')
                if not blank(value) and not isinstance(value, str):
                    reasons.append('编码需按文本保留前导零')
            if name == 'origin':
                reasons.append('原产地补值来源须核实')
            if name in ('specification', 'channel', 'yd') and not blank(value) and not isinstance(value, str):
                reasons.append('文本字段类型待核')
            if isinstance(value, str) and len(value) > 32767:
                reasons.append('文本长度待核')
            edits.append(dict(field, sheet=ws.title, cell=address, before=shown(old), after=shown(new),
                              manual_change=True, status='proposed_only', confirmed=False,
                              material_approval=False, needs_further_confirmation=bool(reasons), reasons=reasons))
    if violations:
        raise InvalidReturn('受保护内容被修改，整份回传拒绝', violations)
    return edits


def cache_differences(before, after):
    result = []
    for old in before.sheets:
        new = next(s for s in after.sheets if s.name == old.name)
        for address, cell in old.cells.items():
            other = new.cells.get(address, {})
            if cell.get('f') and cell.get('v') != other.get('v'):
                result.append({'sheet': old.name, 'cell': address, 'issued_cache': scalar(cell.get('v')),
                               'returned_cache': scalar(other.get('v')), 'adopted': False})
    return result


def packaging_audit(reg, wb):
    groups = defaultdict(list)
    for field in reg['fields']:
        if field['field'] != 'pieces_per_box':
            continue
        cell = wb[field['sheet']][field['cell']]; n = cell.row
        if cell.data_type == 'f':
            legacy = re.sub(r'[\s$]', '', str(cell.value)).upper() == f'=G{n}/K{n}' and reg['profile_id'] == 'kmt-native-16-v1'
            kind = 'legacy_price_ratio_formula' if legacy else 'protected_formula_without_independent_packaging_evidence'
        elif blank(cell.value):
            kind = 'blank_packaging_not_required_until_conversion'
        elif positive_integer(cell.value) is not None:
            kind = 'candidate_not_adopted' if field['status'] == 'candidate' else 'positive_literal_observation_not_new_confirmation'
        else:
            kind = 'invalid_literal_needs_evidence_if_conversion_required'
        groups[kind].append({'row_id': field['row_id'], 'sheet': field['sheet'], 'cell': field['cell']})
    return {'groups': [{'kind': kind, 'count': len(items), 'rows': items} for kind, items in groups.items()],
            'counted_as_new_edits': False, 'qty_unit_inferred': False, 'packaging_approved': False,
            'new_business_action_count': None, 'unchanged_red_fills_rewritten': False,
            'safe_correction': '原H公式不动；在对话说明原行与每盒件数，后台生成待确认提案。未确认前不换算。'}
