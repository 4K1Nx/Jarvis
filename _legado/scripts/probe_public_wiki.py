"""Public encyclopedia lookup; no credentials or personal query."""
import httpx,json
r=httpx.get('https://en.wikipedia.org/w/api.php',params={'action':'query','list':'search','srsearch':'Transformers Prime first Prima','format':'json','srlimit':5},headers={'User-Agent':'VivResearch/1.2 (public search test)'},timeout=15)
print('HTTP',r.status_code)
if r.status_code==200:
 for h in r.json().get('query',{}).get('search',[]):print(json.dumps({'title':h['title'],'snippet':h['snippet']},ensure_ascii=True))
