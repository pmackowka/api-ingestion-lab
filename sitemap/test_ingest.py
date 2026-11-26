from sitemap.ingest import parse_article, parse_index, parse_urlset, section

INDEX = """<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://pmdata.pl/sitemap-0.xml</loc><lastmod>2026-11-25T00:00:00.000Z</lastmod></sitemap></sitemapindex>"""

URLSET = """<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://pmdata.pl/</loc></url>
<url><loc>https://pmdata.pl/artykuly/dbt/</loc><lastmod>2026-11-22T00:00:00.000Z</lastmod></url></urlset>"""


def _page(*blocks: str) -> str:
    return "<html><head>" + "".join(f'<script type="application/ld+json">{b}</script>' for b in blocks) + "</head></html>"


def test_parse_index_reads_sitemap_locations_with_namespace():
    assert parse_index(INDEX) == ["https://pmdata.pl/sitemap-0.xml"]


def test_parse_urlset_keeps_missing_lastmod_as_none():
    assert parse_urlset(URLSET) == [
        {"url": "https://pmdata.pl/", "lastmod": None},
        {"url": "https://pmdata.pl/artykuly/dbt/", "lastmod": "2026-11-22T00:00:00.000Z"},
    ]


def test_parse_article_takes_dates_from_article_block_only():
    html = _page('{"@type": "BreadcrumbList"}',
                 '{"@type": "BlogPosting", "headline": "dbt", "datePublished": "2026-11-01", "dateModified": "2026-11-22"}')

    assert parse_article(html) == {"headline": "dbt", "date_published": "2026-11-01", "date_modified": "2026-11-22"}
    assert parse_article(_page('{"@type": "BreadcrumbList"}'))["date_published"] is None


def test_section_is_first_path_segment_or_none_for_home():
    assert section("https://pmdata.pl/artykuly/tag/dbt/") == "artykuly"
    assert section("https://pmdata.pl/") is None
