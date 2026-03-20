from pipx.progress import InstallProgress


def test_collecting_shows_dependency_names(monkeypatch):
    progress = InstallProgress("black")
    progress.stderr_is_tty = False

    shown_messages = []
    monkeypatch.setattr(progress, "_display_progress", shown_messages.append)

    progress.parse_line("Collecting black")
    progress.parse_line("Collecting click>=8.0")
    progress.parse_line("Collecting platformdirs<5,>=2")

    assert shown_messages == [
        "📦 Resolving dependency: black (1 total)",
        "📦 Resolving dependency: click (2 total)",
        "📦 Resolving dependency: platformdirs (3 total)",
    ]


def test_installing_packages_message_is_summarized(monkeypatch):
    progress = InstallProgress("black")
    progress.stderr_is_tty = False

    shown_messages = []
    monkeypatch.setattr(progress, "_display_progress", shown_messages.append)

    progress.parse_line(
        "Installing collected packages: appdirs, attrs, click, mypy-extensions, packaging, pathspec, platformdirs"
    )

    assert shown_messages == [
        "📦 Installing: appdirs, attrs, click, mypy-extensions, packaging, ... (+2 more)"
    ]


def test_downloading_parses_hyphenated_package_name(monkeypatch):
    progress = InstallProgress("black")
    progress.stderr_is_tty = False

    shown_messages = []
    monkeypatch.setattr(progress, "_display_progress", shown_messages.append)

    progress.parse_line("Downloading prompt_toolkit-3.0.51-py3-none-any.whl (388 kB)")

    assert shown_messages == ["⬇️  Downloading prompt-toolkit (388 kB)..."]


def test_downloading_parses_package_name_from_url(monkeypatch):
    progress = InstallProgress("black")
    progress.stderr_is_tty = False

    shown_messages = []
    monkeypatch.setattr(progress, "_display_progress", shown_messages.append)

    progress.parse_line(
        "Downloading https://files.pythonhosted.org/packages/ab/cd/charset_normalizer-3.4.4-py3-none-any.whl"
    )

    assert shown_messages == ["⬇️  Downloading charset-normalizer..."]


def test_downloading_unknown_artifact_uses_neutral_message(monkeypatch):
    progress = InstallProgress("black")
    progress.stderr_is_tty = False

    shown_messages = []
    monkeypatch.setattr(progress, "_display_progress", shown_messages.append)

    progress.parse_line("Downloading https://example.invalid/download?id=12345")

    assert shown_messages == ["⬇️  Downloading dependency..."]


def test_keep_alive_message_for_installing_phase():
    progress = InstallProgress("black")
    progress.current_action = "Installing"

    assert progress._build_keep_alive_message(12) == "⏳ Still installing packages... (12s elapsed)"


def test_keep_alive_message_for_dependency_processing_phase():
    progress = InstallProgress("black")
    progress.current_action = "Using cached"

    assert progress._build_keep_alive_message(9) == "⏳ Still processing dependencies... (9s elapsed)"
