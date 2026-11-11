"""Original 21-column view of an existing calculation export.

Integrated from the verified per-batch adapter. Binding/evidence and workbooks
stay outside source control. The existing service owns all business decisions.
"""
from pathlib import Path
from fractions import Fraction
import io
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET

from . import load, save, digest, Rejected
from .submission import Service
from native_return.compare import read, compare, passive_links
from arrival_core.operations_adapter import finite
from arrival_core.colored_operations import round0

CELL = re.compile(rb'<c\b[^>]*?/>|<c\b[^>]*>.*?</c>', re.S)
MEMBER = 'xl/worksheets/sheet1.xml'
Q = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def address(raw):
    return re.search(rb'\br="([^"]+)"', raw)[1].decode()


def patched_package(file, transform):
    """Preserve every ZIP member and metadata except the explicitly edited XML."""
    with zipfile.ZipFile(file) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i.filename) for i in infos}
    parts[MEMBER] = transform(parts[MEMBER])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for info in infos:
            z.writestr(info, parts[info.filename])
    return buf.getvalue()


def publish_original(source, binding, target):
    """Reproduce the verified I-only trial; never infer units or replace inputs."""
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve() or target.exists():
        raise Rejected('原样试算必须写入新的隔离文件')
    if digest(source) != binding['source_sha256']:
        raise Rejected('原表SHA与原样布局绑定不符')
    wanted = {r['target']: r for r in binding['items']}
    seen = set()

    def transform(raw):
        def cell(m):
            addr = address(m[0])
            if addr not in wanted:
                return m[0]
            item = wanted[addr]
            # Current verified layout has the price trial in reserved I only.
            n = item['source_row']
            formula = '=ROUND(M%d/(K%d/L%d),0)' % (n, n, n)
            if addr != 'I'+str(n) or item['formula'] != formula:
                raise Rejected('不支持的原样公式或目标列')
            if re.search(rb'<(?:f|v|is)\b', m[0]):
                raise Rejected('I预留列已有内容，禁止覆盖')
            attrs = re.search(rb'<c\b([^>]*?)(?:/?>)', m[0])[1]
            attrs = re.sub(rb'\s+t="[^"]*"', b'', attrs)
            seen.add(addr)
            return b'<c'+attrs+b'><f>'+formula[1:].encode()+b'</f><v>'+str(item['expected']).encode()+b'</v></c>'
        result = CELL.sub(cell, raw)
        if seen != set(wanted):
            raise Rejected('原样试算目标不完整')
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(patched_package(source, transform))
    return {'file': str(target), 'sha256': digest(target), 'rows': len(wanted), 'columns': 21, 'formal_output': False}


