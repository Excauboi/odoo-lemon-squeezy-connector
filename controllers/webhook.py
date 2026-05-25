"""Webhook controller para recibir eventos de Lemon Squeezy.

POST /lemon_squeezy/webhook
- type='http' (no type='json'): necesitamos el body raw bytes para HMAC antes de parsear
- auth='public': el endpoint es público; la autenticación es el HMAC
- csrf=False: webhooks no tienen CSRF token; el HMAC es el mecanismo de autenticación
- save_session=False: no persistir sesión para llamadas webhook (evita rows inútiles)
"""
import json
import logging
import secrets
from datetime import datetime, timezone

from dateutil.relativedelta import relativedelta
from psycopg2 import IntegrityError as PsycopgIntegrityError

from odoo import http
from odoo.http import request

from ..utils.hmac_validator import validate_lemon_squeezy_signature

_logger = logging.getLogger(__name__)

# Supported event_name → handler method (dispatched via getattr in _route_event).
# Listed here for documentation; not used in dispatch logic.
# Adding a 7th handler: define _handle_<event_name> on the controller class.
SUPPORTED_EVENTS_DOC = (
    'order_created',
    'subscription_created',
    'subscription_updated',
    'subscription_payment_success',
    'subscription_payment_failed',
    'subscription_cancelled',
)


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
        if len(body) > 65_536:  # 64 KB cap — LS webhooks never approach this
            _logger.warning("LS webhook: payload too large (%d bytes)", len(body))
            return request.make_response(
                json.dumps({'error': 'payload_too_large'}),
                status=413,
                headers=[('Content-Type', 'application/json')],
            )

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
        """Routing event_name → handler via getattr dispatch (B2.9)."""
        handler = getattr(self, f'_handle_{event_name}', None)
        if not handler:
            event_log.write({'processing_error': f'no_handler_for_{event_name}'})
            _logger.info("LS webhook: %s sin handler", event_name)
            return
        handler(event_log, payload)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_or_create_partner(self, attrs):
        email = attrs.get('user_email')
        name = attrs.get('user_name') or email
        if not email:
            raise ValueError("Payload sin user_email")
        Partner = request.env['res.partner'].sudo()
        partner = Partner.search([('email', '=', email)], limit=1)
        if not partner:
            partner = Partner.create({
                'name': name,
                'email': email,
                'customer_rank': 1,
            })
        return partner

    def _get_mapping_for_variant(self, variant_id):
        return request.env['lemon_squeezy.product_mapping'].sudo().search(
            [('variant_id', '=', str(variant_id))], limit=1
        )

    def _get_or_create_ls_partner(self):
        """Get or create the 'Lemon Squeezy' merchant partner for internal MoR invoicing.

        LS is the Merchant of Record; the connector creates internal account.move
        invoices payable to LS for each customer order. This partner represents LS
        in Odoo accounting.

        Configurable via ir.config_parameter 'lemon_squeezy.merchant_partner_id' (id, cached).
        If unset or invalid, looks up by name (default 'Lemon Squeezy Inc.') or creates.
        Caches the id back to config_parameter for future calls.
        """
        Param = request.env['ir.config_parameter'].sudo()
        Partner = request.env['res.partner'].sudo()

        cached_id = Param.get_param('lemon_squeezy.merchant_partner_id')
        if cached_id:
            partner = Partner.browse(int(cached_id))
            if partner.exists():
                return partner

        name = Param.get_param('lemon_squeezy.merchant_partner_name') or 'Lemon Squeezy Inc.'
        partner = Partner.search(
            [('name', '=', name), ('is_company', '=', True)], limit=1
        )
        if not partner:
            partner = Partner.create({
                'name': name,
                'is_company': True,
                'customer_rank': 1,
                'comment': 'Merchant of Record para ventas vía Lemon Squeezy. '
                           'Factura emitida a este partner por cada order_created (v0.4.0+).',
            })
        Param.set_param('lemon_squeezy.merchant_partner_id', str(partner.id))
        return partner

    def _create_internal_ls_invoice(self, order_id, customer_partner, mapping, subtotal_cents):
        """Crea account.move borrador interna a LS por una venta MoR.

        El cliente final (customer_partner) se referencia en `ref` para tracking,
        pero el partner_id de la factura es LS (Merchant of Record).

        Auto-post configurable via ir.config_parameter 'lemon_squeezy.invoice_auto_post'
        (default 'false' = stays draft for Jose's monthly reconciliation review).

        Returns: account.move record.
        Raises: ValueError if no sale journal found in current company.
        """
        ls_partner = self._get_or_create_ls_partner()

        journal = request.env['account.journal'].sudo().search(
            [('type', '=', 'sale'), ('company_id', '=', request.env.company.id)],
            limit=1,
        )
        if not journal:
            raise ValueError(
                f"No sale journal found for company {request.env.company.name!r}"
            )

        customer_ref = f'Cliente final: {customer_partner.name}'
        if customer_partner.email:
            customer_ref += f' <{customer_partner.email}>'

        move = request.env['account.move'].sudo().create({
            'move_type': 'out_invoice',
            'partner_id': ls_partner.id,
            'journal_id': journal.id,
            'invoice_origin': f'LS Order {order_id}',
            'ref': customer_ref,
            'invoice_line_ids': [(0, 0, {
                'product_id': mapping.product_id.id,
                'quantity': 1.0,
                'price_unit': subtotal_cents / 100.0,
            })],
        })

        Param = request.env['ir.config_parameter'].sudo()
        auto_post = Param.get_param('lemon_squeezy.invoice_auto_post', 'false').lower() in ('true', '1', 'yes')
        if auto_post:
            move.action_post()

        return move

    def _generate_license_key(self, order_id):
        return f"lic_{order_id}_{secrets.token_urlsafe(16)}"

    def _extend_expires_at(self, license_rec):
        """Extend license.expires_at by 1 billing cycle.

        If current expires_at is past, extend from now (graceful recovery from
        late payment_success). Otherwise extend from current expires_at (don't
        lose days from early renewal).
        """
        now = datetime.now(timezone.utc)
        # Odoo stores naive UTC datetimes; convert now to naive for comparison
        now_naive = now.replace(tzinfo=None)
        current = license_rec.expires_at or now_naive
        base = current if current > now_naive else now_naive
        if license_rec.billing_cycle == 'annual':
            new_expires = base + relativedelta(years=1)
        elif license_rec.billing_cycle == 'monthly':
            new_expires = base + relativedelta(months=1)
        else:
            raise ValueError(f"Unknown billing_cycle: {license_rec.billing_cycle!r}")
        license_rec.write({'expires_at': new_expires})

    # ── Event handlers ───────────────────────────────────────────────────────

    def _handle_order_created(self, event_log, payload):
        data = payload['data']['attributes']
        order_id = str(payload['data']['id'])
        first_item = data.get('first_order_item', {})
        variant_id = str(first_item.get('variant_id', ''))

        mapping = self._get_mapping_for_variant(variant_id)
        if not mapping:
            raise ValueError(f"No product_mapping for variant_id={variant_id}")

        partner = self._get_or_create_partner(data)

        # Idempotencia por order_id (LS puede reenviar order_created si pasa algo)
        existing_lic = request.env['lemon_squeezy.license'].sudo().search(
            [('order_id', '=', order_id)], limit=1
        )
        if existing_lic:
            event_log.write({
                'related_partner_id': partner.id,
                'processing_error': f'duplicate_order_id_{order_id}',
            })
            return

        # Crear sale.order confirmed
        SaleOrder = request.env['sale.order'].sudo()
        so = SaleOrder.create({
            'partner_id': partner.id,
            'order_line': [(0, 0, {
                'product_id': mapping.product_id.id,
                'product_uom_qty': 1,
                'price_unit': data.get('subtotal', 0) / 100.0,  # LS centimos
            })],
            'origin': f'LS Order {order_id}',
        })
        so.action_confirm()

        # Compute initial expires_at from billing cycle (B2.12 v0.3.0)
        # Odoo Datetime fields require naive UTC datetimes; strip tzinfo after computing delta.
        now_utc = datetime.now(timezone.utc)
        if mapping.billing_cycle == 'annual':
            expires_at = (now_utc + relativedelta(years=1)).replace(tzinfo=None)
        elif mapping.billing_cycle == 'monthly':
            expires_at = (now_utc + relativedelta(months=1)).replace(tzinfo=None)
        else:
            raise ValueError(f"Unknown billing_cycle: {mapping.billing_cycle!r}")

        # Crear license
        license_key = self._generate_license_key(order_id)
        request.env['lemon_squeezy.license'].sudo().create({
            'license_key': license_key,
            'order_id': order_id,
            'partner_id': partner.id,
            'seats': mapping.seats,
            'despacho_name': partner.name if mapping.seats > 1 else False,
            'status': 'active',
            'billing_cycle': mapping.billing_cycle,  # v0.3.0: persist cycle for renewal
            'expires_at': expires_at,                 # v0.3.0: 1 month or 1 year from now
        })

        event_log.write({
            'related_partner_id': partner.id,
            'related_sale_order_id': so.id,
        })

        # v0.4.0: Crear factura interna a LS (Opción A — LS sigue MoR, esto es factura
        # de Jose a LS por la venta MoR). Falla soft: si crea sale.order + license OK
        # pero la factura falla, el evento NO retry, admin la crea manualmente.
        try:
            invoice = self._create_internal_ls_invoice(
                order_id=order_id,
                customer_partner=partner,
                mapping=mapping,
                subtotal_cents=data.get('subtotal', 0),
            )
            _logger.info(
                "LS connector: factura interna creada %s para order %s",
                invoice.name, order_id,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "LS connector: error creando factura interna LS para order %s: %s",
                order_id, exc,
            )
            # No raise — la venta + license están OK. Admin crea factura manual.

    def _handle_subscription_created(self, event_log, payload):
        # Buscar sale.order del order_created previo (LS dispara order_created + subscription_created)
        order_id = str(payload['data']['attributes'].get('order_id', ''))
        subscription_id = str(payload['data'].get('id', ''))
        if not order_id:
            raise ValueError("subscription_created sin order_id")
        if not subscription_id:
            raise ValueError("subscription_created sin data.id (subscription_id)")
        license = request.env['lemon_squeezy.license'].sudo().search(
            [('order_id', '=', order_id)], limit=1
        )
        if not license:
            raise ValueError(f"subscription_created: license not found for order {order_id}")
        # Persist subscription_id para lookup en payment_*/cancelled/updated handlers (Codex P3)
        license.write({'subscription_id': subscription_id})
        event_log.write({'related_partner_id': license.partner_id.id})

    def _handle_subscription_payment_success(self, event_log, payload):
        subscription_id = str(payload['data'].get('id', ''))
        license = request.env['lemon_squeezy.license'].sudo().search(
            [('subscription_id', '=', subscription_id)], limit=1
        )
        if not license:
            event_log.write({'processing_error': f'license_not_found_for_subscription_{subscription_id}'})
            return
        license.write({'status': 'active'})  # in case it was past_due
        self._extend_expires_at(license)      # v0.3.0: renewal extends license
        event_log.write({'related_partner_id': license.partner_id.id})

    def _handle_subscription_payment_failed(self, event_log, payload):
        subscription_id = str(payload['data'].get('id', ''))
        license = request.env['lemon_squeezy.license'].sudo().search(
            [('subscription_id', '=', subscription_id)], limit=1
        )
        if not license:
            event_log.write({'processing_error': f'license_not_found_for_subscription_{subscription_id}'})
            return
        res_model_id = request.env['ir.model'].sudo().search(
            [('model', '=', 'res.partner')], limit=1
        ).id
        request.env['mail.activity'].sudo().create({
            'res_model_id': res_model_id,
            'res_id': license.partner_id.id,
            'activity_type_id': request.env.ref('mail.mail_activity_data_todo').id,
            'summary': f'LS payment failed — Subscription {subscription_id}',
            'note': f'Lemon Squeezy reportó subscription_payment_failed para license {license.license_key}. Revisar.',
            'user_id': int(
                request.env['ir.config_parameter'].sudo().get_param(
                    'lemon_squeezy.notify_user_id', 1
                )
            ),
        })
        event_log.write({'related_partner_id': license.partner_id.id})

    def _handle_subscription_cancelled(self, event_log, payload):
        subscription_id = str(payload['data'].get('id', ''))
        license = request.env['lemon_squeezy.license'].sudo().search(
            [('subscription_id', '=', subscription_id)], limit=1
        )
        if not license:
            event_log.write({'processing_error': f'license_not_found_for_subscription_{subscription_id}'})
            return
        license.write({'status': 'cancelled'})
        event_log.write({'related_partner_id': license.partner_id.id})

    def _handle_subscription_updated(self, event_log, payload):
        """Upgrade seats o cambio billing_cycle: actualizar license + nuevo sale.order."""
        subscription_id = str(payload['data'].get('id', ''))
        new_variant_id = str(payload['data']['attributes'].get('variant_id', ''))
        license = request.env['lemon_squeezy.license'].sudo().search(
            [('subscription_id', '=', subscription_id)], limit=1
        )
        if not license:
            event_log.write({'processing_error': f'license_not_found_for_subscription_{subscription_id}'})
            return
        if not new_variant_id:
            event_log.write({'processing_error': f'missing_variant_id_for_subscription_{subscription_id}'})
            return
        new_mapping = self._get_mapping_for_variant(new_variant_id)
        if not new_mapping:
            event_log.write({'processing_error': f'no_mapping_for_variant_{new_variant_id}'})
            return

        seats_changed = new_mapping.seats != license.seats
        billing_changed = new_mapping.billing_cycle != license.billing_cycle

        if seats_changed or billing_changed:
            update_vals = {}
            if seats_changed:
                update_vals['seats'] = new_mapping.seats
                # If upgrading Individual (1) → Despacho (>1), set despacho_name (P2 fix)
                if new_mapping.seats > 1 and not license.despacho_name:
                    update_vals['despacho_name'] = license.partner_id.name
            if billing_changed:
                update_vals['billing_cycle'] = new_mapping.billing_cycle
            license.write(update_vals)

            # Crear sale.order diff (simplificado MVP)
            SaleOrder = request.env['sale.order'].sudo()
            so = SaleOrder.create({
                'partner_id': license.partner_id.id,
                'order_line': [(0, 0, {
                    'product_id': new_mapping.product_id.id,
                    'product_uom_qty': 1,
                    'price_unit': new_mapping.product_id.list_price,
                })],
                'origin': f'LS Subscription Update {subscription_id}',
            })
            so.action_confirm()
            event_log.write({
                'related_partner_id': license.partner_id.id,
                'related_sale_order_id': so.id,
            })
