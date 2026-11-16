import unittest
from afc import password_auth as auth
from afc.domain import Problem


class PasswordAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = auth.password_record('Strong-fixture-passphrase-2026', 'maintenance')

    def settings(self):
        return {'jwt_secret': 'fixture-signing-key', 'demo_users': {'ta': dict(self.record)}}

    def test_valid_credentials_issue_access_and_separate_refresh(self):
        settings = self.settings()
        result = auth.login({'username': 'TA', 'password': 'Strong-fixture-passphrase-2026', 'role': 'admin'}, settings, 1000)
        self.assertEqual(result['user']['role'], 'maintenance')
        renewed = auth.refresh({'refresh_token': result['refresh_token']}, settings, 5000)
        self.assertEqual(renewed['user']['role'], 'maintenance')
        self.assertNotIn('refresh_token', renewed)

    def test_wrong_password_is_rejected(self):
        with self.assertRaises(Problem):
            auth.login({'username': 'ta', 'password': 'incorrect'}, self.settings(), 1000)

    def test_access_token_cannot_renew_a_session(self):
        result = auth.login({'username': 'ta', 'password': 'Strong-fixture-passphrase-2026'}, self.settings(), 1000)
        with self.assertRaises(Problem):
            auth.refresh({'refresh_token': result['access_token']}, self.settings(), 1010)

    def test_password_reset_invalidates_refresh(self):
        settings = self.settings()
        result = auth.login({'username': 'ta', 'password': 'Strong-fixture-passphrase-2026'}, settings, 1000)
        settings['demo_users']['ta']['hash'] = 'different-credential-hash'
        with self.assertRaises(Problem):
            auth.refresh({'refresh_token': result['refresh_token']}, settings, 1010)

    def test_expired_refresh_is_rejected(self):
        result = auth.login({'username': 'ta', 'password': 'Strong-fixture-passphrase-2026'}, self.settings(), 1000)
        with self.assertRaises(Problem):
            auth.refresh({'refresh_token': result['refresh_token']}, self.settings(), 1000 + auth.REFRESH_TTL + 1)

    def test_disabled_account_is_rejected(self):
        settings = self.settings(); settings['demo_users']['ta']['active'] = False
        with self.assertRaises(Problem):
            auth.login({'username': 'ta', 'password': 'Strong-fixture-passphrase-2026'}, settings, 1000)


if __name__ == '__main__':
    unittest.main()
