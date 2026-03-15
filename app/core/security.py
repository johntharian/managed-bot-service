import hmac
import hashlib
import json
import base64
from typing import Any
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import os
from app.core.settings import settings

def verify_hub_signature(secret: str, payload: bytes, signature: str) -> bool:
    """
    Verifies an X-Hub-Signature-256 header.
    Expected signature format: ``sha256=<hex>``
    """
    if not signature or not signature.startswith("sha256="):
        return False

    expected_hex = signature[len("sha256="):]
    computed = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, expected_hex)


def verify_hmac_signature(payload: bytes, signature_header: str, secret_key: str) -> bool:
    """Alias kept for backward compatibility — delegates to verify_hub_signature."""
    return verify_hub_signature(secret_key, payload, signature_header)


def encrypt_credentials(creds_dict: dict[str, Any]) -> str:
    """Encrypts integration credentials to AES-256-CBC."""
    key = settings.ENCRYPTION_KEY.encode('utf-8')
    if len(key) != 32:
        raise ValueError("ENCRYPTION_KEY must be exactly 32 bytes")
        
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    
    data = json.dumps(creds_dict).encode('utf-8')
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_data = padder.update(data) + padder.finalize()
    
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    
    # Return as base64 combined IV + CIPHERTEXT
    result = iv + ciphertext
    return base64.b64encode(result).decode('utf-8')


def decrypt_credentials(encrypted_payload: str) -> dict[str, Any]:
    """Decrypts AES-256-CBC credentials back to dict."""
    key = settings.ENCRYPTION_KEY.encode('utf-8')
    
    raw = base64.b64decode(encrypted_payload.encode('utf-8'))
    iv = raw[:16]
    ciphertext = raw[16:]
    
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()
    
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    data = unpadder.update(padded_data) + unpadder.finalize()
    
    return json.loads(data.decode('utf-8'))
