"""Agent CLI configuration tests."""

import pytest

from ros_graph_debugger.agent import _apply_scope_override, _parse_args
from ros_graph_debugger.model import RuntimeGraphStore
from ros_graph_debugger.scope import ScopeConfig
from ros_graph_debugger.server import create_app


def test_scope_node_flag_is_repeatable():
    args = _parse_args([
        '--scope-node', '^/camera/.*', '--scope-node', '^/planner$'])

    assert args.scope_node == ['^/camera/.*', '^/planner$']


def test_profile_help_lists_bundled_scope_example(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(['--help'])

    assert exc_info.value.code == 0
    assert 'scope-example' in capsys.readouterr().out


def test_scope_node_flag_overrides_profile_scope():
    profile_data = {
        'name': 'custom',
        '_scope': ScopeConfig(node_allowlist=['^/from_profile$']),
    }

    result = _apply_scope_override(profile_data, ['^/from_cli$'])

    assert result is profile_data
    assert result['_scope'].node_allowlist == ['^/from_cli$']


def test_scope_node_override_warns_for_each_invalid_regex(capsys):
    result = _apply_scope_override(
        None, ['^/bad[', '^/valid$', '(unclosed'])

    assert result['_scope'].effective_node_allowlist == ['^/valid$']
    assert capsys.readouterr().out.splitlines() == [
        '[warn] bad --scope-node regex: ^/bad[',
        '[warn] bad --scope-node regex: (unclosed',
    ]


def test_scope_node_override_with_only_invalid_regex_warns_and_is_inactive(
        capsys):
    result = _apply_scope_override(None, ['^/bad['])

    assert not result['_scope'].active
    assert capsys.readouterr().out.strip() == \
        '[warn] bad --scope-node regex: ^/bad['


def test_scope_node_override_without_profile_creates_serving_config():
    result = _apply_scope_override(None, ['^/standalone$'])
    app = create_app(RuntimeGraphStore(), '/nonexistent', profile_data=result)
    profile_route = next(
        route for route in app.routes if route.path == '/api/v1/profile')

    assert result['_scope'].effective_node_allowlist == ['^/standalone$']
    assert profile_route.endpoint() == {
        'name': None,
        'groups': {},
        'scope': {'node_allowlist': ['^/standalone$']},
    }


def test_absent_scope_node_flag_preserves_profile_scope():
    profile_scope = ScopeConfig(node_allowlist=['^/from_profile$'])
    profile_data = {'_scope': profile_scope}

    result = _apply_scope_override(profile_data, None)

    assert result['_scope'] is profile_scope
