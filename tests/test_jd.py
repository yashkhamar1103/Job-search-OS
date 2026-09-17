"""The job description watch list."""

from __future__ import annotations

from app.jd import build_watch_list


def _keys(watch):
    return {" ".join(t.key) for t in watch.terms}


def test_taxonomy_terms_become_watch_terms(bundle):
    watch, _ = build_watch_list("You will work with Apache Kafka and Terraform.", bundle)
    assert "kafka" in _keys(watch)
    assert "terraform" in _keys(watch)


def test_camel_case_tokens_become_watch_terms(bundle):
    watch, _ = build_watch_list("Experience with FooBarBaz is required.", bundle)
    assert "foobarbaz" in _keys(watch)


def test_tokens_mixing_letters_and_digits_become_watch_terms(bundle):
    watch, _ = build_watch_list("We run Zorp9 in production.", bundle)
    assert "zorp9" in _keys(watch)


def test_mid_sentence_capitals_outside_english_become_watch_terms(bundle):
    watch, _ = build_watch_list("The team uses Quibblesnort every day.", bundle)
    assert "quibblesnort" in _keys(watch)


def test_ordinary_mid_sentence_capitals_do_not(bundle):
    """Monday and January are English. Flagging them would fill the review file
    with noise and teach Yash to skim it."""
    watch, _ = build_watch_list("Standups happen every Monday in January.", bundle)
    assert "monday" not in _keys(watch)
    assert "january" not in _keys(watch)


def test_a_sentence_opening_capital_is_not_a_signal_by_itself(bundle):
    watch, _ = build_watch_list("Pipelines matter here. Teams ship weekly.", bundle)
    assert "pipelines" not in _keys(watch)
    assert "teams" not in _keys(watch)


def test_bare_numbers_are_not_watch_terms(bundle):
    """Every number becoming a posting term would put G1 in competition with G3
    over the same digits, and a truthful cited metric that also appears in the
    posting would be rejected for being copied."""
    watch, _ = build_watch_list("We process 40% more each quarter, up from 2,500,000.", bundle)
    assert not any(key.strip("0123456789.,%") == "" for key in _keys(watch))


def test_unknown_terms_go_to_the_review_file_not_the_ledger(bundle):
    _, candidates = build_watch_list("The team uses Quibblesnort and FooBarBaz.", bundle)
    surfaces = {c.surface for c in candidates.terms}
    assert "Quibblesnort" in surfaces
    assert "FooBarBaz" in surfaces

    payload = candidates.to_json()
    assert payload["candidates"]
    assert all({"term", "signal"} == set(c) for c in payload["candidates"])


def test_known_taxonomy_terms_are_not_offered_as_new_vocabulary(bundle):
    _, candidates = build_watch_list("You will work with Apache Kafka daily.", bundle)
    assert "Kafka" not in {c.surface for c in candidates.terms}


def test_model_terms_can_only_be_added(bundle):
    """A model call may extend the watch list. It can never shrink it."""
    watch, _ = build_watch_list("You will work with Apache Kafka.", bundle)
    before = _keys(watch)

    extended = watch.extended_with_model_terms(["Snowplow", "Kafka"])
    after = _keys(extended)

    assert before <= after
    assert "snowplow" in after
    assert len(extended.terms) == len(watch.terms) + 1


def test_model_terms_cannot_remove_by_returning_an_empty_list(bundle):
    watch, _ = build_watch_list("You will work with Apache Kafka and Terraform.", bundle)
    assert _keys(watch.extended_with_model_terms([])) == _keys(watch)


def test_copy_ngrams_use_the_configured_size(bundle):
    watch, _ = build_watch_list("one two three four five six seven eight nine", bundle)
    assert watch.ngram_size == int(bundle.policy["jd_copy_ngram"])
    assert all(len(gram) == watch.ngram_size for gram in watch.copy_ngrams)


def test_an_empty_posting_yields_an_empty_watch_list(bundle):
    watch, candidates = build_watch_list("", bundle)
    assert watch.terms == ()
    assert candidates.terms == ()


def test_a_taxonomy_match_watches_every_spelling_of_the_same_product(bundle):
    """The posting says Apache Kafka. A CV saying just Kafka is the same term,
    and watching only the posting's spelling would miss it."""
    watch, _ = build_watch_list("You will work with Apache Kafka.", bundle)
    keys = _keys(watch)
    assert "apache kafka" in keys
    assert "kafka" in keys


def test_alias_expansion_does_not_reach_unrelated_products(bundle):
    watch, _ = build_watch_list("You will work with Apache Kafka.", bundle)
    assert "terraform" not in _keys(watch)
