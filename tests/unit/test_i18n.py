"""Both languages must stay in step: same keys, same placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from google_search_console_mcp import i18n

I18N_DIR = Path(i18n.__file__).parent
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def flatten(data, prefix=""):
    out = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, path + "."))
        else:
            out[path] = value
    return out


def load_raw(language):
    return flatten(json.loads((I18N_DIR / f"{language}.json").read_text(encoding="utf-8")))


def placeholders(value):
    if isinstance(value, list):
        return {name for item in value for name in PLACEHOLDER.findall(str(item))}
    return set(PLACEHOLDER.findall(str(value)))


def test_more_than_one_language_ships():
    assert set(i18n.available_languages()) >= {"en", "it"}


@pytest.mark.parametrize("language", ["it"])
def test_every_language_has_exactly_the_english_keys(language):
    english = load_raw("en")
    other = load_raw(language)

    assert set(other) == set(english), (
        f"missing in {language}: {sorted(set(english) - set(other))}, "
        f"extra in {language}: {sorted(set(other) - set(english))}"
    )


@pytest.mark.parametrize("language", ["it"])
def test_placeholders_match_across_languages(language):
    english = load_raw("en")
    other = load_raw(language)

    mismatched = {
        key: (placeholders(english[key]), placeholders(other[key]))
        for key in english
        if placeholders(english[key]) != placeholders(other[key])
    }
    assert mismatched == {}


@pytest.mark.parametrize("language", ["en", "it"])
def test_no_string_is_empty(language):
    for key, value in load_raw(language).items():
        if isinstance(value, list):
            assert value, f"{language}:{key} is an empty list"
            assert all(str(item).strip() for item in value), f"{language}:{key} has a blank entry"
        else:
            assert str(value).strip(), f"{language}:{key} is blank"


def test_translations_carry_no_client_or_vertical_specifics():
    """A leftover from a real engagement in the copy is a client-data leak."""
    banned = ("made in italy", "non-iron", "shirt", "camicia")
    for language in i18n.available_languages():
        text = (I18N_DIR / f"{language}.json").read_text(encoding="utf-8").lower()
        for phrase in banned:
            assert phrase not in text, f"{language}.json still mentions {phrase!r}"


def test_translation_interpolates_parameters():
    assert i18n.load("en").t("issue.paginated_pages.title", n=12) == "12 paginated pages are indexed"
    assert i18n.load("it").t("issue.paginated_pages.title", n=12) == "12 pagine paginate indicizzate"


def test_a_count_of_one_uses_the_singular_form():
    assert i18n.load("en").plural("issue.paginated_pages.title", 1, n=1) == "One paginated page is indexed"
    assert i18n.load("it").plural("issue.paginated_pages.title", 1, n=1) == "Una pagina paginata indicizzata"


def test_a_count_other_than_one_uses_the_plural_form():
    assert "3" in i18n.load("en").plural("issue.paginated_pages.title", 3, n=3)
    assert "0" in i18n.load("en").plural("issue.paginated_pages.title", 0, n=0)


def test_a_key_with_no_singular_variant_falls_back_to_the_base_form():
    translator = i18n.load("en")
    assert translator.plural("sections.overview", 1) == translator.t("sections.overview")


def test_an_unknown_language_falls_back_to_english():
    translator = i18n.load("xx")
    assert translator.language == "en"


def test_an_unknown_key_returns_the_key_rather_than_raising():
    assert i18n.load("en").t("nope.not.here") == "nope.not.here"


def test_missing_parameters_leave_the_template_intact():
    text = i18n.load("en").t("issue.paginated_pages.title")
    assert "{n}" in text


def test_lists_come_back_as_lists():
    steps = i18n.load("it").list("issue.http_pages.strategy")
    assert len(steps) >= 4
    assert all(isinstance(step, str) for step in steps)
    assert i18n.load("en").list("sections.overview") == []


def test_numbers_follow_the_locale():
    assert i18n.format_number(1234.5, "it", 1) == "1.234,5"
    assert i18n.format_number(1234.5, "en", 1) == "1,234.5"
    assert i18n.format_number(1234567, "it") == "1.234.567"
    assert i18n.format_number(1234567, "en") == "1,234,567"


def test_percentages_carry_the_sign_when_asked():
    translator = i18n.load("it")
    assert translator.pct(9.3, signed=True) == "+9,3%"
    assert translator.pct(-9.3, signed=True) == "−9,3%"
    assert translator.pct(-9.3) == "−9,3%"
    assert translator.pct(None) == "n/a"


def test_the_locale_tag_is_exposed_for_the_html_document():
    assert i18n.load("it").locale == "it-IT"
    assert i18n.load("en").locale == "en-US"


def test_stopwords_and_question_words_are_available_per_language():
    italian = i18n.load("it")
    english = i18n.load("en")

    assert "questo" in italian.stopwords()
    assert "come" in italian.question_words()
    assert "this" in english.stopwords()
    assert "how" in english.question_words()
