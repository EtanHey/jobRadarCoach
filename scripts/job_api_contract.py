from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg

FUNCTIONS = {
    "score_band": "public.score_band(smallint)",
    "job_link_url": "public.job_link_url(text,text)",
    "search_jobs": "public.search_jobs(boolean,integer,text,text,text,boolean,uuid[],boolean,integer)",
    "count_jobs": "public.count_jobs(boolean,integer,text,text,text,boolean,uuid[],boolean)",
    "get_job": "public.get_job(uuid)",
}

def _function_contract(connection: psycopg.Connection, signature: str, name: str) -> dict[str, Any]:
    row = connection.execute(
        "select p.proargnames, p.proargtypes::oid[], p.prorettype, p.proretset, "
        "pg_catalog.format_type(p.prorettype, null) from pg_catalog.pg_proc p where p.oid = %s::regprocedure",
        (signature,),
    ).fetchone()
    if row is None:
        raise ValueError(f"missing function {signature}")
    argument_names, argument_types, return_oid, returns_set, return_type = row
    arguments = [
        {"name": argument_names[index - 1], "type": type_name, "order": index}
        for type_name, index in connection.execute(
            "select pg_catalog.format_type(argument_type, null), ordinality "
            "from pg_catalog.unnest(%s::oid[]) with ordinality as values(argument_type, ordinality) "
            "order by ordinality", (argument_types,),
        ).fetchall()
    ]
    result_columns = connection.execute(
        "select a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnum "
        "from pg_catalog.pg_type t join pg_catalog.pg_attribute a on a.attrelid = t.typrelid "
        "where t.oid = %s and a.attnum > 0 and not a.attisdropped order by a.attnum",
        (return_oid,),
    ).fetchall()
    columns = (
        [{"name": column_name, "type": type_name, "order": order} for column_name, type_name, order in result_columns]
        or [{"name": name, "type": return_type, "order": 1}]
    )
    return {"args": arguments, "returns": {"type": return_type, "set": returns_set, "columns": columns}}

def contract_for_connection(connection: psycopg.Connection) -> dict[str, Any]:
    return {"functions": {name: _function_contract(connection, signature, name) for name, signature in FUNCTIONS.items()}}

def write_contract(connection: psycopg.Connection, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(contract_for_connection(connection), indent=2) + "\n", encoding="utf-8")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    with psycopg.connect(arguments.database_url) as connection:
        write_contract(connection, arguments.output)

if __name__ == "__main__":
    main()
