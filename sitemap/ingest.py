"""Sitemapa pmdata.pl + daty publikacji z JSON-LD stron -> BigQuery (pełna migawka)."""

import argparse
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

from google.cloud import bigquery

from common import cli
from common.bigquery import replace_table

INDEX_URL = "https://pmdata.pl/sitemap-index.xml"
USER_AGENT = "api-ingestion-lab"
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
JSON_LD = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
ARTICLE_TYPES = {"BlogPosting", "Article"}

TARGET_TABLE = "pages"

SCHEMA = [
    bigquery.SchemaField("url", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("section", "STRING"),
    bigquery.SchemaField("lastmod", "TIMESTAMP"),
    bigquery.SchemaField("headline", "STRING"),
    bigquery.SchemaField("date_published", "TIMESTAMP"),
    bigquery.SchemaField("date_modified", "TIMESTAMP"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def fetch(url: str) -> str:
    """Treść strony jednym GET-em."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def parse_index(xml: str) -> list[str]:
    """Indeks sitemap -> adresy sitemap."""
    return [loc.text for loc in ET.fromstring(xml).findall("sm:sitemap/sm:loc", NS)]


def parse_urlset(xml: str) -> list[dict]:
    """Sitemapa -> [{url, lastmod}]; lastmod bywa pominięty (np. strona główna)."""
    return [
        {"url": url.findtext("sm:loc", namespaces=NS), "lastmod": url.findtext("sm:lastmod", namespaces=NS)}
        for url in ET.fromstring(xml).findall("sm:url", NS)
    ]


def parse_article(html: str) -> dict:
    """Tytuł i daty z JSON-LD typu artykuł; strona bez artykułu -> puste pola."""
    for block in JSON_LD.findall(html):
        data = json.loads(block)
        if data.get("@type") in ARTICLE_TYPES:
            return {
                "headline": data.get("headline"),
                "date_published": data.get("datePublished"),
                "date_modified": data.get("dateModified"),
            }
    return {"headline": None, "date_published": None, "date_modified": None}


def section(url: str) -> str | None:
    """Pierwszy segment ścieżki (np. `artykuly`); strona główna -> None."""
    return urlparse(url).path.strip("/").split("/")[0] or None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Wspólny interfejs CLI (common/cli.py); zakres dat ignorowany — pełna migawka."""
    return cli.parse(cli.make_parser("Sitemapa pmdata.pl -> BigQuery", default_dataset="raw_sitemap"), argv)


def main() -> None:
    args = parse_args()
    loaded_at = datetime.now(timezone.utc)

    entries = [entry for sitemap_url in parse_index(fetch(INDEX_URL)) for entry in parse_urlset(fetch(sitemap_url))]
    rows = [
        {**entry, "section": section(entry["url"]), **parse_article(fetch(entry["url"])), "loaded_at": loaded_at.isoformat()}
        for entry in entries
    ]

    replace_table(rows, project=args.project, dataset=args.dataset, table=TARGET_TABLE, schema=SCHEMA)
    articles = sum(1 for row in rows if row["date_published"])
    print(f"{TARGET_TABLE}: {len(rows)} adresów, {articles} z datą publikacji (pełna migawka)")


if __name__ == "__main__":
    main()
