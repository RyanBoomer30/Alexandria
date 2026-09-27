"""ArXiv identifier parsing. Accepts bare ids and abs, pdf, html, and src URLs."""

import re
from dataclasses import dataclass

from paperpath.errors import IngestionError

_NEW_ID = r"(\d{4}\.\d{4,5})"
_OLD_ID = r"([a-z-]+(?:\.[A-Z]{2})?/\d{7})"
_VERSION = r"(v(\d+))?"

_BARE = re.compile(rf"^(?:arxiv:)?(?:{_NEW_ID}|{_OLD_ID}){_VERSION}$", re.IGNORECASE)
_URL = re.compile(
    rf"""
    arxiv\.org/
    (?:abs|pdf|html|src|e-print|format)/
    (?:{_NEW_ID}|{_OLD_ID})
    {_VERSION}
    (?:\.pdf)?
    /?
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class ArxivId:
    """A paper id, with the version split off when the caller supplied one."""

    base: str
    version: int | None = None

    @property
    def canonical(self) -> str:
        if self.version is None:
            return self.base
        return f"{self.base}v{self.version}"

    @property
    def work_id(self) -> str:
        """Identity of the work, ignoring version. Used to avoid recommending the target."""
        return f"arxiv:{self.base.lower()}"

    def with_version(self, version: int) -> "ArxivId":
        return ArxivId(base=self.base, version=version)

    @property
    def filename_token(self) -> str:
        return self.canonical.replace("/", "_")


def parse_arxiv_id(value: str) -> ArxivId:
    text = value.strip()
    if not text:
        raise IngestionError("An arXiv URL or id is required.")

    bare = _BARE.match(text)
    if bare:
        return _from_match(bare)

    # Drop a scheme and www so the URL pattern stays small.
    stripped = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    stripped = re.sub(r"^www\.", "", stripped, flags=re.IGNORECASE)
    stripped = stripped.split("?", 1)[0].split("#", 1)[0]
    url = _URL.search(stripped)
    if url:
        return _from_match(url)

    raise IngestionError(f"Could not parse an arXiv id from {value!r}.")


def _from_match(match: re.Match[str]) -> ArxivId:
    new_id, old_id, _version_token, version_num = match.groups()
    base = new_id or old_id
    if base is None:
        raise IngestionError(f"Could not parse an arXiv id from {match.string!r}.")
    # New-style ids are case-insensitive. Old-style archive prefixes are lowercase.
    if new_id:
        base = base.lower()
    else:
        archive, number = base.split("/", 1)
        base = f"{archive.lower()}/{number}"
    version = int(version_num) if version_num else None
    return ArxivId(base=base, version=version)
