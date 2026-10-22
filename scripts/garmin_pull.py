#!/usr/bin/env python3
"""Bounded Garmin Personal API reads; optional approved in-memory key exchange."""
import argparse
import datetime as dt
import json
from http.client import HTTPException
import os
from pathlib import Path
import re
import stat
import sys
import time
from urllib import error, parse, request

ORIGIN = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
MAX_BYTES = 20 * 1024 * 1024
MAX_TOKEN = 32768
MAX_TOKEN_RESPONSE = 65536
SKILL_DIR = Path(__file__).resolve().parents[1]


class PullError(Exception):
    """A deliberately non-sensitive diagnostic."""


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid arguments; use --help. Argument values are withheld.\n")


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PullError("Redirect refused; verify the official endpoint before continuing.")


def clean_token(value):
    if not isinstance(value, str) or not value or len(value) > MAX_TOKEN:
        raise PullError("An access token is required through the approved runtime input.")
    if not re.fullmatch(r"[A-Za-z0-9\-._~+/]+=*", value):
        raise PullError("Access token input is not a valid OAuth bearer token.")
    return value


def read_secret(from_stdin, env_name):
    if from_stdin:
        raw = sys.stdin.read(MAX_TOKEN + 2)
        if len(raw) > MAX_TOKEN + 1:
            raise PullError("Credential input exceeds the size limit.")
        value = raw.rstrip("\r\n")
    else:
        if not isinstance(env_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
            raise PullError("Specify an environment variable name, not a credential value.")
        value = os.environ.pop(env_name, None)
    return value


def read_token(args):
    return clean_token(read_secret(args.token_stdin, args.token_env))


def clean_api_key(value):
    if not isinstance(value, str) or not value or len(value) > MAX_TOKEN:
        raise PullError("A Personal API key is required through approved runtime input.")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise PullError("API key contains unsupported header characters.")
    return value


def exchange_api_key(api_key, *, approved=False, opener=None):
    """Exchange once, without retries, files, logs, or token-response guessing."""
    if approved is not True:
        raise PullError("Obtain applicable approval before sending an API key and creating an access token.")
    api_key = clean_api_key(api_key)
    req = request.Request(ORIGIN + TOKEN_PATH, method="POST", data=b"", headers={
        "Authorization": "ApiKey " + api_key,
        "Accept": "*/*",
        "User-Agent": "personal-garmin-read/1.0",
    })
    transport = opener or request.build_opener(NoRedirect())
    raw = None
    try:
        with transport.open(req, timeout=30) as response:
            if response.status != 200 or response.headers.get_content_type() != "text/plain":
                raise PullError("Unexpected token response status or type; creation may be uncertain. Content withheld; no retry performed.")
            raw = response.read(MAX_TOKEN_RESPONSE + 1)
            if len(raw) > MAX_TOKEN_RESPONSE:
                raise PullError("Token response exceeds the size limit; content withheld.")
        try:
            token = raw.decode("ascii").strip(" \t\r\n")
        except UnicodeError:
            raise PullError("Unexpected token encoding; credential content withheld.") from None
        return clean_token(token)
    except error.HTTPError as exc:
        status = exc.code
        exc.close()
        uncertainty = " Token creation may be uncertain." if status >= 500 else ""
        raise PullError(f"Garmin token exchange failed with HTTP {status}; content withheld.{uncertainty} No retry performed.") from None
    except (error.URLError, TimeoutError, OSError, HTTPException):
        raise PullError("Token exchange transport failed; outcome may be uncertain. No retry performed.") from None
    finally:
        # Release references, without claiming secure erasure of immutable strings.
        api_key = raw = req = None


def valid_date(value):
    try:
        parsed = dt.date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Use a valid YYYY-MM-DD date.") from None


def date_range(args):
    start, end = dt.date.fromisoformat(args.start_date), dt.date.fromisoformat(args.end_date)
    if not 0 <= (end - start).days <= 30:
        raise PullError("Request 1 to 31 calendar days per run, in ascending order.")


def resource_request(args):
    name = args.resource
    if name in {"activities", "hrv"}:
        date_range(args)
    if name == "activities":
        return "/activitylist-service/activities/search/activities", {
            "startDate": args.start_date, "endDate": args.end_date,
            "limit": args.page_size, "start": 0, "sortOrder": "desc", "excludeChildren": "true"
        }
    if name == "daily":
        return "/usersummary-service/usersummary/daily", {"calendarDate": args.date}
    if name == "sleep":
        return "/sleep-service/sleep/dailySleep", {"date": args.date}
    if name == "heart-rate":
        return "/wellness-service/wellness/dailyHeartRate", {"date": args.date}
    if name == "hrv":
        return f"/hrv-service/hrv/daily/{args.start_date}/{args.end_date}", {}
    if name in {"activity", "activity-file"}:
        if args.activity_id <= 0:
            raise PullError("Activity ID must be a positive integer obtained from Garmin.")
        prefix = "/activity-service/activity" if name == "activity" else "/download-service/files/activity"
        return f"{prefix}/{args.activity_id}", {}
    raise PullError("Unsupported resource.")


class Client:
    def __init__(self, token, opener=None, sleeper=time.sleep):
        self._token = clean_token(token)
        self._opener = opener or request.build_opener(NoRedirect())
        self._sleep = sleeper

    def get(self, path, params, binary=False):
        if not path.startswith("/") or path.startswith("//") or any(c in path for c in "?#\\"):
            raise PullError("Invalid resource path.")
        allowed = (
            r"/activitylist-service/activities/search/activities",
            r"/usersummary-service/usersummary/daily",
            r"/sleep-service/sleep/dailySleep",
            r"/wellness-service/wellness/dailyHeartRate",
            r"/hrv-service/hrv/daily/\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}",
            r"/activity-service/activity/[1-9]\d*",
            r"/download-service/files/activity/[1-9]\d*",
        )
        if not any(re.fullmatch(pattern, path) for pattern in allowed):
            raise PullError("Resource is not in the documented read-only allowlist.")
        url = ORIGIN + path
        if params:
            url += "?" + parse.urlencode(params)
        req = request.Request(url, method="GET", headers={
            "Authorization": "Bearer " + self._token,
            "Accept": "application/x-zip-compressed" if binary else "application/json",
            "User-Agent": "personal-garmin-read/1.0",
        })
        for attempt in range(3):
            try:
                with self._opener.open(req, timeout=30) as response:
                    if response.status == 204:
                        return None
                    if response.status != 200:
                        raise PullError("Unexpected response status; no data saved.")
                    media = response.headers.get_content_type()
                    if not binary and media != "application/json" and not media.endswith("+json"):
                        raise PullError("Expected JSON; response not saved.")
                    body = response.read(MAX_BYTES + 1)
                    if len(body) > MAX_BYTES:
                        raise PullError("Response exceeds the 20 MiB per-request limit.")
                    if binary:
                        if not body.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
                            raise PullError("Expected an original-activity ZIP; response not saved.")
                        return body
                    try:
                        data = json.loads(body)
                    except (ValueError, UnicodeError):
                        raise PullError("Invalid JSON response; content withheld.") from None
                    if not isinstance(data, (dict, list)):
                        raise PullError("Unexpected JSON structure; content withheld.")
                    return data
            except error.HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                exc.close()
                if status in (401, 403):
                    raise PullError("Garmin denied this read (HTTP 401/403). Stop and verify authorized access.") from None
                if status == 429:
                    delay = int(retry_after) if retry_after.isdigit() and len(retry_after) < 9 else None
                    msg = "Garmin rate limit reached."
                    if delay is not None:
                        msg += f" Retry after at least {delay} seconds."
                    raise PullError(msg + " No automatic retry performed.") from None
                if status in (500, 502, 503, 504) and attempt < 2:
                    self._sleep(2 ** attempt)
                    continue
                raise PullError(f"Garmin read failed with HTTP {status}; response content withheld.") from None
            except (error.URLError, TimeoutError, OSError, HTTPException):
                raise PullError("Network or TLS failure; details withheld to protect credentials.") from None
        raise PullError("Read did not complete.")


def collect(client, args):
    path, params = resource_request(args)
    if args.resource != "activities":
        data = client.get(path, params, args.resource == "activity-file")
        if args.resource != "activity-file" and data is not None and not isinstance(data, dict):
            raise PullError("Unexpected resource schema; expected a JSON object.")
        if args.resource in {"daily", "sleep", "heart-rate"} and data is not None:
            returned_date = data.get("calendarDate")
            if returned_date is not None and returned_date != args.date:
                raise PullError("Garmin returned a different calendar date; no data saved.")
        return data, {"complete": True, "pages": 1, "record_count": len(data) if isinstance(data, list) else None, "no_content": data is None}
    records, complete, pages = [], False, 0
    missing_local_dates = 0
    seen = set()
    for page in range(args.max_pages):
        params["start"] = page * args.page_size
        chunk = client.get(path, params)
        pages += 1
        if not isinstance(chunk, list) or len(chunk) > args.page_size:
            raise PullError("Unexpected activity page structure; no data saved.")
        for activity in chunk:
            if not isinstance(activity, dict) or "activityId" not in activity:
                raise PullError("Activity records do not match the documented schema.")
            identity = activity["activityId"]
            if type(identity) is not int or identity <= 0 or identity in seen:
                raise PullError("Repeated or invalid activity identifier; pagination may have changed.")
            seen.add(identity)
            local_start = activity.get("startTimeLocal")
            if local_start is None or local_start == "":
                missing_local_dates += 1
            else:
                try:
                    local_date = valid_date(local_start[:10]) if isinstance(local_start, str) else None
                except argparse.ArgumentTypeError:
                    local_date = None
                if local_date is None or not args.start_date <= local_date <= args.end_date:
                    raise PullError("Activity-local date is invalid or outside the requested range; no data saved.")
        records.extend(chunk)
        if len(chunk) < args.page_size:
            complete = True
            break
    return records, {
        "complete": complete, "pages": pages, "record_count": len(records), "no_content": not records,
        "records_without_local_date": missing_local_dates,
        "date_range_verified": missing_local_dates == 0,
    }


def private_output(path, data, binary=False):
    dest = Path(path).expanduser()
    if not dest.is_absolute():
        raise PullError("Use an absolute private output path outside source-control repositories.")
    if dest.is_symlink() or dest.exists():
        raise PullError("Output already exists or is a symlink; choose a fresh filename.")
    parent = dest.parent.resolve()
    if parent == SKILL_DIR or SKILL_DIR in parent.parents:
        raise PullError("Do not save Garmin data inside the skill.")
    if any((p / ".git").is_file() or (p / ".git" / "HEAD").is_file()
           or ((p / "HEAD").is_file() and (p / "objects").is_dir() and (p / "config").is_file())
           for p in (parent, *parent.parents)):
        raise PullError("Do not save Garmin data in a source-control repository.")
    if not parent.exists():
        parent.mkdir(mode=0o700)
    mode = parent.stat()
    if mode.st_uid != os.getuid() or stat.S_IMODE(mode.st_mode) & 0o077:
        raise PullError("Output directory must be owned by you and private (mode 0700).")
    payload = data if binary else (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    if binary and not isinstance(payload, bytes):
        raise PullError("No activity file was returned; nothing saved.")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(parent / dest.name), flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
    except OSError:
        raise PullError("Could not write the private output; check the destination.") from None


def positive_bound(low, high):
    def parse_int(value):
        try:
            result = int(value)
            if not low <= result <= high:
                raise ValueError()
            return result
        except ValueError:
            raise argparse.ArgumentTypeError(f"Use an integer between {low} and {high}.") from None
    return parse_int


def parser():
    p = SafeArgumentParser(description=__doc__)
    auth = p.add_mutually_exclusive_group(required=True)
    auth.add_argument("--token-stdin", action="store_true", help="Read an existing access token from protected stdin, never an API key.")
    auth.add_argument("--token-env", metavar="NAME", help="Read an existing access token from an authorized runtime environment variable.")
    auth.add_argument("--key-stdin", action="store_true", help="Read a Personal API key from protected stdin for one separately approved exchange.")
    auth.add_argument("--key-env", metavar="NAME", help="Read a Personal API key from an authorized runtime environment variable.")
    p.add_argument("--approved-token-use", action="store_true", help="Required acknowledgement of applicable user approval, not a substitute for obtaining it.")
    p.add_argument("--approved-key-exchange", action="store_true", help="Required with a Personal API key after actual approval to transmit it and generate a token.")
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument("--output", help="Fresh file in a private directory outside all repositories.")
    out.add_argument("--metadata-only", action="store_true", help="Discard response data after reporting counts and status, with no raw output.")
    subs = p.add_subparsers(dest="resource", required=True)
    act = subs.add_parser("activities")
    act.add_argument("--start-date", required=True, type=valid_date)
    act.add_argument("--end-date", required=True, type=valid_date)
    act.add_argument("--page-size", default=50, type=positive_bound(1, 99))
    act.add_argument("--max-pages", default=10, type=positive_bound(1, 20))
    for name in ("daily", "sleep", "heart-rate"):
        s = subs.add_parser(name)
        s.add_argument("--date", required=True, type=valid_date)
    hrv = subs.add_parser("hrv")
    hrv.add_argument("--start-date", required=True, type=valid_date)
    hrv.add_argument("--end-date", required=True, type=valid_date)
    for name in ("activity", "activity-file"):
        s = subs.add_parser(name)
        s.add_argument("--activity-id", required=True, type=int)
    return p


def main(argv=None):
    client = None
    key = token = None
    try:
        args = parser().parse_args(argv)
        if not args.approved_token_use:
            raise PullError("Obtain applicable user approval before transmitting a secret access token.")
        using_key = args.key_stdin or args.key_env is not None
        if using_key and not args.approved_key_exchange:
            raise PullError("Obtain applicable approval before API-key transmission and token generation.")
        resource_request(args)  # Validate scope before touching credentials or network.
        if using_key:
            key = clean_api_key(read_secret(args.key_stdin, args.key_env))
            try:
                token = exchange_api_key(key, approved=True)
            finally:
                key = None
        else:
            token = read_token(args)
        client = Client(token)
        token = None
        data, meta = collect(client, args)
        if args.output:
            private_output(args.output, data, args.resource == "activity-file")
        print(json.dumps({"status": "ok", "resource": args.resource, **meta, "persisted": bool(args.output)}))
        return 0
    except PullError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("Local operation failed; details withheld to protect private data.", file=sys.stderr)
        return 1
    finally:
        key = token = None
        if client is not None:
            client._token = None


if __name__ == "__main__":
    raise SystemExit(main())
