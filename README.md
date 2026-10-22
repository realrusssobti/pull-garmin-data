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
4. In the setup conversation, ask: “Request a personal Network secret named GARMIN_PERSONAL_API_KEY, restricted to personal.connectapi.garmin.com. Do not store its value as an environment-owned secret or in files. Do not call Garmin during setup.” Review **Network secrets > Manage** and the restricted network policy to confirm the requested key and exact allowed host. If setup cannot create a personal requirement, stop and resolve that missing capability before entering a key.
5. In **Settings > Codex Cloud > Personal vault**, select **Add**, choose **Network secret**, and enter the matching key name and your Garmin key directly in that private UI. Under **Applies to**, choose **Selected environments** and only this Garmin environment. The platform may instead prompt for the requested personal value during setup.
6. Review and publish the environment, then start a new task in it.

The environment must request the key. A Personal Vault entry alone is not enough, and personal secrets do not automatically allow network access. Do not use **Environment variable** when **Network secret** is suitable: a direct variable exposes the actual value to the program, whereas a network secret supplies a placeholder. See the official [cloud-environment and Personal Vault guide](https://learn.chatgpt.com/docs/environments/cloud-environments).

The client sends the unchanged placeholder in the Authorization header through the managed HTTPS proxy. The proxy substitutes the real key only for the allowed destination on port 443. The client does not need the raw key, but Garmin's returned short-lived token still enters process memory. Do not disable the proxy, transform the placeholder, or save the token. This is the intended integration based on the documented mechanisms; synthetic regression tests do not prove real platform substitution.

### First bounded pull

In the new cloud task, ask:

> Use the repository's Garmin skill to check one day of activities. Read at most one record and one page, and report only status, count, and completeness. Do not save health data or print credentials.

Specify the date you want checked. Before running, authorize any required transmission of the key to Garmin, token creation, and token use. For the direct CLI equivalent, see the command below. The approval flags are guards, not a substitute for permission.

An empty day can still be a successful request. A full one-record page is incomplete until further pagination proves otherwise. Repeat the bounded check in a **second new task using the same published environment** before calling setup reusable. This verifies fresh-task secret provisioning rather than relying on a previous task's memory or files.

No real account, vault, or new-environment test is performed by installing this repository. Keep the distinction between documented setup, offline tests, and verified live access.

### If you prefer an existing MCP plugin

An eligible authenticated Garmin MCP plugin is another route. Its service must already be deployed and trusted; this repository does not deploy one. Open [ChatGPT Plugins](https://chatgpt.com/plugins), choose **+ → Add custom MCP server**, supply the verified HTTPS URL, configure **OAuth**, create/install it, then test from a new Work chat. Never use a guessed URL or anonymous access for private Garmin data. Follow the [OpenAI Web quickstart](https://developers.openai.com/plugins/quickstart).

MCP authentication uses OAuth rather than an arbitrary Garmin API-key field. This limitation applies to MCP connections, not to the cloud network-secret workflow above. Building a new hosted service requires separate hosting, storage, and access authorization; it is not required if the supported cloud route works for your account.

## Skill installation

Ask a skill-capable ChatGPT environment to install the `pull-garmin-data` skill from this repository. If the skill is already installed, update that same skill instead of creating another copy. The installed instructions are in [SKILL.md](SKILL.md).

For a saved cloud environment, load the repository’s `SKILL.md` explicitly during setup or the task; do not assume a locally installed skill automatically syncs. Global skill installation alone does not attach Personal Vault to a task; the selected environment must request the personal value. An MCP-backed plugin can instead package these instructions with its real connection. The [OpenAI skill build guide](https://developers.openai.com/plugins/build/skills) explains MCP dependency metadata and packaging. Do not add a fictitious endpoint to `agents/openai.yaml`; dependency metadata does not deploy or authenticate a server.

## Backend/client reference

The Python 3.9+ client uses only the standard library. It accepts an existing access token or Personal API key through an already-provisioned runtime environment variable or protected stdin, never a credential value in command-line arguments. These input options consume the configured cloud placeholder or other approved runtime input; the Personal Vault UI is the setup surface, not a CLI flag.

After a real runtime secret mechanism and the necessary approvals exist, a bounded metadata-only request is:

```sh
python3 scripts/garmin_pull.py --key-env GARMIN_PERSONAL_API_KEY --approved-key-exchange --approved-token-use --metadata-only activities --start-date 2020-01-01 --end-date 2020-01-01 --page-size 1 --max-pages 1
```

The date is synthetic. The flags do not grant permission. Key exchange sends one request to Garmin and does not retry uncertain outcomes. Returned tokens stay in process memory; metadata-only reads do not print or save health records. For existing tokens, use `--token-env GARMIN_ACCESS_TOKEN --approved-token-use` instead of the key options. Full command details and endpoint/date semantics are in [SKILL.md](SKILL.md) and [the API reference](references/api-reference.md).

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
