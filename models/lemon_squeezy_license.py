from odoo import models, fields, api


class LemonSqueezyLicense(models.Model):
    _name = 'lemon_squeezy.license'
    _description = 'Active LABORALIA License (for watermark + download)'
    _order = 'create_date desc'
    _rec_name = 'license_key'  # human-trackable identifier

    license_key = fields.Char(string='License Key', required=True)
    order_id = fields.Char(string='LS Order ID', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
        ondelete='restrict',  # no perder licencias si partner accidentalmente eliminado
    )
    seats = fields.Integer(string='Seats', default=1, required=True)
    despacho_name = fields.Char(string='Despacho Name')
    status = fields.Selection([
        ('active', 'Activa'),
        ('expired', 'Expirada'),
        ('cancelled', 'Cancelada'),
    ], string='Status', default='active', required=True)
    expires_at = fields.Datetime(string='Expires At')
    # store=False: recompute en acceso es aceptable; almacenar requeriría trigger en reloj
    # B2.10 download controller usa is_active para gatear acceso
    is_active = fields.Boolean(
        string='Is Active (Computed)',
        compute='_compute_is_active',
        store=False,
    )

    # Odoo 19: use models.Constraint instead of deprecated _sql_constraints.
    # Naming convention: _<short_name> → PostgreSQL constraint named
    # <table>_<short_name> (e.g. _license_key_unique → lemon_squeezy_license_license_key_unique).
    # No index=True on license_key: UNIQUE constraint already creates a B-tree index.
    # index=True on order_id: no UNIQUE (1 order puede generar N licencias); frecuentes lookups en B2.9
    _license_key_unique = models.Constraint(
        'UNIQUE(license_key)',
        'License key must be unique',
    )
    _seats_positive = models.Constraint(
        'CHECK(seats > 0)',
        'Seats must be > 0',
    )

    @api.depends('status', 'expires_at')
    def _compute_is_active(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_active = (
                rec.status == 'active'
                and (not rec.expires_at or rec.expires_at > now)
            )
