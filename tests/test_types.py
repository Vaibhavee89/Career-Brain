from careerbrain.core.types import page_links, page_slug, page_url


def test_page_slug_flattens_path() -> None:
    assert (
        page_slug("profile/resume-variants/eng.md") == "profile--resume-variants--eng"
    )


def test_page_url_joins_base_and_slug_regardless_of_trailing_slash() -> None:
    expected = "https://example.com/pages/projects--etl.html"
    assert page_url("https://example.com", "projects/etl.md") == expected
    assert page_url("https://example.com/", "projects/etl.md") == expected


def test_page_links_extracts_urls_from_raw_frontmatter_value() -> None:
    assert page_links(
        {"links": "[https://github.com/me/etl, https://demo.example]"}
    ) == [
        "https://github.com/me/etl",
        "https://demo.example",
    ]


def test_page_links_empty_when_no_links_field_or_empty_list() -> None:
    assert page_links({}) == []
    assert page_links({"links": "[]"}) == []
