from repoatlas.rename import canonical_target_name, ext_collision_name


def test_keeps_nastech_prefix():
    r = canonical_target_name("nastech-agent")
    assert r.target == "nastech-agent"
    assert r.status == "OK"


def test_replaces_hermes_and_nous():
    assert canonical_target_name("hermes-agent").target == "nastech-agent"
    assert canonical_target_name("nous-research-tool").target == "nastech-research-tool"
    assert canonical_target_name("my-hermes-plugin").target == "my-nastech-plugin"


def test_ext_collision_name():
    assert ext_collision_name("nastech-agent", "foo") == "nastech-agent-ext-foo"
