"""Test E2E integración full lifecycle — Lemon Squeezy webhook → BD.

Orquesta los 3 eventos principales del ciclo de vida de una suscripción
usando el endpoint HTTP real (/lemon_squeezy/webhook) con HMAC válido:

1. order_created  → crea partner + sale.order + license (status=active)
2. subscription_payment_success → license sigue active (no-op)
3. subscription_cancelled → license status=cancelled

Cubre integración B2.8 (webhook HMAC + idempotency) + B2.9 (dispatch +
handlers reales) end-to-end vía HTTP real (HttpCase). No requiere LS
sandbox externo (eso es B5.2 del plan macro, post-MVP).

Notas sobre env staleness (HttpCase):
  url_open() ejecuta el controller en un worker thread separado con su
  propia transacción, que se commitea ANTES de que url_open() retorne.
  self.env mantiene caché ORM de la transacción del test → stale.
  invalidate_all() + browse(id) fuerza relectura fresca desde BD.
"""
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta

from odoo.tests import HttpCase, tagged

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestIntegrationE2E(HttpCase):

    WEBHOOK_SECRET = "test_e2e_secret"

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'lemon_squeezy.webhook_secret', self.WEBHOOK_SECRET
        )
        # Setup product + mapping (Individual annual)
        product = self.env['product.product'].create({
            'name': 'LABORALIA Plugin Skill', 'type': 'service', 'list_price': 1200,
        })
        self.env['lemon_squeezy.product_mapping'].create({
            'variant_id': '12345',
            'variant_name': 'Individual anual',
            'product_id': product.id,
            'seats': 1,
            'billing_cycle': 'annual',
        })

    def _post_event(self, fixture_name):
        """Abre fixture JSON, firma con HMAC y hace POST al endpoint webhook."""
        with open(os.path.join(FIXTURES_DIR, fixture_name)) as f:
            payload = json.load(f)
        body = json.dumps(payload).encode('utf-8')
        sig = hmac.new(
            self.WEBHOOK_SECRET.encode('utf-8'), body, hashlib.sha256
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

    def test_full_lifecycle_order_then_subscription(self):
        """Ciclo completo: order_created → subscription_created → payment_success → cancelled.

        P3 fix: subscription_payment_success/cancelled ahora lookup por subscription_id (data.id).
        El flujo realista incluye subscription_created (que persiste subscription_id en la license)
        antes de los eventos de pago/cancelación.
        """
        # Step 1: order_created → crea partner + SO + license active
        r1 = self._post_event('ls_order_created.json')
        self.assertEqual(r1.status_code, 200)
        self.env.invalidate_all()  # flush ORM cache: controller corrió en transacción separada
        partner = self.env['res.partner'].search([('email', '=', 'test@example.com')])
        self.assertEqual(len(partner), 1)
        license = self.env['lemon_squeezy.license'].search([('order_id', '=', '1234567')])
        self.assertEqual(len(license), 1)
        self.assertEqual(license.status, 'active')

        # Step 2: subscription_created (P3: link subscription_id a license para lookup en payment handlers)
        r2 = self._post_event('ls_subscription_created.json')
        self.assertEqual(r2.status_code, 200)
        self.env.invalidate_all()
        license = self.env['lemon_squeezy.license'].browse(license.id)
        self.assertEqual(license.subscription_id, '9876543')  # populated by handler

        # Step 3: subscription_payment_success → license sigue active (lookup por subscription_id)
        r3 = self._post_event('ls_subscription_payment_success.json')
        self.assertEqual(r3.status_code, 200)
        self.env.invalidate_all()
        # v0.3.0: payment_success extended expires_at
        license = self.env['lemon_squeezy.license'].browse(license.id)
        self.assertGreater(license.expires_at, datetime.now() + timedelta(days=300))

        # Step 4: subscription_cancelled → license status=cancelled
        r4 = self._post_event('ls_subscription_cancelled.json')
        self.assertEqual(r4.status_code, 200)
        self.env.invalidate_all()
        license = self.env['lemon_squeezy.license'].browse(license.id)
        self.assertEqual(license.status, 'cancelled')

        # Verificar los 4 eventos loggeados sin processing_error
        events = self.env['lemon_squeezy.event'].sudo().search([])
        # Filtramos a los event_ids exactos de las fixtures (evita contaminación de otros tests)
        relevant_events = events.filtered(
            lambda e: e.event_id in (
                'evt_fix_oc_001', 'evt_fix_sc_001', 'evt_fix_sps_001', 'evt_fix_sca_001'
            )
        )
        self.assertEqual(
            len(relevant_events), 4,
            f"Esperados 4 eventos, encontrados: {relevant_events.mapped('event_id')}",
        )
        # Ningún evento con processing_error (todos los handlers terminaron sin excepción)
        errored = relevant_events.filtered(lambda e: e.processing_error)
        self.assertFalse(
            errored,
            f"Eventos con error: {errored.mapped('processing_error')}",
        )
