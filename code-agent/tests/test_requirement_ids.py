import pytest
from conftest import DESIGN, design_test_ids, requirement_coverage


def test_design_document_defines_the_m01_and_m02_test_ids():
    defined = design_test_ids(DESIGN.read_text(encoding="utf-8"))
    assert len(defined) == 111
    assert {"M01-UT-001", "M01-SEC-008", "M02-CTX-007", "M02-PRS-005"} <= defined
    # Requirement references such as M01-FR-01 are not test IDs.
    assert not any("-FR-" in test_id for test_id in defined)


def test_markers_map_ids_and_separate_partial_coverage():
    defined = {"M01-UT-001", "M01-UT-002"}
    covered, partial = requirement_coverage(
        [
            ("tests/a.py::test_full", ("M01-UT-001",), {}),
            ("tests/a.py::test_unit_only", ("M01-UT-002",), {"partial": True}),
        ],
        defined,
    )
    assert covered == {"M01-UT-001": {"tests/a.py::test_full"}}
    assert partial == {"M01-UT-002": {"tests/a.py::test_unit_only"}}


@pytest.mark.parametrize(
    "ids, options",
    [(("M01-UT-999",), {}), ((), {}), (("M01-UT-001",), {"parital": True})],
    ids=["unknown-id", "empty", "misspelled-option"],
)
def test_invalid_markers_are_rejected(ids, options):
    with pytest.raises(ValueError):
        requirement_coverage([("tests/a.py::test_x", ids, options)], {"M01-UT-001"})
