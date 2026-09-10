from memory_machine.llm import extract_json_object


def test_bare_object():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_fenced_json_block():
    text = 'Here is the result:\n```json\n{"annotations": [{"memory_id": "M0001"}]}\n```\ndone'
    assert extract_json_object(text)["annotations"][0]["memory_id"] == "M0001"


def test_leading_prose():
    text = 'Sure, here you go:\n{"annotations": []}\nHope that helps.'
    assert extract_json_object(text) == {"annotations": []}


def test_no_object():
    assert extract_json_object("nothing here") == {}


def test_empty():
    assert extract_json_object("") == {}
