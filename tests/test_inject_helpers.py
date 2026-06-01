"""Local unit tests for scripts/inject_env_values.py helpers.
Run from repo root: python tests/test_inject_helpers.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from inject_env_values import _replace_m_param, _find_part, _decode_part, _encode_part

REPO = Path(__file__).resolve().parent.parent
EXPR = REPO / "fabric" / "Contoso-Sales-Model.SemanticModel" / "definition" / "expressions.tmdl"


def test_replace_existing_param():
    """Replace works against whatever is currently committed — Dev IDs on dev branch,
    Prod IDs on prod branch. Asserts on STRUCTURE (replacement happened, old value
    matches the GUID shape), not on the literal pre-replacement value."""
    text = EXPR.read_text(encoding="utf-8")
    new_text, old = _replace_m_param(text, "WorkspaceId", "TEST-WS-ID")
    assert old is not None and len(old) >= 32, f"unexpected old: {old}"
    assert "TEST-WS-ID" in new_text
    new_text2, old2 = _replace_m_param(new_text, "LakehouseId", "TEST-LH-ID")
    assert old2 is not None and len(old2) >= 32, f"unexpected old: {old2}"
    assert "TEST-LH-ID" in new_text2


def test_idempotent_replace():
    text = EXPR.read_text(encoding="utf-8")
    new_text, _ = _replace_m_param(text, "WorkspaceId", "TEST-WS-ID")
    new_text2, old = _replace_m_param(new_text, "WorkspaceId", "TEST-WS-ID")
    assert old is None
    assert new_text2 == new_text


def test_missing_param_raises():
    text = EXPR.read_text(encoding="utf-8")
    try:
        _replace_m_param(text, "BogusParam", "X")
    except RuntimeError as e:
        assert "No M parameter" in str(e)
    else:
        raise AssertionError("should have raised")


def test_duplicate_param_raises():
    text = EXPR.read_text(encoding="utf-8")
    dup_line = '\nexpression WorkspaceId = "dup" meta [IsParameterQuery=true]'
    dup = text + dup_line
    try:
        _replace_m_param(dup, "WorkspaceId", "X")
    except RuntimeError as e:
        assert "Multiple" in str(e)
    else:
        raise AssertionError("should have raised")


def test_base64_roundtrip():
    sample = "hello fabric"
    encoded = _encode_part(sample)
    decoded = _decode_part({"payloadType": "InlineBase64", "payload": encoded})
    assert decoded == sample


def test_find_part_flexible():
    parts = [
        {"path": "definition/expressions.tmdl"},
        {"path": "valueSets/Dev.json"},
        {"path": "valueSets/Prod.json"},
    ]
    assert _find_part(parts, "definition/expressions.tmdl") is parts[0]
    assert _find_part(parts, "valueSets/Dev.json") is parts[1]
    assert _find_part(parts, "valueSets/Foo.json") is None
    # endswith fallback (matches the doc note about valueSet vs valueSets path variance)
    parts_variant = [{"path": "items/x/valueSet/Dev.json"}]
    assert _find_part(parts_variant, "valueSet/Dev.json") is parts_variant[0]


if __name__ == "__main__":
    test_replace_existing_param()
    test_idempotent_replace()
    test_missing_param_raises()
    test_duplicate_param_raises()
    test_base64_roundtrip()
    test_find_part_flexible()
    print("ALL TESTS PASSED")
