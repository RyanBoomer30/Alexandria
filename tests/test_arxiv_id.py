import pytest

from paperpath.domain.arxiv import parse_arxiv_id
from paperpath.errors import IngestionError


@pytest.mark.parametrize(
    ("raw", "base", "version"),
    [
        ("1706.03762", "1706.03762", None),
        ("1706.03762v7", "1706.03762", 7),
        ("arXiv:1706.03762v3", "1706.03762", 3),
        ("https://arxiv.org/abs/1706.03762", "1706.03762", None),
        ("https://arxiv.org/pdf/1706.03762.pdf", "1706.03762", None),
        ("https://arxiv.org/pdf/1706.03762v3.pdf", "1706.03762", 3),
        ("https://arxiv.org/html/1706.03762v1", "1706.03762", 1),
        ("https://arxiv.org/src/1706.03762", "1706.03762", None),
        ("hep-th/9901001", "hep-th/9901001", None),
        ("https://arxiv.org/abs/hep-th/9901001v2", "hep-th/9901001", 2),
        ("https://arxiv.org/abs/cs.AI/0601001", "cs.ai/0601001", None),
    ],
)
def test_parse_arxiv_id(raw: str, base: str, version: int | None) -> None:
    parsed = parse_arxiv_id(raw)
    assert parsed.base == base
    assert parsed.version == version
    if version is None:
        assert parsed.canonical == base
    else:
        assert parsed.canonical == f"{base}v{version}"


def test_parse_arxiv_id_rejects_junk() -> None:
    with pytest.raises(IngestionError):
        parse_arxiv_id("not a paper")
