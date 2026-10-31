import subprocess
import sys

import pytest

from docdrift import __version__
from docdrift.cli import main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_arguments_prints_help(capsys):
    assert main([]) == 0
    assert "docdrift" in capsys.readouterr().out


def test_runs_as_module():
    result = subprocess.run(
        [sys.executable, "-m", "docdrift", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert f"docdrift {__version__}" in result.stdout
