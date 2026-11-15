"""Shared syntax validators. Success is not proof of provider authorization."""
import re


class CredentialError(ValueError):
    def __init__(self, field):
        self.field = field
        super().__init__('Invalid credential format: ' + field)


def validate_ai_key(value, provider='openai'):
    if provider != 'openai' or not isinstance(value, str) or not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,250}', value):
        raise CredentialError('ai_api_key')
    return value


def validate_ai_model(value, provider='openai'):
    if provider != 'openai' or not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}', value):
        raise CredentialError('ai_model')
    return value
