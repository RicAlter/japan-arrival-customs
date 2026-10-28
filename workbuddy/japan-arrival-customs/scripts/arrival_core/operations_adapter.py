"""KMT operations intake. Only mapping, exact normalization and source binding.

The frozen rc.2 importer, arithmetic, renderer and release gate are called intact.
"""
import copy
import hashlib
import json
import re
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from openpyxl import Workbook
from . import _p0_frozen as p0
from .core import Rejected, digest, decimal
from .storage import atomic_json, check_sources
from .excel_writer import literal
from .confirmed_excel import DRAFT_DETAIL_HEADERS, import_confirmed_arrival, gate_status
from .drafts import render_pair, draft_payload, verify_pair

MAPPINGS = Path(__file__).resolve().parents[2] / 'mappings'
UNITS = {'件', '个', '盒', '套', '包', '张', '枚', '支', '只', '本'}


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(value):
    value = Fraction(value)
    with localcontext() as ctx:
        ctx.prec = 100
        result = Decimal(value.numerator) / Decimal(value.denominator)
    if Fraction(result) != value: raise Rejected('派生数量无法精确表示，需补充明确换算')
    return str(result)


def configs():
    result = []
    for name in ('kmt-stage3-v1.json', 'kmt-stage4-v1.json', 'kmt-weights-v1.json'):
        path = MAPPINGS / name
        config = json.loads(path.read_text(encoding='utf-8'))
        config['source'] = {'path': str(path.resolve()), 'sha256': sha(path), 'kind': 'mapping'}
        result.append(config)
    return result


def locate(sheet, config):
    observed = {}
    for col, record in sheet.rows.get(1, {}).items():
        text = p0.text(record.get('v')).strip()
        if text: observed.setdefault(text, []).append(col)
    columns = {}
    for field, header in config['headers'].items():
        found = observed.get(header, [])
        if len(found) != 1: return None
        columns[field] = found[0]
    for field in config['anchored_blank_headers']:
        # An unnamed column can only be mapped when all named anchors stay fixed.
        if any(columns[f] != config['columns'][f] for f in columns): return None
        col = config['columns'][field]
        if p0.good(sheet.v(1, col)): return None
        columns[field] = col
    return columns


def evidence(book, sheet, row, col):
    cell = sheet.cells.get(f'{col}{row}', {})
    return {'path': book.label, 'sha256': book.sha256, 'sheet': sheet.name, 'row': row,
            'cell': f'{col}{row}', 'raw_value': p0.text(cell.get('v')), 'formula': cell.get('f'),
            'cached_value': p0.text(cell.get('v')), 'cell_type': cell.get('type')}


def value(book, sheet, row, field, columns, config):
    col = columns[field]; proof = evidence(book, sheet, row, col)
    raw = sheet.v(row, col); formula = sheet.f(row, col)
    if formula:
        factors = config['formula_products'].get(field)
        if not factors: raise Rejected(f'{sheet.name}!{col}{row}：不支持的公式')
        refs = [columns[f] + str(row) for f in factors]
        normalized = formula.replace('$', '').replace(' ', '').upper()
        if normalized not in ('=' + '*'.join(refs), '=' + '*'.join(reversed(refs))):
            raise Rejected(f'{sheet.name}!{col}{row}：公式超出逐行乘法白名单')
        operands = []
        for ref in refs:
            c = sheet.cells.get(ref, {})
            if c.get('f') or c.get('type') == 'e': raise Rejected('公式引用值不是独立数值')
            operands.append(decimal(p0.text(c.get('v'))))
        expected = Fraction(operands[0]) * Fraction(operands[1])
        if raw is None or Fraction(decimal(p0.text(raw))) != expected:
            raise Rejected(f'{sheet.name}!{col}{row}：公式缓存缺失或与精确复算不一致')
        proof.update(validation='exact_product_matched', precedents=[evidence(book, sheet, row, columns[f]) for f in factors])
    elif not p0.good(raw):
        if field not in config['optional']: raise Rejected(f'{sheet.name}!{col}{row}：缺少必要字段{field}')
        return '', proof
    return p0.text(raw).strip(), proof


