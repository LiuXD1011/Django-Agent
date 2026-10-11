"""Encrypted-at-rest JSON credentials. The installation key never lives in .env."""
import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from filelock import FileLock

from config.runtime_paths import app_data_root

PREFIX = "enc:v1:"
SECRET_KEYS = frozenset({
    "api_key", "apikey", "secret_key", "app_secret", "access_key", "access_token",
    "token", "password", "private_key", "client_secret", "secret", "webhook_secret",
    "public_key", "authorization",
})


def is_secret_key(name):
    normalized = str(name).lower()
    return normalized in SECRET_KEYS or normalized.endswith(("_api_key", "_token", "_secret"))


def master_key(create=False):
    directory = app_data_root() / ".secrets"
    path = directory / "credentials.key"
    if not create and not path.is_file():
        raise ImproperlyConfigured("Credential encryption key is missing; restore the original key.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with FileLock(str(directory / "credentials.lock")):
        if not path.exists() and create:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(AESGCM.generate_key(bit_length=256))
                stream.flush()
                os.fsync(stream.fileno())
        key = path.read_bytes()
    if len(key) != 32:
        raise ImproperlyConfigured("Credential encryption key is invalid; restore the original key.")
    return key


def transform_credentials(value, *, encrypt):
    if isinstance(value, dict):
        result = {}
        for name, item in value.items():
            if is_secret_key(name) and isinstance(item, str) and item:
                if encrypt:
                    # Validate existing ciphertext instead of silently accepting an arbitrary prefix.
                    if item.startswith(PREFIX):
                        transform_credentials({name: item}, encrypt=False)
                        result[name] = item
                    else:
                        nonce = os.urandom(12)
                        sealed = AESGCM(master_key(create=True)).encrypt(nonce, item.encode(), str(name).encode())
                        result[name] = PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode()
                elif item.startswith(PREFIX):
                    try:
                        raw = base64.b64decode(item[len(PREFIX):], altchars=b"-_", validate=True)
                        result[name] = AESGCM(master_key()).decrypt(raw[:12], raw[12:], str(name).encode()).decode()
                    except (InvalidTag, ValueError, UnicodeError):
                        raise ImproperlyConfigured("Stored credential could not be decrypted; restore the original key.") from None
                else:
                    result[name] = item
            else:
                result[name] = transform_credentials(item, encrypt=encrypt)
        return result
    if isinstance(value, list):
        return [transform_credentials(item, encrypt=encrypt) for item in value]
    return value


class CredentialJSONField(models.JSONField):
    def get_db_prep_value(self, value, connection, prepared=False):
        return super().get_db_prep_value(transform_credentials(value, encrypt=True), connection, prepared)

    def from_db_value(self, value, expression, connection):
        return transform_credentials(super().from_db_value(value, expression, connection), encrypt=False)


def public_parameters(parameters):
    if isinstance(parameters, dict):
        return {key: public_parameters(item) for key, item in parameters.items() if not is_secret_key(key)}
    if isinstance(parameters, list):
        return [public_parameters(item) for item in parameters]
    return parameters
