from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from helpers import run_pipx_cli
from pipx import paths
from pipx.backends.pip import PipBackend
from pipx.backends.uv import UvBackend


def test_install_pip_with_uv_backend_errors(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = run_pipx_cli(["install", "pip", "--backend", "uv"])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "'pip' package cannot be installed or exposed via the uv backend" in captured.err


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv binary not on PATH; skipping uv integration smoke")
def test_uv_backend_install_uninstall_smoke(pipx_temp_env, capsys: pytest.CaptureFixture[str]) -> None:
    # Asserts that a uv-built venv records ``backend="uv"``, exposes apps the
    # same way pip venvs do, and uninstalls without re-invoking uv.
    install_rc = run_pipx_cli(["install", "pycowsay", "--backend", "uv", "--python", sys.executable])
    captured = capsys.readouterr()
    assert install_rc == 0, captured.err

    metadata_file = paths.ctx.venvs / "pycowsay" / "pipx_metadata.json"
    assert metadata_file.is_file()
    assert '"backend": "uv"' in metadata_file.read_text()

    list_rc = run_pipx_cli(["list", "--short"])
    list_out = capsys.readouterr().out
    assert list_rc == 0
    assert "pycowsay" in list_out

    uninstall_rc = run_pipx_cli(["uninstall", "pycowsay"])
    assert uninstall_rc == 0
    assert not metadata_file.exists()


def test_pip_backend_install_passes_dry_run(fake_process, tmp_path: Path) -> None:
    venv_root = tmp_path / "venv"
    venv_python = tmp_path / "venv" / "bin" / "python"
    expected_cmd = [
        str(venv_python),
        "-m",
        "pip",
        "--no-input",
        "install",
        "--upgrade",
        "--dry-run",
        "pycowsay",
    ]
    fake_process.register(expected_cmd, stdout="Would install pycowsay-1.2.3\n")

    backend = PipBackend()
    backend.install(
        venv_root=venv_root,
        venv_python=venv_python,
        requirements=["pycowsay"],
        pip_args=[],
        upgrade=True,
        dry_run=True,
    )

    invocations = list(fake_process.calls)
    assert invocations and invocations[-1] == expected_cmd


def test_pip_backend_install_omits_dry_run_by_default(fake_process, tmp_path: Path) -> None:
    venv_root = tmp_path / "venv"
    venv_python = tmp_path / "venv" / "bin" / "python"
    expected_cmd = [
        str(venv_python),
        "-m",
        "pip",
        "--no-input",
        "install",
        "pycowsay",
    ]
    fake_process.register(expected_cmd, stdout="")

    backend = PipBackend()
    backend.install(
        venv_root=venv_root,
        venv_python=venv_python,
        requirements=["pycowsay"],
        pip_args=[],
    )

    invocations = list(fake_process.calls)
    assert invocations and "--dry-run" not in invocations[-1]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv binary not on PATH; skipping uv plumbing test")
def test_uv_backend_install_passes_dry_run(fake_process, tmp_path: Path) -> None:
    venv_root = tmp_path / "venv"
    venv_python = tmp_path / "venv" / "bin" / "python"
    uv_path = shutil.which("uv")
    assert uv_path is not None
    fake_process.register([uv_path, "--version"], stdout="uv 0.4.0\n", occurrences=2)
    fake_process.keep_last_process(True)
    backend = UvBackend()
    fake_process.register(
        [str(backend._binary), "pip", "install", "--python", str(venv_python), fake_process.any()],
        stdout=(
            "Resolved 1 package in 2.05s\n"
            "Would download 1 package\n"
            "Would install 1 package\n"
            " + pycowsay==1.2.3\n"
        ),
    )

    backend.install(
        venv_root=venv_root,
        venv_python=venv_python,
        requirements=["pycowsay"],
        pip_args=[],
        upgrade=True,
        dry_run=True,
    )

    last_call = list(fake_process.calls)[-1]
    assert "--dry-run" in last_call
    assert "--upgrade" in last_call
