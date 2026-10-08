import pytest

from asksql import api
from asksql.db import connect
from asksql.guard import validate

BROKEN = [
    "SELECT 'unfinished FROM analytics.sales",
    'SELECT "amount FROM analytics.sales',
    "SELECT $$unfinished FROM analytics.sales",
]


@pytest.mark.parametrize("sql", BROKEN)
def test_lexical_error_is_controlled_refusal(sql):
    with pytest.raises(ValueError, match="SQL не удалось разобрать"):
        validate(sql)


@pytest.mark.parametrize("sql", BROKEN)
def test_api_refuses_without_execute_replays_and_releases_slot(client, monkeypatch, sql):
    monkeypatch.setattr(api, "generate", lambda *args: {"sql": sql})
    calls = []
    original_execute = api.execute

    def execute(owner, query):
        calls.append(query)
        return original_execute(owner, query)

    monkeypatch.setattr(api, "execute", execute)
    headers = {"Idempotency-Key": "malformed"}
    body = {"question": "общая выручка"}
    response = client.post("/ask", json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "refused"
    assert response.json()["reason"] == "SQL не удалось разобрать"
    assert not calls
    monkeypatch.setattr(
        api, "generate", lambda *args: {"sql": "SELECT COUNT(*) FROM analytics.sales"}
    )
    assert client.post("/ask", json=body, headers=headers).json() == response.json()
    assert not calls
    next_response = client.post("/ask", json=body)
    assert next_response.status_code == 200 and next_response.json()["status"] == "completed"
    assert len(calls) == 1
    with connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM questions").fetchone()["n"] == 2
