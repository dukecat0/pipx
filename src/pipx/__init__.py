import sys

if sys.version_info < (3, 7, 0):
    sys.exit(
        "Python 3.7 or later is required. "
        "See https://github.com/pypa/pipx "
        "for installation instructions."
    )
