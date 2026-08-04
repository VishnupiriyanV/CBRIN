"""
Tests for transcript_parser.py's SRT/VTT/plain-text detection and edge-case handling
(creator-tools-integration-spec.md §2 names SRT parsing edge cases as a top build risk).

Run with: python -m pytest backend/tests/test_transcript_parser.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import transcript_parser as tp  # noqa: E402


SRT_SAMPLE = """1
00:00:00,000 --> 00:00:02,500
Hello and welcome to the show.

2
00:00:02,500 --> 00:00:05,000
Today we're talking about testing.
"""

VTT_SAMPLE = """WEBVTT

00:00:00.000 --> 00:00:02.500
Hello and welcome to the show.

00:00:02.500 --> 00:00:05.000
Today we're talking about testing.
"""


class TestSRT:
    def test_parses_basic_srt(self):
        result = tp.parse_timed_input(SRT_SAMPLE)
        assert result["format"] == "srt"
        assert result["has_timestamps"] is True
        assert len(result["segments"]) == 2
        assert result["segments"][0]["text"] == "Hello and welcome to the show."
        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][0]["duration"] == 2.5
        assert result["duration_sec"] == 5.0

    def test_comma_decimal_separator(self):
        result = tp.parse_timed_input(SRT_SAMPLE)
        assert result["segments"][1]["start"] == 2.5

    def test_crlf_line_endings(self):
        crlf = SRT_SAMPLE.replace("\n", "\r\n")
        result = tp.parse_timed_input(crlf)
        assert result["format"] == "srt"
        assert len(result["segments"]) == 2

    def test_utf8_bom(self):
        result = tp.parse_timed_input("﻿" + SRT_SAMPLE)
        assert result["format"] == "srt"
        assert len(result["segments"]) == 2

    def test_multiline_cue_text_joined(self):
        srt = "1\n00:00:00,000 --> 00:00:02,000\nLine one\nLine two\n"
        result = tp.parse_timed_input(srt)
        assert result["segments"][0]["text"] == "Line one Line two"

    def test_empty_cue_skipped(self):
        srt = "1\n00:00:00,000 --> 00:00:02,000\n\n2\n00:00:02,000 --> 00:00:04,000\nReal text\n"
        result = tp.parse_timed_input(srt)
        assert len(result["segments"]) == 1
        assert result["segments"][0]["text"] == "Real text"


class TestVTT:
    def test_parses_basic_vtt(self):
        result = tp.parse_timed_input(VTT_SAMPLE)
        assert result["format"] == "vtt"
        assert result["has_timestamps"] is True
        assert len(result["segments"]) == 2

    def test_dot_decimal_separator(self):
        result = tp.parse_timed_input(VTT_SAMPLE)
        assert result["segments"][1]["start"] == 2.5

    def test_note_block_skipped(self):
        vtt = "WEBVTT\n\nNOTE This is a comment\nnot a cue\n\n00:00:00.000 --> 00:00:02.000\nActual cue\n"
        result = tp.parse_timed_input(vtt)
        assert len(result["segments"]) == 1
        assert result["segments"][0]["text"] == "Actual cue"

    def test_cue_settings_stripped(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000 align:start position:10%\nPositioned cue\n"
        result = tp.parse_timed_input(vtt)
        assert result["segments"][0]["start"] == 0.0
        assert result["segments"][0]["text"] == "Positioned cue"

    def test_inline_tags_stripped(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n<v Speaker>Hello <c>there</c></v>\n"
        result = tp.parse_timed_input(vtt)
        assert result["segments"][0]["text"] == "Hello there"

    def test_mm_ss_form_without_hours(self):
        vtt = "WEBVTT\n\n00:02.000 --> 00:04.000\nShort form\n"
        result = tp.parse_timed_input(vtt)
        assert result["segments"][0]["start"] == 2.0

    def test_rolling_caption_duplicate_dropped(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000\nSame line\n\n"
            "00:00:02.000 --> 00:00:04.000\nSame line\n\n"
            "00:00:04.000 --> 00:00:06.000\nDifferent line\n"
        )
        result = tp.parse_timed_input(vtt)
        assert len(result["segments"]) == 2
        assert result["segments"][0]["text"] == "Same line"
        assert result["segments"][1]["text"] == "Different line"


class TestPlainFallback:
    def test_plain_text_has_no_timestamps(self):
        result = tp.parse_timed_input("Just a paragraph of text with no timing info at all.")
        assert result["format"] == "plain"
        assert result["has_timestamps"] is False
        assert result["duration_sec"] is None
        assert len(result["segments"]) == 1

    def test_empty_input(self):
        result = tp.parse_timed_input("")
        assert result["format"] == "plain"
        assert result["segments"] == []

    def test_whitespace_only_input(self):
        result = tp.parse_timed_input("   \n\n  ")
        assert result["format"] == "plain"
        assert result["segments"] == []

    def test_nearly_srt_falls_back_to_plain(self):
        garbage = "1\nnot a real timestamp line\nsome text\n\n2\nalso not a timestamp\nmore text\n"
        result = tp.parse_timed_input(garbage)
        assert result["format"] == "plain"
        assert result["has_timestamps"] is False


class TestWordCount:
    def test_word_count(self):
        assert tp.word_count("one two three") == 3
        assert tp.word_count("") == 0
