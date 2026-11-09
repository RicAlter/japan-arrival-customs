import sys,json,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from adapter import identity,key,assess,BoundCache,Service
from reviewed_transport import ReviewedTransport
class Tests(unittest.TestCase):
 def test_binding_not_jan(self):
  q={'jan':'123','yd':'A','spec':'box','name_ja':'x','source_sha256':'a'}
  for k in ['yd','spec','name_ja','source_sha256','source_row']:
   self.assertNotEqual(key(identity(q)),key(identity(dict(q,**{k:'changed'}))))
 def test_no_page_jan_name_mismatch(self):
  self.assertEqual(assess({'jan':'1','name_ja':'a'},{'name_ja':'b','material_original':'紙'},lambda a,b:.1)['status'],'identity_conflict')
 def test_numbered_version(self):
  self.assertEqual(assess({'jan':'1','name_ja':'product vol.2'},{'jan_on_page':'1','name_ja':'product vol.3'},lambda a,b:.9)['status'],'identity_conflict')
 def test_jan_mismatch(self):
  self.assertEqual(assess({'jan':'1'},{'jan_on_page':'2'},lambda a,b:1)['status'],'identity_conflict')
 def test_missing_jan_unresolved(self):
  self.assertEqual(assess({'jan':'1','name_ja':'abc'},{'name_ja':'abc'},lambda a,b:1)['status'],'identity_unresolved')
 def test_exact_still_not_adopted(self):
  self.assertFalse(assess({'jan':'1','name_ja':'abc'},{'jan_on_page':'1','name_ja':'abc'},lambda a,b:1)['adopted'])
 def test_plugin_jan_only_not_upgraded(self):
  r=assess({'jan':'1','name_ja':'abc'},{'jan_on_page':'1','name_ja':'abc','match_status':'jan_only'},lambda a,b:1)
  self.assertEqual(r['status'],'identity_unresolved')
 def test_cache_isolation(self):
  class C:
   def __init__(self):self.d={}
   def put(self,s,j,u,d,t):self.d[s,j]=d
   def get(self,s,j):return self.d.get((s,j))
  c=BoundCache(C());c.binding='a';c.put('s','1','u',{'x':1},60);c.binding='b';self.assertIsNone(c.get('s','1'));c.binding='a';self.assertEqual(c.get('s','1'),{'x':1})
 def test_unreviewed_no_network(self):
  class I:
   def get(self,u):raise AssertionError('network')
  self.assertIsNone(ReviewedTransport(I(),None,'unused').get('https://amnibus.com/products/detail/1').status_code)
 def test_manual_never_calls_plugin(self):
  class Cat:
   sha='sha'
   def lookup(self,q):return {'status':'missing'}
  s=Service.__new__(Service);s.catalogue=Cat()
  # Imports resolve against the fixed vendor in test runner.
  self.assertEqual(s.query({'jan':'1','manual_material':'纸'})['status'],'keep_manual')
 def test_local_priority_no_plugin(self):
  class Cat:
   sha='sha'
   def lookup(self,q):return {'status':'sku_material_candidate'}
  s=Service.__new__(Service);s.catalogue=Cat();self.assertFalse(s.query({'jan':'1'})['plugin_called'])
 def test_query_failure_nonblocking(self):
  class Cat:
   sha='sha'
   def lookup(self,q):return {'status':'missing','cards':[]}
  class Engine:
   def query(self,*a,**kw):raise TimeoutError('timeout')
  s=Service.__new__(Service);s.catalogue=Cat();s.cache=type('Cache',(),{})();s.engine=Engine();r=s.query({'jan':'4571608537527'});self.assertEqual(r['status'],'error');self.assertTrue(r['non_blocking'])
if __name__=='__main__':unittest.main(verbosity=2)
