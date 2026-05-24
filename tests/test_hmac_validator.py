import hashlib
import hmac

from odoo.tests.common import BaseCase, tagged

from odoo.addons.lemon_squeezy_connector.utils.hmac_validator import (
    validate_lemon_squeezy_signature,
)


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestHmacValidator(BaseCase):

    SECRET = "whsec_test_super_secret_string"
    PAYLOAD = b'{"meta":{"event_name":"order_created"},"data":{}}'

    def _compute(self, secret, payload):
        return hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()

    def test_valid_signature_passes(self):
        sig = self._compute(self.SECRET, self.PAYLOAD)
        self.assertTrue(
            validate_lemon_squeezy_signature(self.PAYLOAD, sig, self.SECRET)
        )

    def test_invalid_signature_fails(self):
        self.assertFalse(
            validate_lemon_squeezy_signature(self.PAYLOAD, "deadbeef" * 8, self.SECRET)
        )

    def test_tampered_payload_fails(self):
        sig = self._compute(self.SECRET, self.PAYLOAD)
        tampered = self.PAYLOAD + b'{"injected":true}'
        self.assertFalse(
            validate_lemon_squeezy_signature(tampered, sig, self.SECRET)
        )

    def test_empty_signature_fails(self):
        self.assertFalse(
            validate_lemon_squeezy_signature(self.PAYLOAD, "", self.SECRET)
        )

    def test_none_signature_fails(self):
        self.assertFalse(
            validate_lemon_squeezy_signature(self.PAYLOAD, None, self.SECRET)
        )

    def test_none_payload_fails(self):
        """payload=None must fail-closed (Python 3.13 hmac.new treats None as b'' — spoofing risk)."""
        sig = self._compute(self.SECRET, b"")
        self.assertFalse(
            validate_lemon_squeezy_signature(None, sig, self.SECRET)
        )

    def test_empty_payload_fails(self):
        """payload=b'' must fail-closed (LS never sends empty-body webhooks legitimately)."""
        sig = self._compute(self.SECRET, b"")
        self.assertFalse(
            validate_lemon_squeezy_signature(b"", sig, self.SECRET)
        )

    def test_last_byte_mismatch_fails(self):
        """Smoke that hmac.compare_digest is used: a single last-byte change makes the signature fail.
        Real timing-attack resistance requires statistical timing tests, out of scope for unit tests."""
        # Test indirecto: si la firma cambia solo el último byte, también falla
        sig = self._compute(self.SECRET, self.PAYLOAD)
        wrong_last = sig[:-1] + ('0' if sig[-1] != '0' else '1')
        self.assertFalse(
            validate_lemon_squeezy_signature(self.PAYLOAD, wrong_last, self.SECRET)
        )
