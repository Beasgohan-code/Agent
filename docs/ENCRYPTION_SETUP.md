# What TOKEN_KEY is

`TOKEN_KEY` is a deployment-owned Fernet encryption key. It encrypts stored clone
bot tokens, provider API keys and assistant sessions. PostgreSQL holds the
ciphertext; the bot needs the same key to decrypt it after restart. It is not a
BotFather token, Telegram password, phone verification code or per-clone input.
Only the deployment Owner configures it. Clone users should never receive it.

Ordinary non-clone commands do not require it. Secure clone setup does: removing
that requirement would expose stored credentials rather than remove the need for
protection. Database access controls, HTTPS and masking a screen do not replace
application-level encryption. Encryption does not protect against a compromised
running process or an attacker who has both database and environment secrets.

## Set up once

If no key has ever been configured, generate it in your own trusted terminal:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set the output as the `TOKEN_KEY` secret environment variable on your deployment,
then redeploy/restart. Do not put it in source control, Telegram, logs or this
conversation. Keep a secure backup independent of the application database.
If a key already exists, preserve it; do not generate a replacement casually.
The Agent did not generate or change any production key for this update.

Losing/changing the key can make existing encrypted records unreadable; the
current loader skips records it cannot decrypt. That does not mean they were
safely migrated or deleted. Recover the original key or plan a reviewed
re-encryption migration. Never derive this key from a public value or generate
a new temporary key on every startup. There is no automatic key rotation here.

Low-level legacy SecretBox/store helpers still support plaintext when no key is
supplied. Guided clone creation refuses that mode before collecting credentials;
AI/assistant credential persistence also has encryption checks. This update does
not silently convert production records or remove existing data.
