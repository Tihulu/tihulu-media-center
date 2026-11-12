"""Static guardrails for the Kaffeine 2.0.19 modeless DVB scan patch.

The native source CI builds the transformation against the exact pinned upstream
revision; these offline checks detect accidental regressions in the patch plan.
"""
import inspect
import unittest

from kaffeine_next.patch_upstream import PATHS, transform


class DvbBackgroundScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = inspect.getsource(transform)

    def test_scan_runs_in_modeless_dialog_and_not_a_second_scanner(self):
        self.assertIn("dialog->setModal(false);", self.patch)
        self.assertIn("scanDialog = dialog;", self.patch)
        self.assertIn("if (scanDialog) {", self.patch)
        self.assertIn("scanDialog->activateWindow();", self.patch)
        self.assertIn("Qt::WA_DeleteOnClose", self.patch)
        self.assertNotIn('QProcess::startDetached(QLatin1String("w_scan_cpp")', self.patch)

    def test_tuner_ownership_is_protected_without_blocking_local_media(self):
        self.assertIn("scanDialog && scanDialog->isScanning()", self.patch)
        self.assertIn("before tuning another TV channel", self.patch)
        self.assertIn("instant DVB recording cannot start", self.patch)
        self.assertIn("Close the Channels window before changing DVB receiver", self.patch)
        self.assertIn("mediaWidget->stop();", self.patch)

    def test_dialog_destroyed_before_manager_on_application_exit(self):
        self.assertIn("delete scanDialog;", self.patch)
        self.assertIn("scanDialog = NULL;", self.patch)
        self.assertIn("QPointer<DvbScanDialog> scanDialog", self.patch)
        self.assertIn("return internal != NULL;", self.patch)
        self.assertIn("src/dvb/dvbscandialog.h", PATHS)

    def test_existing_import_safety_kept(self):
        self.assertIn("fix_sql_free_key(files[sql_hdr])", self.patch)
        self.assertIn("manager->getChannelModel()->cloneFrom(channelModel)", self.patch)
        self.assertIn("QSignalBlocker blocker(scanButton)", self.patch)


if __name__ == "__main__":
    unittest.main()
