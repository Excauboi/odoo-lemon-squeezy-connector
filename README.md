# odoo-lemon-squeezy-connector

Módulo Odoo 19 que integra Lemon Squeezy (Merchant of Record) como pasarela de pago para suscripciones y productos digitales, con soporte para watermark dinámico en descargas.

## Features

- Webhook handler con validación HMAC SHA-256
- Idempotencia por `event_id` (LS reintenta eventos hasta 5 veces)
- 6 event handlers: `order_created`, `subscription_created`, `subscription_updated`, `subscription_payment_success`, `subscription_payment_failed`, `subscription_cancelled`
- Endpoint `/lemon_squeezy/download/<license_key>` con sustitución dinámica de placeholders (`{ORDER_ID_PLACEHOLDER}`, `{SEATS_PLACEHOLDER}`, `{DESPACHO_NAME_PLACEHOLDER}`)
- Mapping `lemon_squeezy.product_mapping` LS variant_id <-> Odoo `product.product`
- Estado de licencias `lemon_squeezy.license` (active / expired / cancelled)

## Instalación

```bash
# En odoo.conf, addons_path debe incluir el directorio padre del módulo
docker compose exec odoo odoo -d <db> -i lemon_squeezy_connector --stop-after-init
```

## Configuración

System parameters (`ir.config_parameter`):

| Parameter | Descripción | Ejemplo |
|---|---|---|
| `lemon_squeezy.webhook_secret` | HMAC signing secret del webhook LS | `whsec_xxx...` |
| `lemon_squeezy.store_subdomain` | Subdomain del store LS | `laboralia` |
| `lemon_squeezy.bundle_attachment_id` | `ir.attachment.id` del template bundle digital | `42` |

## Watermark templates (download endpoint)

El endpoint `/lemon_squeezy/download/<license_key>` sirve el archivo configurado en `lemon_squeezy.bundle_attachment_id` (un `ir.attachment` zip o tar.gz) tras sustituir placeholders en archivos `*SKILL.md` (regex case-insensitive) que encuentre dentro.

Los 3 placeholders soportados out-of-the-box (definidos como constantes en `utils/watermark_replacer.py`):

| Placeholder | Sustitución | Cuándo aplica |
|---|---|---|
| `{ORDER_ID_PLACEHOLDER}` | `license.order_id` (LS order ID string) | Siempre (single + multi-seat) |
| `{SEATS_PLACEHOLDER}` | `str(license.seats)` | Solo si `license.seats > 1 AND license.despacho_name` poblado |
| `{DESPACHO_NAME_PLACEHOLDER}` | `license.despacho_name` (entity name) | Solo si `license.seats > 1 AND license.despacho_name` poblado |

**Customizing placeholders**: si tu caso de uso necesita otros placeholders o nombres distintos, edita las constantes `PLACEHOLDER_ORDER`, `PLACEHOLDER_SEATS`, `PLACEHOLDER_DESPACHO` y la regex `SKILL_MD_PATTERN` en `utils/watermark_replacer.py`. El bundle template (zip/tar.gz) que subas como `ir.attachment` debe contener esos mismos placeholders donde quieras la sustitución.

**Caso de uso pensado**: distribución de "skills" o "agent packs" individualizados por compra. El watermark hace deterrence anti-redistribución (el comprador puede ver su order ID en cada archivo que use). Para otros casos (PDF/EPUB de libros, audio, vídeo, código fuente, plugins) el patrón generaliza: cualquier archivo de texto dentro del bundle puede llevar placeholders sustituidos.

**Otros formatos de bundle**: el módulo soporta `application/zip` y `application/gzip` (tar.gz). Si el `attachment.mimetype` no es `application/zip`, se trata como `tar.gz`. Para más formatos (rar, 7z, plain PDF), añade rama en `replace_placeholders_in_bundle_bytes()`.

## Eventos LS soportados

Ver `controllers/webhook.py` para mapping completo evento -> acción Odoo.

## Subscription lifecycle (v0.3.0+)

Cuando `order_created` crea un `lemon_squeezy.license`, ésta se crea con:
- `billing_cycle` heredado del `product_mapping` (anual o mensual)
- `expires_at = now + 1 año` (annual) o `now + 1 mes` (monthly)

Cuando llega `subscription_payment_success` (LS dispara este evento cada vez que renueva la suscripción exitosamente):
- Si `expires_at` está en el futuro → se extiende DESDE `expires_at` (+1 ciclo, no se pierden días por renewal anticipada)
- Si `expires_at` está en el pasado (payment llegó tarde) → se extiende DESDE `now` (graceful recovery)

Cuando llega `subscription_cancelled` (cliente cancela manualmente):
- `status` → `'cancelled'` inmediato; el `is_active` computed devuelve `False` y el endpoint download responde 404

El gate efectivo es `is_active = (status == 'active' AND (expires_at IS NULL OR expires_at > now))`:
- `status == 'cancelled'` → siempre denied
- `status == 'expired'` → siempre denied (admin manual mark)
- `status == 'active'` + `expires_at` futuro → allowed
- `status == 'active'` + `expires_at` pasado → denied (subscription venció sin renovar)
- `status == 'active'` + `expires_at = NULL` → allowed perpetuamente (caso edge: license manual creada sin expiración)

