import pytest

from asksql.guard import validate


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM analytics.sales",
        "SELECT amount FROM analytics.sales; DROP TABLE analytics.sales",
        "SELECT pg_sleep(5) FROM analytics.sales",
        "SELECT set_config('role','analytics_owner',false) FROM analytics.sales",
        "SELECT pg_read_file('/etc/passwd') FROM analytics.sales",
        "SELECT * FROM analytics.sales",
        "SELECT tenant FROM analytics.sales",
        "SELECT amount FROM public.sales",
        "SELECT usename FROM pg_catalog.pg_user",
        "SELECT a.amount FROM analytics.sales a CROSS JOIN analytics.sales b",
        "WITH x AS (SELECT amount FROM analytics.sales) SELECT amount FROM x",
        "SELECT amount FROM analytics.sales UNION SELECT amount FROM analytics.sales",
        "SELECT amount INTO other FROM analytics.sales",
        "SELECT amount FROM analytics.sales FOR UPDATE",
        "SELECT (SELECT amount FROM analytics.sales) FROM analytics.sales",
        "SELECT random() FROM analytics.sales",
    ],
)
def test_adversarial_queries_refused(sql):
    with pytest.raises(ValueError):
        validate(sql)


def test_aggregates_and_limits():
    assert "LIMIT 100" in validate("SELECT SUM(amount) AS revenue FROM analytics.sales")
    assert "LIMIT 5" in validate("SELECT product FROM analytics.sales LIMIT 5")
    assert "LIMIT 100" in validate("SELECT COUNT(*) FROM analytics.sales LIMIT 1000000")
    assert "GROUP BY product" in validate(
        "SELECT product, SUM(amount) FROM analytics.sales GROUP BY product"
    )
