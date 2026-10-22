# Pull Garmin Data

A ChatGPT skill and bounded Python client for your own **Garmin Connect Personal API** data: activities, daily summaries, sleep, heart rate, HRV, activity detail, and original activity ZIP files. This is separate from ChatGPT Health.

## What works now

- The client supports Garmin Personal API key-to-token exchange and read-only data requests, with 52 offline regression tests using synthetic data.
- The skill provides scope, privacy, pagination, and failure-handling instructions.
- **Web setup uses a supported cloud runtime or a connected MCP plugin.** The documented Personal Vault route below does not require a laptop or a separately hosted server, but needs an account with Codex Cloud environments. Actual vault provisioning and fresh-task access must be verified; installing this repository alone does not sign you in.

No Garmin key, token, account data, or personal health records are included. Do not add them to this repository.

## Before creating a key

For the cloud setup below, first confirm your ChatGPT account exposes **Work in > Cloud** and **Settings > Codex Cloud > Personal vault**. If either is unavailable or restricted, pause credential creation: this repository cannot add that account feature. An existing trusted Garmin MCP plugin is a separate option, not something installed by this repository.

## 1. Get your Garmin Personal API key

You need a Garmin Connect account. Follow Garmin's [official Personal API guide](https://developer.garmin.com/gc-developer-program/personal/personal-api):