def extract(book, sheet, config, columns, no_code_reasons):
    output = []; previous_carton = None; total_seen = False
    for row in sorted(sheet.rows):
        if row < config['start_row']: continue
        cells = sheet.rows[row]
        for header in config.get('empty_data_headers', []):
            cols = [c for c, record in sheet.rows.get(1, {}).items() if p0.text(record.get('v')) == header]
            if len(cols) > 1: raise Rejected('价格列存在重复表头')
            if cols and (p0.present(sheet.v(row, cols[0])) or sheet.f(row, cols[0])):
                raise Rejected('首期只接第4步申报准备表；已填价格成品请作为历史对照提供')
        marker = config.get('footer_marker')
        if marker and p0.text(sheet.v(row, marker['column'])) == marker['value']:
            for field in ('实际箱数', '箱组总重量KG'):
                col = columns[field]
                if sheet.f(row, col) != f'=SUM({col}{config["start_row"]}:{col}{row-1})':
                    raise Rejected('箱重合计公式范围不明确')
                total = sum((Fraction(decimal(x['values'][field])) for x in output), Fraction(0))
                if Fraction(decimal(p0.text(sheet.v(row, col)))) != total: raise Rejected('箱重合计缓存不一致')
            total_seen = True; continue
        if total_seen and config['role'] == 'weights':
            if p0.expand(sheet.v(row, columns['箱号组'])): raise Rejected('箱重合计后出现实体箱')
            continue
        # Only a trailing isolated amount total is excluded, never an unnamed item.
        total_field = config.get('trailing_total_field')
        if total_field and set(cells) == {columns[total_field]}:
            col = columns[total_field]
            formula = sheet.f(row, col)
            if formula and formula != f'=SUM({col}{config["start_row"]}:{col}{row-1})':
                raise Rejected('业务金额合计公式范围不明确')
            expected = sum((Fraction(decimal(x['values'][total_field])) for x in output), Fraction(0))
            if Fraction(decimal(p0.text(sheet.v(row, col)))) != expected:
                raise Rejected('业务金额尾部合计与逐行金额不一致')
            total_seen = True; continue
        if total_seen: raise Rejected('合计后出现商品或未知内容')
        if config['role'] == 'weights':
            carton = sheet.v(row, columns['箱号组'])
            if not p0.good(carton):
                if any(p0.good(sheet.v(row, columns[f])) for f in ('实际箱数', '箱组总重量KG')):
                    raise Rejected(f'箱重第{row}行缺少箱号')
                continue
            if not p0.expand(carton):
                # Total/volume rows have no carton identity. Reject numeric count/weight.
                if p0.numeric_text(sheet.v(row, columns['实际箱数'])) is not None:
                    raise Rejected(f'箱重第{row}行箱号无法识别')
                continue
        values = {}; proofs = {}
        for field in columns:
            if field == '商品编码' and not p0.good(sheet.v(row, columns[field])):
                values[field] = ''; proofs[field] = evidence(book, sheet, row, columns[field]); continue
            if field == '箱号' and not p0.good(sheet.v(row, columns[field])) and config['inherit_carton']:
                if previous_carton is None: raise Rejected('首行缺少箱号，不能继承')
                values[field], proofs[field] = copy.deepcopy(previous_carton)
                proofs[field]['inherited_to_row'] = row; continue
            values[field], proofs[field] = value(book, sheet, row, field, columns, config)
        if '箱号' in values: previous_carton = (values['箱号'], proofs['箱号'])
        rid = digest([book.sha256, sheet.name, row])[:24]
        if '商品编码' in values and not values['商品编码']:
            reason = no_code_reasons.get(rid, '')
            if not isinstance(reason, str) or not reason.strip(): raise Rejected(f'无码行{rid}需补充真实原因及唯一配对资料')
            values['无码原因'] = reason.strip()
        values['稳定行号'] = rid
        output.append({'values': values, 'fields': proofs, 'row': row, 'config': config['id']})
    if not output: raise Rejected(f'{sheet.name}没有明细')
    return output


