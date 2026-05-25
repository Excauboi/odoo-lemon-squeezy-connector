"""Tests TDD para los 5 handlers de subscription lifecycle.

Usa unittest.mock.patch para simular odoo.http.request.env en TransactionCase,
ya que los handlers usan request.env (contexto HTTP) que no existe en tests unitarios.
"""
import json
import os
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestHandlerSubscriptionLifecycle(TransactionCase):

    def setUp(self):
        super().setUp()
        # Producto base (Individual - 1 seat - annual)
        self.product = self.env['product.product'].create({
            'name': 'LABORALIA Plugin Skill - Individual Annual',
            'type': 'service',
            'list_price': 1200.0,
        })
        self.mapping = self.env['lemon_squeezy.product_mapping'].create({
            'variant_id': '12345',
            'variant_name': 'Individual anual',
            'product_id': self.product.id,
            'seats': 1,
            'billing_cycle': 'annual',
        })

        # Producto upgrade (Despacho - 3 seats - annual)
        self.product_upgrade = self.env['product.product'].create({
            'name': 'LABORALIA Plugin Skill - Despacho Annual',
            'type': 'service',
            'list_price': 2400.0,
        })
        self.mapping_upgrade = self.env['lemon_squeezy.product_mapping'].create({
            'variant_id': '67890',
            'variant_name': 'Despacho anual (3 seats)',
            'product_id': self.product_upgrade.id,
            'seats': 3,
            'billing_cycle': 'annual',
        })

        # Partner pre-existente (como si order_created ya lo creó)
        self.partner = self.env['res.partner'].create({
            'name': 'Despacho Test',
            'email': 'test@example.com',
            'customer_rank': 1,
        })

        # License pre-existente referenciando order_id del fixture ls_order_created
        self.license = self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_test_fixture_001',
            'order_id': '1234567',
            'subscription_id': '9876543',  # P3: payment handlers lookup by subscription_id (= data.id en fixtures)
            'partner_id': self.partner.id,
            'seats': 1,
            'status': 'active',
        })

    def _load_fixture(self, name):
        with open(os.path.join(FIXTURES_DIR, name)) as f:
            return json.load(f)

    def _make_mock_request(self):
        """Crea un mock de odoo.http.request que delega .env a self.env."""
        mock_req = MagicMock()
        mock_req.env = self.env
        return mock_req

    def test_subscription_created_links_partner(self):
        """_handle_subscription_created enlaza event_log.related_partner_id al partner de la license."""
        from odoo.addons.lemon_squeezy_connector.controllers.webhook import (
            LemonSqueezyWebhookController,
        )
        payload = self._load_fixture('ls_subscription_created.json')
        event_log = self.env['lemon_squeezy.event'].create({
            'event_id': payload['meta']['event_id'],
            'event_name': payload['meta']['event_name'],
            'payload': payload,
        })

        ctrl = LemonSqueezyWebhookController()
        with patch('odoo.addons.lemon_squeezy_connector.controllers.webhook.request',
                   self._make_mock_request()):
            ctrl._handle_subscription_created(event_log, payload)

        self.env.invalidate_all()
        event_fresh = self.env['lemon_squeezy.event'].browse(event_log.id)
        self.assertEqual(event_fresh.related_partner_id, self.partner)
        lic_fresh = self.env['lemon_squeezy.license'].browse(self.license.id)
        self.assertEqual(lic_fresh.subscription_id, '9876543')  # P3: subscription_id persisted by handler

    def test_subscription_payment_success_keeps_active(self):
        """_handle_subscription_payment_success mantiene/restablece license.status='active'."""
        from odoo.addons.lemon_squeezy_connector.controllers.webhook import (
            LemonSqueezyWebhookController,
        )
        payload = self._load_fixture('ls_subscription_payment_success.json')
        event_log = self.env['lemon_squeezy.event'].create({
            'event_id': payload['meta']['event_id'],
            'event_name': payload['meta']['event_name'],
            'payload': payload,
        })

        ctrl = LemonSqueezyWebhookController()
        with patch('odoo.addons.lemon_squeezy_connector.controllers.webhook.request',
                   self._make_mock_request()):
            ctrl._handle_subscription_payment_success(event_log, payload)

        self.env.invalidate_all()
        lic_fresh = self.env['lemon_squeezy.license'].browse(self.license.id)
        self.assertEqual(lic_fresh.status, 'active')

        event_fresh = self.env['lemon_squeezy.event'].browse(event_log.id)
        self.assertEqual(event_fresh.related_partner_id, self.partner)

    def test_subscription_payment_failed_creates_activity(self):
        """_handle_subscription_payment_failed crea mail.activity to-do en el partner."""
        from odoo.addons.lemon_squeezy_connector.controllers.webhook import (
            LemonSqueezyWebhookController,
        )
        payload = self._load_fixture('ls_subscription_payment_failed.json')
        event_log = self.env['lemon_squeezy.event'].create({
            'event_id': payload['meta']['event_id'],
            'event_name': payload['meta']['event_name'],
            'payload': payload,
        })

        # Contar actividades previas del partner
        before = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', self.partner.id),
        ])
        before_count = len(before)

        ctrl = LemonSqueezyWebhookController()
        with patch('odoo.addons.lemon_squeezy_connector.controllers.webhook.request',
                   self._make_mock_request()):
            ctrl._handle_subscription_payment_failed(event_log, payload)

        self.env.invalidate_all()
        after = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', '=', self.partner.id),
        ])
        self.assertEqual(len(after), before_count + 1)

        # Verificar que el summary menciona el subscription_id (P3: handlers usan subscription_id, no order_id)
        new_activity = after.filtered(lambda a: '9876543' in (a.summary or ''))
        self.assertTrue(new_activity, "La actividad debe mencionar el subscription_id en el summary")

        event_fresh = self.env['lemon_squeezy.event'].browse(event_log.id)
        self.assertEqual(event_fresh.related_partner_id, self.partner)

    def test_subscription_cancelled_marks_license_cancelled(self):
        """_handle_subscription_cancelled cambia license.status a 'cancelled'."""
        from odoo.addons.lemon_squeezy_connector.controllers.webhook import (
            LemonSqueezyWebhookController,
        )
        payload = self._load_fixture('ls_subscription_cancelled.json')
        event_log = self.env['lemon_squeezy.event'].create({
            'event_id': payload['meta']['event_id'],
            'event_name': payload['meta']['event_name'],
            'payload': payload,
        })

        ctrl = LemonSqueezyWebhookController()
        with patch('odoo.addons.lemon_squeezy_connector.controllers.webhook.request',
                   self._make_mock_request()):
            ctrl._handle_subscription_cancelled(event_log, payload)

        self.env.invalidate_all()
        lic_fresh = self.env['lemon_squeezy.license'].browse(self.license.id)
        self.assertEqual(lic_fresh.status, 'cancelled')

        event_fresh = self.env['lemon_squeezy.event'].browse(event_log.id)
        self.assertEqual(event_fresh.related_partner_id, self.partner)

    def test_subscription_updated_changes_seats_creates_new_so(self):
        """_handle_subscription_updated detecta cambio de seats → actualiza license + crea nuevo sale.order."""
        from odoo.addons.lemon_squeezy_connector.controllers.webhook import (
            LemonSqueezyWebhookController,
        )
        # Fixture con variant_id="67890" (3 seats) — diferente al variant_id="12345" (1 seat) de la license
        payload = self._load_fixture('ls_subscription_updated.json')
        event_log = self.env['lemon_squeezy.event'].create({
            'event_id': payload['meta']['event_id'],
            'event_name': payload['meta']['event_name'],
            'payload': payload,
        })

        # Contar sale.orders previos del partner
        so_before = self.env['sale.order'].search([('partner_id', '=', self.partner.id)])
        so_count_before = len(so_before)

        ctrl = LemonSqueezyWebhookController()
        with patch('odoo.addons.lemon_squeezy_connector.controllers.webhook.request',
                   self._make_mock_request()):
            ctrl._handle_subscription_updated(event_log, payload)

        self.env.invalidate_all()

        # License seats actualizado a 3
        lic_fresh = self.env['lemon_squeezy.license'].browse(self.license.id)
        self.assertEqual(lic_fresh.seats, 3)
        self.assertEqual(lic_fresh.despacho_name, 'Despacho Test')  # P2: despacho_name set on upgrade Individual → Despacho

        # Nuevo sale.order creado
        so_after = self.env['sale.order'].search([('partner_id', '=', self.partner.id)])
        self.assertEqual(len(so_after), so_count_before + 1)

        event_fresh = self.env['lemon_squeezy.event'].browse(event_log.id)
        self.assertEqual(event_fresh.related_partner_id, self.partner)
