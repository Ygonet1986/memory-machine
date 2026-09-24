import copy
import json
from pathlib import Path

import pytest

from memory_machine.companion_persona import render_persona_prompt, validate_sheet
from memory_machine.secrets import SecretError


TEMPLATE = Path(__file__).resolve().parents[1] / "personas" / "lia" / "v1.json"


def sheet():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_template_valid_and_render_deterministic():
    data = sheet()
    assert validate_sheet(data) == data
    assert render_persona_prompt(data) == render_persona_prompt(data)
    prompt = render_persona_prompt(data)
    for value in [data["voice"], *data["values"], *data["boundaries"], *data["bio"]]:
        assert value in prompt
    assert "ficcionais e histórias não são fatos" in prompt
    assert "sem culpa ou exclusividade" in prompt


@pytest.mark.parametrize("field,value", [
    ("name", ""), ("voice", "x" * 501), ("version", 0), ("version", True),
    ("version", 1.5), ("language", "en-US"), ("bio", ["a", "b"]),
    ("bio", ["a"] * 13), ("values", []), ("boundaries", ["a\nb"]),
])
def test_reject_invalid_sheet(field, value):
    data = sheet()
    data[field] = value
    with pytest.raises(ValueError):
        validate_sheet(data)


def test_reject_extra_fields_and_secrets_without_echo():
    data = copy.deepcopy(sheet())
    data["token"] = "hidden"
    with pytest.raises(ValueError):
        validate_sheet(data)
    del data["token"]
    secret = "sk-" + "x" * 30
    data["bio"][0] = secret
    with pytest.raises(SecretError) as exc:
        render_persona_prompt(data)
    assert secret not in str(exc.value)
