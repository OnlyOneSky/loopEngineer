"""The deterministic gate for the landing-page spec. These files are READ-ONLY
to the actor (they live under tests/). They parse the built page from disk with
the stdlib only — no server, no browser, no third-party deps."""
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "index.html"
STYLES = REPO / "styles.css"


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[str] = []
        self.attrs: dict[str, list[dict]] = {}
        self._stack: list[str] = []
        self.text_by_tag: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.setdefault(tag, []).append(dict(attrs))
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data):
        for tag in self._stack:
            self.text_by_tag[tag] = self.text_by_tag.get(tag, "") + data


def _parse() -> _Collector:
    c = _Collector()
    c.feed(INDEX.read_text(encoding="utf-8"))
    return c


def test_index_exists_with_title():
    assert INDEX.exists()
    c = _parse()
    assert "title" in c.tags
    assert c.text_by_tag.get("title", "").strip()  # non-empty title text


def test_stylesheet_linked():
    c = _parse()
    links = c.attrs.get("link", [])
    assert any(l.get("rel") == "stylesheet" and l.get("href") == "styles.css"
               for l in links), "expected <link rel=stylesheet href=styles.css>"


def test_nav_has_home_about_contact():
    c = _parse()
    assert "nav" in c.tags, "expected a <nav>"
    nav_text = c.text_by_tag.get("nav", "").lower()
    for label in ("home", "about", "contact"):
        assert label in nav_text, f"nav is missing a '{label}' link"


def test_single_h1_hero():
    c = _parse()
    assert c.tags.count("h1") == 1, "expected exactly one <h1> hero heading"


def test_all_images_have_alt():
    c = _parse()
    for img in c.attrs.get("img", []):
        assert img.get("alt", "").strip(), "every <img> needs a non-empty alt"


def test_footer_has_copyright():
    c = _parse()
    assert "footer" in c.tags, "expected a <footer>"
    footer = c.text_by_tag.get("footer", "").lower()
    assert "©" in footer or "copyright" in footer, "footer needs a copyright notice"


def test_styles_present_and_nonempty():
    assert STYLES.exists()
    assert STYLES.read_text(encoding="utf-8").strip(), "styles.css must not be empty"
