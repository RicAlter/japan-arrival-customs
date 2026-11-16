import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from test_enrichment import book
from rebuild_mvp import enrichment as E
from rebuild_mvp.service import handle
from rebuild_mvp.xlsxio import read_book
from rebuild_mvp.purchase_images import image_rows,match
from material_foundation import service as M
from material_foundation.parsing import parse

class LinkStage(unittest.TestCase):
    def test_offline_link_stage_then_final_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'in.xlsx';book(source)
            req=dict(workflow='rebuild_mvp_v1',action='prepare',mode='enrich_review',batch_id='test',input_file=str(source),output=str(root/'run'),materials=False,pictures=True,allow_online=True)
            record={'codes':['4571696823571'],'yd':'YD2026070101','url':'https://example.com/a.png'}
            from PIL import Image
            from rebuild_mvp.service import digest
            p=root/'a.png';Image.new('RGB',(20,10),'blue').save(p)
            img=dict(path=str(p),sha256=digest(p),width=20,height=10)
            with patch.object(E,'observations',return_value=([record],[])),patch.object(E,'download',return_value=img) as download:
                first=handle(req);self.assertNotEqual(first['status'],'failed',first);download.assert_not_called()
                self.assertEqual(first['summary']['missing_picture_link_rows'],0)
                self.assertEqual(first['summary']['blank_picture_rows'],1)
                path=first['business_files'][0]
                row=read_book(path)['sheets'][0]['rows'][1]
                self.assertEqual(row['values']['E'],record['url']);self.assertFalse(image_rows(path,'invoice (計算)'))
                second=handle(dict(workflow='rebuild_mvp_v1',action='resume',task_root=str(root/'run'),finalize_pictures=True))
                self.assertNotEqual(second['status'],'failed',second);self.assertEqual(download.call_count,1)
                self.assertEqual(image_rows(second['business_files'][0],'invoice (計算)'),{2})
                handle(dict(workflow='rebuild_mvp_v1',action='resume',task_root=str(root/'run')));self.assertEqual(download.call_count,1)
    def test_existing_url_reused_but_manual_text_not_adopted(self):
        rows=[{'row':2,'values':{'C':'123','E':'https://example.com/a'}},{'row':3,'values':{'C':'123','E':'人工备注'}}]
        result=match(rows,[],set());self.assertEqual(result['2']['url'],'https://example.com/a');self.assertIsNone(result['3']['url'])
    def test_404_not_absence_and_next_site_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'in.xlsx';book(source)
            job=root/'job';M.handle(dict(action='prepare',input_file=str(source),output=str(job),sheet='invoice (計算)',columns={'code':'C','material':'R'},nonblocking=True))
            request=M.handle(dict(action='next',task_root=str(job)))['request']
            result=M.handle(dict(action='submit',task_root=str(job),request_id=request['id'],http_status=404,body='Not Found'))
            self.assertNotEqual(result.get('status'),'failed',result)
            stored=json.loads((job/'job.json').read_text(encoding='utf8'));item=stored['codes'][request['jan']]
            self.assertEqual(item['status'],'retry');self.assertEqual(item['attempts'][-1]['error_code'],'HTTP_404_UNVERIFIED')
            self.assertEqual(M.handle(dict(action='next',task_root=str(job)))['request']['site'],'colleize')
    def test_html_and_null_api_response_are_errors(self):
        for site in ('anime_store','colleize','amiami'):
            for body in ('<html>login</html>','null','[]'):
                self.assertEqual(parse(site,'4571696823571','search',body,'x')['status'],'error')

if __name__=='__main__':unittest.main()