1. Sign in to Garmin Connect Web and open [Settings → Personal API Key](https://connect.garmin.com/app/settings/personalApiToken).
2. Select **Create Key**.
3. Read Garmin's terms and accept them if you agree.
4. Choose an expiration period and select **Create**.
5. Copy the key into an appropriate private secret store immediately. Garmin displays it only once. Select **Done** when finished.

Available lifetimes are **30 days, 90 days, 180 days, or one year**. If you lose the value, revoke it and create a replacement. Revocation also disables tokens generated from it. Access tokens last at most 24 hours, or until the key expires; Garmin does not issue refresh tokens. These rules are documented in the [Personal API FAQ](https://developer.garmin.com/gc-developer-program/personal/personal-faq/).

Treat the key like a password. Do not paste it into ChatGPT, terminal command arguments, GitHub, screenshots, or configuration files committed to Git.

## 2. Set up ChatGPT Web with Personal Vault

### Check availability first

This route uses a **saved Codex Cloud environment**, selected through **Work in > Cloud** on the web. It is not a universal keychain in an ordinary Work chat, and it does not rely on files left in a previous chat. Check that your account shows **Settings > Codex Cloud > Personal vault** and supports creating cloud environments. If those controls are absent or restricted, this route is not ready for your account. Do not paste the key into chat as a workaround.

### Prepare the environment

1. In a new web task, choose **Work in > Cloud > Select environment > Create environment**.
2. Select this GitHub repository; connect GitHub if prompted. During setup, ask it to use Python 3.9 or newer, read the repository's `SKILL.md`, and run the offline tests. No Garmin credentials or live requests are needed for those tests.
3. Keep **Privacy > Who can use** set to **Only me**.
4. In the setup conversation, ask: “Request a personal Environment variable named GARMIN_API_KEY. Allow HTTPS access only to personal.connectapi.garmin.com for Garmin requests. Do not copy its value to environment-owned storage or files, and do not call Garmin during setup.” Review **Environment variables > Manage** and the restricted network policy. If your existing vault value is a **Network secret**, request that type instead and review **Network secrets > Manage**. Stop if setup cannot request a personal value.
5. If the value is already saved in **Settings > Codex Cloud > Personal vault**, reuse it with the same name and type. Otherwise select **Add**, choose the matching type (**Environment variable** for the setup prompt above), and enter your Garmin key directly in that private UI. For new entries, prefer **Applies to > Selected environments** and this Garmin environment only. An existing **All environments** entry works where an environment requests it; do not duplicate it merely for setup. The platform may instead prompt for the personal value during setup.
6. Review and publish the environment, then start a new task in it.

The environment must request the key **with the matching type**. A Personal Vault entry alone is not enough, and personal values do not automatically allow network access. Only requested values reach a task. See the official [cloud-environment and Personal Vault guide](https://learn.chatgpt.com/docs/environments/cloud-environments).

**Environment variable:** the actual key is available to the client process. The helper removes it from its own process environment after reading and does not print or save it. This does not erase the parent environment or the saved vault entry. Keep credentials out of environment dumps, files, logs, and source code.

**Network secret, optional:** this lower-exposure mode supplies a placeholder instead of the raw key. It requires a matching network-secret request and the allowed Garmin destination. The client preserves the placeholder in the Authorization header and uses the managed HTTPS proxy, which substitutes the key for allowed requests on port 443. Do not disable the proxy or transform the placeholder. Switching an existing value to this type is a separate configuration choice, not required by the client. Actual platform substitution still needs an authorized test.

Both modes return a short-lived Garmin token into process memory. Never save or print it. No account-specific vault or live-cloud verification is performed by these offline tests.

### First bounded pull

In the new cloud task, ask:

> Use the repository's Garmin skill to check one day of activities. Read at most one record and one page, and report only status, count, and completeness. Do not save health data or print credentials.

Specify the date you want checked. Before running, authorize any required transmission of the key to Garmin, token creation, and token use. For the direct CLI equivalent, see the command below. The approval flags are guards, not a substitute for permission.

An empty day can still be a successful request. A full one-record page is incomplete until further pagination proves otherwise. Repeat the bounded check in a **second new task using the same published environment** before calling setup reusable. This verifies fresh-task secret provisioning rather than relying on a previous task's memory or files.

No real account, vault, or new-environment test is performed by installing this repository. Keep the distinction between documented setup, offline tests, and verified live access.

### If you prefer an existing MCP plugin

An eligible authenticated Garmin MCP plugin is another route. Its service must already be deployed and trusted; this repository does not deploy one. Open [ChatGPT Plugins](https://chatgpt.com/plugins), choose **+ → Add custom MCP server**, supply the verified HTTPS URL, configure **OAuth**, create/install it, then test from a new Work chat. Never use a guessed URL or anonymous access for private Garmin data. Follow the [OpenAI Web quickstart](https://developers.openai.com/plugins/quickstart).

MCP authentication uses OAuth rather than an arbitrary Garmin API-key field. This limitation applies to MCP connections, not to the cloud Personal Vault workflow above. Building a new hosted service requires separate hosting, storage, and access authorization; it is not required if the supported cloud route works for your account.

## Skill installation

Ask a skill-capable ChatGPT environment to install the `pull-garmin-data` skill from this repository. If the skill is already installed, update that same skill instead of creating another copy. The installed instructions are in [SKILL.md](SKILL.md).

For a saved cloud environment, load the repository’s `SKILL.md` explicitly during setup or the task; do not assume a locally installed skill automatically syncs. Global skill installation alone does not attach Personal Vault to a task; the selected environment must request the personal value. An MCP-backed plugin can instead package these instructions with its real connection. The [OpenAI skill build guide](https://developers.openai.com/plugins/build/skills) explains MCP dependency metadata and packaging. Do not add a fictitious endpoint to `agents/openai.yaml`; dependency metadata does not deploy or authenticate a server.

## Backend/client reference

The Python 3.9+ client uses only the standard library. It accepts an existing access token or Personal API key through an already-provisioned runtime environment variable or protected stdin, never a credential value in command-line arguments. These input options consume the configured direct variable, network-secret placeholder, or other approved runtime input; the Personal Vault UI is the setup surface, not a CLI flag.

After a real runtime secret mechanism and the necessary approvals exist, a bounded metadata-only request is:

```sh
python3 scripts/garmin_pull.py --key-env GARMIN_API_KEY --approved-key-exchange --approved-token-use --metadata-only activities --start-date 2020-01-01 --end-date 2020-01-01 --page-size 1 --max-pages 1
```

The canonical key name is `GARMIN_API_KEY`. Existing setups with another approved variable name remain supported: use `--key-env NAME` with that exact name instead of moving or duplicating the secret. The date is synthetic. The flags do not grant permission. Key exchange sends one request to Garmin and does not retry uncertain outcomes. Returned tokens stay in process memory; metadata-only reads do not print or save health records. For existing tokens, use `--token-env GARMIN_ACCESS_TOKEN --approved-token-use` instead of the key options. Full command details and endpoint/date semantics are in [SKILL.md](SKILL.md) and [the API reference](references/api-reference.md).

Run the offline tests without any Garmin credential:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

## Privacy and limits

- Only the official Personal API is used, not account scraping or browser-cookie extraction.
- Date ranges are bounded to 31 days per invocation, activity pagination is capped, and partial results are disclosed.
- No background collection or health-data persistence is enabled by default.
- The Personal API is for individual use. A public code repository is not a public service for sharing one account's data or a commercial multi-user Garmin integration.
- An installed skill, passing offline tests, an OAuth connection, and a successful Garmin read are distinct states. None substitutes for the others.
