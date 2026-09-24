from app.services.fact_extraction import _parse_json


def test_fact_extraction_accepts_fenced_json() -> None:
    value = _parse_json('```json\n{"facts": []}\n```')
    assert value == {"facts": []}


def test_fact_extraction_rejects_non_json() -> None:
    try:
        _parse_json("模型没有返回结构化事实")
    except ValueError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("expected ValueError")
