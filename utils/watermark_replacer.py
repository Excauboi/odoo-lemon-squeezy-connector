"""Sustitución dinámica de placeholders watermark en bundles de skills.

Reemplaza al servir el ZIP descarga:
- {ORDER_ID_PLACEHOLDER} → license.order_id
- {SEATS_PLACEHOLDER} → license.seats (solo si seats > 1)
- {DESPACHO_NAME_PLACEHOLDER} → license.despacho_name (solo si seats > 1)

Soporta dos formatos de bundle: zip y tar.gz.
"""
import io
import re
import tarfile
import zipfile
from typing import Optional

PLACEHOLDER_ORDER = "{ORDER_ID_PLACEHOLDER}"
PLACEHOLDER_SEATS = "{SEATS_PLACEHOLDER}"
PLACEHOLDER_DESPACHO = "{DESPACHO_NAME_PLACEHOLDER}"

SKILL_MD_PATTERN = re.compile(r'.*SKILL\.md$', re.IGNORECASE)


def replace_placeholders_in_text(
    text: str,
    order_id: str,
    seats: int,
    despacho_name: Optional[str],
) -> str:
    """Reemplaza placeholders en un texto SKILL.md.

    Para seats=1: sustituye solo {ORDER_ID_PLACEHOLDER}. Otros placeholders
    Despacho típicamente no están presentes en el SKILL.md Individual.

    Para seats>1: sustituye los 3 placeholders.

    Caller contract:
        - If seats > 1 but despacho_name is None/empty, the SEATS/DESPACHO
          placeholders are left LITERAL in output (silent no-op). B2.10 download
          controller must validate license.despacho_name is non-empty before
          calling this function for seats > 1 licenses.
        - Caller must ensure order_id and despacho_name do not contain
          placeholder substrings (curly braces), or idempotency is not guaranteed.
    """
    out = text.replace(PLACEHOLDER_ORDER, order_id)
    if seats > 1 and despacho_name:
        out = out.replace(PLACEHOLDER_SEATS, str(seats))
        out = out.replace(PLACEHOLDER_DESPACHO, despacho_name)
    return out


def _should_rewrite(filename: str) -> bool:
    """Solo modifica SKILL.md (no README, no plugin.json, no binarios)."""
    return bool(SKILL_MD_PATTERN.match(filename))


def replace_placeholders_in_bundle_bytes(
    bundle_bytes: bytes,
    bundle_format: str,
    order_id: str,
    seats: int,
    despacho_name: Optional[str],
) -> bytes:
    """Lee bundle (zip o tar.gz), reescribe SKILL.md files con placeholders sustituidos, devuelve nuevo bundle bytes.

    Args:
        bundle_bytes: bytes raw del bundle template
        bundle_format: 'zip' | 'tar.gz'
        order_id, seats, despacho_name: parámetros de sustitución

    Returns:
        bytes del nuevo bundle con SKILL.md modificados.

    Raises:
        ValueError: si bundle_format no es 'zip' ni 'tar.gz'
    """
    if bundle_format == 'zip':
        return _rewrite_zip(bundle_bytes, order_id, seats, despacho_name)
    if bundle_format == 'tar.gz':
        return _rewrite_tar(bundle_bytes, order_id, seats, despacho_name)
    raise ValueError(f"Unsupported bundle_format: {bundle_format!r}")


def _rewrite_zip(data: bytes, order_id: str, seats: int, despacho_name: Optional[str]) -> bytes:
    out_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data), 'r') as src, \
         zipfile.ZipFile(out_buf, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            content = src.read(info.filename)
            if _should_rewrite(info.filename):
                text = content.decode('utf-8')
                text = replace_placeholders_in_text(text, order_id, seats, despacho_name)
                content = text.encode('utf-8')
            dst.writestr(info, content)
    return out_buf.getvalue()


def _rewrite_tar(data: bytes, order_id: str, seats: int, despacho_name: Optional[str]) -> bytes:
    out_buf = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as src, \
         tarfile.open(fileobj=out_buf, mode='w:gz') as dst:
        for member in src.getmembers():
            if member.isfile() and _should_rewrite(member.name):
                src_file = src.extractfile(member)
                if src_file is None:
                    continue
                original = src_file.read().decode('utf-8')
                modified = replace_placeholders_in_text(original, order_id, seats, despacho_name).encode('utf-8')
                new_info = tarfile.TarInfo(member.name)
                new_info.size = len(modified)
                new_info.mode = member.mode
                new_info.mtime = member.mtime
                new_info.uid = member.uid
                new_info.gid = member.gid
                new_info.uname = member.uname
                new_info.gname = member.gname
                dst.addfile(new_info, io.BytesIO(modified))
            else:
                dst.addfile(member, src.extractfile(member) if member.isfile() else None)
    return out_buf.getvalue()
