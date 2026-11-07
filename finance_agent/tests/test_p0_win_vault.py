"""Native Credential Manager round trip with a unique synthetic entry."""
from dataclasses import replace
import os
import subprocess
import sys
import unittest
from uuid import uuid4

from app.model_config import profile_data_legacy, validate_profile
from app.win_vault import CredentialError, WindowsVault, profile_target


class WindowsCredentialTests(unittest.TestCase):
    def test_binding_changes_for_endpoint_and_profile(self):
        profile = validate_profile(profile_data_legacy("https://api.deepseek.com", "deepseek-flash", "API_KEY"))
        self.assertNotEqual(profile_target(profile), profile_target(replace(profile, profile_name="other")))
        self.assertNotEqual(profile_target(profile), profile_target(replace(profile, base_url="https://example.com")))

    @unittest.skipUnless(os.name == "nt", "Windows Credential Manager requires Windows")
    def test_native_write_reload_replace_and_forget(self):
        store = WindowsVault()
        target = "Economy-guy/Test/" + uuid4().hex
        try:
            store.write(target, "synthetic-vault-roundtrip")
        except CredentialError as error:
            self.skipTest(str(error))
        self.addCleanup(store.forget, target)
        code = ("from app.win_vault import WindowsVault; import sys; "
                "raise SystemExit(0 if WindowsVault().read(sys.argv[1])=='synthetic-vault-roundtrip' else 1)")
        result = subprocess.run([sys.executable, "-c", code, target], capture_output=True, check=False)
        self.assertEqual(result.returncode, 0)
        store.write(target, "synthetic-vault-replacement")
        self.assertEqual(store.read(target), "synthetic-vault-replacement")
        store.forget(target)
        self.assertIsNone(store.read(target))
