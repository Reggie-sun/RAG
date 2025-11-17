
import re, json, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
reqs=[]
for line in open('rag-system/backend/requirements.txt'):
    line=line.strip()
    if not line or line.startswith('#'): continue
    m=re.match(r'([A-Za-z0-9_.-]+)==([^#\\s]+)', line)
    if not m: continue
    name,ver=m.groups()
    norm=re.sub(r'[-_.]+','-',name).lower()
    url=f'https://pypi.org/pypi/{norm}/{ver}/json'
    reqs.append((name,ver,url))
def fetch(name,ver,url):
    try:
        with urllib.request.urlopen(url,timeout=10) as resp:
            data=json.load(resp)
        return name,ver,data['info'].get('requires_python','')
    except urllib.error.HTTPError as e:
        return name,ver,f'HTTP {e.code}'
    except Exception as e:
        return name,ver,f'ERROR: {e}'
with ThreadPoolExecutor(max_workers=12) as ex:
    rows=[f.result() for f in as_completed([ex.submit(fetch,*r) for r in reqs])]
for name,ver,rp in sorted(rows):
    print(f'{name}=={ver} -> {rp}')

