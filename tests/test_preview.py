from __future__ import annotations

import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from src import db
from src.scraping import preview

VACANCY = "Senior ML Engineer, remote, отклик @hr_bob"
NOISE = "Всем привет, как дела?"


# --- fixtures mirroring the real t.me/s/ markup -----------------------------

def post_html(
    channel: str,
    mid: int,
    *,
    text: str | None = VACANCY,
    age_days: float = 1.0,
    author: str | None = None,
    link_preview: bool = False,
    forwarded: str | None = None,
    service: bool = False,
) -> str:
    posted = datetime.now(timezone.utc) - timedelta(days=age_days)
    classes = "tgme_widget_message text_not_supported_wrap"
    if service:
        classes += " service_message"
    body = ""
    if text is not None:
        body = (
            '<div class="tgme_widget_message_text js-message_text" dir="auto">'
            + text.replace("\n", "<br/>")
            + "</div>"
        )
    return f"""
<div class="tgme_widget_message_wrap js-widget_message_wrap">
  <div class="{classes} js-widget_message" data-post="{channel}/{mid}">
    <div class="tgme_widget_message_user"><a href="https://t.me/{channel}"></a></div>
    <div class="tgme_widget_message_bubble">
      <div class="tgme_widget_message_author accent_color">
        <a class="tgme_widget_message_owner_name" href="https://t.me/{channel}">
          <span dir="auto">Some Channel</span></a>
        {f'<span class="tgme_widget_message_from_author">{author}</span>' if author else ''}
      </div>
      {f'<div class="tgme_widget_message_forwarded_from accent_color">'
       f'<a class="tgme_widget_message_forwarded_from_name">{forwarded}</a></div>'
       if forwarded else ''}
      {body}
      {'''<a class="tgme_widget_message_link_preview" href="https://news.example/x">
        <div class="link_preview_site_name">FinTech Global</div>
        <div class="link_preview_title">Nevis bags $35m to build AI for wealth management</div>
        <div class="link_preview_description">A remote ML Engineer platform for advisors</div>
      </a>''' if link_preview else ''}
      <div class="tgme_widget_message_footer compact js-message_footer">
        <div class="tgme_widget_message_info short js-message_info">
          <span class="tgme_widget_message_views">5.08K</span>
          <span class="tgme_widget_message_meta">
            <a class="tgme_widget_message_date" href="https://t.me/{channel}/{mid}">
              <time datetime="{posted.isoformat()}" class="time">15:00</time></a>
          </span>
        </div>
      </div>
      <div class="tgme_widget_message_reactions js-message_reactions">
        <span class="tgme_reaction"><i class="emoji"><b>🔥</b></i>4</span>
      </div>
    </div>
  </div>
</div>"""


def page_html(*posts: str) -> str:
    return (
        '<html><body><main class="tgme_main">'
        '<section class="tgme_channel_history js-message_history">'
        + "".join(posts)
        + "</section></main></body></html>"
    )


def parse_one(html: str) -> preview.Post:
    parser = preview._PageParser("somechan")
    parser.feed(html)
    parser.close()
    assert len(parser.posts) == 1
    return parser.posts[0]


# --- parsing ---------------------------------------------------------------

def test_parses_id_date_and_text():
    post = parse_one(page_html(post_html("somechan", 42, text="Hello", age_days=2)))

    assert post.id == 42
    assert post.text == "Hello"
    assert post.url == "https://t.me/somechan/42"
    assert post.date is not None and post.date.tzinfo is not None
    assert 1.9 < (datetime.now(timezone.utc) - post.date).days + 1 < 3.1


def test_keeps_emoji_entities_and_line_breaks():
    body = (
        '<b>Senior ML Engineer</b><br/><br/>'
        '<i class="emoji" style="background-image:url(x)"><b>📍</b></i>Cyprus &amp; Remote<br/>'
        '<a href="https://apply.example/1" target="_blank">Apply here</a>'
    )
    post = parse_one(page_html(post_html("somechan", 7, text=None).replace(
        '<div class="tgme_widget_message_bubble">',
        '<div class="tgme_widget_message_bubble">'
        '<div class="tgme_widget_message_text js-message_text">' + body + "</div>",
    )))

    assert post.text == "Senior ML Engineer\n\n📍Cyprus & Remote\nApply here"


def test_link_preview_card_never_reaches_the_body():
    post = parse_one(page_html(
        post_html("somechan", 9, text="Senior ML Engineer, remote", link_preview=True)
    ))

    assert post.text == "Senior ML Engineer, remote"
    for leak in ("FinTech Global", "Nevis bags", "advisors"):
        assert leak not in post.text


