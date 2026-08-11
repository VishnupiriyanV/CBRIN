"""
Tests for reference_resolver.py — referential dependencies, the second dependency type the
narrative solver satisfies (narrative_engine._extend_for_references).

The bar here is asymmetric on purpose: a missed antecedent costs a slightly longer clip, a
missed dangling reference ships a clip that opens on nothing. So false positives are cheap and
false negatives are not, and the tests are written that way.

Run with: python -m pytest backend/tests/test_reference_resolver.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import reference_resolver as rr  # noqa: E402


def _sentence(idx, text):
    return {"sentence_idx": idx, "text": text, "start_sec": idx * 3, "end_sec": (idx + 1) * 3}


class TestUnboundAnaphorDetection:
    def test_third_person_pronoun_opener_is_unbound(self):
        assert rr.opens_with_unbound_anaphor("He told me the whole story.")
        assert rr.opens_with_unbound_anaphor("She never called back.")
        assert rr.opens_with_unbound_anaphor("They shut the whole thing down.")
        assert rr.opens_with_unbound_anaphor("Him and I went anyway.")

    def test_leading_connectives_do_not_hide_the_anaphor(self):
        # "So he told me" is exactly as dangling as "He told me".
        assert rr.opens_with_unbound_anaphor("So he told me the whole story.")
        assert rr.opens_with_unbound_anaphor("And then they shut it down.")
        assert rr.opens_with_unbound_anaphor("But actually she was right.")

    def test_first_and_second_person_are_not_anaphoric(self):
        # Deictic to speaker and viewer — they resolve with no prior sentence at all.
        assert not rr.opens_with_unbound_anaphor("I quit my job that year.")
        assert not rr.opens_with_unbound_anaphor("You should never sign that.")
        assert not rr.opens_with_unbound_anaphor("We built the whole thing in a week.")

    def test_pleonastic_it_is_not_anaphoric(self):
        # Expletive "it" is a grammatical placeholder; it refers to nothing.
        assert not rr.opens_with_unbound_anaphor("It's been three years since then.")
        assert not rr.opens_with_unbound_anaphor("It turns out nobody checked.")
        assert not rr.opens_with_unbound_anaphor("It was hard to explain.")
        assert not rr.opens_with_unbound_anaphor("It takes about a week.")

    def test_weather_it_is_pleonastic_in_any_tense(self):
        # "it rained" has exactly as little referent as "it's raining".
        assert not rr.opens_with_unbound_anaphor("It rained the entire week we were filming.")
        assert not rr.opens_with_unbound_anaphor("It's raining again.")
        assert not rr.opens_with_unbound_anaphor("It snowed right through April.")
        assert not rr.opens_with_unbound_anaphor("It poured the whole afternoon.")

    def test_demonstrative_on_a_deictic_noun_is_not_anaphoric(self):
        # Points at the moment of speaking, or at the artifact already on screen — both
        # resolve with nothing before them.
        assert not rr.opens_with_unbound_anaphor("This week I want to talk about pricing.")
        assert not rr.opens_with_unbound_anaphor("That year everything changed for us.")
        assert not rr.opens_with_unbound_anaphor("This video is going to be a short one.")
        assert not rr.opens_with_unbound_anaphor("This lesson is my shortest ever.")

    def test_demonstrative_on_an_ordinary_noun_is_still_anaphoric(self):
        assert rr.opens_with_unbound_anaphor("That decision cost me the contract.")
        assert rr.opens_with_unbound_anaphor("This mistake is the expensive one.")

    def test_referential_it_is_anaphoric(self):
        assert rr.opens_with_unbound_anaphor("It changed everything about how I work.")
        assert rr.opens_with_unbound_anaphor("It cost me the entire contract.")

    def test_demonstrative_openers_are_anaphoric(self):
        assert rr.opens_with_unbound_anaphor("That was the moment I knew.")
        assert rr.opens_with_unbound_anaphor("This is why nobody does it.")
        assert rr.opens_with_unbound_anaphor("Those were the good years.")

    def test_explicit_backreference_phrases(self):
        assert rr.opens_with_unbound_anaphor("As I said, the numbers never worked.")
        assert rr.opens_with_unbound_anaphor("That's why I stopped taking clients.")
        assert rr.opens_with_unbound_anaphor("Going back to the first point.")

    def test_ordinary_openers_are_self_contained(self):
        assert not rr.opens_with_unbound_anaphor("Most founders underprice their first product.")
        assert not rr.opens_with_unbound_anaphor("The hardest part is saying no.")
        assert not rr.opens_with_unbound_anaphor("Nobody tells you this before you start.")

    def test_empty_and_whitespace_are_safe(self):
        assert not rr.opens_with_unbound_anaphor("")
        assert not rr.opens_with_unbound_anaphor("   ")

    def test_sentence_of_only_connectives_does_not_crash(self):
        assert not rr.opens_with_unbound_anaphor("So, well, anyway.")


class TestReferentialDependencies:
    def test_only_anaphoric_sentences_get_entries(self):
        sentences = [
            _sentence(0, "Most founders underprice their first product."),
            _sentence(1, "He told me he charged fifty dollars an hour."),
            _sentence(2, "The fix is to raise prices before you feel ready."),
        ]
        deps = rr.referential_dependencies(sentences)
        assert deps == {1: 0}

    def test_first_sentence_never_gets_a_dependency(self):
        # Nothing precedes it, so no expansion could ever fix it.
        sentences = [
            _sentence(0, "He told me the whole story."),
            _sentence(1, "That was the moment I knew."),
        ]
        deps = rr.referential_dependencies(sentences)
        assert 0 not in deps
        assert deps[1] == 0

    def test_lookback_is_configurable(self):
        sentences = [_sentence(i, "Filler sentence here.") for i in range(5)]
        sentences[4] = _sentence(4, "He said it was fine.")
        assert rr.referential_dependencies(sentences, lookback=1)[4] == 3
        assert rr.referential_dependencies(sentences, lookback=3)[4] == 1

    def test_lookback_clamps_at_the_first_sentence(self):
        sentences = [_sentence(0, "Opening line."), _sentence(1, "He left.")]
        assert rr.referential_dependencies(sentences, lookback=10)[1] == 0

    def test_gapped_sentence_indices_resolve_to_a_real_sentence(self):
        # Indices need not be contiguous; a dependency must still land on one that exists.
        sentences = [_sentence(0, "Opening line."), _sentence(5, "He left without saying why.")]
        deps = rr.referential_dependencies(sentences, lookback=1)
        assert deps[5] == 0

    def test_empty_input(self):
        assert rr.referential_dependencies([]) == {}


class TestDanglingIndices:
    def test_dependency_inside_the_clip_is_not_dangling(self):
        deps = {5: 4}
        assert rr.dangling_indices(deps, 4, 8) == []

    def test_dependency_outside_the_clip_is_dangling(self):
        deps = {5: 3}
        assert rr.dangling_indices(deps, 4, 8) == [5]

    def test_reports_every_offending_sentence(self):
        deps = {4: 2, 6: 1, 7: 6}
        # 7 depends on 6, which IS in range, so only 4 and 6 escape.
        assert rr.dangling_indices(deps, 4, 8) == [4, 6]

    def test_no_dependencies_means_nothing_dangles(self):
        assert rr.dangling_indices({}, 0, 10) == []
