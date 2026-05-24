from odoo.tests import TransactionCase, tagged


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestProductMapping(TransactionCase):

    def setUp(self):
        super().setUp()
        self.product = self.env['product.product'].create({
            'name': 'LABORALIA Plugin Skill - Individual Annual',
            'type': 'service',
            'list_price': 1200.0,
        })

    def test_mapping_create_and_lookup(self):
        mapping = self.env['lemon_squeezy.product_mapping'].create({
            'variant_id': '12345',
            'variant_name': 'Individual anual',
            'product_id': self.product.id,
            'seats': 1,
            'billing_cycle': 'annual',
        })
        found = self.env['lemon_squeezy.product_mapping'].search([('variant_id', '=', '12345')])
        self.assertEqual(found, mapping)
        self.assertEqual(found.seats, 1)
        self.assertEqual(found.billing_cycle, 'annual')

    def test_lookup_by_seats_billing(self):
        self.env['lemon_squeezy.product_mapping'].create({
            'variant_id': '67890',
            'variant_name': 'Despacho 3 mensual',
            'product_id': self.product.id,
            'seats': 3,
            'billing_cycle': 'monthly',
        })
        found = self.env['lemon_squeezy.product_mapping'].search([
            ('seats', '=', 3),
            ('billing_cycle', '=', 'monthly'),
        ])
        self.assertEqual(len(found), 1)
        self.assertEqual(found.variant_id, '67890')

    def test_variant_id_unique_constraint(self):
        # psycopg2 IntegrityError from UNIQUE constraint
        self.env['lemon_squeezy.product_mapping'].create({
            'variant_id': '11111',
            'product_id': self.product.id,
            'billing_cycle': 'annual',
        })
        with self.assertRaises(Exception):
            self.env['lemon_squeezy.product_mapping'].create({
                'variant_id': '11111',
                'product_id': self.product.id,
                'billing_cycle': 'monthly',
            })
