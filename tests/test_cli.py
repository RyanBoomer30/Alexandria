import pytest

from paperpath.cli import _parser, _prepare_argv, main


def test_paper_link_is_the_command_argument() -> None:
    args = _parser().parse_args(_prepare_argv(["https://arxiv.org/abs/1706.03762"]))
    assert args.paper == "https://arxiv.org/abs/1706.03762"
    assert args.output is None
    assert args.serve is False


def test_output_flag_and_legacy_subcommands() -> None:
    exported = _parser().parse_args(_prepare_argv(["export", "1706.03762v7", "-o", "vault.zip"]))
    assert exported.paper == "1706.03762v7"
    assert exported.output == "vault.zip"

    generated = _parser().parse_args(_prepare_argv(["generate", "https://arxiv.org/pdf/1706.03762.pdf"]))
    assert generated.paper == "https://arxiv.org/pdf/1706.03762.pdf"

    served = _parser().parse_args(_prepare_argv(["serve", "--port", "9000"]))
    assert served.serve is True
    assert served.port == 9000


def test_missing_link_is_an_error() -> None:
    with pytest.raises(SystemExit) as caught:
        main([])
    assert caught.value.code == 2


def test_help_shows_the_paper_link(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    assert "python -m paperpath PAPER_LINK" in help_text
    assert "https://arxiv.org/abs/1706.03762" in help_text
