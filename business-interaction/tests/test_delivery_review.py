"""Isolated audit fixtures; no synthetic material is used in business outputs."""
from pathlib import Path
import tempfile
import unittest
import io
from copy import deepcopy
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from PIL import Image
from interaction import ROOT,load,save,digest,Rejected,key
from interaction.preparation_workbook import native_project,update_cells,graft_images
from interaction.delivery_review import review_delivery,picture_rows
from interaction.photo_layout import parts
from interaction.material_review import website_execution,read_rows
from interaction.website_query import apply_review_overlay
from native_copy.profiles import inspect_source


class DeliveryReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        request=load(ROOT.parents[1]/'reports/first-phase-upgrade-20261106/prepare-request.json')
        cls.source=inspect_source(request['input_file'])
        cls.base=native_project(cls.source,20)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.file=self.root/'current.xlsx';self.file.write_bytes(self.base)
        sop=ROOT/'workbuddy/japan-arrival-customs-trial/references/business-preparation-sop.md'
        self.config={'background':str(self.root),'prepared_file':str(self.file),'source':str(self.source['path']),
                     'source_sha256':digest(self.source['path']),'sheet':self.source['sheet'].name,
                     'delivery_review_required':True,'material_review_settings':{'allow_online':False},
                     'preparation_policy':{'sop':{'path':str(sop),'sha256':digest(sop)}}}
        self.evidence={str(n):{'lookup_execution':{'executed':True},'status':'missing','sources':[],
                              'image_execution':{'status':'not_executed','reason':'download_images_disabled'}}
                       for n in range(2,len(self.source['rows'])+2)}
        save(self.root/'evidence.json',{'rows':self.evidence})

    def audit(self):return review_delivery(self.config)

    def website(self):
        row=self.source['rows'][0]
        binding={'row':2,'jan':row['code'],'name_ja':row['japanese_name'],'spec':'','yd':''}
        snapshot=self.root/'fixture.html';snapshot.write_text('SYNTHETIC material fixture',encoding='utf-8')
        candidate={'jan':binding['jan'],'rows':[binding],'material_original':'SYNTHETIC 原文','material_zh':'SYNTHETIC 材质',
                   'url':'https://example.invalid/fixture','snapshot':str(snapshot),'content_sha256':digest(snapshot),
                   'match_status':'exact_jan_name_spec','status':200}
        manifest=self.root/'manifest.json';save(manifest,{'candidates':[candidate]})
        candidate.update(manifest=str(manifest),manifest_sha256=digest(manifest))
        report=self.root/'material-review.json';save(report,{'rows':{'2':{'binding':binding,
            'website':{'status':'found','values':['SYNTHETIC 材质'],'evidence':[candidate]},
            'website_execution':{'status':'verified_evidence','reason':'row_bound_raw_snapshot_verified'}}}})
        dual={'reference_report':str(report)};save(self.root/'material-review-complete.json',dual)
        return dual,snapshot

    def test_disabled_queries_are_incomplete_and_current_audit_is_idempotent(self):
        before=digest(self.file),self.file.stat().st_mtime_ns
        result=self.audit();self.assertEqual(result['actual_embedded_image_rows'],0)
        self.assertEqual(result['status'],'incomplete_with_reasons');self.assertEqual(result['new_confirmations'],0)
        self.assertGreater(result['unfinished_reason_counts']['download_images_disabled'],0)
        stamp=(self.root/'delivery-completeness.json').stat().st_mtime_ns
        self.audit();self.assertEqual(stamp,(self.root/'delivery-completeness.json').stat().st_mtime_ns)
        self.assertEqual(before,(digest(self.file),self.file.stat().st_mtime_ns))

    def test_missing_lookup_record_blocks(self):
        self.evidence['2'].pop('lookup_execution');save(self.root/'evidence.json',{'rows':self.evidence})
        with self.assertRaisesRegex(Rejected,'资料检索状态'):self.audit()

    def test_claimed_download_without_actual_picture_blocks(self):
        self.evidence['2']['image_execution']={'status':'downloaded','reason':'download_succeeded'}
        save(self.root/'evidence.json',{'rows':self.evidence})
        with self.assertRaisesRegex(Rejected,'图片未嵌入'):self.audit()

    def test_missing_picture_reason_blocks(self):
        self.evidence['2']['image_execution']={'status':'data_missing'}
        save(self.root/'evidence.json',{'rows':self.evidence})
        with self.assertRaisesRegex(Rejected,'原因缺失'):self.audit()

    def test_actual_picture_is_counted_from_anchor_and_media(self):
        png=self.root/'fixture.png';Image.new('RGB',(8,8),'blue').save(png)
        w=Workbook();w.active.title=self.config['sheet'];w.active.add_image(ExcelImage(io.BytesIO(png.read_bytes())),'E2')
        canvas=self.root/'canvas.xlsx';w.save(canvas)
        self.file.write_bytes(graft_images(self.base,canvas.read_bytes(),self.config['sheet'],[{'row':2,'width':8,'height':8,'file':str(png)}]))
        self.assertEqual(picture_rows(parts(self.file.read_bytes()),self.config['sheet']),{2})
        self.assertEqual(self.audit()['actual_embedded_image_rows'],1)

    def test_raw_quantity_and_formula_cache_changes_block(self):
        self.file.write_bytes(update_cells(self.base,self.config['sheet'],[{'target':'K2','value':999999}]))
        with self.assertRaisesRegex(Rejected,'原始qty变化'):self.audit()
        self.file.write_bytes(update_cells(self.base,self.config['sheet'],[{'target':'M2','value':999999}]))
        with self.assertRaisesRegex(Rejected,'原金额公式或缓存变化'):self.audit()

    def test_sop_drift_blocks(self):
        self.config['preparation_policy']['sop']['sha256']='wrong'
        with self.assertRaisesRegex(Rejected,'SOP版本'):self.audit()

    def test_verified_website_result_reaches_R_and_cache_can_be_rechecked(self):
        dual,_=self.website();apply_review_overlay(self.config,dual)
        result=self.audit();self.assertEqual(result['fields_filled']['R'],1)
        self.assertEqual(result['execution_counts']['website:verified_evidence'],1)
        self.assertEqual(load(self.root/'website-overlay.json')['rows']['2']['value'],'SYNTHETIC 材质')

    def test_existing_R_conflict_is_preserved(self):
        dual,_=self.website()
        self.file.write_bytes(update_cells(self.base,self.config['sheet'],[{'target':'R2','value':'existing human value'}]))
        before=digest(self.file);apply_review_overlay(self.config,dual)
        self.assertEqual(digest(self.file),before)
        self.assertIn('existing_R_conflict_or_verified_result_not_presented',self.audit()['unfinished_reason_counts'])

    def test_tampered_website_snapshot_blocks_even_if_report_says_found(self):
        dual,snapshot=self.website();apply_review_overlay(self.config,dual)
        snapshot.write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(Rejected,'缓存证据无法复核'):self.audit()


