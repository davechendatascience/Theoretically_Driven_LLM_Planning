"""Comment markers in Python source, read from the token stream.

A file whose ids belong to the projects it builds -- a test suite that writes fixture
declarations -- says so once with `# tdlp:foreign-ids <why>`: its mentions are not checked, and the
scan's scope lists it. Its regions and relations are checked like any other.

Only real comments are markers: Python's own tokenizer says what is a comment, so marker-like
text inside a string or a docstring is never one. Mentions -- ids named in prose -- are read from
comments and from docstrings, which is where code cites the theory it follows; other string
literals are data (messages, fixtures, patterns) and are not read.

The body digest is what a body pin vouches for, so it is built to change when the code changes
and only then:

  - comments, blank lines and the whitespace inside a line are set aside, so a formatter run or
    a reworded comment does not ask for a re-review;
  - each logical line keeps its indentation relative to the block's least-indented line, so a
    statement moved into or out of a branch is a change, and the block moved to another nesting
    level is not;
  - an f-string (or t-string) is one token, its text as written, so the digest is the same on a
    Python that splits f-strings into parts (3.12 and later) and one that does not.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import tokenize
from dataclasses import dataclass, field

from .model import (ERROR, GRAMMAR_VERSION, RELATION_KINDS, Block, Diagnostic, Mention, Relation,
                    display)

BLOCK_ID = r"CODE-[A-Za-z0-9][A-Za-z0-9_-]*"
NODE_ID = r"(?:AXM|DEF|LMA|BRN)-[A-Za-z0-9][A-Za-z0-9_-]*"
PIN = r"[0-9a-f]{8}"

_MARKER = re.compile(r"^#+\s*tdlp:(\S*)(.*)$")
_BEGIN = re.compile(rf"({BLOCK_ID})(?:@({PIN}))?")
_END = re.compile(BLOCK_ID)
_RELATION = re.compile(rf"({NODE_ID})(?:@({PIN}))?")
_LEADING_BLOCK = re.compile(rf"^({BLOCK_ID})")
#: An id a reader would take for a reference, in prose. It ends on a letter or digit, so a line
#: wrapped after a hyphen does not produce `BRN-x-`.
MENTION = re.compile(r"(?<![A-Za-z0-9_-])((?:AXM|DEF|LMA|BRN|CODE)-[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?)")

#: Tokens that are not code: they never enter a body digest, and none ends a header.
_LAYOUT = {"COMMENT", "NL", "NEWLINE", "INDENT", "DEDENT", "ENCODING", "ENDMARKER"}


@dataclass
class FileScan:
    path: str
    blocks: list[Block] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    foreign: bool = False           # `# tdlp:foreign-ids`: its ids belong to projects it builds


@dataclass
class _Open:
    block: Block
    header: bool = True                                  # no code token seen yet
    lines: list[tuple[int, list[str]]] = field(default_factory=list)
    current: list[str] = field(default_factory=list)
    current_col: int = 0

    def add(self, text: str, col: int) -> None:
        self.header = False
        if not self.current:
            self.current_col = col
        self.current.append(text)

    def flush(self) -> None:
        if self.current:
            self.lines.append((self.current_col, self.current))
            self.current = []


def decode(data: bytes) -> str:
    """Source bytes as text, by the file's own coding declaration (PEP 263); line endings LF."""
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    text = data.decode(encoding)
    return text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")


def body_digest(lines: list[tuple[int, list[str]]]) -> str:
    base = min((col for col, _ in lines), default=0)
    payload = [GRAMMAR_VERSION, [[col - base, toks] for col, toks in lines]]
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def source_digest(text_lines: list[str], start: int, end: int) -> str:
    region = "\n".join(line.rstrip() for line in text_lines[start - 1:end])
    return hashlib.sha256(region.encode("utf-8")).hexdigest()[:16]


def code_tokens(text: str) -> list[tuple[str, str, tuple[int, int]]]:
    """The token stream as (kind, text, start), with each f-string or t-string merged into one
    STRING token carrying its source text. Raises what tokenize raises on a broken file."""
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    def at(pos: tuple[int, int]) -> int:
        return offsets[pos[0] - 1] + pos[1]

    out: list[tuple[str, str, tuple[int, int]]] = []
    depth, start = 0, (0, 0)
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        kind = tokenize.tok_name.get(tok.type, str(tok.type))
        if kind.endswith("STRING_START"):
            depth += 1
            if depth == 1:
                start = tok.start
            continue
        if depth:
            if kind.endswith("STRING_END"):
                depth -= 1
                if depth == 0:
                    out.append(("STRING", text[at(start):at(tok.end)], start))
            continue
        out.append((kind, tok.string, tok.start))
    return out


