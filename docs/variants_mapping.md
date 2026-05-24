# Lemon Squeezy variants mapping — LABORALIA

> Output de Task B0.3 del plan Hito 2a. Estos IDs los anota Jose al crear los variants en el panel LS (test mode). Se cargan en `lemon_squeezy.product_mapping` vía data XML o script setup.

## 11 Anuales

| # | Variant Name | Seats | Billing | LS variant_id (rellenar al crear) |
|---|---|---|---|---|
| 1 | Individual anual | 1 | annual | `<TBD>` |
| 2 | Despacho 2 anual | 2 | annual | `<TBD>` |
| 3 | Despacho 3 anual | 3 | annual | `<TBD>` |
| 4 | Despacho 4 anual | 4 | annual | `<TBD>` |
| 5 | Despacho 5 anual | 5 | annual | `<TBD>` |
| 6 | Despacho 6 anual | 6 | annual | `<TBD>` |
| 7 | Despacho 7 anual | 7 | annual | `<TBD>` |
| 8 | Despacho 8 anual | 8 | annual | `<TBD>` |
| 9 | Despacho 9-10 anual | 10 | annual | `<TBD>` |
| 10 | Despacho 11-20 anual | 20 | annual | `<TBD>` |
| 11 | Despacho custom anual | — | manual | `<NA mailto>` |

## 11 Mensuales

| # | Variant Name | Seats | Billing | LS variant_id (rellenar al crear) |
|---|---|---|---|---|
| 12 | Individual mes | 1 | monthly | `<TBD>` |
| 13 | Despacho 2 mes | 2 | monthly | `<TBD>` |
| 14 | Despacho 3 mes | 3 | monthly | `<TBD>` |
| 15 | Despacho 4 mes | 4 | monthly | `<TBD>` |
| 16 | Despacho 5 mes | 5 | monthly | `<TBD>` |
| 17 | Despacho 6 mes | 6 | monthly | `<TBD>` |
| 18 | Despacho 7 mes | 7 | monthly | `<TBD>` |
| 19 | Despacho 8 mes | 8 | monthly | `<TBD>` |
| 20 | Despacho 9-10 mes | 10 | monthly | `<TBD>` |
| 21 | Despacho 11-20 mes | 20 | monthly | `<TBD>` |
| 22 | Despacho custom mes | — | manual | `<NA mailto>` |

## Notas operativas

- **`variant_name` siempre debe poblarse al cargar el fixture** — aunque el campo es opcional en el modelo, `_rec_name = 'variant_name'` lo usa para mostrar el record en dropdowns y breadcrumbs. Sin él la UI muestra el ID interno.
- **Filas 11 y 22 (`<NA mailto>`) nunca se insertan como `lemon_squeezy.product_mapping`** — los planes "custom" se gestionan vía flujo email manual fuera de Lemon Squeezy. La columna Billing muestra `manual` solo como descripción funcional; `billing_cycle` Selection del modelo solo acepta `monthly` o `annual`.

## Cargar en Odoo

Tras rellenar los IDs reales, generar fixture XML en `data/variants_demo.xml` o ejecutar script de carga (no requerido en MVP — Jose puede cargar manualmente en UI Backend).
