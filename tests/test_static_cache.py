"""The page and its files must be revalidated, or a browser keeps showing an old design after a deploy."""
import pytest

PATHS = ["/", "/static/styles.css", "/static/app.js", "/static/pattern-mobile.svg"]


@pytest.mark.parametrize("path", PATHS)
def test_page_and_static_files_ask_the_browser_to_revalidate(client, path):
    r = client.get(path)

    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers.get("etag")  # so the check below costs a 304, not a download


@pytest.mark.parametrize("path", PATHS[1:])  # the page itself is 2 KB and is simply sent again
def test_an_unchanged_static_file_answers_304(client, path):
    etag = client.get(path).headers["etag"]

    again = client.get(path, headers={"If-None-Match": etag})

    assert again.status_code == 304
