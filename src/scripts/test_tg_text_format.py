from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple


MARKDOWN_SAMPLE = """
- This is a list item
- This is a list item
- This is a list item
*加粗*
_斜体_
__下划线__
~删除线~
*斜体加粗*
`行内代码`
```code block```
[链接文本](https://example.com)"""


@dataclass(frozen=True)
class ParsedEntity:
    kind: str
    text: str
    start: int
    end: int
    meta: Dict[str, str]


class TelegramMarkdownV2Parser:
    """Minimal, local Markdown V2 parser that mirrors Telegram highlights we rely on."""

    # Order matters: longer spans first to avoid double counting.
    _PATTERNS: Sequence[Tuple[str, re.Pattern[str]]] = (
        ("code_block", re.compile(r"```(?P<text>[\s\S]+?)```")),
        ("link", re.compile(r"\[(?P<text>[^\]\n]+)\]\((?P<url>[^)\n]+)\)")),
        ("inline_code", re.compile(r"`(?P<text>[^`\n]+)`")),
        ("bold_italic", re.compile(r"\*_(?P<text>.+?)_\*", re.DOTALL)),
        ("italic_bold", re.compile(r"_\*(?P<text>.+?)\*_", re.DOTALL)),
        ("underline", re.compile(r"__(?P<text>[^_][\s\S]*?)__")),
        ("bold", re.compile(r"\*(?P<text>[^\*\n]+)\*")),
        ("italic", re.compile(r"_(?P<text>[^_\n]+)_")),
        ("strikethrough", re.compile(r"~(?P<text>[^~\n]+)~")),
    )

    def parse(self, text: str) -> List[ParsedEntity]:
        consumed: List[Tuple[int, int]] = []
        results: List[ParsedEntity] = []

        def span_available(start: int, end: int) -> bool:
            return all(not (start < stop and end > begin) for begin, stop in consumed)

        for kind, pattern in self._PATTERNS:
            for match in pattern.finditer(text):
                start, end = match.span()
                if not span_available(start, end):
                    continue

                captured = match.groupdict()
                entity_text = captured.get("text", "")
                meta: Dict[str, str] = {}

                if kind == "code_block":
                    entity_text = entity_text.strip("\n")
                    meta["multiline"] = "true"
                if kind == "link":
                    meta["url"] = captured.get("url", "")

                results.append(
                    ParsedEntity(
                        kind=kind,
                        text=entity_text,
                        start=start,
                        end=end,
                        meta=meta,
                    )
                )
                consumed.append((start, end))

        results.sort(key=lambda item: item.start)
        return results


def _strip_markdown_v2(text: str, entities: Iterable[ParsedEntity]) -> str:
    plain_parts: List[str] = []
    cursor = 0

    for entity in sorted(entities, key=lambda item: item.start):
        plain_parts.append(text[cursor : entity.start])
        plain_parts.append(entity.text)
        cursor = entity.end

    plain_parts.append(text[cursor:])
    return "".join(plain_parts)


def format_markdown_v2_diagnostics(sample_text: str) -> str:
    parser = TelegramMarkdownV2Parser()
    entities = parser.parse(sample_text)

    lines: List[str] = ["Detected entities (ordered by appearance):"]
    for entity in entities:
        meta_suffix = f" {entity.meta}" if entity.meta else ""
        lines.append(f"- {entity.kind}: {entity.text}{meta_suffix}")

    plain_text = _strip_markdown_v2(sample_text, entities)
    lines.append("\nPlain text reconstruction (markup removed):")
    lines.append(plain_text)
    return "\n".join(lines)


def run_sample_inspection() -> None:
    print(format_markdown_v2_diagnostics(MARKDOWN_V2_SAMPLE))


def test_markdown_v2_sample() -> None:
    parser = TelegramMarkdownV2Parser()
    entities = parser.parse(MARKDOWN_V2_SAMPLE)

    expected_order = [
        "bold",
        "italic",
        "underline",
        "strikethrough",
        "bold",
        "inline_code",
        "code_block",
        "link",
    ]
    actual_order = [entity.kind for entity in entities]
    assert actual_order == expected_order, f"Unexpected entity order: {actual_order}"

    labeled = {entity.kind: entity for entity in entities if entity.kind != "bold"}

    assert labeled["italic"].text == "斜体"
    assert labeled["underline"].text == "下划线"
    assert labeled["strikethrough"].text == "删除线"
    assert labeled["inline_code"].text == "行内代码"
    assert labeled["code_block"].text.strip() == "code block"
    assert labeled["link"].meta["url"] == "https://example.com"

    plain_text = _strip_markdown_v2(MARKDOWN_V2_SAMPLE, entities)
    assert plain_text.count("加粗") == 2


if __name__ == "__main__":
    test_markdown_v2_sample()
    run_sample_inspection()
