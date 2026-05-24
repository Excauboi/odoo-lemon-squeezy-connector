from odoo import models, fields


class LemonSqueezyProductMapping(models.Model):
    _name = 'lemon_squeezy.product_mapping'
    _description = 'Map Lemon Squeezy variant_id -> Odoo product.product'
    _order = 'seats, billing_cycle'
    _rec_name = 'variant_name'  # variant_name is human-readable; variant_id is opaque LS ID

    variant_id = fields.Char(string='LS Variant ID', required=True)
    variant_name = fields.Char(string='Variant Name')
    product_id = fields.Many2one(
        'product.product',
        string='Odoo Product',
        required=True,
        ondelete='restrict',  # prevent product deletion if mappings exist
    )
    seats = fields.Integer(string='Seats', default=1)
    billing_cycle = fields.Selection([
        ('monthly', 'Mensual'),
        ('annual', 'Anual'),
    ], string='Billing Cycle', required=True)

    # Odoo 19: use models.Constraint instead of deprecated _sql_constraints.
    # Naming convention: _<short_name> → PostgreSQL constraint named
    # <table>_<short_name> (e.g. _variant_id_unique → lemon_squeezy_product_mapping_variant_id_unique).
    # No index=True on variant_id: UNIQUE constraint already creates a B-tree index.
    _variant_id_unique = models.Constraint(
        'UNIQUE(variant_id)',
        'LS variant_id must be unique',
    )
    _seats_billing_unique = models.Constraint(
        'UNIQUE(seats, billing_cycle)',
        'Combinación seats + billing_cycle debe ser única',
    )
