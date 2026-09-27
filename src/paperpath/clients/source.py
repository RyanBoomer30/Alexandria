"""Turn an arXiv source bundle or HTML page into sectioned plain text."""

import io
import re
import tarfile
from html.parser import HTMLParser
from pathlib import Path

from paperpath.domain.models import Section
from paperpath.errors import IngestionError

_SECTION = re.compile(r"\\(section|subsection|subsubsection)\*?\{([^{}]*)\}")
_INPUT = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_COMMENT = re.compile(r"(?<!\\)%.*")
_MAX_MEMBERS = 400
_MAX_MEMBER_BYTES = 30_000_000


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "li", "br", "section"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    text = "".join(parser.parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def unpack_arxiv_source(blob: bytes, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    if blob[:2] == b"\x1f\x8b" and not _looks_like_tar(blob):
        import gzip

        text = gzip.decompress(blob)
        path = dest / "main.tex"
        path.write_bytes(text)
        return [path]

    try:
        archive = tarfile.open(fileobj=io.BytesIO(blob), mode="r:*")
    except tarfile.TarError as exc:
        raise IngestionError("arXiv source is not a readable archive.") from exc

    with archive:
        members = archive.getmembers()
        if len(members) > _MAX_MEMBERS:
            raise IngestionError("arXiv source archive has too many files.")
        safe: list[tarfile.TarInfo] = []
        for member in members:
            if member.issym() or member.islnk():
                continue
            parts = Path(member.name).parts
            if not parts or parts[0] in {"", ".", ".."} or ".." in parts or member.name.startswith("/"):
                raise IngestionError("arXiv source archive contains an unsafe path.")
            if member.size > _MAX_MEMBER_BYTES:
                raise IngestionError("arXiv source archive contains a file that is too large.")
            safe.append(member)
        archive.extractall(dest, members=safe, filter="data")
    return sorted(dest.rglob("*.tex"))


def read_latex_source(tex_files: list[Path]) -> list[Section]:
    main = _main_tex(tex_files)
    if main is None:
        return []
    raw = _inline_inputs(main.read_text(errors="replace"), main.parent)
    return sections_from_latex(raw)


def sections_from_latex(source: str) -> list[Section]:
    cleaned = "\n".join(_COMMENT.sub("", line) for line in source.splitlines())
    matches = list(_SECTION.finditer(cleaned))
    if not matches:
        body = _latex_to_text(cleaned)
        return [Section(level=1, title="Body", text=body)] if body.strip() else []

    sections: list[Section] = []
    preamble = cleaned[: matches[0].start()]
    preamble_text = _latex_to_text(preamble)
    if preamble_text.strip():
        sections.append(Section(level=1, title="Preamble", text=preamble_text))
    for index, match in enumerate(matches):
        level = {"section": 1, "subsection": 2, "subsubsection": 3}[match.group(1)]
        title = _latex_to_text(match.group(2)).strip() or "Untitled"
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        body = _latex_to_text(cleaned[match.end() : end])
        sections.append(Section(level=level, title=title, text=body.strip()))
    return sections


def sections_from_plain(text: str) -> list[Section]:
    body = text.strip()
    if not body:
        return []
    return [Section(level=1, title="Body", text=body)]


def _latex_to_text(source: str) -> str:
    try:
        from pylatexenc.latex2text import LatexNodes2Text

        return LatexNodes2Text().latex_to_text(source).strip()
    except Exception:
        rough = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", source)
        return re.sub(r"\s+", " ", rough).strip()


def _inline_inputs(text: str, base: Path, depth: int = 0) -> str:
    if depth > 5:
        return text

    def replace(match: re.Match[str]) -> str:
        path = _resolve_tex(base, match.group(1))
        if path is None:
            return ""
        return _inline_inputs(path.read_text(errors="replace"), path.parent, depth + 1)

    return _INPUT.sub(replace, text)


def _resolve_tex(base: Path, name: str) -> Path | None:
    candidate = Path(name)
    if candidate.suffix != ".tex":
        candidate = candidate.with_suffix(".tex")
    path = (base / candidate).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def _main_tex(tex_files: list[Path]) -> Path | None:
    if not tex_files:
        return None
    classed = [path for path in tex_files if r"\documentclass" in path.read_text(errors="replace")]
    pool = classed or tex_files
    named = [path for path in pool if path.stem.lower() in {"main", "paper", "ms"}]
    if named:
        return named[0]
    return max(pool, key=lambda path: path.stat().st_size)


def _looks_like_tar(blob: bytes) -> bool:
    try:
        tarfile.open(fileobj=io.BytesIO(blob), mode="r:*").close()
    except tarfile.TarError:
        return False
    return True