class OriginalView:
    def __init__(self, config):
        self.config = load(config) if not isinstance(config, dict) else dict(config)
        path = self.config.get('native_view_binding')
        if not path:
            raise Rejected('未配置原样布局绑定；不得猜选历史批次')
        self.binding = load(path)
        self.issued = Path(self.binding['issued_file'])
        self.service = Service(self.config)
        if self.binding['columns'] != 21 or self.binding.get('requires_backend_price_basis_rebind'):
            raise Rejected('原样布局或日方价版本尚未绑定')
        if Path(self.binding['backend_root']).resolve() != self.service.root.resolve():
            raise Rejected('原样视图与当前session根不符')
        if digest(self.issued) != self.binding['issued_sha256']:
            raise Rejected('原样发出基准摘要变化')
        if digest(self.binding['backend_export']['file']) != self.binding['backend_export']['sha256']:
            raise Rejected('后台计算导出摘要变化')

    def preview(self, file):
        binding = self.binding
        data = self.issued.read_bytes()
        a, _ = read(data, trusted_external=passive_links(data))
        b = None
        try:
            b, _ = read(Path(file).read_bytes(), trusted_external=passive_links(data))
            for item in binding['items']:
                old = a[binding['sheet']][item['target']]
                new = b[binding['sheet']][item['target']]
                old_formula = old.value
                if old.data_type == 'f':
                    old.value = item['expected']
                    if new.data_type == 'f' and new.value == old_formula:
                        new.value = item['expected']
                    elif new.data_type == 'f':
                        raise Rejected('I列计算公式变化；不执行未知公式')
                elif new.data_type == 'f':
                    raise Rejected('不执行回传新增的未知算价公式')
            fields, rowmap = [], []
            editable = {'F':'internal_name', 'G':'specification', 'H':'purchase_unit_price',
                        'I':'business_execution_unit_price', 'K':'declared_total_pieces',
                        'O':'category', 'P':'material_reference', 'Q':'channel', 'R':'yd'}
            for row in binding['row_map']:
                n, rid, sheet = row['source_row'], row['row_id'], binding['sheet']
                fields.extend({'sheet':sheet, 'cell':c+str(n), 'field':name, 'row_id':rid,
                               'status':'submitted', 'sources':[]} for c, name in editable.items())
                rowmap.append({'row_id':rid, 'source_row':n, 'source':{'sheet':sheet, 'cells':{
                    'code':{'cell':'C'+str(n)}, 'qty':{'cell':'L'+str(n)}, 'ja':{'cell':'J'+str(n)}}}})
            changes = compare(a, b, {'fields':fields, 'row_map':rowmap})
        finally:
            a.close()
            if b is not None:
                b.close()
        return {'schema':'original-business-view-preview/1', 'head':binding['head'],
                'rows':len(binding['row_map']), 'columns':21, 'modified_cells':len(changes),
                'changes':changes, 'business_saved':False, 'formal_output':False}

    def project(self, file, reference):
        if not str(reference or '').strip():
            raise Rejected('需保留本次运营回传出处')
        p = self.preview(file)
        binding = self.binding
        basic = [c for c in p['changes'] if c['field'] not in {
            'business_execution_unit_price', 'declared_total_pieces', 'material_reference'}]
        if basic:
            return {**p, 'status':'requires_basics_sync_before_calculation', 'basis_changes':basic,
                    'message':'宿主须先通过既有基础资料入口同步再重算；不得静默沿用旧基础资料。'}
        if not p['changes']:
            return {**p, 'request':{'kind':'calculation', 'file':binding['backend_export']['file'], 'reference':reference}}
        sha = digest(file)
        folder = self.service.background/'original-view-returns'/sha
        folder.mkdir(parents=True, exist_ok=True)
        retained = folder/'operator-original.xlsx'
        if not retained.exists():
            shutil.copyfile(file, retained)
        from openpyxl import load_workbook
        w = load_workbook(file, read_only=True, data_only=False)
        try:
            rows = list(w[binding['sheet']].values)
        finally:
            w.close()
        plan = load(self.service.root/'objects'/(binding['backend_export']['export_id']+'.json'))['plan']
        changed = {(c['cell'], c['field']) for c in p['changes']}
        updates = {}
        for n, row in enumerate(plan['rows'], 5):
            source_row = row['source_row']
            v, token = rows[source_row-1], str(source_row)
            if ('K'+token, 'declared_total_pieces') in changed:
                total, qty = Fraction(str(v[10])), Fraction(str(v[11]))
                factor = total/qty if qty else None
                if total <= 0 or total.denominator != 1:
                    raise Rejected('K总单件数须为正整数：行'+token)
                updates['N'+str(n)] = int(factor) if factor is not None and factor >= 1 and factor.denominator == 1 else None
                updates.update({c+str(n):val for c, val in [('I','原Qty计价单位'), ('K','原Qty计价单位'),
                    ('P','个'), ('O','运营回传K'+token+'为整行总单件数；'+reference)]})
            if ('I'+token, 'business_execution_unit_price') in changed:
                price, total = Fraction(str(v[8])), Fraction(str(v[10]))
                if price < 0 or price.denominator != 1 or total <= 0:
                    raise Rejected('执行单价须为非负整日元，且总件数须为正数：行'+token)
                amount = finite(price*total)
                updates['L'+str(n)] = float(amount)
                if Fraction(str(updates['L'+str(n)])) != Fraction(str(amount)):
                    raise Rejected('金额超出既有Excel精度范围：行'+token)
                updates['AA'+str(n)] = '运营提交原表I'+token+'单价，按K总件数形成业务调整金额；原日方源价格/原表金额未改；'+reference+'；附件SHA='+sha
            if ('P'+token, 'material_reference') in changed:
                updates['V'+str(n)] = v[15]

        def transform(raw):
            root, seen = ET.fromstring(raw), set()
            for cell in root.iter(Q+'c'):
                addr = cell.get('r')
                if addr not in updates:
                    continue
                value = updates[addr]
                seen.add(addr)
                cell.attrib.pop('t', None)
                for child in list(cell):
                    cell.remove(child)
                if value is None:
                    continue
                if isinstance(value, (int, float)):
                    ET.SubElement(cell, Q+'v').text = str(value)
                else:
                    cell.set('t', 'inlineStr')
                    ET.SubElement(ET.SubElement(cell, Q+'is'), Q+'t').text = str(value)
            if seen != set(updates):
                raise Rejected('后台映射目标不完整')
            return ET.tostring(root, encoding='utf-8', xml_declaration=True)
        target = folder/'canonical-review.xlsx'
        target.write_bytes(patched_package(binding['backend_export']['file'], transform))
        return {**p, 'request':{'kind':'calculation', 'file':str(target), 'reference':reference}}

    def operate(self, request):
        s, binding = self.service, self.binding
        if request['action'] in {'current', 'start'}:
            return s.deliver()
        if request['action'] == 'native-preview':
            return self.preview(request['file'])
        if request['action'] != 'upload':
            raise Rejected('原样交付适配仅处理current、native-preview及upload')
        file, reference = Path(request['file']).resolve(), request['reference']
        inputsha, head = digest(file), s.status()['head']
        receipt = s.background/'last-original-layout-submission.json'
        if receipt.exists():
            old = load(receipt)
            if old['input_sha256'] == inputsha and old['head'] == head:
                return {**old['result'], 'receipt_replayed':True}
        projected = self.project(file, reference)
        if projected.get('status') == 'requires_basics_sync_before_calculation':
            return projected
        result = s.upload(**projected['request'])
        if result['stage'] == 'calculation':
            from openpyxl import load_workbook
            w = load_workbook(file, read_only=True, data_only=True)
            try:
                rows = list(w[binding['sheet']].values)
            finally:
                w.close()
            known = {x['target']:x for x in binding['items']}

            def transform(raw):
                def cache(m):
                    addr = address(m[0])
                    if addr not in known or re.search(rb'<f[^>]*>', m[0]) is None:
                        return m[0]
                    v = rows[known[addr]['source_row']-1]
                    total = Fraction(str(v[10]))
                    if total <= 0:
                        return m[0]
                    value = round0(Fraction(str(v[12]))*Fraction(str(v[11]))/total)
                    return re.sub(rb'<v>[^<]*</v>', b'<v>'+str(value).encode()+b'</v>', m[0])
                return CELL.sub(cache, raw)
            native = patched_package(file, transform)
            retained = s.background/'original-layout-submissions'
            retained.mkdir(exist_ok=True)
            rawcopy = retained/(inputsha+'.xlsx')
            if not rawcopy.exists():
                shutil.copyfile(file, rawcopy)
            public = s.public/(s.config['batch_label']+'_计算审核.xlsx')
            public.write_bytes(native)
            pointer = s.background/'current-review-submission.json'
            if pointer.exists():
                value = load(pointer)
                value.update(file=str(public), sha256=digest(public), operator_native_source=str(rawcopy))
                save(pointer, value)
            result.update(business_files=[str(public)], business_view='original-21', original_layout_preserved=True)
        save(receipt, {'input_sha256':inputsha, 'head':s.status()['head'], 'result':result, 'formal_output':False})
        return result
