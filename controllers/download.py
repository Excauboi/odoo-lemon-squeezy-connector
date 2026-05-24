"""Controller de descarga de bundles LABORALIA.

Endpoint público con license_key gating:
    GET /laboralia/download/<license_key>

Flujo:
1. Lookup license: status='active' AND is_active=True → 404 si no
2. Lookup bundle template (ir.attachment via ir.config_parameter
   'lemon_squeezy.bundle_attachment_id') → 404 si no
3. B2.7 contract guard: si seats>1 SIN despacho_name → 404
   (evitar placeholders literales en output)
4. replace_placeholders_in_bundle_bytes en try/except → 500 si
   bundle malformado (BadZipFile / tarfile.ReadError)
5. Crear lemon_squeezy.event log (event_name='download', event_id con secrets.token_hex suffix)
6. make_response con application/zip + Content-Disposition attachment
"""
import base64
import logging
import secrets

from odoo import http
from odoo.http import request

from ..utils.watermark_replacer import replace_placeholders_in_bundle_bytes

_logger = logging.getLogger(__name__)


class LemonSqueezyDownloadController(http.Controller):

    @http.route(
        '/laboralia/download/<string:license_key>',
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
    )
    def download(self, license_key, **kwargs):
        # 1. Lookup license — status='active' filtra canceladas/expiradas por campo
        License = request.env['lemon_squeezy.license'].sudo()
        lic = License.search([
            ('license_key', '=', license_key),
            ('status', '=', 'active'),
        ], limit=1)
        # is_active añade la comprobación de expires_at (belt and suspenders)
        if not lic or not lic.is_active:
            return request.not_found()

        # 2. Cargar bundle template vía ir.config_parameter
        attachment_id_param = request.env['ir.config_parameter'].sudo().get_param(
            'lemon_squeezy.bundle_attachment_id'
        )
        if not attachment_id_param:
            _logger.error(
                "lemon_squeezy.bundle_attachment_id no configurado — descarga abortada para license %s",
                license_key,
            )
            return request.not_found()

        attachment = request.env['ir.attachment'].sudo().browse(int(attachment_id_param))
        if not attachment.exists() or not attachment.datas:
            _logger.error(
                "Bundle attachment id=%s no existe o vacío — descarga abortada para license %s",
                attachment_id_param,
                license_key,
            )
            return request.not_found()

        template_bytes = base64.b64decode(attachment.datas)
        fmt = 'zip' if attachment.mimetype == 'application/zip' else 'tar.gz'

        # 3. B2.7 TRACKERS: validar despacho_name si seats > 1
        if lic.seats > 1 and not lic.despacho_name:
            _logger.error(
                "License %s tiene seats=%d pero despacho_name vacío — descarga rechazada para evitar placeholders literales en output",
                license_key,
                lic.seats,
            )
            return request.not_found()

        # 4. Reemplazar placeholders (catch bundles malformados)
        try:
            modified_bytes = replace_placeholders_in_bundle_bytes(
                template_bytes,
                fmt,
                order_id=lic.order_id,
                seats=lic.seats,
                despacho_name=lic.despacho_name,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "Bundle template malformado para license %s: %s",
                license_key,
                exc,
            )
            return request.make_response(
                'Bundle template error',
                status=500,
                headers=[('Content-Type', 'text/plain')],
            )

        # 5. Log download event
        request.env['lemon_squeezy.event'].sudo().create({
            'event_id': f'dl_{license_key}_{secrets.token_hex(4)}',
            'event_name': 'download',
            'payload': {
                'license_key': license_key,
                'order_id': lic.order_id,
                'seats': lic.seats,
            },
            'processed': True,
            'related_partner_id': lic.partner_id.id,
        })

        # 6. Responder con el bundle modificado
        content_type = 'application/zip' if fmt == 'zip' else 'application/gzip'
        filename = f'laboralia-{lic.order_id}.{fmt}'
        return request.make_response(
            modified_bytes,
            headers=[
                ('Content-Type', content_type),
                ('Content-Disposition', f'attachment; filename={filename}'),
                ('Content-Length', str(len(modified_bytes))),
            ],
        )
