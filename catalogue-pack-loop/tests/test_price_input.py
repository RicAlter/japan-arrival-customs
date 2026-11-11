"""Price-layout adapter regression against the pinned real KMT20261003 files."""
import json,sys,unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from packloop import runtime,price_input
from packloop.support import Rejected,digest

OLD=Path('C:/Users/Administrator/.codex/worktrees/phase1-repair-integration/material-sop-restore-20261110')
RAW16=OLD/'out/p1/run/后台/fixed-inputs/original.xlsx'
RAW11=next(Path('D:/日本到货海关报单数据/05_独立资料库镜像/日本到货业务资料库/01_原始资料').glob('a00678cbf18081*.xlsx'))
AUDIT=OLD/'outputs/kmt20261003-historical-return-20261111/phase2-input-check.json'

class PriceInput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before={p:digest(p) for p in [RAW16,RAW11]}
        cls.a,cls.ainfo=runtime.updates.invoice(RAW11)
        cls.b,cls.binfo=runtime.updates.invoice(RAW16)
        cls.audit=json.loads(AUDIT.read_text(encoding='utf-8'))
        cls.arows={r['row']:r for r in cls.a};cls.brows={r['row']:r for r in cls.b}
    def test_11_column_legacy_rows_and_totals_unchanged(self):
        from packloop.support import load_module
        legacy,_=load_module('packloop.flow.legacy_test',runtime.updates.__file__).invoice(RAW11)
        self.assertEqual(len(legacy),571)
        for old,new in zip(legacy,self.a):
            self.assertEqual(old,{k:new[k] for k in old})
        self.assertEqual(self.ainfo['loop_total_checks'],[{'row':677,'amount_cell':'K677','quantity_cell':'I677','consistent':True}])
        from native22.profiles import inspect_source
        s=inspect_source(RAW11)
        for r in self.a:
            for field,col in [('price','H'),('quantity','I'),('amount','K')]:
                self.assertEqual(r[field],str(s['sheet'].v(r['row'],col)))
    def test_16_rows_keep_original_coordinates_and_cached_values(self):
        self.assertEqual(len(self.b),1967)
        self.assertEqual([r['row'] for r in self.b],list(range(2,1969)))
        from arrival_core import _p0_frozen as p0
        for r in self.b:
            for field,col in [('code','C'),('ja','I'),('price','K'),('quantity','J'),('amount','L')]:
                self.assertEqual(r[field],p0.text(self.binfo['sheet'].v(r['row'],col)))
            self.assertEqual(r['source']['row'],r['row'])
    def test_11_full_identity_keeps_Ref_and_HS_fields(self):
        row=deepcopy(self.a[0]);row['identity'][1]='existing Ref'
        self.assertNotEqual(price_input.identity_key(row,self.ainfo),price_input.identity_key(self.a[0],self.ainfo))
    def test_16_identity_uses_only_existing_identity_columns(self):
        r=self.b[0]
        self.assertEqual(price_input.identity_key(r,self.binfo),(r['carton'],r['code'],r['ja'],r['origin']))
    def test_profile_specific_original_row_mapping(self):
        row={'source':{'row':2}}
        self.assertEqual(price_input.source_row(row,self.ainfo),18)
        self.assertEqual(price_input.source_row(row,self.binfo),2)
    def test_no_source_unit_or_packaging_inference(self):
        for r in self.a+self.b:
            self.assertEqual(r['currency'],'JPY')
            self.assertIsNone(r['price_unit']);self.assertIsNone(r['quantity_unit'])
            self.assertEqual(r['unit_status'],'source_pricing_and_quantity_units_unconfirmed')
    def test_each_price_has_original_version_and_source(self):
        for rows,file in [(self.a,RAW11),(self.b,RAW16)]:
            h=digest(file)
            for r in rows:
                self.assertEqual(r['price_version']['sha256'],h)
                self.assertEqual(r['price_version']['row'],r['source']['row'])
                self.assertEqual(r['source']['sha256'],h)
    def test_both_validated_weight_sheet_names_retained(self):
        self.assertEqual(price_input.weight_sheet(self.ainfo['book'],self.ainfo).name,'重さとサイズ')
        self.assertEqual(price_input.weight_sheet(self.binfo['book'],self.binfo).name,'重さとサイズ (2)')
    def test_ambiguous_weight_pages_do_not_guess(self):
        with self.assertRaises(Rejected):price_input.weight_sheet(self.ainfo['book'],{'weights':[]})
    def test_20_column_business_output_is_not_an_invoice(self):
        with self.assertRaises(Rejected):runtime.updates.invoice(self.audit['source_current']['excel'])
    def test_real_490_direct_identity_relationships(self):
        matched=[r for r in self.audit['rows'] if r['match_route']=='exact_carton_JAN_japanese_description_origin']
        self.assertEqual(len(matched),490)
        for r in matched:
            self.assertEqual(price_input.identity_key(self.brows[r['row']],self.binfo),price_input.identity_key(self.arows[r['actual_price_row']],self.binfo))
    def proof(self):
        r=next(x for x in self.audit['rows'] if x['link_sources'])
        s=r['link_sources'][0]
        from openpyxl.utils import get_column_letter
        proof={'new_row':r['actual_price_row'],'reference':'Existing real source evidence',
               'code_link':{k:s[k] for k in ['path','sha256','sheet','row']}}
        proof['code_link']['columns']={k:get_column_letter(s['columns'][k]+1) for k in ['jan','pcs','name','spec']}
        view={'fields':{name:{'row_id':'actual-row','field':name,'value':{'value':r['name'] if name=='internal_name' else r['spec']}} for name in ['internal_name','specification']}}
        return r,proof,view
    def test_6_real_pcs_links_have_locatable_identity_proof(self):
        links=[r for r in self.audit['rows'] if r['link_sources']]
        self.assertEqual(len(links),6)
        from openpyxl.utils import get_column_letter
        for r in links:
            s=r['link_sources'][0];proof={'new_row':r['actual_price_row'],'reference':'Existing source',
              'code_link':{**{k:s[k] for k in ['path','sha256','sheet','row']},'columns':{k:get_column_letter(s['columns'][k]+1) for k in ['jan','pcs','name','spec']}}}
            view={'fields':{n:{'row_id':'actual-row','field':n,'value':{'value':r['name'] if n=='internal_name' else r['spec']}} for n in ['internal_name','specification']}}
            self.assertTrue(price_input.link_matches(self.brows[r['row']],self.arows[r['actual_price_row']],self.binfo,proof,view,'actual-row'))
    def test_plain_reference_cannot_authorize_a_changed_JAN(self):
        r,p,v=self.proof();p.pop('code_link')
        self.assertFalse(price_input.link_matches(self.brows[r['row']],self.arows[r['actual_price_row']],self.binfo,p,v,'actual-row'))
    def test_pcs_source_hash_tampering_rejected(self):
        r,p,v=self.proof();p['code_link']['sha256']='0'*64
        with self.assertRaises(Rejected):price_input.link_matches(self.brows[r['row']],self.arows[r['actual_price_row']],self.binfo,p,v,'actual-row')
    def test_pcs_source_does_not_cover_different_product_or_spec(self):
        r,p,v=self.proof();v['fields']['specification']['value']['value']+='different'
        self.assertFalse(price_input.link_matches(self.brows[r['row']],self.arows[r['actual_price_row']],self.binfo,p,v,'actual-row'))
    def test_pcs_link_never_changes_carton_or_Japanese_identity(self):
        r,p,v=self.proof();new=deepcopy(self.arows[r['actual_price_row']]);new['ja']+='different'
        self.assertFalse(price_input.link_matches(self.brows[r['row']],new,self.binfo,p,v,'actual-row'))
    def test_link_schema_does_not_accept_extra_approval_flags(self):
        self.assertTrue(price_input.valid_link({'new_row':18,'reference':'real'}))
        self.assertFalse(price_input.valid_link({'new_row':18,'reference':'real','approved':True}))
    def test_raw11_link_schema_stays_unchanged(self):
        _,proof,_=self.proof()
        self.assertFalse(price_input.valid_link(proof,self.ainfo))
        self.assertTrue(price_input.valid_link(proof,self.binfo))
    def test_source_bytes_unchanged(self):
        self.assertEqual(self.before,{p:digest(p) for p in self.before})

if __name__=='__main__':unittest.main()
