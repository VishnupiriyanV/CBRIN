"""
Tests for MultimodalEngine.segment_transcript_into_sentences — the sentence chunker
flagged in IMPROVEMENT-PLAN.md 1.2. Covers the specific failure modes described there:
no punctuation, multi-sentence single segments (the TypeError case), empty segments,
and a single segment.

Run with: python -m pytest backend/tests -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from multimodal_engine import MultimodalEngine  # noqa: E402


def _seg(start, duration, text):
    return {"start": start, "duration": duration, "text": text}


class TestNoPunctuation:
    def test_no_punctuation_does_not_become_one_giant_sentence(self):
        # 30 segments, 5s / ~8 words each, no punctuation anywhere — common shape for
        # YouTube auto-captions. Old code: nothing ever flushes, whole transcript is 1
        # "sentence". New code: hard time/word caps force multiple flushes.
        segments = [_seg(i * 5.0, 5.0, "word " * 8) for i in range(30)]
        sentences = MultimodalEngine.segment_transcript_into_sentences(segments)

        assert len(sentences) > 1
        for s in sentences:
            assert s["end_sec"] - s["start_sec"] <= MultimodalEngine.MAX_SENTENCE_SECONDS + 5
            assert len(s["text"].split()) <= MultimodalEngine.MAX_SENTENCE_WORDS + 8

    def test_word_cap_triggers_before_absurd_length(self):
        segments = [_seg(i * 1.0, 1.0, "supercalifragilistic ") for i in range(200)]
        sentences = MultimodalEngine.segment_transcript_into_sentences(segments)
        assert len(sentences) > 1


class TestMultiSentenceSingleSegment:
    def test_two_sentences_in_one_segment_does_not_crash(self):
        # This is the exact bug: after the first sentence flushes,
        # sentence_start_sec used to be set to None; the second sentence's flush
        # then did math.floor(None) -> TypeError.
        segments = [_seg(10.0, 6.0, "Hello there friend. This is another sentence.")]
        sentences = MultimodalEngine.segment_transcript_into_sentences(segments)

        assert len(sentences) == 2
        for s in sentences:
            assert isinstance(s["start_sec"], int)
            assert isinstance(s["end_sec"], int)
            assert s["start_sec"] == 10  # reset to the segment's start, not None

    def test_three_sentences_in_one_segment(self):
        segments = [_seg(0.0, 9.0, "One two three go. Four five six stop! Seven eight nine end?")]
        sentences = MultimodalEngine.segment_transcript_into_sentences(segments)
        assert len(sentences) == 3
        assert [s["sentence_idx"] for s in sentences] == [0, 1, 2]


class TestEmptySegments:
    def test_empty_segments_are_skipped(self):
        segments = [
            _seg(0.0, 2.0, "Real words here now."),
            _seg(2.0, 1.0, ""),
            _seg(3.0, 0.5, "   "),
            _seg(3.5, 2.0, "More real words follow."),
        ]
        sentences = MultimodalEngine.segment_transcript_into_sentences(segments)
        assert len(sentences) == 2

    def test_all_empty_segments_yields_nothing(self):
        segments = [_seg(0.0, 1.0, ""), _seg(1.0, 1.0, "  ")]
        assert MultimodalEngine.segment_transcript_into_sentences(segments) == []

    def test_no_segments_yields_nothing(self):
        assert MultimodalEngine.segment_transcript_into_sentences([]) == []


class TestSingleSegment:
    def test_single_punctuated_segment(self):
        segments = [_seg(5.0, 3.0, "Just one sentence here.")]
        sentences = MultimodalEngine.segment_transcript_into_sentences(segments)
        assert len(sentences) == 1
        assert sentences[0]["start_sec"] == 5
        assert sentences[0]["end_sec"] == 8

    def test_single_unpunctuated_segment_still_flushes_at_end(self):
        segments = [_seg(0.0, 4.0, "no ending punctuation at all here")]
        sentences = MultimodalEngine.segment_transcript_into_sentences(segments)
        assert len(sentences) == 1
        assert sentences[0]["text"].startswith("no ending")

    def test_too_short_fragment_is_dropped(self):
        # Fewer than 3 words — matches the existing minimum-length filter.
        segments = [_seg(0.0, 1.0, "Hi.")]
        assert MultimodalEngine.segment_transcript_into_sentences(segments) == []


class TestSentenceIdxIsSequential:
    def test_sentence_idx_increments_across_segments(self):
        segments = [
            _seg(0.0, 2.0, "First sentence right here."),
            _seg(2.0, 2.0, "Second sentence right here."),
            _seg(4.0, 2.0, "Third sentence right here."),
        ]
        sentences = MultimodalEngine.segment_transcript_into_sentences(segments)
        assert [s["sentence_idx"] for s in sentences] == [0, 1, 2]
