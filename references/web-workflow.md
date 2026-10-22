# Credential and runtime setup

## Existing access

Use a connected Garmin plugin, an existing runtime credential, or a key/token supplied by the user, including in chat. The Python client works locally and in cloud environments. Pass credentials through stdin or a named environment variable; reuse a token across the requested reads.

## Create a Garmin key

Follow Garmin's [Personal API guide](https://developer.garmin.com/gc-developer-program/personal/personal-api). Open [Personal API Key settings](https://connect.garmin.com/app/settings/personalApiToken), select **Create Key**, review the terms, choose an expiration, and copy the once-displayed value.

The [FAQ](https://developer.garmin.com/gc-developer-program/personal/personal-faq/) lists 30-, 90-, 180-day, and one-year key lifetimes. Tokens last up to 24 hours or the key's earlier expiry, with no refresh token. Revoking a key invalidates its associated tokens.

## Optional Codex Cloud setup

For accounts with saved Codex Cloud environments and Personal Vault:

1. Create or select an environment from **Work in > Cloud**, using the repository containing this skill and Python 3.9+.
2. Set environment privacy to **Only me**.
3. Request a personal value named `GARMIN_API_KEY`, matching the type of any existing vault entry. Configure HTTPS access to `personal.connectapi.garmin.com`.
4. Enter or select the value through **Settings > Codex Cloud > Personal vault** or the platform's personal-value prompt. A new entry can be scoped to the selected environment.
5. Publish the environment and start a task in it.

The environment must request the vault value by name and type. Personal values and network destination permissions are configured separately. See [Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments).

An **Environment variable** supplies the raw key to the client process. The client removes it from its own environment after reading it; the parent environment and vault entry remain unchanged.

A **Network secret** supplies a placeholder. Preserve it unchanged in the `Authorization: ApiKey ...` header and retain the configured HTTPS proxy and TLS verification so the proxy can substitute the value for the allowed host. Both modes return a Garmin access token into process memory.

Use a requested date with a small metadata-only activity read to check a new configuration. A full page can be incomplete; inspect pagination metadata before drawing conclusions about activity coverage.

## Existing MCP service

A deployed Garmin MCP service can provide authenticated tools instead of the Python client. Use its actual connection configuration and supported resources. For connecting an existing service, see the [OpenAI plugin quickstart](https://developers.openai.com/plugins/quickstart) and [MCP authentication guide](https://developers.openai.com/plugins/build/auth).
