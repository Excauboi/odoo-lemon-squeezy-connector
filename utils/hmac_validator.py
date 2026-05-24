"""HMAC SHA-256 signature validation para webhooks Lemon Squeezy.

LS firma el body raw del POST con HMAC-SHA256 usando el signing secret
configurado en el panel. La firma viaja en header `X-Signature` (hex string).
"""
import hashlib
import hmac
from typing import Optional


def validate_lemon_squeezy_signature(
    payload: bytes,
    signature_header: Optional[str],
    secret: str,
) -> bool:
    """Valida HMAC SHA-256 del payload contra la firma del header.

    Args:
        payload: bytes raw del body del POST (NO el JSON parsed)
        signature_header: contenido del header `X-Signature` enviado por LS
        secret: signing secret configurado en LS panel

    Returns:
        True si la firma es válida, False en cualquier otro caso (firma vacía,
        None, longitud incorrecta, payload modificado, secret incorrecto).
    """
    if not payload or not signature_header or not secret:
        return False

    expected = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison previene timing attacks
    return hmac.compare_digest(expected, signature_header)
