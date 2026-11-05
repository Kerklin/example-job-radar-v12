"""V12 Job Radar: python radar.py [test]. Standard library; no AI or user secrets."""
import concurrent.futures as cf
import datetime as dt
import html,json,os,re,sys,unittest,urllib.request,urllib.error,urllib.parse,urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET
NOW=lambda:dt.datetime.now(dt.timezone.utc)
SOURCES={
 'UNDP':['https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs'],
 'UNICEF':['https://careers.pageuppeople.com/671/cw/en/rss'],
 'UNOPS':['https://careers.unops.org/careersmarketplace/SearchJobs/feed/?listFilterMode=1&jobRecordsPerPage=6','https://rss.careers.unops.org/'],
 'UN Careers':['https://careers.un.org/jobfeed?language=en','https://careers.un.org/jobfeed?isPage=true'],
 'UNjobs':['https://unjobs.org/skills/civil-engineer'],
 'Impactpool':['https://www.impactpool.org/search?occupational_groups%5B%5D=Engineering'],
 'UNJobsFeed':['https://unjobsfeed.org/']}
# HTML anchors must have a vacancy-specific URL. Navigation is never a vacancy.
PATTERNS={
 'UNDP':r'/hcmUI/CandidateExperience/en/sites/CX_1/(?:jobs/preview|job)/[0-9]+',
 'UNICEF':r'/job/\d+', 'UNOPS':r'/(?:JobDetail|vacancies|ViewVacancy|job)/[^/?#]+',
 'UN Careers':r'/(?:jobSearchDescription|jobOpening)/\d+',
 'UNjobs':r'/vacancies/\d+', 'Impactpool':r'/jobs/\d+',
 'UNJobsFeed':r'/(?:jobs|job)/[^/?#]+'}
TRACKS={
 'Construction':['project manager infrastructure','project manager construction','construction engineer','construction management engineer','construction officer','construction manager','construction specialist','site engineer','resident engineer','engineering officer','engineering associate','clerk of works','construction supervision','civil works','rehabilitation'],
 'Infrastructure':['civil engineer','structural engineer','road engineer','bridge engineer','infrastructure engineer','infrastructure specialist','building services engineer','geotechnical engineer','energy efficiency engineer','reinforced concrete','pavement'],
 'WASH':['wash engineer','water engineer','sanitation engineer','water supply','water treatment','sewerage','wastewater','boreholes'],
 'Contracts':['quantity surveyor','fidic','contract manager','contracts manager','cost engineer','works contracts','bill of quantities','bills of quantities','boq'],
 'Facilities':['facilities manager','facility manager','common premises','building maintenance','refurbishment','property management'],
 'Architecture':['architect','heritage conservation','restoration','urban planner','housing reconstruction','architectural design']}

def norm(s):return re.sub(r'[^a-z0-9]+',' ',html.unescape(re.sub(r'<[^>]*>',' ',s or '')).lower()).strip()
def has(s,p):return ' '+norm(p)+' ' in ' '+norm(s)+' '
def safe_url(u):
 try:return urllib.parse.urlsplit(u).scheme in ('https','http') and bool(urllib.parse.urlsplit(u).hostname) and not urllib.parse.urlsplit(u).username
 except ValueError:return False

def rank(title,desc):
 t,d=norm(title),norm(desc)
 if any(has(t,x) for x in ['intern','internship','driver','finance officer','communications officer','human resources','software','cloud','data engineer','solutions architect','enterprise architect','digital infrastructure','digital public infrastructure']):return 0,''
 if any(has(t+' '+d,x) for x in ['internal candidates only','internal applicants only']):return 0,''
 if re.search(r'open to (?:tier[s]? )?[012 ,&and]+ applicants',t) and not has(t,'external'):return 0,''
 scores={k:sum(24 if has(t,p) else 8 if has(d,p) else 0 for p in terms) for k,terms in TRACKS.items()}
 track=max(scores,key=scores.get);s=scores[track]
 if s<16:return 0,''
 return s+(10 if any(has(t+' '+d,x) for x in ['sarajevo','bosnia','western balkans']) else 0),track

