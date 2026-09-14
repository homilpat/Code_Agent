from kh_agent.application import Application


def test_loose_branch_head_is_normal(environment):
    result = Application(environment.db).execute("status", environment.repo)
    assert result["branch"] == "main"
    assert result["declared_head_oid"] == "a" * 40
    assert result["head_state"] == "NORMAL"


def test_packed_branch_head_is_normal(environment):
    git = environment.repo / ".git"
    (git / "refs/heads/main").unlink()
    (git / "packed-refs").write_bytes(b"b" * 40 + b" refs/heads/main\n")
    result = Application(environment.db).execute("status", environment.repo)
    assert result["declared_head_oid"] == "b" * 40
    assert result["head_state"] == "NORMAL"


def test_detached_head_is_unchanged(environment):
    (environment.repo / ".git/HEAD").write_bytes(b"c" * 40 + b"\n")
    result = Application(environment.db).execute("status", environment.repo)
    assert result["branch"] is None
    assert result["head_state"] == "DETACHED"
