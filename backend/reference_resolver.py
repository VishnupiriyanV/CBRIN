"""
Referential dependencies: which sentences cannot be understood without an earlier one.

`requires_setup_from_idx` (narrative_engine) is a NARRATIVE dependency — a punchline needs its
setup. This module supplies the other kind: a REFERENTIAL dependency, where a sentence opens
with a pronoun or demonstrative whose antecedent lives earlier in the transcript. Both are
dependency edges, so narrative_engine's existing backward-expansion machinery can satisfy
them with the same code path.

Why this exists: clip_scoring._self_containedness previously counted deixis terms in the first
ten words and then added +/-0.2 based on the LLM's own `self_contained` boolean. That is a
heuristic wrapped around an unverified model claim, in a module whose whole selling point is
that the setup constraint is structural rather than something an LLM can shrug off. This
replaces the assertion with a computed, deterministic predicate.


WHAT THIS DOES AND DOES NOT PROVE
---------------------------------
This is NOT full coreference resolution. It does not identify *which* entity a pronoun refers
to; it detects that a sentence OPENS with an unbound anaphor and therefore needs whatever came
before it. That is deliberately narrower than coref, and it is the part that actually matters
at a clip boundary: "So he told me the whole thing" is broken as an opening line no matter
which "he" it is.

It leans on the locality property of pronominal anaphora — an unbound pronoun almost always
refers to something in the immediately preceding sentence or two — rather than on a parser we
do not have. Consequences worth knowing:

  * It is conservative in the direction that matters. A missed antecedent costs a slightly
    longer clip; a missed DANGLING reference ships a clip that opens on nothing. So ambiguous
    cases resolve toward "needs context".
  * It only inspects the sentence OPENING. A pronoun mid-sentence with a noun ahead of it is
    treated as bound, and a pronoun deep in a clip whose antecedent is two sentences back —
    still inside the clip — is not a boundary problem at all.
  * Pleonastic "it" ("it's raining", "it rained", "it turns out") is excluded; it refers to
    nothing.
  * First and second person are excluded. "I" and "you" are deictic to the speaker and the
    viewer, and resolve without any prior sentence.
  * Demonstrative DETERMINERS on temporal or self-referential nouns are excluded — "this
    week", "that year", "this video" point at the moment of speaking or at the artifact
    already on screen, not at prior text.

KNOWN OVER-FIRING, measured on the real corpus (24 of 439 sentences flagged, ~5%): a bare
demonstrative heading an artifact reference — "This is probably going to be one of my shortest
lessons ever" — is deictic, but is surface-indistinguishable from the anaphoric "This is why
nobody does it" without a parser. Roughly a fifth of flagged sentences are this pattern. Left
in deliberately: the cost is a clip a sentence or two longer than it needed to be, against the
cost of shipping one that opens on nothing.

Swapping in a real coref model (fastcoref, spaCy) means replacing referential_dependencies()
and nothing else — narrative_engine and clip_scoring consume the {sentence_idx: earliest
required idx} mapping and never look inside it.
"""
import re
from typing import Any, Dict, List

# Third person only. "I"/"we"/"you" are deictic to speaker and audience — they need no
# antecedent, and treating them as anaphoric would flag nearly every spoken sentence.
_ANAPHORIC_PRONOUNS = {
    "he", "she", "it", "they", "him", "her", "them",
    "his", "hers", "its", "their", "theirs",
    "himself", "herself", "itself", "themselves",
}

# Demonstratives standing in for something previously said ("That was the moment", "This is
# why"). As bare openers these are almost always anaphoric in speech.
_DEMONSTRATIVES = {"this", "that", "these", "those"}

# Multi-word openers that explicitly point backwards.
_BACKREF_PHRASES = (
    "as i said", "as i mentioned", "like i said", "like i mentioned",
    "as we discussed", "going back to", "back to that", "that's why",
    "thats why", "which is why", "that's when", "thats when",
    "so anyway", "anyway", "as a result", "because of that", "after that",
    "the same thing", "same thing", "that said",
)

# Discourse markers that can precede the real opener without changing whether it is anaphoric:
# "So he told me" is exactly as dangling as "He told me".
_LEADING_CONNECTIVES = {
    "so", "and", "but", "then", "now", "well", "okay", "ok", "yeah",
    "right", "actually", "basically", "obviously", "anyway", "however",
    "because", "since", "plus", "also", "though", "although",
}

# Expletive / pleonastic "it" — a grammatical placeholder that refers to nothing, so it cannot
# dangle. "It's been three years" needs no antecedent; "It changed everything" does.
_PLEONASTIC_IT = re.compile(
    r"^it\s*'?s?\s+(been|going|about|time|cold|hot|hard|easy|"
    r"important|possible|impossible|worth|clear|obvious|likely|unlikely|true|false|"
    r"funny|weird|crazy|nice|good|bad|great|late|early|okay|fine)\b"
    r"|^it\s+(is|was|has|had|will|would|takes|took|seems|seemed|turns|turned|looks|looked|"
    r"appears|appeared|feels|felt|happens|happened|occurred|matters|mattered)\b"
    # Weather, in any tense — "it rained" has exactly as little referent as "it's raining".
    r"|^it\s*'?s?\s*(rain|snow|pour|drizzle|hail|thunder)(s|ed|ing)?\b"
    r"|^it\s*'?s\b(?=\s+(a|an|the|not|no|just|only|all|so|too|very|really)\b)",
    re.IGNORECASE,
)

