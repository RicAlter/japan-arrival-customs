import io,tempfile,unittest,zipfile,types
from pathlib import Path
from unittest.mock import patch
from hashlib import sha256
from interaction import Rejected
from interaction import large_return as L

def package(**changes):
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    p={'xl/workbook.xml':f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets><sheet name="业务表" sheetId="1" r:id="rId1"/></sheets></workbook>'.encode(),
       'xl/_rels/workbook.xml.rels':b'<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
       'xl/worksheets/sheet1.xml':f'<worksheet xmlns="{ns}" xmlns:r="{rel}"><sheetData><row r="2"><c r="M2"><f>K2*L2</f><v>50</v></c><c r="N2" t="inlineStr"><is><t>人工值</t></is></c></row></sheetData><drawing r:id="rId1"/></worksheet>'.encode(),
       'xl/worksheets/_rels/sheet1.xml.rels':b'<Relationships><Relationship Id="rId1" Target="../drawings/drawing1.xml"/></Relationships>',
       'xl/drawings/drawing1.xml':f'<xdr:wsDr xmlns:xdr="{L.D[1:-1]}" xmlns:a="{L.A[1:-1]}" xmlns:r="{rel}"><xdr:oneCellAnchor><xdr:from><xdr:col>4</xdr:col><xdr:row>1</xdr:row></xdr:from><xdr:pic><a:blip r:embed="rId1"/></xdr:pic></xdr:oneCellAnchor></xdr:wsDr>'.encode(),
       'xl/drawings/_rels/drawing1.xml.rels':b'<Relationships><Relationship Id="rId1" Target="../media/image1.png"/></Relationships>',
       'xl/media/image1.png':L.PIXEL,
       'docProps/custom.xml':b'<Properties>CustomsAStageExportVersion</Properties>'}
    p.update(changes);out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for n,b in p.items():z.writestr(n,b)
    return out.getvalue()

