"""Version-bound DDG adapter with an independent public RSS search fallback."""
import xml.etree.ElementTree as ET
import httpx
from duckduckgo_search import DDGS
from core.metrics import measure


class VivSearch(DDGS):
    # Verified with duckduckgo-search 7.2.1 + primp 2.0.1.
    _impersonates = ('chrome_146',)


def _rss_search(query, limit):
    # Independent provider when DDG is unavailable/rate-limited; never bypass challenges.
    with httpx.Client(timeout=10, verify=True, follow_redirects=True) as client:
        response = client.get('https://www.bing.com/search',
                              params={'q': query, 'format': 'rss'})
        response.raise_for_status()
        if len(response.content) > 1_000_000:
            raise ValueError('Search response exceeds size limit')
        root = ET.fromstring(response.content)
    hits = []
    for item in root.findall('./channel/item'):
        url = item.findtext('link', '')
        title = item.findtext('title', '')
        if title and url.startswith(('https://', 'http://')):
            hits.append({'title': title, 'href': url,
                         'body': item.findtext('description', ''), 'provider': 'bing-rss'})
    return hits[:limit]


def search(query, max_results=4):
    if not query.strip():
        return []
    with measure('search_ms'):
        try:
            with VivSearch(timeout=10, verify=True) as client:
                hits = list(client.text(query, region='br-pt', backend='html', max_results=max_results))
                if hits:
                    return [dict(hit, provider='duckduckgo') for hit in hits]
        except Exception:
            pass
        try:
            return _rss_search(query, max_results)
        except Exception:
            raise RuntimeError('Pesquisa indisponível nos provedores públicos. Tente novamente mais tarde.') from None
