"""Tests HttpCase para el webhook controller Lemon Squeezy.

5 tests de integración:
- invalid_signature → 401 + NO evento creado
- valid_signature → 200 + evento en BD
- idempotency → 2 posts mismo event_id → 1 solo registro
- missing X-Signature header → 401
- unknown event_name → 200 + evento processed=True (evita LS retries)
"""
import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestWebhookController(HttpCase):

    WEBHOOK_SECRET = "test_webhook_secret_for_pytest_only"

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'lemon_squeezy.webhook_secret', self.WEBHOOK_SECRET
        )

    def _signed_post(self, payload: dict):
        body = json.dumps(payload).encode('utf-8')
        sig = hmac.new(
            self.WEBHOOK_SECRET.encode('utf-8'),
            body,
            hashlib.sha256,
        ).hexdigest()
        return self.url_open(
            '/lemon_squeezy/webhook',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Signature': sig,
                'X-Event-Name': payload['meta']['event_name'],
            },
        )

    def _unsigned_post(self, payload: dict, signature: str = "deadbeef"):
        body = json.dumps(payload).encode('utf-8')
        return self.url_open(
            '/lemon_squeezy/webhook',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Signature': signature,
                'X-Event-Name': payload['meta']['event_name'],
            },
        )

    def test_invalid_signature_returns_401(self):
        payload = {
            'meta': {'event_name': 'order_created', 'event_id': 'evt_sig_fail'},
            'data': {'id': 'ord_1', 'type': 'orders', 'attributes': {}},
        }
        r = self._unsigned_post(payload)
        self.assertEqual(r.status_code, 401)
        self.env.invalidate_all()
        self.assertFalse(
            self.env['lemon_squeezy.event'].search([('event_id', '=', 'evt_sig_fail')])
        )

    def test_valid_signature_creates_event_returns_200(self):
        payload = {
            'meta': {'event_name': 'order_created', 'event_id': 'evt_sig_ok_001'},
            'data': {'id': 'ord_2', 'type': 'orders', 'attributes': {}},
        }
        r = self._signed_post(payload)
        self.assertEqual(r.status_code, 200)
        self.env.invalidate_all()
        events = self.env['lemon_squeezy.event'].search([('event_id', '=', 'evt_sig_ok_001')])
        self.assertEqual(len(events), 1)
        self.assertEqual(events.event_name, 'order_created')

    def test_idempotency_same_event_twice_returns_200_no_duplicate(self):
        payload = {
            'meta': {'event_name': 'order_created', 'event_id': 'evt_idem_001'},
            'data': {'id': 'ord_3', 'type': 'orders', 'attributes': {}},
        }
        r1 = self._signed_post(payload)
        r2 = self._signed_post(payload)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.env.invalidate_all()
        events = self.env['lemon_squeezy.event'].search([('event_id', '=', 'evt_idem_001')])
        self.assertEqual(len(events), 1)  # Solo 1 evento creado

    def test_missing_signature_header_returns_401(self):
        body = json.dumps({
            'meta': {'event_name': 'order_created', 'event_id': 'evt_no_sig'},
        }).encode()
        r = self.url_open(
            '/lemon_squeezy/webhook',
            data=body,
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(r.status_code, 401)

    def test_unknown_event_name_returns_200_but_logs(self):
        """Eventos no soportados se loggean (processing_error) pero devuelven 200 para evitar LS retries."""
        payload = {
            'meta': {'event_name': 'unknown_event_type', 'event_id': 'evt_unknown_001'},
            'data': {},
        }
        r = self._signed_post(payload)
        self.assertEqual(r.status_code, 200)
        self.env.invalidate_all()
        event = self.env['lemon_squeezy.event'].search([('event_id', '=', 'evt_unknown_001')])
        self.assertTrue(event)
        self.assertTrue(event.processed)  # marcado processed aunque sin handler
        self.assertEqual(event.processing_error, 'unknown_event: unknown_event_type')