class LargeReturnTests(unittest.TestCase):
    def test_comparison_view_keeps_every_nonimage_byte_including_formula_cache_manual(self):
        raw=package();checked=L.inspect_package(raw)
        self.assertEqual(checked['picture_anchors'],1)
        with zipfile.ZipFile(io.BytesIO(raw)) as a,zipfile.ZipFile(io.BytesIO(checked['view'])) as b:
            for n in a.namelist():
                if not n.startswith('xl/media/'):self.assertEqual(a.read(n),b.read(n))

    def test_duplicate_parts_and_traversal_rejected(self):
        for extra in ['../escape.xml','C:/escape.xml']:
            with self.assertRaises(Rejected):L.inspect_package(package(**{extra:b'x'}))
        malformed=package(**{'xl/escape.xml':b'x'}).replace(b'xl/escape.xml',b'xl\\escape.xml')
        with self.assertRaises(Rejected):L.inspect_package(malformed)
        raw=io.BytesIO(package())
        with zipfile.ZipFile(raw,'a') as z:z.writestr('xl/media/image1.png',b'x')
        with self.assertRaises(Rejected):L.inspect_package(raw.getvalue())

    def test_resource_bounds_are_checked_before_inflation(self):
        raw=package()
        for setting in ['MAX_FILE','MAX_EXPANDED','MAX_XML','MAX_IMAGE','MAX_PARTS']:
            with patch.object(L,setting,1):
                with self.assertRaises(Rejected):L.inspect_package(raw)

    def test_macros_external_connections_and_entities_rejected(self):
        for n in ['xl/vbaProject.bin','xl/connections.xml','xl/queryTables/a.xml','xl/embeddings/a.bin']:
            with self.assertRaises(Rejected):L.inspect_package(package(**{n:b'x'}))
        with self.assertRaises(Rejected):L.inspect_package(package(**{'extra.xml':b'<!DOCTYPE a [<!ENTITY x "xx">]><a/>'}))

    def test_external_image_and_incomplete_anchor_rejected(self):
        for raw in [b'<Relationships><Relationship Id="rId1" Target="http://example/image.png" TargetMode="External"/></Relationships>',b'<Relationships/>']:
            with self.assertRaises(Rejected):L.inspect_package(package(**{'xl/drawings/_rels/drawing1.xml.rels':raw}))

    def test_renamed_lossless_deduplicated_media_matches_original_anchors(self):
        raw=package();old=L.inspect_package(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:p={n:z.read(n) for n in z.namelist()}
        p['xl/media/renamed.png']=p.pop('xl/media/image1.png')
        p['xl/drawings/_rels/drawing1.xml.rels']=p['xl/drawings/_rels/drawing1.xml.rels'].replace(b'image1.png',b'renamed.png')
        o=io.BytesIO()
        with zipfile.ZipFile(o,'w',zipfile.ZIP_DEFLATED) as z:
            for n,b in p.items():z.writestr(n,b)
        self.assertEqual(old['pictures'],L.inspect_package(o.getvalue())['pictures'])

    def test_changed_image_or_anchor_refused_before_save(self):
        original=L.inspect_package(package())
        with tempfile.TemporaryDirectory() as d:
            guard=L.Guard.__new__(L.Guard);guard.expected=original['pictures'];guard.original_unused=set();guard.views={};guard.receipts=[];guard.config={'background':d}
            f=Path(d)/'returned.xlsx';f.write_bytes(package(**{'xl/media/image1.png':b'changed bytes'}))
            with self.assertRaises(Rejected):guard.authorize(f)
            drawing=zipfile.ZipFile(io.BytesIO(package())).read('xl/drawings/drawing1.xml').replace(b'<xdr:row>1</xdr:row>',b'<xdr:row>2</xdr:row>')
            f=Path(d)/'moved.xlsx';f.write_bytes(package(**{'xl/drawings/drawing1.xml':drawing}))
            with self.assertRaises(Rejected):guard.authorize(f)
            self.assertFalse(guard.views)

    def test_parser_wrapper_is_context_scoped_and_preserves_external_link_checks(self):
        import native_return.compare as C
        def original(data,*,trusted_external=None):return data,trusted_external
        with patch.object(C,'read',original):
            L._install();self.assertEqual(C.read(b'unregistered'),(b'unregistered',None))
            scope=types.SimpleNamespace(views={sha256(b'original').hexdigest():b'view'})
            token=L.ACTIVE.set(scope)
            try:
                self.assertEqual(C.read(b'original',trusted_external={'existing':'proof'}),(b'view',{'existing':'proof'}))
                with self.assertRaises(Rejected):C.read(b'unverified')
            finally:L.ACTIVE.reset(token)
            self.assertEqual(C.read(b'original'),(b'original',None))

    def test_marker_peek_does_not_load_media_or_rewrite_upload(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'copy.xlsx';raw=package();f.write_bytes(raw)
            self.assertTrue(L.has_basics_marker(f));self.assertEqual(f.read_bytes(),raw)
            guard=L.Guard.__new__(L.Guard);guard.config={'background':d};guard.receipts=[{'original_sha256':sha256(raw).hexdigest()}]
            guard.retain_original(f);saved=Path(d)/'large-return-inputs'/(sha256(raw).hexdigest()+'.xlsx')
            self.assertEqual(saved.read_bytes(),raw)
            f.write_bytes(raw+b'changed')
            with self.assertRaises(Rejected):guard.retain_original(f)
            with patch.object(L,'MAX_FILE',1):
                with self.assertRaises(Rejected):L.has_basics_marker(f)

    def test_unregistered_layout_cannot_enable_large_media_channel(self):
        engine=types.SimpleNamespace(root=Path('.'),bid='batch',store=types.SimpleNamespace(load=lambda _:{}),basics=types.SimpleNamespace(_baseline=lambda _:({'registration_ref':'reg'},)))
        with patch('interaction.get',return_value={'stage1_policy':{'registered_output_columns':19}}):
            with self.assertRaises(Rejected):L.Guard({'schema':'prepared-basics-session/1'},engine,'file.xlsx')

if __name__=='__main__':unittest.main()