**Caso uso típico**: vender skill/plugin/bundle por suscripción anual a través de Lemon Squeezy. Cliente puede descargar actualizaciones cuantas veces quiera durante el año (re-fetch del bundle template actualizado en `ir.attachment`). Si renueva, sigue. Si no, expires_at pasa y el endpoint denegará.

**Para "push" notificaciones de update**: añadir cron + mail.template que detecte cambios en bundle_attachment_id y notifique a partners con licenses active. Out-of-scope del módulo MVP, pero pattern documentado en `_handle_subscription_*` handlers (mail.activity ejemplo).

## Internal invoicing to Lemon Squeezy (v0.4.0+)

Modelo: Lemon Squeezy es Merchant of Record (MoR) → factura LEGALMENTE al cliente final + recauda IVA UE. El vendor (tú) factura A LS por las ventas netas. Este conector automatiza esa factura interna en Odoo.

**Cada `order_created` dispara**:
1. Crear/encontrar partner `res.partner` del cliente final (por email)
2. Crear `sale.order` confirmado (registro de venta indirecta)
3. Crear `lemon_squeezy.license` activa
4. **(v0.4.0+)** Crear `account.move` borrador a "Lemon Squeezy Inc." con:
   - `partner_id` = LS partner (no el cliente final)
   - `invoice_origin` = "LS Order <order_id>"
   - `ref` = "Cliente final: <name> <email>" (tracking interno)
   - Línea: producto del mapping + qty 1 + `price_unit = subtotal/100` (centimos LS → euros, pre-IVA)
   - Estado: `draft` por defecto

**Configuración** vía `ir.config_parameter`:

| Parameter | Default | Descripción |
|---|---|---|
| `lemon_squeezy.merchant_partner_name` | `'Lemon Squeezy Inc.'` | Nombre del partner LS en Odoo. Override si tu factura debe ir a otra razón social (ej. LS GmbH para Europa) |
| `lemon_squeezy.merchant_partner_id` | (auto-cached) | ID del partner. Se cachea automáticamente tras el primer call para evitar lookup repetido |
| `lemon_squeezy.invoice_auto_post` | `'false'` | Si `'true'`, el `account.move` se publica (`action_post()`) automáticamente. Si `'false'`, queda en draft para revisión manual en reconciliación mensual |

**IVA y tax**: la línea de factura usa el `taxes_id` configurado en el `product.product` del mapping. Configura el producto con el IVA que corresponda a tu caso fiscal:
- B2B intracomunitaria (factura a LS Malta/Irlanda/US): típicamente 0% / exenta, comentario "Operación intracomunitaria" o "Exportación servicios"
- Consulta tu fiscalista. Para Jose autónomo EDN en España: 0% intracomunitaria.

**Fallo soft**: si la creación de la factura falla (ej. no hay sale journal configurado), el `order_created` NO da error — sale.order y license se crean OK, la factura se loggea como exception y el admin la crea manualmente desde el sale.order.

**Reconciliación con LS payout**: la factura interna usa `subtotal` (pre-IVA + pre-LS-fees). LS te paga el net después de retener IVA + fees. Mensualmente exporta el LS payout report y agrega/concilia con las facturas Odoo. Diferencia = LS fees + retenciones IVA. Registra esa diferencia como gasto bancario o fee en una cuenta dedicada.

## Tests

```bash
docker compose exec odoo odoo -d <db> -i lemon_squeezy_connector --test-enable --stop-after-init --test-tags lemon_squeezy_connector
```

## Production hardening (post-MVP)

Para despliegue producción más allá de single-tenant Jose, considerar:

### Seguridad

- **Rotar `lemon_squeezy.webhook_secret` periódicamente** o si el DB dump se comparte fuera del equipo dev. El secret se almacena en `ir.config_parameter` plain text — accesible para cualquier dump del DB.
- **`license_key` es sensible** — la URL `/lemon_squeezy/download/<license_key>` da acceso directo a la descarga. Tratar como contraseña en logs, emails, browser history.
- **Rate limiting**: el endpoint webhook (`/lemon_squeezy/webhook`) no tiene rate limit en Odoo. Configurar regla CF WAF en producción (recomendado: 30 req/min por IP).
- **Body size cap** (~64KB en código) protege OOM ante atacantes; LS webhooks reales son <5KB.

### Operaciones

- Configurar `lemon_squeezy.notify_user_id` (ir.config_parameter) con el user_id del admin que debe ver las activities de `subscription_payment_failed`. Default `1` (SUPERUSER).
- Backup periódico de la BD: las licenses + event log son críticas — sin licenses no hay downloads, sin events no hay audit trail.

### Monitoring

- Watch `lemon_squeezy.event` con `processing_error != False` — son los gaps que requieren atención manual.
- Watch `mail.activity` to-do sobre `res.partner` con summary `LS payment failed —` — son los renewals fallidos.

## Licencia

LGPL-3.0-or-later. Ver `LICENSE`.

## Autor

Jose Ruiberriz / Excauboi — https://github.com/Excauboi
