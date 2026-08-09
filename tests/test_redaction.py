from repoarena.utils.redaction import redact


def test_redacts_common_credentials_and_explicit_values() -> None:
    fake_openai_key = "sk-" + "abcdefghijklmnop"
    fake_github_token = "ghp_" + "abcdefghijklmnopqrst"
    output = redact(
        f"\x1b[91mAuthorization: bearer-secret api_key={fake_openai_key} "
        f"token {fake_github_token}\x1b[0m",
        ["bearer-secret"],
    )

    assert "bearer-secret" not in output
    assert fake_openai_key not in output
    assert fake_github_token not in output
    assert "\x1b" not in output
    assert "[REDACTED]" in output
