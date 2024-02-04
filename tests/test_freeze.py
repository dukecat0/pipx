import json

from helpers import run_pipx_cli
from package_info import PKG


def test_freeze(pipx_temp_env, monkeypatch, capsys):
    assert not run_pipx_cli(["install", "pycowsay", PKG["black"]["spec"]])
    assert not run_pipx_cli(
        ["inject", "black", PKG["nox"]["spec"], PKG["pylint"]["spec"]]
    )
    captured = capsys.readouterr()

    assert not run_pipx_cli(["freeze"])
    captured = capsys.readouterr()

    json_parsed = json.loads(captured.out)

    assert sorted(json_parsed["venvs"].keys()) == ["black", "pycowsay"]
    assert sorted(
        json_parsed["venvs"]["black"]["metadata"]["injected_packages"].keys()
    ) == ["nox", "pylint"]
