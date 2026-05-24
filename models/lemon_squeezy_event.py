from odoo import models, fields


class LemonSqueezyEvent(models.Model):
    _name = 'lemon_squeezy.event'
    _description = 'Lemon Squeezy Webhook Event (idempotency log)'
    _order = 'received_at desc'
    _rec_name = 'event_id'

    event_id = fields.Char(string='Event ID', required=True)
    event_name = fields.Char(string='Event Name', required=True)
    payload = fields.Json(string='Payload')
    received_at = fields.Datetime(
        string='Received At',
        default=fields.Datetime.now,
        readonly=True,
    )
    processed = fields.Boolean(string='Processed', default=False)
    processing_error = fields.Text(string='Processing Error')
    related_partner_id = fields.Many2one('res.partner', string='Partner')
    related_sale_order_id = fields.Many2one('sale.order', string='Sale Order')

    # Odoo 19: use models.Constraint instead of deprecated _sql_constraints.
    # Naming convention: _<short_name> → PostgreSQL constraint named
    # <table>_<short_name> (e.g. _event_id_unique → lemon_squeezy_event_event_id_unique).
    # B2.3/B2.4: follow this same _<short_name> pattern for new constraints.
    _event_id_unique = models.Constraint(
        'UNIQUE(event_id)',
        'Lemon Squeezy event_id must be unique',
    )
