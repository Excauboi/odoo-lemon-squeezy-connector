import json
import os
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestHandlerOrderCreated(TransactionCase):

    def setUp(self):
        super().setUp()
        # Crear product + mapping
        self.product = self.env['product.product'].create({
            'name': 'LABORALIA Plugin Skill - Individual Annual',
            'type': 'service',
            'list_price': 1200.0,
        })
        self.env['lemon_squeezy.product_mapping'].create({
            'variant_id': '12345',
            'variant_name': 'Individual anual',
            'product_id': self.product.id,
            'seats': 1,
            'billing_cycle': 'annual',
        })

    def _load_fixture(self, name):
        with open(os.path.join(FIXTURES_DIR, name)) as f:
            return json.load(f)

    def _make_mock_request(self):
        """Crea mock de odoo.http.request con .env apuntando a self.env."""
        mock_req = MagicMock()
        mock_req.env = self.env
        return mock_req

    def test_order_created_creates_partner_sale_order_license(self):
        from odoo.addons.lemon_squeezy_connector.controllers.webhook import (
            LemonSqueezyWebhookController,
        )
        payload = self._load_fixture('ls_order_created.json')

        event_log = self.env['lemon_squeezy.event'].create({
            'event_id': payload['meta']['event_id'],
            'event_name': payload['meta']['event_name'],
            'payload': payload,
        })

        ctrl = LemonSqueezyWebhookController()
        with patch('odoo.addons.lemon_squeezy_connector.controllers.webhook.request',
                   self._make_mock_request()):
            ctrl._handle_order_created(event_log, payload)

        # Verificar partner creado por email
        partners = self.env['res.partner'].search([('email', '=', 'test@example.com')])
        self.assertEqual(len(partners), 1)
        self.assertEqual(partners.name, 'Despacho Test')

        # Verificar sale.order creado
        sale_orders = self.env['sale.order'].search([('partner_id', '=', partners.id)])
        self.assertEqual(len(sale_orders), 1)
        self.assertEqual(sale_orders.state, 'sale')  # confirmed

        # Verificar license creada
        licenses = self.env['lemon_squeezy.license'].search([('order_id', '=', '1234567')])
        self.assertEqual(len(licenses), 1)
        self.assertEqual(licenses.seats, 1)
        self.assertEqual(licenses.status, 'active')

        # Verificar event log enlazado — refrescar cache del recordset
        self.env.invalidate_all()
        event_log_fresh = self.env['lemon_squeezy.event'].browse(event_log.id)
        self.assertEqual(event_log_fresh.related_partner_id, partners)
        self.assertEqual(event_log_fresh.related_sale_order_id, sale_orders)

    def test_order_created_idempotent_by_order_id(self):
        """Si ya existe license con order_id, no crea sale.order duplicada."""
        from odoo.addons.lemon_squeezy_connector.controllers.webhook import (
            LemonSqueezyWebhookController,
        )
        payload = self._load_fixture('ls_order_created.json')
        ctrl = LemonSqueezyWebhookController()

        mock_req = self._make_mock_request()
        event1 = self.env['lemon_squeezy.event'].create({
            'event_id': 'evt_idem_oc_001',
            'event_name': 'order_created',
            'payload': payload,
        })
        with patch('odoo.addons.lemon_squeezy_connector.controllers.webhook.request', mock_req):
            ctrl._handle_order_created(event1, payload)

        event2 = self.env['lemon_squeezy.event'].create({
            'event_id': 'evt_idem_oc_002',  # event_id distinto, mismo order_id
            'event_name': 'order_created',
            'payload': payload,
        })
        with patch('odoo.addons.lemon_squeezy_connector.controllers.webhook.request', mock_req):
            ctrl._handle_order_created(event2, payload)

        licenses = self.env['lemon_squeezy.license'].search([('order_id', '=', '1234567')])
        self.assertEqual(len(licenses), 1)
