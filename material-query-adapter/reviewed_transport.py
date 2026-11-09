"""Fail-closed, robots checked and budgeted public page transport."""
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import hashlib,json,time

class ReviewedTransport:
 def __init__(self,inner,review,state):
  self.inner=inner;self.review=json.loads(Path(review).read_text('utf-8')) if review else {};self.state=Path(state);self.count=0;self.last={}
 def get(self,url):
  from jpmaterial.transport import HttpResponse
  u=urlparse(url);site=self.review.get('hosts',{}).get(u.hostname,{})
  if u.scheme!='https' or not site.get('enabled') or self.count>=self.review.get('request_budget',0):return HttpResponse(url,error='access review not enabled or request budget exhausted')
  robots=RobotFileParser();robots.parse(site.get('robots_text','').splitlines())
  if not site.get('robots_checked') or not robots.can_fetch('JPMaterialQuery',url) or not any(u.path.startswith(p) for p in site.get('allowed_prefixes',[])):return HttpResponse(url,error='path denied by access review/robots')
  delay=max(15,site.get('interval_seconds',15));time.sleep(max(0,delay-(time.time()-self.last.get(u.hostname,0))))
  self.last[u.hostname]=time.time();self.count+=1;response=self.inner.get(url)
  folder=self.state/'pages';folder.mkdir(parents=True,exist_ok=True);name=hashlib.sha256((url+str(time.time_ns())).encode()).hexdigest();body=folder/(name+'.html');body.write_text(response.text,encoding='utf-8')
  meta={'url':url,'final_url':response.url,'status':response.status_code,'error':response.error,'fetched_at':time.time(),'body':str(body),'sha256':hashlib.sha256(body.read_bytes()).hexdigest()}
  (folder/(name+'.json')).write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
  if response.url and urlparse(response.url).hostname!=u.hostname:return HttpResponse(url,error='redirected outside reviewed host')
  return response