def test_surrounding_chrome_is_not_body_text():
    post = parse_one(page_html(
        post_html("somechan", 11, text="ML Engineer", author="Jane", forwarded="Other Chan")
    ))

    assert post.text == "ML Engineer"
    assert post.author == "Jane"
    assert "5.08K" not in post.text and "Other Chan" not in post.text


def test_posts_without_text_survive_parsing():
    parser = preview._PageParser("somechan")
    parser.feed(page_html(
        post_html("somechan", 1, text=None),
        post_html("somechan", 2, text=None, service=True),
        post_html("somechan", 3, text="ML Engineer"),
    ))
    parser.close()

    assert [p.id for p in parser.posts] == [1, 2, 3]
    assert [bool(p.text) for p in parser.posts] == [False, False, True]


def test_signed_author_is_absent_by_default():
    assert parse_one(page_html(post_html("somechan", 4))).author is None


# --- fetching --------------------------------------------------------------

class FakeResponse:
    def __init__(self, body: str, url: str):
        self._body, self._url = body, url

    def read(self):
        return self._body.encode("utf-8")

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_page_rejects_a_channel_without_a_preview(monkeypatch):
    monkeypatch.setattr(
        preview.urllib.request, "urlopen",
        lambda *a, **kw: FakeResponse("<html/>", "https://t.me/cyprusithr"),
    )

    with pytest.raises(preview.PreviewUnavailable):
        preview.fetch_page("cyprusithr")


def test_fetch_page_maps_a_404_to_preview_unavailable(monkeypatch):
    def raise_404(*a, **kw):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    monkeypatch.setattr(preview.urllib.request, "urlopen", raise_404)

    with pytest.raises(preview.PreviewUnavailable):
        preview.fetch_page("gone")