def carton_key(raw):
    expanded = p0.expand(raw)
    if not expanded: raise Rejected('箱号不能识别：' + raw)
    return tuple(sorted(expanded))


def keyed(rows):
    result = {}
    for row in rows:
        v = row['values']; key = (carton_key(v['箱号']), v['商品编码'])
        if not key[1]: raise Rejected('无码商品无法按箱号＋编码唯一配对，需单独提供关联依据')
        if key in result: raise Rejected('箱号＋编码存在重复候选，禁止按行序配对')
        result[key] = row
    return result


def prepare(files, comparison_files=(), no_code_reasons=None):
    config_list = configs(); sources = []; matched = {}; books = []
    for name in files:
        path = Path(name).resolve(strict=True)
        if path.suffix.lower() != '.xlsx': raise Rejected('只接受xlsx运营原件')
        book = p0.Book(path.read_bytes(), str(path)); books.append(book)
        sources.append({'path': str(path), 'sha256': book.sha256, 'kind': 'operations_original'})
        used = False
        for config in config_list:
            for sheet in book.sheets:
                if config.get('sheet') and sheet.name != config['sheet']: continue
                columns = locate(sheet, config)
                if not columns: continue
                role = config['role']
                if role in matched: raise Rejected('同角色出现多个工作簿/版本：' + role)
                matched[role] = extract(book, sheet, config, columns, no_code_reasons or {})
                used = True
        if not used: raise Rejected('无法识别运营文件结构：' + path.name)
    missing = sorted({'business', 'declaration', 'weights'} - set(matched))
    if missing: raise Rejected('缺少必要来源：' + '、'.join(missing))
    business, declaration = keyed(matched['business']), keyed(matched['declaration'])
    if set(business) != set(declaration): raise Rejected('第3/4步商品身份不能双向完整匹配')
    details = []; special = []
    origins = {'Japan': 'JP', 'China': 'CN', 'Vietnam': 'VN', '日本': 'JP', '中国': 'CN'}
    for key, a in business.items():
        b = declaration[key]; av, bv = a['values'], b['values']; fields = copy.deepcopy(a['fields'])
        for f in ('品类', '最终申报材质'):
            if av[f] != bv[f]: raise Rejected(f'{av["稳定行号"]}第3/4步{f}冲突')
        if origins.get(bv['原产国'], bv['原产国']) != av['原产国']: raise Rejected('原产国冲突')
        v = dict(av)
        for f in ('海关申报品名', '内部盒数', '申报数量'):
            v[f] = bv[f]; fields[f] = b['fields'][f]
        for f in ('业务确认数量', '内部盒数', '申报数量'):
            if decimal(v[f]) <= 0: raise Rejected(f'{v["稳定行号"]}{f}必须为正数')
        qty, boxes, declared = [Fraction(decimal(v[f])) for f in ('业务确认数量', '内部盒数', '申报数量')]
        if decimal(v['业务确认金额JPY']) < 0: raise Rejected('金额不能为负数')
        if Fraction(decimal(av['业务单价'])) * qty != Fraction(decimal(v['业务确认金额JPY'])):
            raise Rejected('业务单价×数量与第3步金额不一致')
        v.update(内部数量=v['业务确认数量'], 每盒件数=finite(qty / boxes), 申报换算系数=finite(declared / qty), 无码原因=v.get('无码原因', ''))
        for f, expression, inputs in (('内部数量', '业务确认数量', ['业务确认数量']),
                ('每盒件数', '业务确认数量/内部盒数', ['业务确认数量', '内部盒数']),
                ('申报换算系数', '申报数量/业务确认数量', ['申报数量', '业务确认数量'])):
            fields[f] = {'derived': expression, 'sources': [fields[x] for x in inputs]}
        if declared != qty:
            special.append({'row_id': v['稳定行号'], 'source_row': a['row'], 'business_quantity': v['业务确认数量'],
                            'carton': v['箱号'], 'code': v['商品编码'], 'internal_name': v['内部中文名'],
                            'declaration_quantity': v['申报数量'], 'factor': v['申报换算系数']})
        details.append({'values': v, 'fields': fields})
    differences = []
    for name in comparison_files:
        path = Path(name).resolve(strict=True); book = p0.Book(path.read_bytes(), str(path))
        if not book.sheets or not locate(book.sheets[0], config_list[1]):
            raise Rejected('历史金额对照结构不符合KMT海关表')
        if p0.text(book.sheets[0].v(1, 'P')) != '金額': raise Rejected('历史对照缺少明确金额列')
        sources.append({'path': str(path), 'sha256': book.sha256, 'kind': 'comparison_only'})
        # Explicit comparison role; never feeds standard values.
        rows = p0.records(book, 5)
        ref = {}
        for r in rows:
            key = (carton_key(r['carton']), r['code'])
            if key in ref: raise Rejected('历史对照存在重复身份')
            ref[key] = r
        if set(ref) != set(business): raise Rejected('历史对照不能完整匹配')
        for key, a in business.items():
            r = ref[key]; amount = decimal(a['values']['业务确认金额JPY'])
            if Fraction(r['amount']) != Fraction(amount):
                differences.append({'row_id': a['values']['稳定行号'], 'business': a['fields']['业务确认金额JPY'],
                    'historical': evidence(book, book.sheets[0], r['row'], 'P'),
                    'delta': str(Fraction(r['amount']) - Fraction(amount)), 'applied': False})
    sources += [config['source'] for config in config_list]
    for s in sources:
        if sha(s['path']) != s['sha256']: raise Rejected('读取期间来源发生变化')
    return {'schema': 'operations-kmt-adapter-v1', 'sources': sources, 'details': details,
            'weights': matched['weights'], 'special_conversions': special,
            'special_conversion_hash': digest(special), 'historical_amount_differences': differences,
            'source_bundle_hash': digest(sources), 'formal_output': False}


