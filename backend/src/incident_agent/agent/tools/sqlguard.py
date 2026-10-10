"""A lexical guard for the run_sql tool.

It tokenises the query (strings and quoted identifiers become single opaque tokens) and then
enforces statement shape, a keyword deny-list, a table allow-list and a function allow-list.
It is deliberately strict: anything it cannot classify is rejected. It is not a SQL parser; the
safety of run_sql rests on this guard together with the database role (SELECT only, no `gt`
schema), a read-only transaction, a statement timeout and the shadowing CTEs built in run_sql.
"""

from dataclasses import dataclass

MAX_QUERY_CHARS = 3000


class GuardError(ValueError):
    """The query is not allowed; the message tells the model what to change."""


@dataclass(frozen=True)
class Tok:
    kind: str  # word | qident | str | num | punct | op
    text: str  # words are lower-cased; quoted identifiers keep their exact text

    @property
    def is_name(self) -> bool:
        return self.kind in ("word", "qident")


# Tables run_sql may read. The time-series ones are shadowed by filtered CTEs (see run_sql).
SHADOWED = ("cell_kpis", "core_kpis", "alarms", "changes", "maintenance", "external_events")
STATIC = ("nodes", "cells", "regions")
ALLOWED_TABLES = frozenset((*SHADOWED, *STATIC))
OTHER_TABLES = {
    "alerts": "use get_anomalies",
    "anomalies": "use get_anomalies",
    "runbook_docs": "use search_runbooks",
    "runbook_chunks": "use search_runbooks",
    "dataset_meta": "not available",
    "region_kpis_15m": "use query_kpis with entity_type=region",
    "scenarios": "not available",
}

_FORBIDDEN_SCHEMAS = {
    "public",
    "gt",
    "app",
    "information_schema",
    "pg_catalog",
    "pg_temp",
    "pg_toast",
}
_FORBIDDEN_WORDS = {
    "insert", "update", "delete", "merge", "create", "alter", "drop", "truncate", "grant",
    "revoke", "copy", "call", "do", "set", "reset", "show", "execute", "prepare", "deallocate",
    "listen", "notify", "unlisten", "vacuum", "analyze", "analyse", "cluster", "reindex",
    "refresh", "comment", "security", "lock", "explain", "begin", "start", "commit", "rollback",
    "savepoint", "release", "abort", "checkpoint", "load", "discard", "import", "declare",
    "fetch", "move", "close", "into", "returning", "table", "nowait",
}  # fmt: skip
_CLOCK_WORDS = {
    "current_date", "current_time", "current_timestamp", "localtime", "localtimestamp",
    "current_user", "session_user", "user", "current_role", "current_schema", "current_catalog",
}  # fmt: skip

# Words that can legitimately be followed by "(" without being a function call.
_SYNTAX_BEFORE_PAREN = {
    "in", "not", "exists", "any", "all", "some", "and", "or", "on", "using", "over", "filter",
    "values", "as", "from", "where", "select", "union", "intersect", "except", "then", "else",
    "when", "case", "by", "partition", "order", "group", "having", "limit", "offset", "join",
    "array", "row", "rows", "range", "between", "like", "ilike", "similar", "is", "distinct",
    "with", "within", "lateral", "interval", "at", "recursive", "materialized", "only",
    "cross", "inner", "left", "right", "full", "natural", "outer", "end", "symmetric",
    "asymmetric", "escape", "ties", "nulls", "first", "last", "unbounded", "preceding",
    "following", "current", "exclude", "to",
}  # fmt: skip
_ALLOWED_FUNCTIONS = {
    # aggregates and statistics
    "count", "sum", "avg", "min", "max", "stddev", "stddev_pop", "stddev_samp", "variance",
    "var_pop", "var_samp", "percentile_cont", "percentile_disc", "mode", "corr", "regr_slope",
    "regr_intercept", "string_agg", "array_agg", "bool_and", "bool_or", "every", "json_agg",
    "jsonb_agg",
    # windows
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag", "lead",
    "first_value", "last_value", "nth_value",
    # scalar
    "coalesce", "nullif", "greatest", "least", "abs", "round", "ceil", "ceiling", "floor",
    "sqrt", "power", "pow", "exp", "ln", "log", "log10", "mod", "sign", "trunc", "div",
    "width_bucket", "isfinite",
    # time
    "date_trunc", "date_part", "extract", "date_bin", "make_interval", "make_timestamptz",
    "age", "to_char", "to_timestamp", "to_date", "timezone",
    # text
    "lower", "upper", "length", "char_length", "character_length", "substr", "substring",
    "position", "strpos", "replace", "concat", "concat_ws", "left", "right", "trim", "ltrim",
    "rtrim", "btrim", "split_part", "regexp_replace", "initcap", "string_to_array",
    "array_to_string", "array_length", "array_position", "cardinality",
    # set-returning
    "generate_series", "unnest",
    # casts written as functions or types with arguments
    "cast", "numeric", "decimal", "varchar", "char", "text", "float8", "float4", "int",
    "integer", "bigint", "timestamptz", "timestamp", "date",
    # json (built from visible values only)
    "jsonb_extract_path_text", "json_build_object", "jsonb_build_object",
}  # fmt: skip

_OP_CHARS = set("+-*/<>=~!@#%^&|`?:")


