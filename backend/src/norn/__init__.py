"""Norn: all your home cameras in one place."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("norn-hub")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0"
