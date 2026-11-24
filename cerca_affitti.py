"""Find residential rentals in Figline e Incisa Valdarno."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from lxml import html

PLACE = 'Figline e Incisa Valdarno'
START = 'https://www.idealista.it/affitto-case/figline-e-incisa-valdarno-firenze/?ordine=prezzi-asc'


def page(url):
    request = Request(url, headers={'User-Agent': 'Casa-Valdarno/1.0'})
    with urlopen(request, timeout=20) as response:
        if response.url.split('?')[0].rstrip('/') != url.split('?')[0].rstrip('/'):
            raise ValueError('Pagina reindirizzata')
        return html.fromstring(response.read(), base_url=url)


def field(doc, css_class):
    nodes = doc.xpath('//*[contains(concat(" ", normalize-space(@class), " "), $name)]',
                      name=' ' + css_class + ' ')
    return ' '.join(nodes[0].text_content().split()) if nodes else ''


def details(url):
    doc = page(url)
    if doc.xpath('string(//link[@rel="canonical"]/@href)').rstrip('/') != url.rstrip('/'):
        return None
    title = field(doc, 'main-info__title-main')
    location = field(doc, 'main-info__title-minor')
    description = field(doc, 'comment')
    facts = ' '.join(doc.xpath('//*[@id="details"]//text()'))
    if PLACE.lower() not in location.lower() or 'affitto' not in title.lower():
        return None
    if re.search(r'transitori|no residenza|non (?:è|vi è) (?:possibile|contratto)|contratti brevi|affitto a riscatto|solo per i mesi|non vi è contratto|non è possibile prender[vV]i residenza|esclusivamente.{0,20}riscatto|non.{0,18}residenza|solo contratto.{0,15}turistic', description, re.I):
        return None
    parking = re.search(r'box (?:singolo |doppio )?compreso nel prezzo', facts, re.I)
    has_garage = bool(parking) or bool(re.search(r'(?:ampio|comodo|proprio) garage|garage (?:privato|esclusivo|al piano)', description, re.I))
    rent = re.search(r'([\d.]+)\s*€\s*/\s*mese', field(doc, 'info-data-price'))
    area = re.search(r'(\d+)\s*m²', facts)
    if not rent or not area:
        return None
    return dict(title=title, zone=location.split(',')[0], municipality=PLACE,
                garage=has_garage, parking=parking.group().capitalize() if parking else ('Garage indicato nella descrizione' if has_garage else ('Posto auto indicato' if 'posto auto' in description.lower() else 'Garage non indicato')),
                rent=int(rent[1].replace('.', '')), area=int(area[1]), url=url,
                contract='Durata da chiarire', note='', privateOwner=True if 'Privato' in doc.xpath('//text()[normalize-space()="Privato"]') else (False if field(doc,'advertiser-name') else None))


def discover(catalog):
    url = START
    visited = set()
    links = set()
    while url and url not in visited:
        visited.add(url)
        doc = page(url)
        paths = doc.xpath('//article//a/@href')
        found = {urljoin(START,p) for p in paths if re.fullmatch(r'/immobile/\d+/',p)}
        if not found and not doc.xpath('//*[contains(@class,"no-results")]'):
            raise ValueError('Elenco non leggibile')
        links.update(found)
        next_page = doc.xpath('//a[@rel="next"]/@href | //li[contains(@class,"next")]/a/@href')
        url = urljoin(START,next_page[0]) if next_page else None
        if url and (urlsplit(url).hostname != urlsplit(START).hostname or '/affitto-case/figline-e-incisa-valdarno-firenze/' not in url):
            raise ValueError('Paginazione inattesa')
    known = {link: home for home in catalog['homes'] for link in [home['url'],*home.get('links',[])]}
    added = failed = 0
    def inspect(url):
        try:
            return url, details(url), False
        except (OSError, ValueError):
            return url, None, True

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(inspect, sorted(links)))
    for url, home, error in results:
        failed += int(error)
        if not home:
            continue
        if url in known:
            known[url].update({key:home[key] for key in ('rent','municipality')})
            if home['garage']:
                known[url].update(garage=True, parking=home['parking'])
        else:
            def street(title):
                match = re.search(r'\b(?:via|piazza|corso|viale)\s+[^,]+', title.lower())
                return match[0].strip() if match else None
            address = street(home['title'])
            duplicate = next((h for h in catalog['homes'] if address and street(h['title']) == address
                              and h.get('municipality') == PLACE and h['area'] == home['area']
                              and h['rent'] == home['rent']), None)
            if duplicate:
                duplicate.setdefault('links', []).append(url)
                continue
            catalog['homes'].append(home)
            added += 1
    return f'{len(links)} schede individuate, {added} nuove, {failed} non leggibili.'


if __name__ == '__main__':
    path = Path('affitti.json')
    catalog = json.loads(path.read_text())
    try:
        report = discover(catalog)
    except (OSError, ValueError) as exc:
        report = f'Ricerca non completata ({type(exc).__name__}).'
    catalog['sources']['idealista · ricerca nel comune'] = report
    print(report)
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False)+'\n')