def tokenize(sql: str) -> list[Tok]:
    """Split `sql` into tokens, rejecting comments, escapes and dollar quoting."""
    toks: list[Tok] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
        elif sql.startswith("--", i) or sql.startswith("/*", i):
            raise GuardError("Comments are not allowed in the query.")
        elif c == "'":
            prev = sql[i - 1] if i else ""
            before = sql[i - 2] if i > 1 else ""
            if prev == "&" or (prev in "eE" and prev and not (before.isalnum() or before == "_")):
                raise GuardError("Escape strings (E'...' or U&'...') are not allowed.")
            j = i + 1
            while True:
                if j >= n:
                    raise GuardError("Unterminated string literal.")
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            toks.append(Tok("str", sql[i : j + 1]))
            i = j + 1
        elif c == '"':
            if i and sql[i - 1] == "&":
                raise GuardError('Unicode-escaped identifiers (U&"...") are not allowed.')
            j = i + 1
            name: list[str] = []
            while True:
                if j >= n:
                    raise GuardError("Unterminated quoted identifier.")
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        name.append('"')
                        j += 2
                        continue
                    break
                name.append(sql[j])
                j += 1
            if not name:
                raise GuardError("Empty quoted identifier.")
            toks.append(Tok("qident", "".join(name)))
            i = j + 1
        elif c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            j = i
            while j < n and (sql[j].isdigit() or sql[j] == "."):
                j += 1
            if (
                j < n
                and sql[j] in "eE"
                and j + 1 < n
                and (sql[j + 1].isdigit() or sql[j + 1] in "+-")
            ):
                j += 2
                while j < n and sql[j].isdigit():
                    j += 1
            toks.append(Tok("num", sql[i:j]))
            i = j
        elif c.isalpha() or c == "_" or ord(c) > 127:
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_" or ord(sql[j]) > 127):
                j += 1
            toks.append(Tok("word", sql[i:j].lower()))
            i = j
        elif c in "(),;.[]":
            toks.append(Tok("punct", c))
            i += 1
        elif c in _OP_CHARS:
            j = i
            while j < n and sql[j] in _OP_CHARS:
                if sql.startswith("--", j) or sql.startswith("/*", j):
                    raise GuardError("Comments are not allowed in the query.")
                j += 1
            toks.append(Tok("op", sql[i:j]))
            i = j
        elif c == "$":
            raise GuardError("'$' (parameters, dollar quoting) is not allowed.")
        elif c == "\\":
            raise GuardError("Backslashes are not allowed outside string literals.")
        else:
            raise GuardError(f"Unexpected character {c!r}.")
    return toks


def check_sql(sql: str) -> str:
    """Return the statement without a trailing semicolon, or raise GuardError."""
    stripped = sql.strip()
    if not stripped:
        raise GuardError("Empty query.")
    if len(stripped) > MAX_QUERY_CHARS:
        raise GuardError(f"Query too long ({len(stripped)} > {MAX_QUERY_CHARS} characters).")
    toks = tokenize(stripped)
    if toks and toks[-1].kind == "punct" and toks[-1].text == ";":
        toks = toks[:-1]
        stripped = stripped.rstrip().removesuffix(";").rstrip()
    if any(t.kind == "punct" and t.text == ";" for t in toks):
        raise GuardError("Only one statement is allowed (found ';' inside the query).")
    if not toks:
        raise GuardError("Empty query.")
    first = toks[0]
    if first.kind != "word" or first.text not in ("select", "with"):
        raise GuardError("Only a single SELECT (or WITH ... SELECT) statement is allowed.")

    for pos, tok in enumerate(toks):
        if tok.kind == "word":
            _check_word(tok.text, toks, pos)
        elif tok.kind == "qident":
            _check_name(tok.text)
            if pos + 1 < len(toks) and toks[pos + 1].text == "(":
                raise GuardError(f'Quoted function name "{tok.text}" is not allowed.')
    return stripped


def _check_name(name: str) -> None:
    if (
        name in _FORBIDDEN_SCHEMAS
        or name.startswith("pg_")
        or name.startswith("information_schema")
    ):
        raise GuardError(
            f"'{name}' is not accessible. Use bare table names "
            f"({', '.join(sorted(ALLOWED_TABLES))}); schema-qualified names and system "
            "catalogs are blocked."
        )
    if name in OTHER_TABLES:
        raise GuardError(f"Table '{name}' is not available in run_sql: {OTHER_TABLES[name]}.")


def _check_word(word: str, toks: list[Tok], pos: int) -> None:
    _check_name(word)
    if word in _FORBIDDEN_WORDS:
        raise GuardError(
            f"'{word.upper()}' is not allowed; only read-only SELECT queries run here."
        )
    if word in _CLOCK_WORDS:
        raise GuardError(
            f"'{word}' is not allowed: use explicit timestamps (the current time is asked_at)."
        )
    if (
        word == "for"
        and pos + 1 < len(toks)
        and toks[pos + 1].text in ("update", "share", "no", "key")
    ):
        raise GuardError("Row locking (FOR UPDATE/SHARE) is not allowed.")
    nxt = toks[pos + 1] if pos + 1 < len(toks) else None
    if nxt is not None and nxt.kind == "punct" and nxt.text == "(":
        prev = toks[pos - 1] if pos else None
        if prev is not None and prev.kind == "punct" and prev.text == ".":
            raise GuardError(f"Qualified function '{word}' is not allowed.")
        after_as = prev is not None and prev.kind == "word" and prev.text == "as"
        if word in _SYNTAX_BEFORE_PAREN or after_as:
            return
        if word not in _ALLOWED_FUNCTIONS:
            raise GuardError(
                f"Function '{word}' is not allowed. Allowed: aggregates (count, sum, avg, min, "
                "max, percentile_cont, ...), window functions, date_trunc/extract/to_char, math, "
                "string functions, generate_series, coalesce, nullif, cast."
            )
