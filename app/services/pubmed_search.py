"""PubMed search utilities backed by NCBI E-utilities."""

from __future__ import annotations

from json import loads
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_ARTICLE_URL = "https://pubmed.ncbi.nlm.nih.gov"
DEFAULT_TIMEOUT_SECONDS = 10
USER_AGENT = "openbiosignal/0.1"


def _request_json(endpoint: str, params: dict[str, str]) -> dict:
    """Fetch a JSON payload from an E-utilities endpoint."""

    url = f"{EUTILS_BASE_URL}/{endpoint}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("PubMed request failed") from exc


def _request_xml(endpoint: str, params: dict[str, str]) -> ElementTree.Element:
    """Fetch and parse an XML payload from an E-utilities endpoint."""

    url = f"{EUTILS_BASE_URL}/{endpoint}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return ElementTree.fromstring(response.read())
    except (HTTPError, URLError, TimeoutError, ElementTree.ParseError) as exc:
        raise RuntimeError("PubMed XML request failed") from exc


def _search_pubmed_ids(query: str, max_results: int) -> list[str]:
    """Return PubMed IDs for a free-text search query."""

    payload = _request_json(
        "esearch.fcgi",
        {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": str(max_results),
            "sort": "relevance",
        },
    )
    return payload.get("esearchresult", {}).get("idlist", [])


def _fetch_pubmed_summaries(pmids: list[str]) -> list[dict[str, str | None]]:
    """Fetch and normalize PubMed summary metadata for a set of PMIDs."""

    if not pmids:
        return []

    payload = _request_json(
        "esummary.fcgi",
        {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "json",
        },
    )
    result = payload.get("result", {})
    summaries: list[dict[str, str | None]] = []

    for pmid in result.get("uids", []):
        item = result.get(pmid, {})
        author_names = ", ".join(author.get("name", "") for author in item.get("authors", []) if author.get("name"))
        summaries.append(
            {
                "pmid": pmid,
                "title": item.get("title") or "Untitled article",
                "journal": item.get("fulljournalname") or item.get("source"),
                "pubdate": item.get("pubdate") or item.get("sortpubdate"),
                "authors": author_names or None,
                "source_url": f"{PUBMED_ARTICLE_URL}/{pmid}/",
            }
        )

    return summaries


def _normalize_abstract_text(article: ElementTree.Element) -> str | None:
    """Extract and normalize abstract text from a PubMed article element."""

    abstract_nodes = article.findall(".//Abstract/AbstractText")
    parts: list[str] = []

    for node in abstract_nodes:
        text = "".join(node.itertext()).strip()
        if not text:
            continue

        label = (node.attrib.get("Label") or "").strip()
        parts.append(f"{label}: {text}" if label else text)

    if not parts:
        return None

    return "\n\n".join(parts)


def search_pubmed(query: str, max_results: int = 10) -> list[dict[str, str | None]]:
    """Search PubMed and return normalized candidate paper metadata."""

    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    try:
        pmids = _search_pubmed_ids(cleaned_query, max_results=max_results)
        return _fetch_pubmed_summaries(pmids)
    except RuntimeError:
        return []


def fetch_pubmed_abstracts(pmids: list[str]) -> list[dict[str, str | None]]:
    """Fetch PubMed abstracts for a list of PMIDs using EFetch."""

    cleaned_pmids = [pmid.strip() for pmid in pmids if pmid and pmid.strip()]
    if not cleaned_pmids:
        return []

    try:
        root = _request_xml(
            "efetch.fcgi",
            {
                "db": "pubmed",
                "id": ",".join(cleaned_pmids),
                "retmode": "xml",
            },
        )
    except RuntimeError:
        return []

    records: list[dict[str, str | None]] = []
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//MedlineCitation/PMID")
        if not pmid:
            continue

        records.append(
            {
                "pmid": pmid.strip(),
                "abstract": _normalize_abstract_text(article),
            }
        )

    return records
