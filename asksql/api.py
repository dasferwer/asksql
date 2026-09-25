import hashlib
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from asksql.db import connect, init
from asksql.guard import validate
from asksql.model import SYSTEM, ModelFailure, generate


@asynccontextmanager
async def lifespan(app):
    init()
    yield


def authorize(x_api_key: str = Header(default="")):
    import json

    for key, owner in json.loads(os.environ.get("CLIENT_KEYS", "{}")).items():
        if secrets.compare_digest(key, x_api_key) and owner in {"a", "b"}:
            return owner
    raise HTTPException(401, "Неверный ключ")


app = FastAPI(title="AskSQL", lifespan=lifespan)


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    parent: uuid.UUID | None = None


def execute(owner, sql):
    with psycopg.connect(
        os.environ[f"ANALYTICS_{owner.upper()}_URL"], row_factory=dict_row, connect_timeout=5
    ) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout='1s'")
        conn.execute("SET LOCAL lock_timeout='250ms'")
        conn.execute("SET LOCAL search_path=pg_catalog,analytics")
        plan = conn.execute("EXPLAIN (FORMAT JSON) " + sql).fetchone()["QUERY PLAN"][0]["Plan"]
        if plan["Total Cost"] > 10000:
            raise ValueError("План запроса превышает бюджет стоимости")
        return conn.execute(sql).fetchmany(100)


def conversation(parent, owner):
    messages = []
    with connect() as conn:
        for _ in range(8):
            if not parent:
                break
            row = conn.execute(
                "SELECT question,response,parent FROM questions WHERE id=%s AND owner=%s",
                (parent, owner),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Предыдущий вопрос не найден")
            answer = {
                key: row["response"][key]
                for key in ("sql", "clarification", "explanation")
                if key in row["response"]
            }
            messages[0:0] = [
                {"role": "user", "content": row["question"]},
                {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
            ]
            parent = row["parent"]
    if sum(len(m["content"]) for m in messages) > 10000:
        raise HTTPException(422, "Контекст слишком длинный; начните новую цепочку")
    return messages


@app.post("/ask")
def ask(
    body: Question,
    owner: Annotated[str, Depends(authorize)],
    idempotency_key: str | None = Header(default=None, max_length=120),
):
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    with connect() as guard:
        guard.autocommit = True
        lock = 350100 + (owner == "b")
        if not guard.execute("SELECT pg_try_advisory_lock(%s) AS ok", (lock,)).fetchone()["ok"]:
            raise HTTPException(429, "У клиента уже выполняется вопрос; повторите позже")
        try:
            if idempotency_key:
                saved = guard.execute(
                    "SELECT * FROM requests WHERE owner=%s AND key=%s", (owner, idempotency_key)
                ).fetchone()
                if saved:
                    if saved["fingerprint"] != fingerprint:
                        raise HTTPException(409, "Ключ уже использован для другого вопроса")
                    return saved["response"]
            return answer(body, owner, idempotency_key, fingerprint)
        finally:
            guard.execute("SELECT pg_advisory_unlock(%s)", (lock,))


def answer(body, owner, request_key, fingerprint):
    started = time.monotonic()
    previous = conversation(body.parent, owner) if body.parent else None
    try:
        generated = generate(body.question, previous)
        if not isinstance(generated, dict):
            raise TypeError("Некорректный ответ модели")
        if generated.get("sql") is None:
            result = {
                "status": "clarification",
                "clarification": str(generated.get("clarification") or "Уточните вопрос")[:2000],
            }
        else:
            if not isinstance(generated["sql"], str):
                raise TypeError("SQL должен быть строкой")
            safe_sql = validate(generated["sql"])
            rows = execute(owner, safe_sql)
            result = {
                "status": "completed",
                "sql": safe_sql,
                "rows": rows,
                "explanation": str(generated.get("explanation", ""))[:2000],
                "limit": 100,
            }
    except (ValueError, psycopg.Error) as exc:
        result = {"status": "refused", "reason": str(exc).splitlines()[0][:300]}
    except (ModelFailure, httpx.HTTPError, KeyError, TypeError) as exc:
        raise HTTPException(502, "Модель недоступна или вернула некорректный ответ") from exc
    result["generation"] = {
        "mode": os.environ.get("MODEL_MODE", "demo"),
        "model": os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:1.5b")
        if os.environ.get("MODEL_MODE") == "ollama"
        else "demo-templates",
        "prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
    }
    identity = uuid.uuid4()
    result = json.loads(json.dumps(result, default=str))
    with connect() as conn:
        conn.execute(
            "INSERT INTO questions(id,owner,question,parent,response) VALUES (%s,%s,%s,%s,%s)",
            (identity, owner, body.question, body.parent, Jsonb(result)),
        )
        response = {"id": str(identity), **result}
        if request_key:
            conn.execute(
                "INSERT INTO requests(owner,key,fingerprint,response) VALUES (%s,%s,%s,%s)",
                (owner, request_key, fingerprint, Jsonb(response)),
            )
    return response


@app.get("/health")
def health(owner: Annotated[str, Depends(authorize)]):
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "model_mode": os.environ.get("MODEL_MODE", "demo")}
