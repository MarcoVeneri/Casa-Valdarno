"""Check each catalog URL before it can appear in the app."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


class DetailPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.canonical = None
        self.ignored = 0
        self.heading = False
        self.headings = []
        self.words = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self.ignored += 1
        if tag == 'h1':
            self.heading = True
        if tag == 'link' and 'canonical' in attrs.get('rel', '').lower().split():
            self.canonical = attrs.get('href')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.ignored = max(0, self.ignored - 1)
        if tag == 'h1':
            self.heading = False

    def handle_data(self, value):
        if not self.ignored and value.strip():
            self.words.append(value.strip())
            if self.heading:
                self.headings.append(value.strip())


def identity(url):
    parts = urlsplit(url)
    return parts.hostname, parts.path.rstrip('/')


def check(item):
    url, rent = item
    request = Request(url, headers={'User-Agent': 'Casa-Valdarno/1.0 (listing availability check)'})
    try:
        with urlopen(request, timeout=20) as response:
            if identity(response.url) != identity(url):
                return url, 'redirect'
            page = DetailPage()
            page.feed(response.read(4000000).decode('utf-8', errors='replace'))
        if page.canonical and identity(urljoin(url, page.canonical)) != identity(url):
            return url, 'redirect'
        visible = ' '.join(' '.join(page.words).lower().split())
        if re.search(r'(?:questo|quest[’\x27])\s*(?:immobile|annuncio) non (?:è|e\x27) più disponibile|annuncio (?:è stato |è )?(?:ritirato|disattivato|scaduto)', visible):
            return url, 'withdrawn'
        price = rf'(?:€\s*{rent}\b|\b{rent}\s*(?:€|euro))'
        if page.headings and page.canonical and re.search(price, visible):
            return url, 'detail'
        return url, 'unverified'
    except HTTPError as exc:
        return url, 'withdrawn' if exc.code in (404, 410) else 'unverified'
    except (OSError, ValueError):
        return url, 'unverified'


if __name__ == '__main__':
    homes = json.loads(Path('affitti.json').read_text())['homes']
    urls = {url: h['rent'] for h in homes for url in [h['url'], *h.get('links', [])]}
    with ThreadPoolExecutor(max_workers=3) as pool:
        status = dict(pool.map(check, urls.items()))
    result = {'date': datetime.now(timezone.utc).date().isoformat(), 'urls': status}
    path = Path('verifiche.json')
    previous = json.loads(path.read_text()) if path.exists() else {}
    confirmed = previous.get('lastConfirmed', {})
    result['lastConfirmed'] = {}
    for url, state in status.items():
        if state == 'detail':
            result['lastConfirmed'][url] = result['date']
        elif state == 'unverified' and url in confirmed:
            result['lastConfirmed'][url] = confirmed[url]
    path.write_text(json.dumps(result, indent=2) + '\n')
