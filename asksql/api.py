import os
import secrets
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
from asksql.model import generate


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


@app.post("/ask")
def ask(body: Question, owner: Annotated[str, Depends(authorize)]):
    previous = None
    if body.parent:
        with connect() as conn:
            row = conn.execute(
                "SELECT question FROM questions WHERE id=%s AND owner=%s", (body.parent, owner)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Предыдущий вопрос не найден")
        previous = row["question"]
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
    except (httpx.HTTPError, KeyError, TypeError) as exc:
        raise HTTPException(502, "Модель недоступна или вернула некорректный ответ") from exc
    identity = uuid.uuid4()
    import json

    result = json.loads(json.dumps(result, default=str))
    with connect() as conn:
        conn.execute(
            "INSERT INTO questions(id,owner,question,parent,response) VALUES (%s,%s,%s,%s,%s)",
            (identity, owner, body.question, body.parent, Jsonb(result)),
        )
    return {"id": identity, **result}


@app.get("/health")
def health(owner: Annotated[str, Depends(authorize)]):
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}
