from app.router import route_topic

from fakes import FakeClient


def _topics():
    return [
        {
            "id": "20260907-233512",
            "name": "2026-09-07 23:35",
            "label": "",
            "summary": "decidir o banco de dados Postgres",
        },
        {
            "id": "20260908-091200",
            "name": "2026-09-08 09:12",
            "label": "login",
            "summary": "migração do login OAuth",
        },
    ]


def test_route_returns_topic_id():
    client = FakeClient(lambda messages, temperature: '{"topic_id": "20260907-233512"}')
    assert route_topic(client, _topics(), "o que decidimos ontem sobre o banco?") == "20260907-233512"


def test_route_returns_none():
    client = FakeClient(lambda messages, temperature: '{"topic_id": null}')
    assert route_topic(client, _topics(), "vamos começar algo novo") is None


def test_route_ignores_unknown_id():
    client = FakeClient(lambda messages, temperature: '{"topic_id": "nope"}')
    assert route_topic(client, _topics(), "mensagem qualquer") is None


def test_route_no_topics():
    client = FakeClient(lambda messages, temperature: '{"topic_id": "x"}')
    assert route_topic(client, [], "mensagem") is None


def test_route_fenced_json():
    client = FakeClient(
        lambda messages, temperature: 'Sure.\n```json\n{"topic_id":"20260908-091200"}\n```'
    )
    assert route_topic(client, _topics(), "sobre o login") == "20260908-091200"
