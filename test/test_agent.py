"""Agent CLI configuration tests."""

from ros_graph_debugger.agent import _apply_scope_override, _parse_args
from ros_graph_debugger.scope import ScopeConfig


def test_scope_node_flag_is_repeatable():
    args = _parse_args([
        '--scope-node', '^/camera/.*', '--scope-node', '^/planner$'])

    assert args.scope_node == ['^/camera/.*', '^/planner$']


def test_scope_node_flag_overrides_profile_scope():
    profile_data = {
        'name': 'custom',
        '_scope': ScopeConfig(node_allowlist=['^/from_profile$']),
    }

    result = _apply_scope_override(profile_data, ['^/from_cli$'])

    assert result is profile_data
    assert result['_scope'].node_allowlist == ['^/from_cli$']


def test_absent_scope_node_flag_preserves_profile_scope():
    profile_scope = ScopeConfig(node_allowlist=['^/from_profile$'])
    profile_data = {'_scope': profile_scope}

    result = _apply_scope_override(profile_data, None)

    assert result['_scope'] is profile_scope
