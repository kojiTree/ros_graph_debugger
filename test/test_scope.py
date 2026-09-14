"""Profile scope parsing and node allowlist matching."""

import pytest

from ros_graph_debugger.profile import load_profile
from ros_graph_debugger.scope import ScopeConfig


def test_profile_parses_node_allowlist(tmp_path):
    profile = tmp_path / 'scoped.yaml'
    profile.write_text(
        'name: scoped\n'
        'scope:\n'
        '  node_allowlist:\n'
        "    - '^/camera/.*'\n"
        "    - '^/planner$'\n")

    data, name = load_profile(str(profile))

    assert name == 'scoped'
    assert isinstance(data['_scope'], ScopeConfig)
    assert data['_scope'].node_allowlist == ['^/camera/.*', '^/planner$']
    assert data['_scope'].active


@pytest.mark.parametrize('contents', [
    'name: missing\n',
    'name: empty\nscope: {}\n',
    "name: invalid\nscope:\n  node_allowlist: ['[']\n",
])
def test_missing_empty_or_invalid_scope_is_inactive(tmp_path, contents):
    profile = tmp_path / 'profile.yaml'
    profile.write_text(contents)

    data, _ = load_profile(str(profile))
    scope = data['_scope']

    assert not scope.active
    assert scope.matches_node('/any/fully_qualified_node')


def test_scope_matches_fully_qualified_node_ids_and_skips_invalid_patterns():
    scope = ScopeConfig(node_allowlist=['[', '^/camera/.*', '^/planner$'])

    assert scope.active
    assert scope.matches_node('/camera/front')
    assert scope.matches_node('/planner')
    assert not scope.matches_node('/camera_driver')
    assert not scope.matches_node('/planner/helper')