def test_fetch_page_retries_then_gives_up(monkeypatch):
    calls = []

    def flaky(*a, **kw):
        calls.append(1)
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(preview.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(preview.time, "sleep", lambda s: None)

    with pytest.raises(ConnectionError):
        preview.fetch_page("somechan")
    assert len(calls) == preview.MAX_RETRIES


def test_fetch_page_asks_for_the_right_url(monkeypatch):
    seen = {}

    def capture(request, timeout=None):
        seen["url"] = request.full_url
        return FakeResponse("<html/>", request.full_url)

    monkeypatch.setattr(preview.urllib.request, "urlopen", capture)

    preview.fetch_page("somechan", before=500)
    assert seen["url"] == "https://t.me/s/somechan?before=500"


# --- pagination ------------------------------------------------------------

def paged_fetch(pages: dict[int | None, str], log: list | None = None):
    def fetch(channel, before=None):
        if log is not None:
            log.append(before)
        return pages.get(before, page_html())

    return fetch


def test_iter_posts_walks_backwards_until_the_watermark():
    pages = {
        None: page_html(*[post_html("c", i, age_days=1) for i in (30, 31, 32)]),
        30: page_html(*[post_html("c", i, age_days=2) for i in (27, 28, 29)]),
    }
    log: list = []

    got = list(preview.iter_posts(
        "c", min_id=28, fetch=paged_fetch(pages, log), sleep=lambda s: None
    ))

    assert [p.id for p in got] == [32, 31, 30, 29]
    assert log == [None, 30]


def test_iter_posts_stops_at_the_cutoff():
    pages = {
        None: page_html(
            post_html("c", 9, age_days=1),
            post_html("c", 8, age_days=40),
        )
    }
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    got = list(preview.iter_posts(
        "c", cutoff=cutoff, fetch=paged_fetch(pages), sleep=lambda s: None
    ))

    assert [p.id for p in got] == [9]


def test_iter_posts_stops_when_a_page_repeats_itself():
    same = page_html(post_html("c", 5), post_html("c", 4))
    calls: list = []

    got = list(preview.iter_posts(
        "c", fetch=paged_fetch({None: same, 4: same}, calls), sleep=lambda s: None
    ))

    assert [p.id for p in got] == [5, 4]
    assert calls == [None, 4]


def test_iter_posts_reports_the_page_cap(capsys):
    def endless(channel, before=None):
        top = (before or 10_000) - 1
        return page_html(*[post_html("c", top - i) for i in range(3)])

    got = list(preview.iter_posts(
        "c", max_pages=2, fetch=endless, sleep=lambda s: None
    ))

    assert len(got) == 6
    assert "2-page cap" in capsys.readouterr().out


# --- a full cycle ----------------------------------------------------------

def run_scrape(pages, channels=("somechan",), **kwargs):
    kwargs.setdefault("verbose", False)
    fetch = paged_fetch(pages) if isinstance(pages, dict) else pages
    original = preview.iter_posts

    def patched(channel, **kw):
        kw["fetch"] = fetch
        kw["sleep"] = lambda s: None
        return original(channel, **kw)

    preview.iter_posts, saved = patched, preview.iter_posts
    try:
        return preview.scrape(channels=list(channels), **kwargs)
    finally:
        preview.iter_posts = saved


def test_a_cycle_stores_vacancies_and_advances_the_watermark(db_path):
    pages = {None: page_html(
        post_html("somechan", 10, text=VACANCY, age_days=1),
        post_html("somechan", 11, text=NOISE, age_days=0.5),
        post_html("somechan", 12, text=VACANCY, age_days=0.1),
    )}

    counts = run_scrape(pages)

    assert counts["matched"] == 2
    assert counts["channels"] == 1
    with db.connect() as conn:
        assert len(db.query(conn)) == 2
        assert db.get_watermark(conn, "somechan") == 12
        assert db.stats(conn)["last_scraped"] is not None


def test_a_second_cycle_only_reads_what_is_new(db_path):
    first = {None: page_html(post_html("somechan", 10, text=VACANCY))}
    run_scrape(first)

    seen: list = []
    second = {None: page_html(
        post_html("somechan", 10, text=VACANCY),
        post_html("somechan", 11, text=VACANCY),
    )}
    run_scrape(paged_fetch(second, seen))

    assert seen == [None]
    with db.connect() as conn:
        assert db.get_watermark(conn, "somechan") == 11
        assert len(db.query(conn)) == 2


def test_full_cycle_ignores_the_watermark(db_path):
    pages = {None: page_html(post_html("somechan", 10, text=VACANCY))}
    run_scrape(pages)

    with db.connect() as conn:
        conn.execute("DELETE FROM vacancies")
        conn.commit()

    run_scrape(pages, full=True)
    with db.connect() as conn:
        assert len(db.query(conn)) == 1


def test_the_channel_handle_is_the_contact_of_last_resort(db_path):
    pages = {None: page_html(
        post_html("somechan", 1, text="Senior ML Engineer, Москва, офис"),
    )}

    run_scrape(pages)
    with db.connect() as conn:
        assert db.query(conn)[0]["contact"] == "@somechan"


def test_a_signed_author_wins_over_the_channel_handle(db_path):
    pages = {None: page_html(
        post_html("somechan", 1, text="Senior ML Engineer, Москва, офис", author="Jane Doe"),
    )}

    run_scrape(pages)
    with db.connect() as conn:
        assert db.query(conn)[0]["contact"] == "Jane Doe"


def test_promo_posts_are_counted_and_skipped(db_path):
    pages = {None: page_html(
        post_html("somechan", 1, text="Открытый урок для ML инженеров, erid=2Vfn"),
    )}

    counts = run_scrape(pages)
    assert counts["promo_skipped"] == 1
    assert counts["matched"] == 0


def test_a_cycle_prunes_expired_rows(db_path):
    from conftest import add_row

    with db.connect() as conn:
        add_row(conn, channel="somechan", message_id=999, age_days=40, title="expired")

    counts = run_scrape({None: page_html(post_html("somechan", 1, text=VACANCY))})

    assert counts["pruned"] == 1
    with db.connect() as conn:
        rows = db.query(conn, days=None)
        assert len(rows) == 1
        assert rows[0]["title"].startswith("Senior ML Engineer")


def test_a_preview_less_channel_is_reported_not_fatal(db_path):
    def fetch(channel, before=None):
        if channel == "groupchat":
            raise preview.PreviewUnavailable("groupchat: no public web preview")
        return page_html(post_html(channel, 5, text=VACANCY))

    unavailable: list = []
    counts = run_scrape(
        fetch, channels=("somechan", "groupchat"), unavailable=unavailable
    )

    assert unavailable == ["groupchat"]
    assert counts["channels"] == 1
    assert counts["matched"] == 1


def test_an_unreachable_channel_counts_as_an_error(db_path):
    def fetch(channel, before=None):
        if channel == "flaky":
            raise ConnectionError("flaky: preview unreachable")
        return page_html(post_html(channel, 5, text=VACANCY))

    counts = run_scrape(fetch, channels=("somechan", "flaky"))

    assert counts["errors"] == 1
    assert counts["channels"] == 1
    assert counts["matched"] == 1


def test_scrape_needs_no_telegram_credentials(db_path, monkeypatch):
    for name in ("TG_API_ID", "TG_API_HASH", "TG_SESSION"):
        monkeypatch.delenv(name, raising=False)

    counts = run_scrape({None: page_html(post_html("somechan", 1, text=VACANCY))})
    assert counts["matched"] == 1
