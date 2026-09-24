import sqlglot
from sqlglot import exp

ALLOWED = {
    "Select",
    "Alias",
    "Column",
    "Identifier",
    "Table",
    "From",
    "Where",
    "Group",
    "Order",
    "Ordered",
    "Limit",
    "Literal",
    "EQ",
    "NEQ",
    "GT",
    "GTE",
    "LT",
    "LTE",
    "And",
    "Or",
    "Not",
    "Paren",
    "Between",
    "In",
    "Sum",
    "Count",
    "Avg",
    "Min",
    "Max",
    "Star",
}
COLUMNS = {"day", "product", "region", "amount"}


def validate(sql):
    if len(sql) > 5000:
        raise ValueError("SQL превышает 5000 символов")
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise ValueError("SQL не удалось разобрать") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError("Разрешён один SELECT")
    tree = statements[0]
    nodes = list(tree.walk())
    if len(nodes) > 200 or any(type(node).__name__ not in ALLOWED for node in nodes):
        raise ValueError("SQL содержит запрещённую конструкцию или функцию")
    if sum(isinstance(node, exp.Select) for node in nodes) != 1:
        raise ValueError("Вложенные запросы запрещены")
    tables = list(tree.find_all(exp.Table))
    if (
        len(tables) != 1
        or tables[0].name != "sales"
        or tables[0].db != "analytics"
        or tables[0].catalog
    ):
        raise ValueError("Разрешена только analytics.sales")
    if tables[0].args.get("alias"):
        raise ValueError("Псевдонимы таблиц запрещены")
    for column in tree.find_all(exp.Column):
        if (
            column.name not in COLUMNS
            or column.table not in {"", "sales"}
            or column.db
            or column.catalog
        ):
            raise ValueError("Запрошена недоступная колонка")
    for star in tree.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count) or any(
            value is not None for value in star.args.values()
        ):
            raise ValueError("Звёздочка разрешена только в COUNT(*)")
    # Ограничение применяется к AST, поэтому пользовательский LIMIT не снимает верхнюю границу.
    limit = 100
    if tree.args.get("limit"):
        value = tree.args["limit"].expression
        if not isinstance(value, exp.Literal) or not value.this.isdigit() or int(value.this) < 1:
            raise ValueError("LIMIT должен быть положительным целым числом")
        limit = min(100, int(value.this))
    tree.set("limit", exp.Limit(expression=exp.Literal.number(limit)))
    return tree.sql(dialect="postgres")
