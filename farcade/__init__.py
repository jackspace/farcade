"""Farcade: an arcade at a distance.

Turn-based games over low-bandwidth, high-latency links. See docs/spec.md.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("farcade")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0+source"
