from app.core.security import decrypt_secret, encrypt_secret, hash_password, verify_password


def test_password_hash_is_not_plaintext_and_roundtrips() -> None:
    password = "correct horse battery staple"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong", hashed)


def test_provider_secret_is_encrypted_and_roundtrips() -> None:
    encrypted = encrypt_secret("sk-local-test")
    assert encrypted != "sk-local-test"
    assert "sk-local-test" not in encrypted
    assert decrypt_secret(encrypted) == "sk-local-test"