def run(output, files, *, units_confirmation=None, comparison_files=(), no_code_reasons=None):
    output = Path(output).resolve()
    for name in [*files, *comparison_files]:
        path = Path(name).resolve()
        if output.is_relative_to(path.parent) or path.is_relative_to(output):
            raise Rejected('输出必须与原件目录隔离')
    output.mkdir(parents=True, exist_ok=True)
    try:
        plan = prepare(files, comparison_files, no_code_reasons)
        preview = {'status': 'needs_confirmation', 'source_bundle_hash': plan['source_bundle_hash'],
                   'special_conversion_hash': plan['special_conversion_hash'], 'rows': len(plan['details']),
                   'sources': [s for s in plan['sources'] if s['kind'] != 'mapping'],
                   'required_units': ['business_unit', 'internal_unit', 'declaration_unit'],
                   'special_conversions': plan['special_conversions'], 'formal_output': False}
        atomic_json(output / (plan['source_bundle_hash'][:24] + '-preview.json'), preview)
        if units_confirmation is None: return preview
        units = units_confirmation
        required = {'business_unit', 'internal_unit', 'declaration_unit', 'reference', 'confirm',
                    'source_bundle_hash', 'special_conversion_hash'}
        if not isinstance(units, dict) or set(units) != required: raise Rejected('批次单位确认字段不完整或未知')
        if units['confirm'] is not True or units['source_bundle_hash'] != plan['source_bundle_hash'] or units['special_conversion_hash'] != plan['special_conversion_hash']:
            raise Rejected('先展示当前来源及特殊换算清单，再明确确认当前哈希')
        if any(units[k] not in UNITS for k in ('business_unit', 'internal_unit', 'declaration_unit')):
            raise Rejected('必须提供明确实际单位，不能使用待确认占位')
        if units['business_unit'] != units['internal_unit']: raise Rejected('首期引擎要求业务数量与内部数量同层级')
        if not isinstance(units['reference'], str) or not units['reference'].strip(): raise Rejected('单位确认依据必填')
        key = digest({'source': plan['source_bundle_hash'], 'units': units})[:24]
        folder = output / key
        if folder.exists() and not (folder / 'batch.json').exists():
            raise Rejected('发现不完整运行目录；保留现场，请选择新的输出目录重试')
        folder.mkdir(exist_ok=True)
        canonical = folder / 'standard' / 'confirmed-arrival-v1.xlsx'
        provenance = folder / 'evidence' / 'provenance.json'
        if not canonical.exists():
            canonical.parent.mkdir(exist_ok=True); provenance.parent.mkdir(exist_ok=True)
            wb = Workbook(); meta = wb.active; meta.title = '批次确认'
            for k, v in zip(('模板版本', '批次号', '币种', '重量单位', '确认依据编号', '数据版本'),
                           ('confirmed-arrival-v1', key, 'JPY', 'KG', units['reference'], plan['source_bundle_hash'])):
                meta.append([k, v])
            sheet = wb.create_sheet('已确认明细'); headers = list(DRAFT_DETAIL_HEADERS) + ['YD', '渠道']
            sheet.append(headers)
            for index, row in enumerate(plan['details'], 2):
                row['values'].update(计价单位=units['business_unit'], 申报单位=units['declaration_unit'])
                for f in ('计价单位', '申报单位'):
                    row['fields'][f] = {'source': 'explicit_batch_confirmation', 'confirmation': units, 'trusted_identity': False}
                for col, field in enumerate(headers, 1): literal(sheet.cell(index, col), row['values'].get(field, ''))
            weights = wb.create_sheet('箱重'); weight_fields = ['箱号组', '实际箱数', '箱组总重量KG']
            weights.append(weight_fields)
            for row in plan['weights']: weights.append([row['values'][f] for f in weight_fields])
            wb.save(canonical); wb.close()
            atomic_json(provenance, plan)
        batch_file = folder / 'batch.json'
        if batch_file.exists():
            batch = json.loads(batch_file.read_text(encoding='utf-8')); check_sources(batch)
        else:
            batch = import_confirmed_arrival(canonical)
            batch['sources'] += plan['sources'] + [{'path': str(provenance), 'sha256': sha(provenance), 'kind': 'field_provenance'}]
            batch['operations_adapter'] = {'source_bundle_hash': plan['source_bundle_hash'], 'provenance': str(provenance), 'units': units, 'trusted_identity': False}
            for row, original in zip(batch['rows'], plan['details']): row['operations_provenance'] = original['fields']
            atomic_json(batch_file, batch)
        pair = folder / 'pair'
        if pair.exists(): result = {'directory': str(pair), 'comparison': verify_pair(batch, pair, draft_payload(batch)), 'replayed': True}
        else: result = render_pair(batch, pair)
        check_sources(batch)
        return {'status': 'ok', 'batch': batch['id'], 'standard_input': str(canonical), 'provenance': str(provenance),
                'result': result, 'gates': gate_status(batch), 'special_conversion_count': len(plan['special_conversions']),
                'historical_amount_difference_count': len(plan['historical_amount_differences']), 'formal_output': False}
    except (Rejected, OSError, ValueError, KeyError) as exc:
        report = {'status': 'needs_input', 'reason': str(exc), 'formal_output': False}
        atomic_json(output / 'input-problems.json', report)
        return report
