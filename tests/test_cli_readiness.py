from helm.cli import _prime_config_field_not_set


def test_prime_config_field_not_set_with_rich_table() -> None:
    output = """
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Setting             ┃ Value                ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ API Key             │ Not set              │
│ User ID             │ Not set              │
└─────────────────────┴──────────────────────┘
"""
    assert _prime_config_field_not_set(output, "API Key") is True
    assert _prime_config_field_not_set(output, "User ID") is True


def test_prime_config_field_not_set_with_populated_values() -> None:
    output = """
│ API Key             │ pi_abc123            │
│ User ID             │ user_123             │
"""
    assert _prime_config_field_not_set(output, "API Key") is False
    assert _prime_config_field_not_set(output, "User ID") is False


def test_prime_config_field_not_set_plain_text_fallback() -> None:
    output = "API Key: Not set\nUser ID: user_123\n"
    assert _prime_config_field_not_set(output, "API Key") is True
    assert _prime_config_field_not_set(output, "User ID") is False
