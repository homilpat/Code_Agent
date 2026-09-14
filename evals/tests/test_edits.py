import pytest

from evals.runner.edits import EditError, apply_edits, parse_edits


def block(path, search, replace):
    return f"{path}\n<<<<<<< SEARCH\n{search}=======\n{replace}>>>>>>> REPLACE\n"


def test_fenced_blocks_apply_in_order_and_create_files(tmp_path):
    (tmp_path / "a.py").write_bytes(b"x = 1\ny = 2\n")
    reply = (
        "Explanation first.\n```python\n"
        + block("a.py", "x = 1\n", "x = 10\n")
        + "```\n\n"
        + block("pkg/b.py", "", "z = 3\n")
    )
    previous = apply_edits(tmp_path, parse_edits(reply))
    assert previous == {"a.py": "x = 1\ny = 2\n", "pkg/b.py": None}
    assert (tmp_path / "a.py").read_bytes() == b"x = 10\ny = 2\n"
    assert (tmp_path / "pkg/b.py").read_bytes() == b"z = 3\n"


@pytest.mark.parametrize(
    "reply",
    [
        block("a.py", "missing\n", "changed\n"),
        block("a.py", "v = 1\n", "changed\n"),
        block("../outside.py", "v = 1\n", "changed\n"),
        block("a.py", "", "exists\n"),
        block("a.py", "w = 2\n", "w = 3\n") + block("a.py", "missing\n", "changed\n"),
    ],
    ids=["no-match", "ambiguous", "escape", "create-existing", "all-or-nothing"],
)
def test_rejected_replies_write_nothing(tmp_path, reply):
    original = b"v = 1\nv = 1\nw = 2\n"
    (tmp_path / "a.py").write_bytes(original)
    with pytest.raises(EditError) as error:
        apply_edits(tmp_path, parse_edits(reply))
    assert error.value.category == "APPLY_ERROR"
    assert (tmp_path / "a.py").read_bytes() == original
    assert not (tmp_path.parent / "outside.py").exists()


@pytest.mark.parametrize(
    "reply", ["no blocks here", "a.py\n<<<<<<< SEARCH\nx\n=======\ny\n", "<<<<<<< SEARCH\n"]
)
def test_malformed_replies_are_format_errors(reply):
    with pytest.raises(EditError) as error:
        parse_edits(reply)
    assert error.value.category == "FORMAT_ERROR"
