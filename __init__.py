from . import models
from . import controllers


def _post_init_default_billing_cycle(env):
    """Default billing_cycle for any pre-existing license rows (upgrade from v0.2.0).

    Idempotente: solo escribe en filas que todavía tengan billing_cycle=False
    (Selection nullable cuando el campo se añade a una BD existente).
    """
    licenses = env['lemon_squeezy.license'].search([('billing_cycle', '=', False)])
    if licenses:
        licenses.write({'billing_cycle': 'annual'})