# Demonstratives used as DETERMINERS on these nouns are deictic, not anaphoric — they point at
# the moment of speaking or at the artifact the viewer is already watching, both of which
# resolve with no prior sentence. "This week I want to talk about pricing" needs nothing
# before it; "This is why nobody does it" does.
_DEICTIC_HEAD_NOUNS = {
    # temporal — deictic to the time of speaking
    "week", "weekend", "month", "year", "morning", "afternoon", "evening",
    "night", "day", "time", "summer", "winter", "spring", "fall", "season",
    # the artifact itself — deictic to what is already on screen
    "video", "channel", "episode", "lesson", "podcast", "series", "clip",
    "course", "session", "one",
}

# "that" as a complementiser or relativiser ("I knew that he...", "the thing that matters") is
# not anaphoric. Only a demonstrative in subject position is.
_THAT_COMPLEMENTISER = re.compile(r"^that\s+(is|was|are|were)\s+\w", re.IGNORECASE)

_WORD_RE = re.compile(r"[a-zA-Z']+")


def _tokens(text: str) -> List[str]:
    return _WORD_RE.findall(text.lower())


def _strip_leading_connectives(tokens: List[str]) -> List[str]:
    """Drop discourse filler from the front so the real opener is inspected. Bounded at three
    so a sentence made entirely of connectives can't consume the whole token list."""
    i = 0
    while i < len(tokens) and i < 3 and tokens[i] in _LEADING_CONNECTIVES:
        i += 1
    return tokens[i:]


def opens_with_unbound_anaphor(text: str) -> bool:
    """
    True when this sentence, used as a clip's opening line, would refer to something the
    viewer has not seen.

    Checks the opener only — a pronoun later in the sentence generally has a noun ahead of it
    in the same sentence, and one that doesn't is a far weaker signal than a sentence that
    starts by pointing backwards.
    """
    stripped = text.strip().lower()
    if not stripped:
        return False

    for phrase in _BACKREF_PHRASES:
        if stripped.startswith(phrase):
            return True

    tokens = _strip_leading_connectives(_tokens(stripped))
    if not tokens:
        return False

    first = tokens[0]

    if first == "it":
        # Rebuild the text from the first real token so the pleonastic patterns anchor
        # correctly even when connectives were stripped ("So it turns out...").
        remainder = " ".join(tokens)
        if _PLEONASTIC_IT.match(remainder):
            return False
        return True

    if first in _ANAPHORIC_PRONOUNS:
        return True

    if first in _DEMONSTRATIVES:
        # Determiner use on a temporal or self-referential noun is deictic, not anaphoric.
        if len(tokens) > 1 and tokens[1] in _DEICTIC_HEAD_NOUNS:
            return False
        if first == "that" and _THAT_COMPLEMENTISER.match(" ".join(tokens)):
            # "That is ..." is still demonstrative in speech; only treat it as bound when it
            # heads a relative clause, which the pattern above does not match on its own.
            return True
        return True

    return False


# How far back an unbound anaphor is assumed to reach. Pronominal anaphora is overwhelmingly
# local — the antecedent is in the previous sentence or the one before it. 1 is the
# conservative-but-not-greedy choice: it fixes the opening line without dragging in unrelated
# material, and the solver re-checks the newly included sentence, so a run of anaphoric
# sentences still walks back as far as it needs to.
DEFAULT_LOOKBACK = 1


def referential_dependencies(
    sentences: List[Dict[str, Any]], lookback: int = DEFAULT_LOOKBACK
) -> Dict[int, int]:
    """
    Map {sentence_idx -> earliest sentence_idx required for its references to resolve}.

    Only sentences that open with an unbound anaphor appear. A sentence with no entry has no
    referential dependency, so callers should treat a missing key as "self-contained" rather
    than defaulting to anything.

    The first sentence of the transcript never gets an entry: there is nothing before it, so
    whatever it refers to was never on screen anyway and no expansion can fix it.
    """
    if not sentences:
        return {}

    ordered = sorted(sentences, key=lambda s: s["sentence_idx"])
    first_idx = ordered[0]["sentence_idx"]
    valid = {s["sentence_idx"] for s in ordered}

    deps: Dict[int, int] = {}
    for s in ordered:
        idx = s["sentence_idx"]
        if idx == first_idx:
            continue
        if not opens_with_unbound_anaphor(s.get("text", "")):
            continue
        target = idx - lookback
        while target not in valid and target > first_idx:
            target -= 1
        deps[idx] = max(target, first_idx)
    return deps


def dangling_indices(
    referential_deps: Dict[int, int], start_idx: int, end_idx: int
) -> List[int]:
    """
    Sentences inside [start_idx, end_idx] whose referential dependency falls OUTSIDE it — the
    literal set of places this clip points at something the viewer never saw.

    An empty list is the property worth stating out loud: this clip contains no reference that
    escapes its own boundaries.
    """
    return [
        idx for idx in range(start_idx, end_idx + 1)
        if idx in referential_deps and referential_deps[idx] < start_idx
    ]