def canonical(u):
 p=urllib.parse.urlsplit(u);q=urllib.parse.parse_qsl(p.query,keep_blank_values=True)
 q=[(k,v) for k,v in q if not k.lower().startswith('utm_')]
 return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,urllib.parse.urlencode(q),''))

def deadline(text):
 # Only labelled, unambiguous dates. Unknown dates are never guessed.
 m=re.search(r'(?:deadline|closing date|application deadline|apply by)\s*:?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})',text,re.I)
 if not m:return None
 for fmt in ('%Y-%m-%d','%d %B %Y','%d %b %Y','%B %d, %Y','%B %d %Y','%b %d, %Y'):
  try:return dt.datetime.strptime(m[1],fmt).date().isoformat()
  except ValueError:pass
 return None

class Links(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.href=None;self.text=[];self.rows=[];self.feeds=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='a':self.href=a.get('href');self.text=[]
  if tag=='link' and 'alternate' in a.get('rel','') and any(x in a.get('type','') for x in ('rss','atom')):self.feeds.append(a.get('href',''))
 def handle_data(self,s):
  if self.href is not None:self.text.append(s)
 def handle_endtag(self,tag):
  if tag=='a' and self.href is not None:self.rows.append((self.href,' '.join(self.text).strip()));self.href=None

def decode(raw,content_type):
 m=re.search(r'charset=([\w-]+)',content_type,re.I)
 return raw.decode(m[1] if m else 'utf-8',errors='replace').lstrip('\ufeff').strip()

def parse(raw,ctype,base,source):
 text=decode(raw,ctype)
 if not text:raise ValueError('Empty response')
 if re.search(r'captcha|verify you are human|just a moment|access denied',text[:4000],re.I):raise ValueError('Access challenge; not bypassed')
 xml_feed=bool(re.search(r'<(?:rss|feed|rdf:RDF)\b',text[:1000],re.I))
 is_html=not xml_feed and ('text/html' in ctype.lower() or bool(re.search(r'<!doctype\s+html|<html\b',text[:1000],re.I)))
 rows=[];feeds=[];mode='HTML'
 if is_html:
  p=Links();p.feed(text);feeds=[urllib.parse.urljoin(base,u) for u in p.feeds]
  for href,title in p.rows:
   url=urllib.parse.urljoin(base,href)
   if re.search(PATTERNS[source],urllib.parse.urlsplit(url).path,re.I) and len(title)>8:rows.append((title,url,''))
 else:
  mode='XML'
  try:root=ET.fromstring(text)
  except ET.ParseError:
   # Limited repair, not arbitrary recovery: bare ampersands and illegal XML controls.
   repaired=re.sub(r'&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]+;)','&amp;',text)
   repaired=re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f]','',repaired)
   root=ET.fromstring(repaired);mode='XML (limited repair)'
  if root.tag.split('}')[-1].lower() not in ('rss','feed','rdf'):raise ValueError('Response is not a supported feed')
  for item in root.iter():
   if item.tag.split('}')[-1] not in ('item','entry'):continue
   fields={c.tag.split('}')[-1]:c for c in item}
   def val(k):
    e=fields.get(k);return ''.join(e.itertext()).strip() if e is not None else ''
   link=val('link');le=fields.get('link')
   if not link and le is not None:link=le.get('href','')
   rows.append((val('title'),urllib.parse.urljoin(base,link),val('description') or val('summary') or val('content')))
 jobs=[];expired=0
 for title,url,desc in rows:
  if not safe_url(url):continue
  end=deadline(desc)
  if end and end<NOW().date().isoformat():expired+=1;continue
  s,tr=rank(title,desc)
  if s:jobs.append(dict(title=html.unescape(title),url=canonical(url),source=source,score=s,track=tr,deadline=end,last_seen=NOW().isoformat(),retained=False))
 return jobs,dict(format=mode,parsed=len(rows),expired=expired),feeds

def request(url):
 req=urllib.request.Request(url,headers={'User-Agent':'DamirJobRadar/12 public vacancy reader','Accept':'application/rss+xml,application/atom+xml,text/html;q=0.8,*/*;q=0.5'})
 with urllib.request.urlopen(req,timeout=15) as r:
  raw=r.read(3_000_001)
  if len(raw)>3_000_000:raise ValueError('Response too large')
  return raw,r.headers.get('Content-Type',''),r.geturl()

