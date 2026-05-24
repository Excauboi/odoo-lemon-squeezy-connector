from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestLemonSqueezyEventIdempotency(TransactionCase):

    def test_event_creates_with_required_fields(self):
        ev = self.env['lemon_squeezy.event'].create({
            'event_id': 'evt_test_001',
            'event_name': 'order_created',
            'payload': {'foo': 'bar'},
        })
        self.assertEqual(ev.event_id, 'evt_test_001')
        self.assertEqual(ev.event_name, 'order_created')
        self.assertFalse(ev.processed)
        self.assertEqual(ev.payload, {'foo': 'bar'})

    def test_event_id_unique_constraint(self):
        self.env['lemon_squeezy.event'].create({
            'event_id': 'evt_dupe_001',
            'event_name': 'order_created',
            'payload': {},
        })
        with self.assertRaises(Exception):
            self.env['lemon_squeezy.event'].create({
                'event_id': 'evt_dupe_001',
                'event_name': 'order_created',
                'payload': {},
            })

    def test_event_processed_toggle(self):
        ev = self.env['lemon_squeezy.event'].create({
            'event_id': 'evt_proc_001',
            'event_name': 'subscription_created',
            'payload': {},
        })
        ev.write({'processed': True})
        self.assertTrue(ev.processed)
