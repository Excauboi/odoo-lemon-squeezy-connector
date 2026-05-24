"""Webhook controller para recibir eventos de Lemon Squeezy.

POST /lemon_squeezy/webhook
- type='http' (no type='json'): necesitamos el body raw bytes para HMAC antes de parsear
- auth='public': el endpoint es público; la autenticación es el HMAC
- csrf=False: webhooks no tienen CSRF token; el HMAC es el mecanismo de autenticación
- save_session=False: no persistir sesión para llamadas webhook (evita rows inútiles)
"""
import json
import logging

from psycopg2 import IntegrityError as PsycopgIntegrityError

from odoo import http
from odoo.http import request

from ..utils.hmac_validator import validate_lemon_squeezy_signature

_logger = logging.getLogger(__name__)

# Mapping event_name → handler method name del controller
KNOWN_EVENTS = {
    'order_created',
    'subscription_created',
    'subscription_updated',
    'subscription_payment_success',
    'subscription_payment_failed',
    'subscription_cancelled',
}


class LemonSqueezyWebhookController(http.Controller):

    @http.route(
        '/lemon_squeezy/webhook',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def webhook(self, **kwargs):
        # 1. Validar HMAC
        secret = request.env['ir.config_parameter'].sudo().get_param(
            'lemon_squeezy.webhook_secret'
        )
        if not secret:
            _logger.error("LS webhook: lemon_squeezy.webhook_secret no configurado")
            return request.make_response(
                json.dumps({'error': 'server_not_configured'}),
                status=500,
                headers=[('Content-Type', 'application/json')],
            )

        signature = request.httprequest.headers.get('X-Signature')
        if signature:
            signature = signature.strip()  # B2.6 tracker: edge case whitespace en HTTP headers
        body = request.httprequest.get_data()  # bytes raw

        if not validate_lemon_squeezy_signature(body, signature, secret):
            _logger.warning("LS webhook: firma HMAC inválida (signature=%.32s...)", signature or '')
            return request.make_response(
                json.dumps({'error': 'invalid_signature'}),
                status=401,
                headers=[('Content-Type', 'application/json')],
            )

        # 2. Parsear payload
        try:
            payload = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _logger.warning("LS webhook: payload no parseable: %s", e)
            return request.make_response(
                json.dumps({'error': 'invalid_payload'}),
                status=400,
                headers=[('Content-Type', 'application/json')],
            )

        meta = payload.get('meta', {})
        event_id = meta.get('event_id') or meta.get('webhook_id')  # LS usa distintos fields según versión
        event_name = meta.get('event_name') or request.httprequest.headers.get('X-Event-Name')

        if not event_id or not event_name:
            _logger.warning("LS webhook: meta.event_id/event_name ausentes")
            return request.make_response(
                json.dumps({'error': 'missing_metadata'}),
                status=400,
                headers=[('Content-Type', 'application/json')],
            )

        # 3. Idempotencia por event_id
        existing = request.env['lemon_squeezy.event'].sudo().search(
            [('event_id', '=', event_id)], limit=1
        )
        if existing:
            _logger.info("LS webhook: evento %s ya procesado (idempotency)", event_id)
            return request.make_response(
                json.dumps({'status': 'already_processed'}),
                status=200,
                headers=[('Content-Type', 'application/json')],
            )

        # 4. Crear log evento (idempotencia race-safe via IntegrityError catch)
        try:
            event_log = request.env['lemon_squeezy.event'].sudo().create({
                'event_id': event_id,
                'event_name': event_name,
                'payload': payload,
                'processed': False,
            })
        except PsycopgIntegrityError:
            # Race: otro worker creó el event_id entre nuestro search y create.
            # Tratar como already_processed — respuesta idempotente, sin retry LS.
            _logger.info("LS webhook: race idempotency para %s, descartado", event_id)
            return request.make_response(
                json.dumps({'status': 'already_processed'}),
                status=200,
                headers=[('Content-Type', 'application/json')],
            )

        # 5. Routing: handler por event_name (implementado en B2.9)
        try:
            self._route_event(event_log, event_name, payload)
            event_log.write({'processed': True})
        except Exception as exc:  # noqa: BLE001
            _logger.exception("LS webhook: error procesando %s/%s", event_name, event_id)
            event_log.write({
                'processed': True,
                'processing_error': str(exc),
            })

        # 6. Responder siempre 200 OK para evitar LS retries innecesarios
        return request.make_response(
            json.dumps({'status': 'ok', 'event_id': event_id}),
            status=200,
            headers=[('Content-Type', 'application/json')],
        )

    def _route_event(self, event_log, event_name, payload):
        """Routing event_name → handler. Implementación detallada en B2.9 (handlers).

        En B2.8 solo se loggea unknown events para que tests de idempotency + auth pasen.
        """
        if event_name not in KNOWN_EVENTS:
            event_log.write({'processing_error': f'unknown_event: {event_name}'})
            _logger.info("LS webhook: evento %s desconocido (no handler)", event_name)
            return
        # Los handlers reales se cablean en B2.9
        # Por ahora marcamos como processed sin acción
        _logger.info("LS webhook: %s recibido (handler pendiente B2.9)", event_name)
