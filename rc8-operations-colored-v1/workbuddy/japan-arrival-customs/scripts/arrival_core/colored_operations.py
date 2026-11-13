"""Explicit operational rounding/allocation inputs; no automatic tail allocation."""
import copy
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction

from .core import Rejected, decimal, digest


def fraction(value):
    if value is None or value == '' or isinstance(value, bool): raise Rejected('缺少必要数值')
    try: return Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc: raise Rejected('数值格式无效') from exc


def round0(value):
    value = fraction(value)
    with localcontext() as ctx:
        ctx.prec = max(100, len(str(abs(value.numerator))) + len(str(value.denominator)) + 10)
        return int((Decimal(value.numerator) / Decimal(value.denominator)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def allocated_rate(components, reference):
    """Weights are explicit business inputs, not inferred quantities/value shares."""
    if not isinstance(reference, str) or not reference.strip(): raise Rejected('分摊依据必填')
    if not isinstance(components, list) or not components: raise Rejected('分摊组件必填')
    numerator = Fraction(); denominator = Fraction()
    for item in components:
        if not isinstance(item, dict) or set(item) != {'rate', 'weight'}: raise Rejected('分摊组件须提供税率和明确权重')
        rate, weight = fraction(item['rate']), fraction(item['weight'])
        if not 0 <= rate <= 1 or weight < 0: raise Rejected('分摊税率/权重范围无效')
        numerator += rate * weight; denominator += weight
    if denominator <= 0: raise Rejected('分摊总权重须为正数')
    return numerator / denominator


def compound_category(value): return bool(re.search('[，,]', value or ''))


def read_tax_input(book, sheet, row, config, values):
    from .operations_adapter import evidence, finite
    cols = config['tax_columns']; price_col = config['columns']['业务单价']
    qty_col = config['columns']['业务确认数量']; boxes_col = config['columns']['来源盒数']
    rate_value = sheet.v(row, cols['rate']); rate = None
    if rate_value is not None and str(rate_value).strip() != '':
        if sheet.f(row, cols['rate']): raise Rejected('税率公式需提供明确分摊组件/权重，不执行未知公式')
        rate = fraction(rate_value)
        if not 0 <= rate <= 1: raise Rejected('运营税率必须在0到1之间')
    vat_formula = sheet.f(row, cols['vat']); vat = None
    expected_prefix = f'={price_col}{row}*(1+{cols["rate"]}{row})*'
    if vat_formula:
        normalized = vat_formula.replace('$','').replace(' ','').upper()
        if not normalized.startswith(expected_prefix): raise Rejected('增值税公式超出本行白名单')
        constant = normalized[len(expected_prefix):]
        if not re.fullmatch(r'(?:0(?:\.\d+)?|1(?:\.0+)?)', constant): raise Rejected('增值税率须在源公式中明确给出')
        vat = fraction(constant)
    elif sheet.v(row, cols['vat']) is not None:
        raise Rejected('仅有增值税金额，缺少明确增值税率，不能倒推')
    expected_formulas = {
        cols['pieces']: f'={qty_col}{row}/{boxes_col}{row}',
        cols['duty']: f'={cols["rate"]}{row}*{price_col}{row}',
        cols['box_tax']: f'=({cols["vat"]}{row}+{cols["duty"]}{row})*{cols["pieces"]}{row}'}
    for col, expected in expected_formulas.items():
        formula = sheet.f(row, col)
        if formula and formula.replace('$','').replace(' ','').upper() != expected:
            raise Rejected(f'{sheet.name}!{col}{row}：公式超出逐行税金白名单')
    unit = fraction(values['业务单价']); boxes = fraction(values['来源盒数'])
    if boxes <= 0: raise Rejected('来源盒数必须为正数')
    pieces = fraction(values['业务确认数量'])/boxes
    calculations = {cols['pieces']: pieces}
    if rate is not None:
        calculations[cols['duty']] = unit * rate
        if vat is not None:
            calculations[cols['vat']] = unit*(1+rate)*vat
            calculations[cols['box_tax']] = (unit*rate+unit*(1+rate)*vat)*pieces
    for col, expected in calculations.items():
        observed = sheet.v(row,col)
        if observed is not None and abs(fraction(observed)-expected) > Fraction(1,10**8):
            raise Rejected(f'{sheet.name}!{col}{row}：税金/盒规缓存与复算不一致')
        if sheet.f(row,col) and observed is None:
            raise Rejected(f'{sheet.name}!{col}{row}：公式缓存缺失')
    return {'rate': finite(rate) if rate is not None else None,
            'vat_rate': finite(vat) if vat is not None else None,
            'allocation': compound_category(values['品类']), 'reference': False,
            'basis': '运营已确认分摊结果' if compound_category(values['品类']) else '运营已确认本批税率',
            'fields': {k: evidence(book,sheet,row,col) for k,col in cols.items()}}


def prepare_calculation_inputs(plan, reference_data=None, allocations=None):
    from .operations_adapter import finite
    if allocations is not None and not isinstance(allocations, dict): raise Rejected('分摊输入须按稳定行号提供')
    allocations = allocations or {}
    known_ids = {row['values']['稳定行号'] for row in plan['details']}
    if set(allocations)-known_ids: raise Rejected('分摊输入含未知稳定行号')
    for row in plan['details']:
        value = row['values']; execution = row['execution_input']
        supplied = execution.get('price'); supplied_amount = execution.get('amount')
        if bool(supplied not in (None,'')) != bool(supplied_amount not in (None,'')):
            raise Rejected('已填申报单价与金额必须同时完整提供')
        if supplied not in (None,''):
            price = fraction(supplied); declared = fraction(value['申报数量'])
            if price < 0 or price.denominator != 1: raise Rejected('运营已填执行单价须为非负整数，不能静默覆盖')
            if fraction(supplied_amount) != price*declared: raise Rejected('已填海关金额与执行单价×数量不一致')
        tax = row.get('tax_input')
        if reference_data:
            ref = reference_data['by_source_row'][str(row['source_rows']['business'])]
            if ref['duty_rate'] is not None:
                if tax and tax.get('rate') is not None and fraction(tax['rate']) != fraction(ref['duty_rate']):
                    raise Rejected('运营税率与参考证据冲突，不自动覆盖')
                if tax and tax.get('vat_rate') is not None and fraction(tax['vat_rate']) != fraction(reference_data['vat_rate']):
                    raise Rejected('运营增值税率与参考证据冲突，不自动覆盖')
                if tax:
                    tax = copy.deepcopy(tax)
                    supplemented = False
                    if tax.get('rate') is None: tax['rate'] = ref['duty_rate']; supplemented = True
                    if tax.get('vat_rate') is None: tax['vat_rate'] = reference_data['vat_rate']; supplemented = True
                    if supplemented:
                        tax['reference'] = True
                        tax['basis'] += '；明确参考补充：' + ref['basis']
                else:
                    tax = {'rate': ref['duty_rate'], 'vat_rate': reference_data['vat_rate'],
                           'basis': ref['basis'], 'allocation': compound_category(value['品类']), 'reference': True}
        if value['稳定行号'] in allocations:
            entry = allocations[value['稳定行号']]
            if not isinstance(entry,dict) or set(entry) != {'components','reference','vat_rate'}: raise Rejected('分摊输入需有组件、依据及增值税率')
            computed = allocated_rate(entry['components'],entry['reference'])
            if tax and tax.get('rate') is not None and computed != fraction(tax['rate']):
                raise Rejected('分摊计算与已填税率不一致，不自动改写')
            vat = fraction(entry['vat_rate'])
            if not 0 <= vat <= 1: raise Rejected('分摊增值税率范围无效')
            if tax and tax.get('vat_rate') is not None and vat != fraction(tax['vat_rate']):
                raise Rejected('分摊增值税率与运营已填值冲突，不自动覆盖')
            tax = {'rate': finite(computed),'vat_rate':finite(vat),'basis':entry['reference'],
                   'allocation':True,'reference':False,'components':copy.deepcopy(entry['components'])}
        row['tax_input'] = tax
    return digest(allocations)


def execution(row):
    quantity = fraction(row['authority']['quantity']) * fraction(row['packaging']['declaration_factor'])
    amount = fraction(row['authority']['amount']); exact = amount/quantity; baseline = round0(exact)
    supplied = row.get('operational_execution',{}).get('price')
    selected = fraction(supplied) if supplied not in (None,'') else Fraction(baseline)
    if selected.denominator != 1 or selected < 0: raise Rejected('执行单价不是非负整数')
    return {'exact_price':str(exact),'round0':baseline,'price':int(selected),'amount':selected*quantity,
            'business_amount':amount,'adjusted':selected!=baseline,'rounded':Fraction(baseline)!=exact,
            'source':row.get('operational_execution',{}).get('fields',{})}
