"""One case per issue rule: it fires, it stays quiet, and the edge that used to mislead."""

from __future__ import annotations

from google_search_console_mcp.insights import issues
from google_search_console_mcp.insights.thresholds import Thresholds

TH = Thresholds(min_impressions=100, min_clicks=10, high_visibility_impressions=1000)


def page(url, clicks=50, impressions=1000, position=5.0, ctr=None):
    return {
        "page": url,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr if ctr is not None else (clicks / impressions if impressions else 0.0),
        "position": position,
    }


def query(text, clicks=50, impressions=1000, position=5.0, ctr=None):
    return {
        "query": text,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr if ctr is not None else (clicks / impressions if impressions else 0.0),
        "position": position,
    }


# -- paginated_pages ----------------------------------------------------------


def test_page_parameters_and_page_paths_count_as_pagination():
    found = issues.paginated_pages(
        [
            page("https://example.com/shoes?page=2"),
            page("https://example.com/blog/page/3/"),
            page("https://example.com/list?paged=4"),
        ],
        TH,
    )
    assert found is not None
    assert found["params"]["n"] == 3
    assert found["severity"] == "low"


def test_a_wordpress_post_permalink_is_not_pagination():
    # `/?p=123` is WordPress's default permalink for a post, not page 123 of a list.
    assert issues.paginated_pages([page("https://example.com/?p=123")], TH) is None


def test_p_counts_only_when_the_same_path_ranks_without_it():
    rows = [page("https://example.com/catalog"), page("https://example.com/catalog?p=2")]
    found = issues.paginated_pages(rows, TH)
    assert found is not None
    assert found["params"]["n"] == 1


def test_page_one_is_not_reported():
    assert issues.paginated_pages([page("https://example.com/shoes?page=1")], TH) is None


# -- http / hosts -------------------------------------------------------------


def test_http_pages_are_flagged():
    found = issues.http_pages([page("http://example.com/a"), page("https://example.com/b")], TH)
    assert found["params"]["n"] == 1


def test_www_and_bare_host_both_ranking_is_flagged():
    found = issues.mixed_hosts([page("https://www.example.com/a"), page("https://example.com/b")], TH)
    assert found is not None
    assert found["params"]["n"] == 2


def test_one_host_is_fine():
    assert issues.mixed_hosts([page("https://example.com/a"), page("https://example.com/b")], TH) is None


# -- CTR rules share the CTR-gap definition ------------------------------------


def test_low_ctr_queries_use_the_expected_ctr_curve():
    # Position 1 normally earns 27.5%; 5% is under 60% of that.
    found = issues.low_ctr_queries([query("poor", clicks=100, impressions=2000, position=1.0)], TH)
    assert found is not None
    assert found["params"]["lost"] > 0


def test_a_query_at_its_expected_ctr_is_not_low():
    # Position 10 expects 2.2%; 2% is above 60% of it.
    assert issues.low_ctr_queries([query("fine", clicks=40, impressions=2000, position=10.0)], TH) is None


def test_weak_pages_ignore_results_off_the_first_page():
    assert issues.weak_high_visibility_pages([page("https://e.com/a", 1, 5000, 25.0)], TH) is None


def test_weak_pages_flag_a_first_page_result_with_a_poor_ctr():
    found = issues.weak_high_visibility_pages([page("https://e.com/a", 10, 5000, 3.0)], TH)
    assert found is not None


# -- page two -----------------------------------------------------------------


def test_page_two_queries_need_enough_impressions():
    assert issues.page_two_queries([query("thin", 1, 50, 14.0)], TH) is None
    assert issues.page_two_queries([query("real", 1, 500, 14.0)], TH)["params"]["n"] == 1


# -- sitemaps -----------------------------------------------------------------


def test_sitemap_errors_are_high_and_warnings_medium():
    errors = issues.sitemap_problems([{"path": "s.xml", "errors": "2", "warnings": "0"}], TH)
    warnings = issues.sitemap_problems([{"path": "s.xml", "errors": "0", "warnings": "3"}], TH)
    assert errors["severity"] == "high"
    assert warnings["severity"] == "medium"
    assert issues.sitemap_problems([{"path": "s.xml", "errors": "0", "warnings": "0"}], TH) is None


# -- indexing -----------------------------------------------------------------


def test_a_failed_inspection_is_not_an_indexing_problem():
    assert issues.indexing_problems([{"url": "u", "verdict": "ERROR", "coverage_state": "429"}], TH) is None


def test_fail_is_high_and_neutral_alone_is_medium():
    fail = issues.indexing_problems([{"url": "u", "verdict": "FAIL"}], TH)
    neutral = issues.indexing_problems([{"url": "u", "verdict": "NEUTRAL"}], TH)
    assert fail["severity"] == "high"
    assert neutral["severity"] == "medium"
    assert issues.indexing_problems([{"url": "u", "verdict": "PASS"}], TH) is None


# -- traffic drop -------------------------------------------------------------


def test_a_traffic_drop_names_its_baseline():
    found = issues.traffic_drop({"clicks": 80}, {"clicks": 100}, TH, "year")
    assert found["params"]["baseline"] == "year"
    assert found["params"]["pct"] == 20.0


def test_a_small_dip_is_not_a_traffic_drop():
    assert issues.traffic_drop({"clicks": 95}, {"clicks": 100}, TH) is None


def test_detect_issues_uses_the_page_thresholds_for_page_rules():
    page_th = Thresholds(min_impressions=100, min_clicks=10, high_visibility_impressions=100_000)
    data = {"pages": [page("https://e.com/a", 10, 5000, 3.0)], "queries": []}
    keys_default = {i["key"] for i in issues.detect_issues(data, TH)}
    keys_pages = {i["key"] for i in issues.detect_issues(data, TH, page_th)}
    assert "weak_high_visibility_pages" in keys_default
    assert "weak_high_visibility_pages" not in keys_pages
