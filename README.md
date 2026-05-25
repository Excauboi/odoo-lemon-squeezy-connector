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
