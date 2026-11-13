import datetime as dt

from scout.research.classify import TaggedBatch, TaggedItem, keyword_tag, tag_all
from scout.research.report import render
from scout.research.reviews import Review, from_csv

from .conftest import FakeLlm


def rv(i, text, score=1, thumbs=0):
    return Review(id=f"r{i}", source="app", text=text, score=score, thumbs_up=thumbs, at=dt.date(2026, 11, 1))


def test_keyword_tagger_does_not_match_the_app_name():
    t = keyword_tag(rv(1, "Splitwise is great, love it", score=5))
    assert "settling_math" not in t.themes and not t.complaint


def test_keyword_tagger_finds_themes():
    t = keyword_tag(rv(1, "I have to chase everyone for reminders and nobody sends a screenshot."))
    assert {"chasing_reminders", "payment_proof"} <= set(t.themes) and t.complaint


def test_model_quotes_must_be_verbatim_and_unknown_ids_are_ignored():
    reviews = [rv(1, "Ads everywhere now. Paywall for basic stuff!"), rv(2, "Settling up is confusing.")]
    llm = FakeLlm(TaggedBatch(items=[
        TaggedItem(id="r1", themes=["pricing_ads"], complaint=True, quote="Paywall for basic stuff!"),
        TaggedItem(id="r2", themes=["settling_math"], complaint=True, quote="Settling up is a nightmare."),
        TaggedItem(id="r99", themes=["sync_bugs"], complaint=True, quote="made up"),
    ]))
    tagged, method = tag_all(reviews, llm)
    assert method == "llm"
    assert tagged[0].quote == "Paywall for basic stuff!"
    assert tagged[1].quote is None  # paraphrase, not a quote: dropped
    assert len(tagged) == 2


def test_reviews_the_model_skips_fall_back_to_keywords():
    reviews = [rv(1, "Ads everywhere now."), rv(2, "The app crashes daily.")]
    llm = FakeLlm(TaggedBatch(items=[TaggedItem(id="r1", themes=["pricing_ads"], complaint=True, quote=None)]))
    tagged, method = tag_all(reviews, llm)
    assert method == "llm+keywords" and "sync_bugs" in tagged[1].themes


def test_report_counts_and_quotes():
    tagged, _ = tag_all([rv(1, "Too many ads. Really.", thumbs=9), rv(2, "Ads and a paywall.", thumbs=1),
                         rv(3, "Works fine", score=5)], None)
    md = render(tagged, "keywords", "Test")
    assert "| Paywall, pricing, ads | 2 | 100% |" in md
    assert md.index("Too many ads.") < md.index("Ads and a paywall.")  # most-liked first


def test_csv_reader(tmp_path):
    p = tmp_path / "posts.csv"
    p.write_text("text,score,source,date\nNobody pays on time,2,reddit,2026-10-01\n,,,\n", encoding="utf-8")
    rows = from_csv(p)
    assert len(rows) == 1 and rows[0].source == "reddit" and rows[0].score == 2
