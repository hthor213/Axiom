# Excluded Files

Files that are gitignored because they contain environment-specific details. If you've cloned this repo and need to create them, follow the instructions below.

## credentials/vault.enc

Your encrypted credential vault containing API keys, tokens, and passwords.

**How to create:**
1. Install age: `brew install age` (macOS) or `apt install age` (Linux)
2. Generate a key pair: `age-keygen -o credentials/age-key.txt`
3. Copy the example: `cp credentials/vault.example.yaml credentials/vault.yaml`
4. Fill in your actual API keys and passwords following the structure in vault.example.yaml
5. Encrypt: `age -r $(grep 'public key' credentials/age-key.txt | awk '{print $NF}') -o credentials/vault.enc credentials/vault.yaml`

Every credential entry should have `source` (where it came from) and `used_by` (which projects reference it) annotations.

## credentials/age-key.txt

Your age private key. Generated in step 2 above. Keep this on local machines only — never commit or share it.

## services/*.yaml

Infrastructure configuration files specific to your environment. These contain IPs, ports, usernames, and connection details — not secrets, but specific to your setup.

**How to create:**
1. Copy each example file: `cp services/example_devserver.yaml services/devserver.yaml` (repeat for databases, auth, cloud, notifications)
2. Remove the `example_` prefix
3. Fill in your actual infrastructure details

See `services/example_*.yaml` for the expected structure of each file.

## chat_history.md

Session transcript from development conversations. Not needed for operation — this is generated during work sessions and excluded for privacy.

## addressed_improvements.md

Internal analysis document comparing this system to competitors. The public version of this analysis lives in `docs/comparison.md`.