def docstring_lines(text: str) -> set[int] | None:
    """Lines that belong to a module, class or function docstring; None when the file does not
    parse, in which case its docstrings are not read."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                lines.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    return lines


def parse_python(path: str, text: str) -> FileScan:
    scan = FileScan(path)

    def diag(code: str, subject: str, message: str, line: int) -> None:
        scan.diagnostics.append(Diagnostic(code, ERROR, subject, message, path, line))

    try:
        tokens = code_tokens(text)
    except (tokenize.TokenError, SyntaxError) as exc:
        diag("SOURCE_UNPARSABLE", path, f"Python's tokenizer stops here ({display(exc, 100)}); "
             "its markers and mentions are not read until it parses", getattr(exc, "lineno", 0) or 0)
        return scan
    docstrings = docstring_lines(text)
    if docstrings is None:
        diag("SOURCE_UNPARSABLE", path, "the file does not parse as Python; its comments were read "
             "and its docstrings were not", 0)
        docstrings = set()
    text_lines = text.split("\n")
    stack: list[_Open] = []

    def close(entry: _Open, line: int, *, valid: bool) -> None:
        entry.flush()
        block = entry.block
        block.end_line = line
        block.body_hash = body_digest(entry.lines)
        block.source_hash = source_digest(text_lines, block.start_line, line)
        block.n_code_lines = len(entry.lines)
        block.valid = block.valid and valid
        if not entry.lines:
            block.valid = False
            diag("EMPTY_BLOCK", block.block_id, "the region holds no code; a link to nothing is "
                 "aligned with anything", block.start_line)
        if not block.relations:
            diag("NO_RELATIONS", block.block_id, "the region declares no relation; put "
                 "`# tdlp:implements <id>` (or uses, checks, motivated-by) right after begin, or "
                 "remove the markers", block.start_line)
        scan.blocks.append(block)

    def mentions(text_: str, line: int, where: str) -> None:
        enclosing = stack[-1].block.block_id if stack else None
        for offset, chunk in enumerate(text_.split("\n")):
            for m in MENTION.finditer(chunk):
                scan.mentions.append(Mention(m.group(1), path, line + offset, where, enclosing))

    for kind, string, (row, col) in tokens:
        if kind == "COMMENT":
            marker = _MARKER.match(string.strip())
            if marker is None:
                mentions(string, row, "comment")
                continue
            word, args = marker.group(1), marker.group(2).split()
            where = f"{path}:{row}"
            if word == "begin":
                arg = args[0] if len(args) == 1 else ""
                m = _BEGIN.fullmatch(arg)
                bid = m.group(1) if m else (_LEADING_BLOCK.match(arg).group(1)
                                             if _LEADING_BLOCK.match(arg) else None)
                if not m:
                    diag("MALFORMED_MARKER", where, f"`{display(string.strip(), 80)}`: begin takes one "
                         "CODE- id, optionally pinned as CODE-<name>@<8 hex>", row)
                if bid is None:
                    continue
                block = Block(bid, path, row, row, pin=m.group(2) if m else None)
                if stack:
                    block.valid = False
                    diag("NESTED_BLOCK", bid, f"begins inside {stack[-1].block.block_id}; regions "
                         "may not nest or overlap -- end the outer one first, or split it", row)
                stack.append(_Open(block))
            elif word == "end":
                if len(args) != 1 or not _END.fullmatch(args[0]):
                    diag("MALFORMED_MARKER", where, f"`{display(string.strip(), 80)}`: end takes the "
                         "CODE- id its begin named, and no pin", row)
                    continue
                bid = args[0]
                if not stack:
                    diag("UNMATCHED_END", bid, "ends a region that was never begun in this file", row)
                elif stack[-1].block.block_id == bid:
                    close(stack.pop(), row, valid=True)
                elif any(e.block.block_id == bid for e in stack):
                    while stack[-1].block.block_id != bid:
                        inner = stack.pop()
                        diag("UNMATCHED_BEGIN", inner.block.block_id,
                             f"is still open where {bid} ends; regions may not overlap", inner.block.start_line)
                        close(inner, row, valid=False)
                    close(stack.pop(), row, valid=False)
                else:
                    top = stack.pop()
                    diag("MISMATCHED_END", top.block.block_id,
                         f"is ended by `tdlp:end {bid}`; begin and end must name the same id", row)
                    close(top, row, valid=False)
            elif word in RELATION_KINDS:
                if not stack:
                    diag("MISPLACED_RELATION", where, f"tdlp:{word} outside any region; it relates "
                         "nothing -- move it under a begin marker", row)
                    continue
                entry = stack[-1]
                if not entry.header:
                    diag("MISPLACED_RELATION", entry.block.block_id, f"tdlp:{word} after the region's "
                         "code began; relations go in the header, right after begin", row)
                    continue
                arg = args[0] if len(args) == 1 else ""
                m = _RELATION.fullmatch(arg)
                if not m:
                    diag("MALFORMED_MARKER", where, f"`{display(string.strip(), 80)}`: a relation names "
                         "one AXM-, DEF-, LMA- or BRN- id, optionally pinned as <id>@<8 hex>", row)
                    continue
                if any(r.kind == word and r.target == m.group(1) for r in entry.block.relations):
                    diag("DUPLICATE_RELATION", entry.block.block_id,
                         f"declares {word} {m.group(1)} twice", row)
                    continue
                entry.block.relations.append(Relation(word, m.group(1), m.group(2), row))
            elif word == "foreign-ids":
                scan.foreign = True        # the rest of the line is the reason, for the reader
            else:
                diag("UNKNOWN_MARKER", where, f"tdlp:{display(word, 40)} is not a marker; expected "
                     f"begin, end, {', '.join(RELATION_KINDS)}, foreign-ids", row)
            continue
        if kind == "NEWLINE":
            for entry in stack:
                entry.flush()
            continue
        if kind in _LAYOUT:
            continue
        if kind == "STRING" and row in docstrings:
            mentions(string, row, "docstring")
        for entry in stack:
            entry.add(string, col)

    for entry in reversed(stack):
        diag("UNMATCHED_BEGIN", entry.block.block_id, "is never ended in this file; regions cannot "
             "cross files", entry.block.start_line)
        close(entry, len(text_lines), valid=False)
    scan.blocks.sort(key=lambda b: b.start_line)
    if scan.foreign:
        # A file that builds throwaway projects names their ids, which resolve nowhere here.
        # Its mentions are set aside whole -- a real id named there is not checked either -- and
        # the scope says which files did this, so it is never silent.
        scan.mentions = []
    return scan
