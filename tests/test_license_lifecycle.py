from datetime import timedelta
from odoo.tests import TransactionCase, tagged
from odoo import fields


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestLicenseLifecycle(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Despacho Test',
            'email': 'test@example.com',
        })

    def test_license_create_default_status_active(self):
        lic = self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_test_001',
            'order_id': 'ord_test_001',
            'partner_id': self.partner.id,
            'seats': 1,
        })
        self.assertEqual(lic.status, 'active')
        self.assertEqual(lic.seats, 1)
        self.assertFalse(lic.despacho_name)

    def test_license_despacho_with_seats_and_name(self):
        lic = self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_test_002',
            'order_id': 'ord_test_002',
            'partner_id': self.partner.id,
            'seats': 5,
            'despacho_name': 'Despacho Pérez & Asociados',
        })
        self.assertEqual(lic.seats, 5)
        self.assertEqual(lic.despacho_name, 'Despacho Pérez & Asociados')

    def test_license_key_unique(self):
        # psycopg2 IntegrityError from UNIQUE constraint
        self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_dup_001',
            'order_id': 'ord_dup_001',
            'partner_id': self.partner.id,
            'seats': 1,
        })
        with self.assertRaises(Exception):
            self.env['lemon_squeezy.license'].create({
                'license_key': 'lic_dup_001',
                'order_id': 'ord_dup_002',
                'partner_id': self.partner.id,
                'seats': 1,
            })

    def test_license_status_transitions(self):
        lic = self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_lc_001',
            'order_id': 'ord_lc_001',
            'partner_id': self.partner.id,
            'seats': 1,
        })
        lic.write({'status': 'cancelled'})
        self.assertEqual(lic.status, 'cancelled')

        lic.write({'status': 'expired', 'expires_at': fields.Datetime.now() - timedelta(days=1)})
        self.assertEqual(lic.status, 'expired')
        self.assertLess(lic.expires_at, fields.Datetime.now())

    def test_license_is_active_computed(self):
        """is_active = status == 'active' AND (expires_at IS NULL OR expires_at > now)"""
        lic_active = self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_act_001',
            'order_id': 'ord_act_001',
            'partner_id': self.partner.id,
            'seats': 1,
        })
        self.assertTrue(lic_active.is_active)

        lic_active.write({'expires_at': fields.Datetime.now() - timedelta(days=1)})
        # status sigue 'active' pero expires_at pasado → is_active False
        self.assertFalse(lic_active.is_active)

        # Edge case: cancelled status overrides expires_at='future' (most operationally dangerous case)
        lic_cancel = self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_cancel_001',
            'order_id': 'ord_cancel_001',
            'partner_id': self.partner.id,
            'seats': 1,
            'expires_at': fields.Datetime.now() + timedelta(days=30),  # future
        })
        self.assertTrue(lic_cancel.is_active)  # active + future expires → True
        lic_cancel.write({'status': 'cancelled'})
        self.assertFalse(lic_cancel.is_active)  # cancelled + future expires → False (status override)
