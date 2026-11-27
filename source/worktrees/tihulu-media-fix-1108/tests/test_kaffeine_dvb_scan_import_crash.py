"""Regression for Kaffeine 2.0.19 scan/import SIGSEGV, KDE #503740.

Reproduces the upstream SQL allocator *source* defect that appears in
DvbChannelModel::cloneFrom() when Scan Results are imported, without
touching DVB hardware, channel storage, or user's configuration.
"""
import unittest
from kaffeine_next.patch_upstream import PATHS, fix_sql_free_key


UPSTREAM = """template<class Container> SqlKey sqlFindFreeKey(const Container &container) const
{
    SqlKey sqlKey(1);
    if (!container.isEmpty()) {
        sqlKey = SqlKey(std::prev(container.constEnd(), -1).key().sqlKey + 1);
        while (container.contains(sqlKey) || !sqlKey.isSqlKeyValid()) {
            sqlKey = SqlKey(123);
        }
    }
    return sqlKey;
}
"""


class KaffeineDvbScanImportCrashTests(unittest.TestCase):
    def test_pinned_sql_header_is_built_from_patched_source(self):
        self.assertIn("src/sqlinterface.h", PATHS)

    def test_invalid_forward_from_end_replaced_by_backward_iterator(self):
        fixed = fix_sql_free_key(UPSTREAM)
        self.assertIn("std::prev(container.constEnd()).key().sqlKey + 1", fixed)
        self.assertNotIn("std::prev(container.constEnd(), -1)", fixed)
        self.assertIn("if (!container.isEmpty()) {", fixed)
        self.assertIn("while (container.contains(sqlKey)", fixed)

    def test_already_correct_upstream_is_safe_idempotent(self):
        once = fix_sql_free_key(UPSTREAM)
        self.assertEqual(fix_sql_free_key(once), once)

    def test_unknown_or_unguarded_upstream_fails_closed(self):
        with self.assertRaises(ValueError):
            fix_sql_free_key(UPSTREAM.replace("if (!container.isEmpty()) {",
                                               "if (true) {"))
        with self.assertRaises(ValueError):
            fix_sql_free_key(UPSTREAM.replace("std::prev(container.constEnd(), -1)",
                                              "std::next(container.constEnd())"))
        with self.assertRaises(ValueError):
            fix_sql_free_key(UPSTREAM.replace("std::prev(container.constEnd(), -1)",
                                              "std::prev(container.constEnd(), -1), "
                                              "std::prev(container.constEnd(), -1)"))


if __name__ == "__main__":
    unittest.main()
