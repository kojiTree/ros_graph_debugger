"""Configuration and snapshot filtering for node-scoped graph views.

This module deliberately has no ROS dependencies so profile loading and graph
consumers can share it without importing :mod:`rclpy`.  Nodes are the sole
allowlist: topics are derived from their retained publisher/subscriber
endpoints, and graph edges must connect two retained nodes through a retained
topic.  Callbacks and issues are filtered through their node/topic references.
TF edges and diagnostics stay global because their identifiers are frames and
arbitrary status names rather than node ids, so applying node regexes to them
would be misleading.  Existing topic analysis fields (including ``status`` and
``qos_status``) are preserved rather than recomputed: this pure view transform
does not rerun analysis after narrowing endpoint counts.
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

    @property
    def effective_node_allowlist(self) -> list[str]:
        """Patterns that compiled successfully and are applied to the view."""
        return [pattern.pattern for pattern in self._node_allowlist_re]

    def matches_node(self, node_id: str) -> bool:
        """Return whether a fully-qualified node id belongs in this scope."""
        if not self.active:
            return True
        return any(pattern.search(node_id) for pattern in self._node_allowlist_re)


def filter_snapshot(snapshot: dict, scope: ScopeConfig) -> dict:
    """Return a copy of ``snapshot`` narrowed to ``scope``'s node allowlist.

    An inactive scope returns the original snapshot unchanged.  The active
    path does not mutate either argument and preserves unrecognised top-level
    snapshot fields for forward compatibility.
    """
    if not scope.active:
        return snapshot

    node_ids = {
        node_id for node in snapshot.get('nodes', [])
        if (node_id := node.get('id')) is not None
        and scope.matches_node(node_id)
    }

    topics = []
    for topic in snapshot.get('topics', []):
        publishers = [node for node in topic.get('publishers', [])
                      if node in node_ids]
        subscribers = [node for node in topic.get('subscribers', [])
                       if node in node_ids]
        if not publishers and not subscribers:
            continue
        narrowed = dict(topic)
        narrowed['publishers'] = publishers
        narrowed['subscribers'] = subscribers
        narrowed['publisher_count'] = len(publishers)
        narrowed['subscriber_count'] = len(subscribers)
        if 'qos_endpoints' in narrowed:
            narrowed['qos_endpoints'] = [
                endpoint for endpoint in narrowed.get('qos_endpoints', [])
                if endpoint.get('node') in node_ids
            ]
        topics.append(narrowed)

    topic_names = {topic.get('name') for topic in topics}
    nodes = []
    for node in snapshot.get('nodes', []):
        if node.get('id') not in node_ids:
            continue
        narrowed = dict(node)
        narrowed['publishers'] = [topic for topic in node.get('publishers', [])
                                  if topic in topic_names]
        narrowed['subscribers'] = [topic for topic in node.get('subscribers', [])
                                   if topic in topic_names]
        nodes.append(narrowed)

    edges = [
        edge for edge in snapshot.get('edges', [])
        if edge.get('from_node') in node_ids
        and edge.get('to_node') in node_ids
        and edge.get('topic') in topic_names
    ]
    callbacks = [
        callback for callback in snapshot.get('callbacks', [])
        if callback.get('node') in node_ids
        and (not callback.get('topic')
             or callback.get('topic') in topic_names)
    ]

    issues = []
    for issue in snapshot.get('issues', []):
        related_nodes = issue.get('related_nodes', [])
        related_topics = issue.get('related_topics', [])
        if ((related_nodes or related_topics)
                and not (node_ids.intersection(related_nodes)
                         or topic_names.intersection(related_topics))):
            continue
        narrowed = dict(issue)
        narrowed['related_nodes'] = [node for node in related_nodes
                                     if node in node_ids]
        narrowed['related_topics'] = [topic for topic in related_topics
                                      if topic in topic_names]
        issues.append(narrowed)

    result = dict(snapshot)
    result.update(nodes=nodes, topics=topics, edges=edges,
                  callbacks=callbacks, issues=issues)
    return result
