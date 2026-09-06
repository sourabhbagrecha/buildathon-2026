import unittest

from ripple.databricks_backend import AGG_DIFF_SQL, ROW_DIFF_SQL, SCHEMA, _lit, _values


class DatabricksSqlTests(unittest.TestCase):
    """SQL generation only; no network."""

    def test_literal_escaping(self):
        self.assertEqual(_lit("it's"), "'it''s'")
        self.assertEqual(_lit(1.5), "1.5")
        self.assertEqual(_lit(None), "NULL")

    def test_values_with_extra_columns(self):
        v = _values([{"a": 1, "b": "x"}], ["run_id", "a", "b"], {"run_id": "r1"})
        self.assertEqual(v, "('r1', 1, 'x')")

    def test_diff_sql_joins_base_and_head_of_same_run(self):
        sql = ROW_DIFF_SQL.format(schema=SCHEMA, run_id=_lit("r1"))
        self.assertIn("b.version = 'base' AND h.version = 'head'", sql)
        self.assertIn("b.run_id = 'r1'", sql)
        self.assertIn("NOT (b.amount <=> h.amount)", sql)
        self.assertIn("daily_revenue", AGG_DIFF_SQL)


if __name__ == "__main__":
    unittest.main()
