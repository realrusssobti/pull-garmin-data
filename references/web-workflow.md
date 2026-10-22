# Web runtime and credential setup

## Obtain Garmin access

Check that the selected runtime has a supported credential setup route before asking the user to create a key. Then follow Garmin's [official guide](https://developer.garmin.com/gc-developer-program/personal/personal-api): sign in to [Personal API Key settings](https://connect.garmin.com/app/settings/personalApiToken), choose **Create Key**, review/accept the terms, select an expiration, create, preserve the once-displayed key privately, and finish. Never request the value in chat.

The [FAQ](https://developer.garmin.com/gc-developer-program/personal/personal-faq/) offers 30-, 90-, 180-day, or one-year key lifetimes. Revocation invalidates associated tokens. Tokens last up to 24 hours or the key's earlier expiry, with no refresh token. Key creation, terms acceptance, storage, and token generation are setup/credential actions, not incidental reads.

## Non-hosted Web route: a saved cloud environment

OpenAI documents Personal Vault for **saved Codex Cloud environments**, available on the web through **Work in > Cloud**. It is not a promise of a universal keychain in every Work chat. Check account availability and environment configuration before use. See [Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments).

After applicable permission, prepare a private environment from the repository containing this skill; connect GitHub if prompted. Have its setup load `SKILL.md` and run the offline tests, not an authenticated request. Configure:

- Privacy: **Only me**.
- Ask the setup conversation to request a **personal Network secret**, key `GARMIN_PERSONAL_API_KEY`, for only `personal.connectapi.garmin.com`. Review **Network secrets > Manage**. Do not supply the value as an environment-owned secret. If a personal requirement cannot be configured, stop before requesting the key.
- The exact allowed destination `personal.connectapi.garmin.com` and restricted internet access permitting it. Do not add wildcard hosts or broaden to unrestricted internet.
- A matching Personal Vault **Network secret**, scoped to **Selected environments**, supplied directly by the user through **Settings > Codex Cloud > Personal vault** or the platform's personal-secret prompt. Do not type the value for them or read it back.

The environment must request the key; a vault entry alone does not expose it to tasks. Personal values do not automatically add network destinations. Publish the setup, start a new task in that environment, and verify an approved bounded read. Repeat from another new task before calling the setup reusable. Do not include credentials in the published filesystem or start instructions. Repository code can be loaded there; do not assume local personal skills automatically sync.

### Runtime handling

Network secrets give programs a placeholder. The platform substitutes the value only for allowed HTTPS destinations on port 443. The client preserves that placeholder in `Authorization: ApiKey ...`, uses the default proxy, and does not require the raw key. Do not disable proxies, alter TLS settings, transform the placeholder, or place it in another field. The exact platform placeholder format and real substitution must be tested in the configured environment; synthetic tests establish only the client's transport behavior.

The exchange response contains a short-lived token in process memory. Keep it out of outputs/files and retain no health data for a connection check. Do not persist it to a file, Linux keyring, environment snapshot, or source repository. Each cloud task has separate files; saved VM state is not a durable credential store.

If the user cannot see the documented environment or vault controls, stop this route and report that exact missing feature. Do not claim the current chat can access the vault, create a plaintext substitute, or switch to a laptop automatically.

## Optional alternative: an authenticated MCP plugin

If an eligible installed Garmin plugin already exists, use its real tools and OAuth connection. For a new hosted backend, obtain separate hosting, credential-storage, and authorization approval; these files do not deploy one.

OpenAI uses [skills for workflows](https://developers.openai.com/plugins/build/skills) and [MCP servers for service access](https://developers.openai.com/plugins/concepts/plugins). Its [MCP auth guide](https://developers.openai.com/plugins/build/auth) requires OAuth for private user data and does not support presenting arbitrary custom API keys. That restriction concerns MCP connections, not the cloud network-secret route above.

Once a trusted owner-restricted HTTPS MCP server actually exists, use [ChatGPT Plugins](https://chatgpt.com/plugins) > **+ > Add custom MCP server**, configure **OAuth**, create/install the personal plugin, and test it in a new Work chat. Follow the [official web quickstart](https://developers.openai.com/plugins/quickstart). Never invent an endpoint or use anonymous access for private data. Add MCP dependency metadata only for the real deployed server.

Both routes are separate from ChatGPT Health. The Personal API is for the individual's own data, not a commercial multi-user Garmin service.
