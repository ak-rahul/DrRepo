import pytest

from drrepo.core.github_url import RepoRef, parse_github_url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/octo/demo",
        "https://github.com/octo/demo/",
        "https://github.com/octo/demo.git",
        "https://github.com/octo/demo/tree/main/src",
        "http://www.github.com/octo/demo",
        "github.com/octo/demo",
        "  https://github.com/octo/demo  ",
    ],
)
def test_accepts_common_forms(url):
    assert parse_github_url(url) == RepoRef("octo", "demo")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://gitlab.com/octo/demo",
        "https://github.com/octo",
        "ftp://github.com/octo/demo",
        "https://user:pass@github.com/octo/demo",
        "https://github.com/-bad/demo",
        "https://github.com/octo/..",
        "https://github.com.evil.com/octo/demo",
    ],
)
def test_rejects_invalid(url):
    with pytest.raises(ValueError):
        parse_github_url(url)


def test_derived_urls():
    ref = RepoRef("octo", "demo")
    assert ref.full_name == "octo/demo"
    assert ref.html_url == "https://github.com/octo/demo"
    assert ref.clone_url == "https://github.com/octo/demo.git"
