import json
from contextlib import contextmanager

import pytest

from asksql.model import ModelFailure, call_model


@pytest.mark.parametrize(
    "content", [{"sql": 42}, {"sql": "SELECT 1", "extra": "unexpected"}, "broken"]
)
def test_model_schema_rejects_invalid_types_and_fields(monkeypatch, content):
    from asksql import model

    class Response:
        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield json.dumps(
                {
                    "message": {
                        "content": json.dumps(content) if isinstance(content, dict) else content
                    }
                }
            ).encode()

    @contextmanager
    def stream(*args, **kwargs):
        assert kwargs["json"]["format"]["type"] == "object"
        assert kwargs["json"]["options"]["num_predict"] == 512
        yield Response()

    monkeypatch.setattr(model.httpx, "stream", stream)
    with pytest.raises(ModelFailure):
        call_model([])


def test_model_response_size_is_bounded(monkeypatch):
    from asksql import model

    class Response:
        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"x" * 65537

    @contextmanager
    def stream(*args, **kwargs):
        yield Response()

    monkeypatch.setattr(model.httpx, "stream", stream)
    with pytest.raises(ModelFailure):
        call_model([])
