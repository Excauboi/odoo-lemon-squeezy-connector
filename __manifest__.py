{
    'name': 'Lemon Squeezy Connector',
    'version': '19.0.3.0.0',
    'category': 'Sales/Subscriptions',
    'summary': 'Pasarela Lemon Squeezy (Merchant of Record) <-> Odoo: webhooks + licencias + watermark dinámico',
    'description': """
Conector Odoo <-> Lemon Squeezy
================================

Procesa webhooks Lemon Squeezy (HMAC SHA-256 validated), crea res.partner +
sale.order + lemon_squeezy.license, y sirve descargas digitales con sustitución
dinámica de placeholders watermark en serve time.

Eventos soportados (6):
- order_created
- subscription_created
- subscription_updated
- subscription_payment_success
- subscription_payment_failed
- subscription_cancelled

Reusable: cualquier instalación Odoo 19 que monetice mediante Lemon Squeezy.
""",
    'author': 'Jose Ruiberriz / Excauboi',
    'website': 'https://github.com/Excauboi/odoo-lemon-squeezy-connector',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'sale', 'account', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'views/lemon_squeezy_event_views.xml',
        'views/lemon_squeezy_license_views.xml',
        'views/lemon_squeezy_product_mapping_views.xml',
        'views/menu_items.xml',
    ],
    'post_init_hook': '_post_init_default_billing_cycle',
    'installable': True,
    'application': False,
    'auto_install': False,
}
