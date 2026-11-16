"""Synthetic guard tests; actual source and WPS receipts stay outside Git."""
from pathlib import Path
import sys,tempfile,unittest,copy,zipfile,subprocess,os
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'business-interaction'),str(ROOT/'business-interaction/rebuild_mvp/tests')]
import verify_pair_acceptance as A
from test_enrichment import book
from rebuild_mvp.xlsxio import HEADERS,Q,extract_batch

def patch_cell(path,addr,value,formula=None,typ='inlineStr'):
    with zipfile.ZipFile(path)as z:parts={n:z.read(n)for n in z.namelist()}
    member=A.sheet_info(path)[0]['path'];tree=ET.fromstring(parts[member]);sd=tree.find(Q+'sheetData');n=''.join(c for c in addr if c.isdigit());row=next((r for r in sd if r.get('r')==n),None)
    if row is None:row=ET.SubElement(sd,Q+'row',{'r':n})
    cell=next((c for c in row if c.get('r')==addr),None)
    if cell is None:cell=ET.SubElement(row,Q+'c',{'r':addr})
    cell[:]=[];cell.set('t',typ)
    if formula is not None:ET.SubElement(cell,Q+'f').text=formula
    if typ=='inlineStr':ET.SubElement(ET.SubElement(cell,Q+'is'),Q+'t').text=value
    else:ET.SubElement(cell,Q+'v').text=value
    parts[member]=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED)as z:
        for name,data in parts.items():z.writestr(name,data)

class AcceptanceGuards(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.src=self.root/'input.xlsx';self.out=self.root/'copy.xlsx'
        records=[['A1','JP','001','001','','人工品名','规格甲','','','商品日文','2','10','20','','PVC','','YD1','','','','','','',''],
                 ['A2','JP','001','001','','人工品名2','规格乙','','','商品日文2','3','10','30','','PVC','','YD2','','','','','6','','']]
        book(self.src,headers=HEADERS,records=records);self.out.write_bytes(self.src.read_bytes());b=extract_batch(self.src)
        self.q={'upstream':{'batch_id':'REAL-B'},'rows':[{'sheet':r['sheet'],'original_identity':{'source_sha256':b['source']['sha256'],'source_row':r['source_row']}}for r in b['rows']]}
        self.expected={'kind':'real_batch','batch_id':'REAL-B','source':b['source'],'sheet':b['sheet']}
    def check(self):return A.preserved(self.src,self.out,self.expected['sheet'])
    def test_exact_source_roster_including_duplicate_codes(self):
        d=A.coverage(self.q,self.expected);self.assertTrue(d['whole_batch_covered']);self.assertEqual(d['expected_rows'],2)
    def test_same_jan_does_not_hide_missing_shipment_row(self):
        self.q['rows'].pop();d=A.coverage(self.q,self.expected);self.assertFalse(d['whole_batch_covered']);self.assertEqual(len(d['missing']),1)
    def test_duplicate_row_rejected(self):
        self.q['rows'][1]=copy.deepcopy(self.q['rows'][0]);self.assertFalse(A.coverage(self.q,self.expected)['whole_batch_covered'])
    def test_reordered_rows_not_accepted_as_same_batch(self):
        self.q['rows'].reverse();d=A.coverage(self.q,self.expected);self.assertFalse(d['source_order_complete']);self.assertEqual(d['missing'],[])
    def test_other_source_same_positions_does_not_count(self):
        for row in self.q['rows']:row['original_identity']['source_sha256']='0'*64
        self.assertEqual(A.coverage(self.q,self.expected)['matched_exact_source_rows'],0)
    def test_batch_label_mismatch_does_not_pass(self):
        self.expected['batch_id']='OTHER';self.assertFalse(A.coverage(self.q,self.expected)['whole_batch_covered'])
    def test_sample_cannot_be_relabelled_as_real(self):
        self.expected['batch_id']=self.q['upstream']['batch_id']='TECHNICAL-SAMPLE'
        self.assertFalse(A.coverage(self.q,self.expected)['whole_batch_covered'])
    def test_explicit_technical_scope_not_real(self):
        self.expected['kind']='technical_sample';d=A.coverage(self.q,self.expected);self.assertTrue(d['source_order_complete']);self.assertFalse(d['whole_batch_covered'])
    def test_roster_sha_drift_is_rejected(self):
        self.expected['source']['sha256']='0'*64
        with self.assertRaises(A.MvpError):A.coverage(self.q,self.expected)
    def test_roster_sheet_must_be_exact(self):
        self.expected['sheet']='wrong'
        with self.assertRaises(ValueError):A.coverage(self.q,self.expected)
    def test_identical_preserved(self):
        p=self.check();self.assertFalse(p['errors']);self.assertTrue(p['media_drawing_parts_preserved'])
    def test_blank_quantity_fill_allowed(self):
        patch_cell(self.out,'U2','2',typ='n');self.assertFalse(self.check()['errors']);self.assertEqual(len(self.check()['authorized_blank_fills']),1)
    def test_evidence_order_is_stable_across_process_hash_seeds(self):
        patch_cell(self.out,'U2','2',typ='n');patch_cell(self.out,'V2','4',typ='n')
        code='import json,sys;from verify_pair_acceptance import preserved;print(json.dumps(preserved(sys.argv[1],sys.argv[2],sys.argv[3]),sort_keys=True))'
        results=[subprocess.check_output([sys.executable,'-X','utf8','-B','-c',code,str(self.src),str(self.out),self.expected['sheet']],env={**os.environ,'PYTHONPATH':str(ROOT/'tools'),'PYTHONHASHSEED':seed})for seed in ['1','2']]
        self.assertEqual(results[0],results[1])
    def test_existing_manual_quantity_never_overwritten(self):
        patch_cell(self.out,'V3','99');self.assertTrue(any(e['code']=='PROTECTED_CELL_CHANGED'for e in self.check()['errors']))
    def test_raw_price_change_detected(self):
        patch_cell(self.out,'L2','99');self.assertTrue(self.check()['errors'])
    def test_manual_name_change_detected(self):
        patch_cell(self.out,'F2','new');self.assertTrue(self.check()['errors'])
    def test_formula_and_cache_both_protected(self):
        patch_cell(self.src,'M2','20',formula='K2*L2',typ='n');self.out.write_bytes(self.src.read_bytes());patch_cell(self.out,'M2','30',formula='K2*L2',typ='n');self.assertTrue(self.check()['errors'])
    def test_media_byte_change_detected(self):
        for path,value in [(self.src,b'original'),(self.out,b'changed')]:
            with zipfile.ZipFile(path,'a')as z:z.writestr('xl/media/preserved.png',value)
        p=self.check();self.assertFalse(p['media_drawing_parts_preserved']);self.assertIn('xl/media/preserved.png',p['non_target_zip_parts_changed'])
    def test_weight_sheet_change_detected(self):
        with zipfile.ZipFile(self.out)as z:parts={n:z.read(n)for n in z.namelist()}
        member=A.sheet_info(self.out)[1]['path'];parts[member]=parts[member].replace(b'322',b'999')
        # The tiny fixture may label rather than total weight: change any native
        # XML while keeping parseable structure, proving part-level comparison.
        parts[member]=parts[member].replace(b'</worksheet>',b'<!--changed--></worksheet>')
        with zipfile.ZipFile(self.out,'w')as z:
            for n,b in parts.items():z.writestr(n,b)
        self.assertIn(member,self.check()['non_target_zip_parts_changed'])

if __name__=='__main__':unittest.main()