class WebsiteExecutionTests(unittest.TestCase):
    def result(self,request,state):
        return website_execution({'jan':'4570000000001','identity_key':'x'},{'status':'pending'},request,state)

    def test_disabled_and_exhausted_are_not_network_failures(self):
        self.assertEqual(self.result({}, {})['reason'],'cache_only_no_verified_evidence')
        self.assertEqual(self.result({'allow_online':True},{'budget_exhausted':True})['reason'],'request_budget_exhausted')

    def test_real_access_failure_is_distinct_from_queried_without_material(self):
        failed={'attempts':{'x':[{'site':'a','attempts':[{'error':'blocked_403','fetched_at':'now'}]}]}}
        self.assertEqual(self.result({'allow_online':True},failed)['status'],'external_failure')
        queried={'attempts':{'x':[{'site':'a','attempts':[{'status':200,'fetched_at':'now'}]}]}}
        self.assertEqual(self.result({'allow_online':True},queried)['status'],'queried_unresolved')

    def test_short_internal_codes_remain_in_full_row_coverage(self):
        w=Workbook();s=w.active;s.append(['ProductCode(JANCode)','DescriptionofGoods','规格','渠道','YD','材质','网站查找材质','材质参考'])
        s.append(['2505','特典','','','','','','']);s.append(['TOTAL','','','','','','',''])
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder)/'test.xlsx';w.save(f);_,rows=read_rows(f)
        self.assertEqual(len(rows),1)
        r=website_execution(rows[0],{'status':'pending'},{'allow_online':True},{})
        self.assertEqual(r['reason'],'nonstandard_code_not_verified_JAN')


if __name__=='__main__':unittest.main()
