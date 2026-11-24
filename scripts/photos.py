import json, re, urllib.request, concurrent.futures
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from pathlib import Path

class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.photos=[]; self.scripts=[]; self.in_json=False
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=='meta' and a.get('property','') in ('og:image','og:image:url','og:image:secure_url'):
            self.photos.append(a.get('content',''))
        if tag=='script' and a.get('type')=='application/ld+json':
            self.in_json=True; self.scripts.append('')
    def handle_endtag(self, tag):
        if tag=='script': self.in_json=False
    def handle_data(self, data):
        if self.in_json: self.scripts[-1]+=data

def images(value):
    if isinstance(value,str): yield value
    elif isinstance(value,list):
        for item in value: yield from images(item)
    elif isinstance(value,dict):
        for k in ('url','contentUrl'):
            if k in value: yield from images(value[k])

def listing_images(obj):
    if isinstance(obj,list):
        for item in obj: yield from listing_images(item)
    elif isinstance(obj,dict):
        types=obj.get('@type',[])
        if isinstance(types,str): types=[types]
        if any(t in ('RealEstateListing','Apartment','House','Residence','SingleFamilyResidence','Product','Accommodation','Offer') for t in types):
            yield from images(obj.get('image',[]))
        for key in ('@graph','mainEntity','itemOffered','offers','about'):
            if key in obj: yield from listing_images(obj[key])

def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'CasaValdarno/1.0 (listing metadata)','Accept':'text/html'})
    with urllib.request.urlopen(req,timeout=15) as res:
        if urlparse(res.geturl()).path.rstrip('/') != urlparse(url).path.rstrip('/'):
            return []
        parser=Metadata(); parser.feed(res.read(6000000).decode('utf-8','replace'))
    photos=parser.photos
    for script in parser.scripts:
        try: photos.extend(listing_images(json.loads(script)))
        except (ValueError,TypeError): pass
    result=[]
    for p in photos:
        if not isinstance(p,str): continue
        p=urljoin(url,p)
        if urlparse(p).scheme!='https' or re.search(r'logo|placeholder|default.image|favicon|social.share',p,re.I): continue
        if p not in result: result.append(p)
    return result

def enrich(h):
    found=[]
    for url in [h['url'],*h.get('links',[])]:
        try:
            for p in fetch(url):
                if p not in found: found.append(p)
        except Exception as e: print(url, type(e).__name__)
    if found:
        h['photos']=list(dict.fromkeys(found+h.get('photos',[])))[:30]
        h['photo_status']='retrieved'
    else: h['photo_status']='retained' if h.get('photos') else 'unavailable'
    print(h['title'],len(h.get('photos',[])),h['photo_status'])
    return h

path=Path('affitti.json')
data=json.loads(path.read_text())
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    data['homes']=list(pool.map(enrich,data['homes']))
path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
