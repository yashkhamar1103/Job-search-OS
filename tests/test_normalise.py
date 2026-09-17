"""Text normalisation, tokenisation, and alias matching."""

from __future__ import annotations

import pytest

from app.normalise import (
    AliasIndex,
    normalise,
    normalise_spelling,
    sentence_ranges,
    token_texts,
    tokenise,
    tokens_of,
)


# ---------------------------------------------------------------------------
# Tokens that must survive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        (".NET", (".net",)),
        ("C#", ("c#",)),
        ("C++", ("c++",)),
        ("Node.js", ("node.js",)),
        ("CI/CD", ("ci/cd",)),
        ("PL/SQL", ("pl/sql",)),
        ("Pub/Sub", ("pub/sub",)),
        ("ASP.NET", ("asp.net",)),
        ("Log4j", ("log4j",)),
    ],
)
def test_symbols_survive_tokenisation(text, expected):
    assert token_texts(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Node.js.", ("node.js",)),
        ("CI/CD,", ("ci/cd",)),
        ("the end.", ("the", "end")),
        ("(Python)", ("python",)),
    ],
)
def test_trailing_punctuation_is_trimmed(text, expected):
    assert token_texts(text) == expected


def test_a_leading_dot_is_kept_so_dotnet_is_not_the_word_net():
    assert token_texts(".NET")[0].startswith(".")
    assert token_texts("net") == ("net",)


def test_hyphens_separate_tokens_so_hyphenation_needs_no_special_case():
    assert token_texts("retrieval-augmented generation") == token_texts(
        "retrieval augmented generation"
    )


# ---------------------------------------------------------------------------
# Offsets
# ---------------------------------------------------------------------------


def test_offsets_point_back_at_the_original_text():
    original = "  Wrote   Kafka\tproducers  "
    tokens = tokens_of(original, fold_case=False)
    for token in tokens:
        assert original[token.start : token.end] == token.raw


def test_offsets_survive_a_ligature_expanding_to_two_characters():
    original = "Conﬁgured the path"
    tokens = tokens_of(original, fold_case=False)
    assert tokens[0].folded == "configured"
    assert original[tokens[0].start : tokens[0].end] == "Conﬁgured"


def test_offsets_survive_a_stripped_zero_width_character():
    original = "Ka​fka producers"
    tokens = tokens_of(original, fold_case=False)
    assert tokens[0].folded == "kafka"
    assert original[tokens[0].start : tokens[0].end] == "Ka​fka"


# ---------------------------------------------------------------------------
# Evasion resistance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sneaky",
    [
        "Ka​fka",       # zero width space
        "Kaf­ka",       # soft hyphen
        "Kafka﻿",       # byte order mark
        "Ｋａｆｋａ",  # fullwidth
    ],
)
def test_invisible_and_fullwidth_characters_cannot_hide_a_term(sneaky):
    assert token_texts(sneaky) == ("kafka",)


def test_precomposed_and_decomposed_accents_fold_to_the_same_token():
    assert token_texts("Sémantic") == token_texts("Sémantic")


# ---------------------------------------------------------------------------
# Spelling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "british,american",
    [
        ("optimise", "optimize"),
        ("optimised", "optimized"),
        ("analysed", "analyzed"),
        ("standardisation", "standardization"),
    ],
)
def test_ise_and_yse_spellings_fold_together(british, american):
    assert normalise_spelling(british) == normalise_spelling(american)


def test_irregular_pairs_use_the_explicit_variants_map():
    variants = {"modelled": "modeled"}
    assert normalise_spelling("modelled", variants) == normalise_spelling("modeled", variants)


def test_a_doubled_consonant_rule_is_not_used_because_it_would_collide():
    """filled and filed are different verbs. A doubled-consonant rule would
    fold them together, which is why the explicit map exists instead."""
    assert normalise_spelling("filled") != normalise_spelling("filed")


# ---------------------------------------------------------------------------
# Alias matching
# ---------------------------------------------------------------------------


@pytest.fixture
def index():
    return AliasIndex(
        {
            "azure": ["Azure"],
            "azure_ai_search": ["Azure AI Search", "Cognitive Search"],
            "azure_openai": ["Azure OpenAI"],
            "microservices": ["microservices"],
            "sk": ["SK"],
        }
    )


def test_longest_alias_wins(index):
    tokens = tokens_of("We ran Azure AI Search for lookups.", fold_case=False)
    matched = index.match(tokens)
    assert [m.canonical_id for m in matched] == ["azure_ai_search"]


def test_matches_do_not_overlap(index):
    tokens = tokens_of("Azure OpenAI and Azure AI Search.", fold_case=False)
    matched = index.match(tokens)
    assert [m.canonical_id for m in matched] == ["azure_openai", "azure_ai_search"]


def test_plurals_are_tolerated_on_long_tokens(index):
    tokens = tokens_of("built microservice boundaries", fold_case=False)
    assert [m.canonical_id for m in index.match(tokens)] == ["microservices"]


def test_plurals_are_not_tolerated_on_short_acronyms(index):
    """SK must not be widened into SKs or skew by the plural tolerance."""
    tokens = tokens_of("results that skew the report", fold_case=False)
    assert index.match(tokens) == ()


def test_resolve_is_exact(index):
    assert index.resolve("Cognitive Search") == "azure_ai_search"
    assert index.resolve("Search") is None


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------


def test_sentence_split_does_not_break_on_a_dot_inside_a_token():
    norm = normalise("Wrote Node.js services. Then moved on.", fold_case=False)
    assert len(sentence_ranges(norm)) == 2


def test_sentence_split_does_not_break_on_an_abbreviation():
    norm = normalise("Used queues, e.g. Kafka, for order events.", fold_case=False)
    assert len(sentence_ranges(norm)) == 1


def test_sentence_split_does_not_break_on_a_decimal():
    norm = normalise("Cut latency by 3.5 seconds overall.", fold_case=False)
    assert len(sentence_ranges(norm)) == 1


def test_single_sentence_has_one_range():
    norm = normalise("One sentence with no terminator", fold_case=False)
    assert len(sentence_ranges(norm)) == 1


def test_empty_text_tokenises_to_nothing():
    assert tokenise(normalise("")) == ()
    assert sentence_ranges(normalise("")) == ()