def permitted(url):
 p=urllib.parse.urlsplit(url);robots=urllib.parse.urlunsplit((p.scheme,p.netloc,'/robots.txt','',''))
 try:
  raw,_,_=request(robots);rp=urllib.robotparser.RobotFileParser();rp.parse(raw.decode('utf-8','replace').splitlines())
  if not rp.can_fetch('DamirJobRadar',url):raise PermissionError('robots.txt disallows automated collection')
 except urllib.error.HTTPError as e:
  if e.code!=404:raise

def source_run(pair):
 name,urls=pair;attempts=[]
 for url in urls:
  try:
   permitted(url);raw,ctype,final=request(url);jobs,info,feeds=parse(raw,ctype,final,name)
   if info['format']=='HTML' and not info['parsed']:
    for feed in feeds[:1]:
     if urllib.parse.urlsplit(feed).netloc!=urllib.parse.urlsplit(final).netloc:continue
     permitted(feed);r,c,f=request(feed);jobs,info,_=parse(r,c,f,name)
   if not info['parsed']:raise ValueError('No recognized vacancy records; page may require JavaScript or adapter update')
   return name,jobs,dict(ok=True,message=f"{info['format']}: {info['parsed']} records, {len(jobs)} matches, {info['expired']} expired removed",endpoint=final)
  except Exception as e:attempts.append(f'{url}: {type(e).__name__}: {str(e)[:160]}')
 return name,[],dict(ok=False,message=' | '.join(attempts))

def merge(old,results):
 previous={j['url']:j for j in old.get('jobs',[]) if safe_url(j.get('url',''))};out={};health={}
 for name,jobs,status in results:
  health[name]=status
  if not status['ok']:
   jobs=[]
   for j in previous.values():
    if j['source']!=name:continue
    try:age=NOW()-dt.datetime.fromisoformat(j['last_seen'])
    except (KeyError,ValueError,TypeError):continue
    if age>dt.timedelta(days=7) or (j.get('deadline') and j['deadline']<NOW().date().isoformat()):continue
    jobs.append(dict(j,retained=True))
  for j in jobs:out.setdefault(j['url'],dict(j,new=j['url'] not in previous))
 return dict(updated=NOW().isoformat(),jobs=sorted(out.values(),key=lambda j:(-j['score'],j['title'])),sources=health)

