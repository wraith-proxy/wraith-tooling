import json

import pytest

from wraith_tools.layout import plugin_root


def market(repo, source):
    path = repo / ".claude-plugin" / "marketplace.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"plugins": [{"source": source}]}))


def test_no_marketplace_means_repo_root(tmp_path):
    assert plugin_root(tmp_path) == tmp_path


def test_dot_slash_means_repo_root(tmp_path):
    market(tmp_path, "./")
    assert plugin_root(tmp_path) == tmp_path


def test_subfolder_source(tmp_path):
    market(tmp_path, "./plugin")
    assert plugin_root(tmp_path) == tmp_path / "plugin"


@pytest.mark.parametrize("source", ["../x", "plugin", "./a/../..", 3])
def test_unsafe_or_odd_source_is_rejected(tmp_path, source):
    market(tmp_path, source)
    with pytest.raises(ValueError):
        plugin_root(tmp_path)
