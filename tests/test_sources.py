import io
import tarfile
from datetime import datetime

from paperpath.clients.arxiv import parse_atom
from paperpath.clients.semantic_scholar import candidate_from_s2, canonical_work_id
from paperpath.clients.source import sections_from_latex, unpack_arxiv_source
from paperpath.domain.arxiv import ArxivId

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is All You Need</title>
    <summary>We propose a new network architecture.</summary>
    <author><name>Ashish Vaswani</name></author>
    <category term="cs.CL" />
    <category term="cs.LG" />
  </entry>
</feed>
"""


def test_parse_atom_keeps_the_resolved_version() -> None:
    paper = parse_atom(ATOM, requested=ArxivId("1706.03762"))
    assert paper.key == "1706.03762v7"
    assert paper.version == 7
    assert paper.title == "Attention Is All You Need"
    assert paper.authors == ["Ashish Vaswani"]
    assert paper.categories == ["cs.CL", "cs.LG"]
    assert paper.published == datetime.fromisoformat("2017-06-12T17:57:34+00:00")


def test_unpack_and_section_a_source_bundle(tmp_path) -> None:
    blob = io.BytesIO()
    with tarfile.open(fileobj=blob, mode="w:gz") as archive:
        payload = (
            b"\\documentclass{article}\n"
            b"\\begin{document}\n"
            b"\\section{Model}\n"
            b"Attention is computed in closed form.\n"
            b"\\subsection{Complexity}\n"
            b"The cost is quadratic.\n"
            b"\\end{document}\n"
        )
        info = tarfile.TarInfo("main.tex")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    tex_files = unpack_arxiv_source(blob.getvalue(), tmp_path / "src")
    sections = sections_from_latex((tmp_path / "src" / "main.tex").read_text())
    assert any(path.name == "main.tex" for path in tex_files)
    titles = [section.title for section in sections]
    assert "Model" in titles
    assert "Complexity" in titles


def test_canonical_ids_merge_arxiv_and_doi() -> None:
    assert canonical_work_id(arxiv_id="1706.03762v7") == "arxiv:1706.03762"
    assert canonical_work_id(doi="10.5555/ABC") == "doi:10.5555/abc"
    candidate = candidate_from_s2(
        {
            "isInfluential": True,
            "contexts": ["In related work, prior attention models are discussed."],
            "intents": ["background"],
            "citedPaper": {
                "paperId": "abc",
                "title": "Older Attention",
                "abstract": "An earlier model.",
                "year": 2014,
                "externalIds": {"ArXiv": "1409.0473", "DOI": "10.1/example"},
                "url": "https://arxiv.org/abs/1409.0473",
            },
        }
    )
    assert candidate is not None
    assert candidate.canonical_id == "arxiv:1409.0473"
    assert candidate.influential is True
    assert candidate.contexts[0].section.value == "related_work"
    assert candidate_from_s2({"citedPaper": {"title": "Untitled citation"}}) is None