PAGE=r"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Damir Job Radar V12</title><style>body{font:16px system-ui;max-width:1000px;margin:30px auto;padding:16px;background:#eef3f6;color:#123}header{background:#153b50;color:white;padding:24px;border-radius:14px}article,details{background:white;padding:18px;margin:12px 0;border-radius:10px}input,select,button{padding:12px;margin:10px 6px 10px 0}a{color:#075b9b}.warning{background:#fff0bf;padding:16px}</style><header><h1>Damir's Job Radar</h1><p>Construction · Infrastructure · WASH · Contracts · Facilities · Architecture</p></header><p id=status>Waiting for results...</p><input id=q placeholder="Search title or source" aria-label=Search><select id=track aria-label=Track><option value="">All tracks</option></select><button id=refresh>Refresh</button><main id=jobs></main><details open><summary>Source health</summary><ul id=health></ul></details><details><summary>Other ways to find jobs</summary><p>These are manual search links, NOT automatically collected results.</p><ul id=manual></ul></details><p>Priority is a keyword ranking, not an eligibility score. Check deadlines and work rights. Retained jobs are at most seven days old and may have closed. No AI, email or paid API.</p><script>
const data=__DATA__,el=id=>document.getElementById(id);
function render(){el('jobs').replaceChildren();let n=0;for(const j of data.jobs){if(el('track').value&&j.track!==el('track').value)continue;if(![j.title,j.source,j.track].join(' ').toLowerCase().includes(el('q').value.toLowerCase()))continue;let u;try{u=new URL(j.url);if(!['http:','https:'].includes(u.protocol))continue}catch{continue}const a=document.createElement('a'),h=document.createElement('h2'),p=document.createElement('p'),card=document.createElement('article');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=j.title;h.append(a);p.textContent=`${j.source} | ${j.track} | Priority ${j.score} | ${j.retained?'RETAINED, source unavailable':j.new?'NEW':'Seen before'} | Deadline: ${j.deadline||'not verified'}`;card.append(h,p);el('jobs').append(card);n++}if(!n){const p=document.createElement('p');p.className='warning';p.textContent='No matching jobs. Check source health and manual search links. This is not proof that no vacancies exist.';el('jobs').append(p)}}
el('status').textContent=`Updated ${data.updated} | ${data.jobs.length} results | ${Object.values(data.sources).filter(s=>s.ok).length}/${Object.keys(data.sources).length} sources responding`;
for(const [name,s]of Object.entries(data.sources)){const li=document.createElement('li');li.textContent=`${name}: ${s.ok?'OK':'UNAVAILABLE'} - ${s.message}`;el('health').append(li)}
for(const t of [...new Set(data.jobs.map(j=>j.track))].sort())el('track').add(new Option(t,t));
for(const [name,url]of data.manual){const li=document.createElement('li'),a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=name;li.append(a);el('manual').append(li)}
el('q').oninput=render;el('track').onchange=render;el('refresh').onclick=()=>location.reload();render();</script></html>"""
MANUAL=[('UNDP official careers','https://estm.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs'),('UNICEF official alerts','https://jobs.unicef.org/cw/en-us/subscribe/'),('UNOPS','https://careers.unops.org/'),('UN Careers','https://careers.un.org/'),('UNjobs civil engineering','https://unjobs.org/skills/civil-engineer'),('Impactpool engineering','https://www.impactpool.org/search?occupational_groups%5B%5D=Engineering'),('UNJobsFeed','https://unjobsfeed.org/'),('ReliefWeb API approval required','https://apidoc.reliefweb.int/')]

def build_page(data):
 payload=json.dumps(dict(data,manual=MANUAL),ensure_ascii=True).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')
 return PAGE.replace('__DATA__',payload)

def run():
 old={}
 try:
  raw,_,_=request(os.environ.get('PREVIOUS_DATA_URL',''));old=json.loads(raw)
 except Exception:pass
 with cf.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(source_run,SOURCES.items()))
 data=merge(old,results);Path('site').mkdir(exist_ok=True)
 Path('site/index.html').write_text(build_page(data),encoding='utf-8');Path('site/jobs.json').write_text(json.dumps(data),encoding='utf-8')
 summary='# Job Radar V12\n\n'+f"{len(data['jobs'])} matches; {sum(s['ok'] for s in data['sources'].values())}/{len(SOURCES)} sources responding.\n\n"+'\n'.join(f"- {n}: {s['message']}" for n,s in data['sources'].items())
 if os.environ.get('GITHUB_STEP_SUMMARY'):Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(summary,encoding='utf-8')
 print(summary)

class Tests(unittest.TestCase):
 def test_undp_html(self):
  raw=b'<html><a href="/hcmUI/CandidateExperience/en/sites/CX_1/jobs/preview/12345">Civil Engineer</a><a href="/help">Construction Engineer</a></html>'
  jobs,info,_=parse(raw,'text/html','https://estm.fa.em2.oraclecloud.com','UNDP')
  self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['source'],'UNDP')
 def test_undp_js_shell(self):
  self.assertEqual(parse(b'<html><div id="app"></div></html>','text/html','https://estm.fa.em2.oraclecloud.com','UNDP')[1]['parsed'],0)
 def test_undp_tier(self):
  self.assertEqual(rank('Civil Engineer Open to Tier 1 & 2 applicants','')[0],0)
 def test_undp_external(self):
  self.assertGreater(rank('Civil Engineer Open to internal and external applicants','')[0],0)

 def test_xml(self):self.assertEqual(len(parse(b'<rss><item><title>Construction Engineer</title><link>https://x/1</link></item></rss>','application/xml','https://x','UNOPS')[0]),1)
 def test_bare_amp(self):self.assertEqual(len(parse(b'<rss><item><title>Construction Engineer & Supervisor</title><link>https://x/1?a=1&b=2</link></item></rss>','text/xml','https://x','UNOPS')[0]),1)
 def test_control(self):self.assertEqual(len(parse(b'<rss><item><title>Construction\x01 Engineer</title><link>https://x/1</link></item></rss>','text/xml','https://x','UNOPS')[0]),1)
 def test_html(self):self.assertEqual(len(parse(b'<html><a href="/vacancies/123">Civil Engineer</a></html>','text/html','https://unjobs.org','UNjobs')[0]),1)
 def test_html_not_xml(self):self.assertEqual(parse(b'<html><p>JavaScript required</p></html>','text/html','https://x','UN Careers')[1]['parsed'],0)
 def test_challenge(self):
  with self.assertRaises(ValueError):parse(b'<html>Verify you are human</html>','text/html','https://x','UNOPS')
 def test_malformed(self):
  with self.assertRaises(ET.ParseError):parse(b'<rss><item>','text/xml','https://x','UNOPS')
 def test_atom(self):self.assertEqual(len(parse(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Site Engineer</title><link href="https://x/2"/></entry></feed>','text/xml','https://x','UNOPS')[0]),1)
 def test_nav(self):self.assertEqual(parse(b'<html><a href="/about">Construction Engineer</a></html>','text/html','https://unjobs.org','UNjobs')[1]['parsed'],0)
 def test_bad_url(self):self.assertFalse(safe_url('javascript:alert(1)'))
 def test_canonical(self):self.assertEqual(canonical('https://x/a?utm_source=z&id=1#top'),'https://x/a?id=1')
 def test_deadline(self):self.assertEqual(deadline('Deadline: November 12, 2026'),'2026-11-12')
 def test_expired(self):self.assertEqual(parse(b'<rss><item><title>Civil Engineer</title><link>https://x/1</link><description>Deadline: 2001-01-01</description></item></rss>','text/xml','https://x','UNOPS')[0],[])
 def test_internal(self):self.assertEqual(rank('Construction Engineer','For internal candidates only')[0],0)
 def test_international(self):self.assertGreater(rank('International Construction Engineer','')[0],0)
 def test_digital(self):self.assertEqual(rank('Cloud Infrastructure Engineer','construction')[0],0)
 def test_wash_soft(self):self.assertEqual(rank('WASH Programme Officer','hygiene promotion')[0],0)
 def test_title_tracks(self):
  for track,terms in TRACKS.items():
   for t in terms:self.assertGreater(rank(t,'')[0],0,t)
 def test_retention(self):
  j=dict(url='https://x/1',title='Civil Engineer',source='UNOPS',score=24,last_seen=NOW().isoformat())
  self.assertTrue(merge({'jobs':[j]},[('UNOPS',[],{'ok':False})])['jobs'][0]['retained'])
 def test_stale(self):
  j=dict(url='https://x/1',title='Civil Engineer',source='UNOPS',score=24,last_seen=(NOW()-dt.timedelta(days=8)).isoformat())
  self.assertEqual(merge({'jobs':[j]},[('UNOPS',[],{'ok':False})])['jobs'],[])
 def test_dedupe(self):
  j=dict(url='https://x/1',title='Civil Engineer',source='UNOPS',score=24)
  self.assertEqual(len(merge({},[('UNOPS',[j,j],{'ok':True})])['jobs']),1)
 def test_script_escape(self):
  p=build_page({'jobs':[{'title':'</script><script>alert(1)</script>'}],'sources':{}})
  self.assertNotIn('</script><script>alert',p)
 def test_discovery(self):self.assertEqual(parse(b'<html><link rel="alternate" type="application/rss+xml" href="/feed"></html>','text/html','https://x','UNOPS')[2],['https://x/feed'])
 def test_utf8_bom(self):self.assertEqual(decode(b'\xef\xbb\xbf<rss/>','text/xml'),'<rss/>')

if __name__=='__main__':
 if sys.argv[1:]==['test']:unittest.main(argv=[sys.argv[0]])
 else:run()
