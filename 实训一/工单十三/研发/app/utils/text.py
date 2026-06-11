from __future__ import annotations

import re

# Zero-width / invisible / formatting characters that carry no semantic value.
# Includes zero-width space, ZWNJ, ZWJ, BOM, line/paragraph separators, soft hyphen.
INVISIBLE_CHARS_RE = re.compile(
    r"[­᠎​-‏‪-‮  ⁠﻿]"
)

# Control characters except tab/newline/carriage-return.
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Decorative bullets / shape glyphs frequently injected by PDF extraction.
DECORATIVE_CHARS_RE = re.compile(r"[□■•·▪●○◆◇▲△▼▽※◎★☆➤➢➣◦‣⁃]")

_CJK_RANGE = (
    r"㐀-䶿一-鿿豈-﫿"
    r"　-〿＀-￯"
)
# A space sitting between two CJK characters is an artifact of PDF glyph spacing.
_CJK_GAP_RE = re.compile(rf"([{_CJK_RANGE}]) +(?=[{_CJK_RANGE}])")

# An English word split across a line break by a trailing hyphen: "inter-\nnational".
_DEHYPHEN_RE = re.compile(r"([A-Za-z])-\n([A-Za-z])")

_SENTENCE_END_RE = re.compile(r"(?<=[。！？!?；;])")


def _is_cjk(char: str) -> bool:
    return (
        "㐀" <= char <= "䶿"
        or "一" <= char <= "鿿"
        or "豈" <= char <= "﫿"
    )


def strip_noise_chars(text: str) -> str:
    """Remove invisible, control, and decorative characters."""
    text = INVISIBLE_CHARS_RE.sub("", text)
    text = CONTROL_CHARS_RE.sub(" ", text)
    text = DECORATIVE_CHARS_RE.sub(" ", text)
    return text


def normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("　", " ").replace("\t", " ")
    text = strip_noise_chars(text)
    # Re-join English words broken across lines before collapsing newlines.
    text = _DEHYPHEN_RE.sub(r"\1\2", text)
    text = re.sub(r"[ \f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    # Drop spurious spaces between adjacent CJK characters (run twice for overlaps).
    text = _CJK_GAP_RE.sub(r"\1", text)
    text = _CJK_GAP_RE.sub(r"\1", text)
    # Tighten spacing around punctuation.
    text = re.sub(r" +([，。；：！？、,.!?;:）)】\]])", r"\1", text)
    text = re.sub(r"([（(【\[]) +", r"\1", text)
    # Collapse runs of repeated punctuation noise (e.g. dotted leaders "......").
    text = re.sub(r"([。，、；：·.\-_]){4,}", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def dedupe_lines(text: str) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, keeping terminal punctuation with each sentence.

    Splits on CJK and ASCII sentence terminators. Newlines also act as soft
    boundaries so list items and short lines stay separate.
    """
    sentences: list[str] = []
    for block in text.split("\n"):
        block = block.strip()
        if not block:
            continue
        for piece in _SENTENCE_END_RE.split(block):
            piece = piece.strip()
            if piece:
                sentences.append(piece)
    return sentences
