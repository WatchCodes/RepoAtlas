from repoatlas.classify import classify_url


def test_repo_root():
    c = classify_url("https://github.com/NousResearch/hermes-agent")
    assert c["kind"] == "repo_root"
    assert c["repository"] == "NousResearch/hermes-agent"


def test_deep_link_resolves_repo():
    c = classify_url("https://github.com/NousResearch/hermes-agent/issues/1")
    assert c["kind"] == "deep_link"
    assert c["repository"] == "NousResearch/hermes-agent"


def test_profile_not_repo():
    c = classify_url("https://github.com/NousResearch")
    assert c["kind"] == "profile"
    assert c["repository"] is None
