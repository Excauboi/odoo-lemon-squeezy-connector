"""Tests HttpCase para el download controller Lemon Squeezy.

4 tests de integración:
- 404 license key desconocida
- 404 licencia con status='cancelled'
- 200 con ZIP modificado (watermark ORDER_ID_PLACEHOLDER sustituido)
- Creación de lemon_squeezy.event log tras descarga exitosa
"""
import base64
import io
import zipfile

from odoo.tests import HttpCase, tagged


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestDownloadController(HttpCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Test Buyer', 'email': 'buyer@example.com',
        })
        # Crear bundle template como ir.attachment
        bundle_bytes = self._make_sample_zip()
        attachment = self.env['ir.attachment'].sudo().create({
            'name': 'laboralia-bundle-template.zip',
            'datas': base64.b64encode(bundle_bytes),
            'mimetype': 'application/zip',
        })
        self.env['ir.config_parameter'].sudo().set_param(
            'lemon_squeezy.bundle_attachment_id', str(attachment.id)
        )

    def _make_sample_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('skills/laboral/SKILL.md', """---
name: laboral
---
# /laboral
_Generado por LABORALIA · Order #{ORDER_ID_PLACEHOLDER} · ...
""")
        return buf.getvalue()

    def test_download_404_unknown_license(self):
        r = self.url_open('/lemon_squeezy/download/nonexistent_key_xyz')
        self.assertEqual(r.status_code, 404)

    def test_download_404_cancelled_license(self):
        self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_cancelled_001',
            'order_id': 'ord_cancelled_001',
            'partner_id': self.partner.id,
            'seats': 1,
            'billing_cycle': 'annual',
            'status': 'cancelled',
        })
        r = self.url_open('/lemon_squeezy/download/lic_cancelled_001')
        self.assertEqual(r.status_code, 404)

    def test_download_serves_zip_with_watermark_individual(self):
        self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_active_001',
            'order_id': 'ord-actv-123',
            'partner_id': self.partner.id,
            'seats': 1,
            'billing_cycle': 'annual',
            'status': 'active',
        })
        r = self.url_open('/lemon_squeezy/download/lic_active_001')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('Content-Type'), 'application/zip')
        self.assertIn('attachment', r.headers.get('Content-Disposition', ''))

        self.env.invalidate_all()

        # Verificar contenido del ZIP descargado
        with zipfile.ZipFile(io.BytesIO(r.content), 'r') as zf:
            skill_md = zf.read('skills/laboral/SKILL.md').decode()
            self.assertIn('Order #ord-actv-123', skill_md)
            self.assertNotIn('{ORDER_ID_PLACEHOLDER}', skill_md)

    def test_download_logs_event(self):
        self.env['lemon_squeezy.license'].create({
            'license_key': 'lic_log_001',
            'order_id': 'ord-log-001',
            'partner_id': self.partner.id,
            'seats': 1,
            'billing_cycle': 'annual',
            'status': 'active',
        })
        self.url_open('/lemon_squeezy/download/lic_log_001')
        self.env.invalidate_all()
        events = self.env['lemon_squeezy.event'].sudo().search([
            ('event_name', '=', 'download'),
            ('event_id', 'like', 'dl_lic_log_001%'),
        ])
        self.assertTrue(events)
