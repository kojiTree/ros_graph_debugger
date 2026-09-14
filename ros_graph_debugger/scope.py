"""
Configuration for selecting the nodes shown in a graph view.

This module deliberately has no ROS dependencies so profile loading and graph
consumers can share it without importing :mod:`rclpy`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class ScopeConfig:
    """
    Node allowlist patterns for a graph view.

    Patterns are searched against fully-qualified node ids.  An inactive scope
    includes every node, preserving the unfiltered view when no usable patterns
    were configured.
    """

    node_allowlist: list[str] = field(default_factory=list)
    _node_allowlist_re: list[re.Pattern[str]] = field(
        default_factory=list, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._recompile()

    def _recompile(self) -> None:
        compiled = []
        for pattern in self.node_allowlist:
            if not isinstance(pattern, str):
                continue
            try:
                compiled.append(re.compile(pattern))
            except (re.error, TypeError):
                continue
        self._node_allowlist_re = compiled

    def set_node_allowlist(self, patterns: Iterable[str]) -> None:
        """Replace the node allowlist and rebuild its compiled cache."""
        self.node_allowlist = list(patterns)
        self._recompile()

    @property
    def active(self) -> bool:
        """Whether this scope has at least one usable allowlist pattern."""
        return bool(self._node_allowlist_re)

    def matches_node(self, node_id: str) -> bool:
        """Return whether a fully-qualified node id belongs in this scope."""
        if not self.active:
            return True
        return any(pattern.search(node_id) for pattern in self._node_allowlist_re)
