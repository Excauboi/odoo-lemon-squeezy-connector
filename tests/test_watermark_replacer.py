import io
import tarfile
import zipfile

from odoo.tests import tagged
from odoo.tests.common import BaseCase

from odoo.addons.lemon_squeezy_connector.utils.watermark_replacer import (
    replace_placeholders_in_text,
    replace_placeholders_in_bundle_bytes,
)


SAMPLE_SKILL_MD = """---
name: laboral
description: Sub-skill de derecho laboral
---

# Sub-skill /laboral

Body content here.

## Footer obligatorio de respuesta

Al final de CADA respuesta que generes, incluye literalmente este bloque (sin modificar):

---
_Generado por LABORALIA · Order #{ORDER_ID_PLACEHOLDER} · Licencia EULA propia · soporte@laboralia.pro_
_Información orientativa, no constituye asesoramiento jurídico vinculante. Verifica con fuente oficial y criterio profesional propio._

---
Esta instancia de LABORALIA está licenciada bajo Order #{ORDER_ID_PLACEHOLDER} para uso individual del comprador.
"""

SAMPLE_SKILL_MD_DESPACHO = """---
name: laboral
---

# Sub-skill /laboral
---
_LABORALIA · Order #{ORDER_ID_PLACEHOLDER} · Despacho: {DESPACHO_NAME_PLACEHOLDER} ({SEATS_PLACEHOLDER} abogados autorizados)_
_Cada uso fuera del despacho autorizado constituye infracción de licencia. soporte@laboralia.pro_
"""


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestReplaceText(BaseCase):

    def test_replace_individual_only_order_id(self):
        result = replace_placeholders_in_text(
            SAMPLE_SKILL_MD,
            order_id="abc-123",
            seats=1,
            despacho_name=None,
        )
        self.assertIn("Order #abc-123", result)
        self.assertNotIn("{ORDER_ID_PLACEHOLDER}", result)

    def test_replace_despacho_all_three_placeholders(self):
        result = replace_placeholders_in_text(
            SAMPLE_SKILL_MD_DESPACHO,
            order_id="xyz-789",
            seats=5,
            despacho_name="Despacho Pérez & Asociados",
        )
        self.assertIn("Order #xyz-789", result)
        self.assertIn("5 abogados autorizados", result)
        self.assertIn("Despacho Pérez & Asociados", result)
        self.assertNotIn("{ORDER_ID_PLACEHOLDER}", result)
        self.assertNotIn("{SEATS_PLACEHOLDER}", result)
        self.assertNotIn("{DESPACHO_NAME_PLACEHOLDER}", result)

    def test_replace_individual_ignores_despacho_placeholders(self):
        """Para individual seats=1, no debe inyectar nada de Despacho."""
        result = replace_placeholders_in_text(
            SAMPLE_SKILL_MD,
            order_id="abc-123",
            seats=1,
            despacho_name=None,
        )
        # SAMPLE_SKILL_MD no contiene placeholders Despacho, el output tampoco debe.
        self.assertNotIn("{SEATS_PLACEHOLDER}", result)
        self.assertNotIn("{DESPACHO_NAME_PLACEHOLDER}", result)

    def test_replace_idempotent(self):
        """Re-aplicar replace 2 veces da el mismo resultado."""
        first = replace_placeholders_in_text(SAMPLE_SKILL_MD, order_id="abc-123", seats=1, despacho_name=None)
        second = replace_placeholders_in_text(first, order_id="abc-123", seats=1, despacho_name=None)
        self.assertEqual(first, second)


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestReplaceBundleZip(BaseCase):

    def _make_zip_bundle(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_replace_in_zip_skill_md_only(self):
        bundle = self._make_zip_bundle({
            'skills/laboral/SKILL.md': SAMPLE_SKILL_MD,
            'skills/juridico/SKILL.md': SAMPLE_SKILL_MD.replace("/laboral", "/juridico"),
            'README.md': 'No placeholders here',  # NO debe modificarse
            'plugin.json': '{"name": "laboralia"}',  # NO debe modificarse
        })

        result_bytes = replace_placeholders_in_bundle_bytes(
            bundle, 'zip',
            order_id="bun-456",
            seats=1,
            despacho_name=None,
        )

        with zipfile.ZipFile(io.BytesIO(result_bytes), 'r') as zf:
            laboral = zf.read('skills/laboral/SKILL.md').decode()
            juridico = zf.read('skills/juridico/SKILL.md').decode()
            readme = zf.read('README.md').decode()
            self.assertIn("Order #bun-456", laboral)
            self.assertIn("Order #bun-456", juridico)
            self.assertEqual(readme, 'No placeholders here')  # intacto
            plugin = zf.read('plugin.json').decode()
            self.assertEqual(plugin, '{"name": "laboralia"}')  # also intact


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestReplaceBundleErrors(BaseCase):

    def test_invalid_bundle_format_raises_value_error(self):
        """bundle_format other than 'zip' or 'tar.gz' must raise ValueError (fail loud)."""
        with self.assertRaises(ValueError):
            replace_placeholders_in_bundle_bytes(
                b"", "unknown",
                order_id="x", seats=1, despacho_name=None,
            )


@tagged('-at_install', 'post_install', 'lemon_squeezy_connector')
class TestReplaceBundleTar(BaseCase):

    def _make_tar_bundle(self, files):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as tf:
            for name, content in files.items():
                data = content.encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    def test_replace_in_tarball_despacho(self):
        bundle = self._make_tar_bundle({
            'skills/laboral/SKILL.md': SAMPLE_SKILL_MD_DESPACHO,
        })

        result_bytes = replace_placeholders_in_bundle_bytes(
            bundle, 'tar.gz',
            order_id="tar-999",
            seats=8,
            despacho_name="Bufete Test",
        )

        with tarfile.open(fileobj=io.BytesIO(result_bytes), mode='r:gz') as tf:
            laboral = tf.extractfile('skills/laboral/SKILL.md').read().decode()
            self.assertIn("Order #tar-999", laboral)
            self.assertIn("8 abogados", laboral)
            self.assertIn("Bufete Test", laboral)
