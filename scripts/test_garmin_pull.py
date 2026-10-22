"""Offline synthetic tests. No real Garmin account, tokens, or network requests."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
import io
from http.client import BadStatusLine
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import garmin_pull as g

SYNTHETIC_TOKEN = "synthetic-test-token"
SYNTHETIC_KEY = "synthetic-personal-api-key"


class Response:
    def __init__(self, data=None, status=200, media="application/json", raw=None):
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = media
        self.body = raw if raw is not None else json.dumps(data).encode()
    def read(self, limit):
        return self.body[:limit]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


def activity_args(**kw):
    values = dict(resource="activities", start_date="2020-01-01", end_date="2020-01-07", page_size=2, max_pages=3)
    values.update(kw)
    return argparse.Namespace(**values)


class PullTests(unittest.TestCase):
    def test_network_placeholder_preserved_in_fixed_host_header(self):
        # Synthetic stand-in, not the platform's actual placeholder format.
        placeholder = "SYNTHETIC_NETWORK_SECRET_PLACEHOLDER"
        opener = Mock()
        opener.open.return_value = Response(media="text/plain", raw=SYNTHETIC_TOKEN.encode())
        self.assertEqual(g.exchange_api_key(placeholder, approved=True, opener=opener), SYNTHETIC_TOKEN)
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, g.ORIGIN + g.TOKEN_PATH)
        self.assertEqual(req.get_header("Authorization"), "ApiKey " + placeholder)
        self.assertEqual(req.data, b"")
        self.assertEqual(req.method, "POST")
        self.assertEqual(opener.open.call_count, 1)

    def test_default_transport_preserves_configured_https_proxy(self):
        # Construct handlers only. This test makes no network connection.
        with patch.dict(os.environ, {"https_proxy": "http://synthetic-proxy.invalid:8080"}, clear=True):
            transport = g.request.build_opener(g.NoRedirect())
            proxy_handlers = [h for h in transport.handlers if isinstance(h, g.request.ProxyHandler)]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies["https"], "http://synthetic-proxy.invalid:8080")

    def test_network_placeholder_cli_outputs_metadata_only(self):
        placeholder = "SYNTHETIC_NETWORK_SECRET_PLACEHOLDER"
        exchange_transport = Mock()
        exchange_transport.open.return_value = Response(media="text/plain", raw=SYNTHETIC_TOKEN.encode())
        read_transport = Mock()
        read_transport.open.return_value = Response([{"activityId": 1, "startTimeLocal": "2020-01-01T12:00:00", "privateExample": "synthetic-private-value"}])
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"SYNTHETIC_NETWORK_KEY": placeholder}), patch("garmin_pull.request.build_opener", side_effect=[exchange_transport, read_transport]), redirect_stdout(output), redirect_stderr(errors):
            code = g.main(["--key-env", "SYNTHETIC_NETWORK_KEY", "--approved-key-exchange", "--approved-token-use", "--metadata-only", "activities", "--start-date", "2020-01-01", "--end-date", "2020-01-01", "--page-size", "1", "--max-pages", "1"])
            self.assertNotIn("SYNTHETIC_NETWORK_KEY", os.environ)
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["record_count"], 1)
        self.assertFalse(result["complete"])
        self.assertFalse(result["persisted"])
        self.assertEqual(errors.getvalue(), "")
        for private_value in (placeholder, SYNTHETIC_TOKEN, "synthetic-private-value"):
            self.assertNotIn(private_value, output.getvalue())
        self.assertEqual(exchange_transport.open.call_args.args[0].get_header("Authorization"), "ApiKey " + placeholder)
        self.assertEqual(read_transport.open.call_args.args[0].get_header("Authorization"), "Bearer " + SYNTHETIC_TOKEN)

    def test_documented_activity_route(self):
        path, params = g.resource_request(activity_args())
        self.assertEqual(path, "/activitylist-service/activities/search/activities")
        self.assertEqual(params["startDate"], "2020-01-01")
        self.assertEqual(params["endDate"], "2020-01-07")
        self.assertEqual(params["limit"], 2)

    def test_other_documented_routes(self):
        cases = [
            ("daily", "/usersummary-service/usersummary/daily", {"calendarDate":"2020-01-01"}),
            ("sleep", "/sleep-service/sleep/dailySleep", {"date":"2020-01-01"}),
            ("heart-rate", "/wellness-service/wellness/dailyHeartRate", {"date":"2020-01-01"}),
        ]
        for name, path, params in cases:
            self.assertEqual(g.resource_request(argparse.Namespace(resource=name, date="2020-01-01")), (path, params))
        self.assertEqual(g.resource_request(activity_args(resource="hrv"))[0], "/hrv-service/hrv/daily/2020-01-01/2020-01-07")
        for name, prefix in (("activity", "/activity-service/activity/"), ("activity-file", "/download-service/files/activity/")):
            self.assertEqual(g.resource_request(argparse.Namespace(resource=name, activity_id=123))[0], prefix+"123")

    def test_scope_bounds(self):
        for values in ({"start_date":"2020-01-08"}, {"end_date":"2020-03-01"}):
            with self.assertRaises(g.PullError):
                g.resource_request(activity_args(**values))

    def test_bad_date(self):
        for value in ("2020-02-30", "20200101", "2020-1-1"):
            with self.assertRaises(argparse.ArgumentTypeError):
                g.valid_date(value)

    def test_nonpositive_id(self):
        with self.assertRaises(g.PullError):
            g.resource_request(argparse.Namespace(resource="activity", activity_id=-1))

    def test_pagination_complete(self):
        client = Mock()
        client.get.side_effect = [[{"activityId":1}, {"activityId":2}], [{"activityId":3}]]
        data, meta = g.collect(client, activity_args())
        self.assertEqual(len(data), 3)
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["pages"], 2)

    def test_page_bound_not_claimed_complete(self):
        client = Mock()
        client.get.return_value = [{"activityId":1}, {"activityId":2}]
        _, meta = g.collect(client, activity_args(max_pages=1))
        self.assertFalse(meta["complete"])

    def test_empty_result(self):
        client = Mock()
        client.get.return_value = []
        data, meta = g.collect(client, activity_args())
        self.assertEqual(data, [])
        self.assertTrue(meta["complete"])
        self.assertTrue(meta["no_content"])

    def test_repeated_id_stops(self):
        client = Mock()
        client.get.side_effect = [[{"activityId":1}, {"activityId":2}], [{"activityId":1}]]
        with self.assertRaises(g.PullError):
            g.collect(client, activity_args())

    def test_wrong_activity_shape_stops(self):
        for chunk in ({"data": []}, [{"notActivity":1}], [1,2], [{"activityId":[]} ]):
            client = Mock()
            client.get.return_value = chunk
            with self.assertRaises(g.PullError):
                g.collect(client, activity_args())

    def test_https_origin_and_header_only(self):
        opener = Mock()
        opener.open.return_value = Response({"sample":True})
        self.assertEqual(g.Client(SYNTHETIC_TOKEN, opener).get("/usersummary-service/usersummary/daily", {"calendarDate":"2020-01-01"}), {"sample":True})
        req = opener.open.call_args.args[0]
        self.assertTrue(req.full_url.startswith(g.ORIGIN+"/"))
        self.assertNotIn(SYNTHETIC_TOKEN, req.full_url)
        self.assertEqual(req.get_header("Authorization"), "Bearer " + SYNTHETIC_TOKEN)
        self.assertEqual(req.method, "GET")

    def test_redirect_refused(self):
        with self.assertRaises(g.PullError):
            g.NoRedirect().redirect_request(None,None,302,"",{},"https://example.com")

    def test_header_injection_refused(self):
        for token in ("x\r\nHost: example.com", "", "token with space", "x"*(g.MAX_TOKEN+1)):
            with self.assertRaises(g.PullError):
                g.Client(token, Mock())

    def test_unauthorized_sanitized_not_retried(self):
        opener = Mock()
        opener.open.side_effect = HTTPError("https://example.com/"+SYNTHETIC_TOKEN,401,SYNTHETIC_TOKEN,{},io.BytesIO(SYNTHETIC_TOKEN.encode()))
        with self.assertRaises(g.PullError) as caught:
            g.Client(SYNTHETIC_TOKEN,opener).get("/usersummary-service/usersummary/daily",{})
        self.assertNotIn(SYNTHETIC_TOKEN,str(caught.exception))
        self.assertEqual(opener.open.call_count,1)

    def test_rate_limit_no_retry(self):
        opener=Mock()
        opener.open.side_effect=HTTPError(g.ORIGIN,429,"",{"Retry-After":"60"},io.BytesIO())
        with self.assertRaisesRegex(g.PullError,"60 seconds"):
            g.Client(SYNTHETIC_TOKEN,opener).get("/usersummary-service/usersummary/daily",{})
        self.assertEqual(opener.open.call_count,1)

    def test_transient_read_retry_bounded(self):
        opener=Mock()
        opener.open.side_effect=[HTTPError(g.ORIGIN,503,"",{},io.BytesIO()),Response({"ok":True})]
        sleeper=Mock()
        result=g.Client(SYNTHETIC_TOKEN,opener,sleeper).get("/usersummary-service/usersummary/daily",{})
        self.assertEqual(result,{"ok":True})
        sleeper.assert_called_once_with(1)

    def test_network_failure_sanitized(self):
        opener=Mock()
        opener.open.side_effect=URLError(SYNTHETIC_TOKEN)
        with self.assertRaises(g.PullError) as caught:
            g.Client(SYNTHETIC_TOKEN,opener).get("/usersummary-service/usersummary/daily",{})
        self.assertNotIn(SYNTHETIC_TOKEN,str(caught.exception))

    def test_bad_json_and_html(self):
        for response in (Response(raw=b"not-json"),Response(media="text/html",raw=b"<html>"),Response(data="scalar")):
            opener=Mock()
            opener.open.return_value=response
            with self.assertRaises(g.PullError):
                g.Client(SYNTHETIC_TOKEN,opener).get("/usersummary-service/usersummary/daily",{})

    def test_no_content(self):
        opener=Mock()
        opener.open.return_value=Response(status=204)
        self.assertIsNone(g.Client(SYNTHETIC_TOKEN,opener).get("/hrv-service/hrv/daily/2020-01-01/2020-01-02",{}))

    def test_binary_response(self):
        opener=Mock()
        opener.open.return_value=Response(media="application/x-zip-compressed",raw=b"PK\x03\x04synthetic")
        self.assertEqual(g.Client(SYNTHETIC_TOKEN,opener).get("/download-service/files/activity/1",{},True),b"PK\x03\x04synthetic")

    def test_private_file_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            p=Path(tmp)/"private"/"result.json"
            g.private_output(str(p),{"synthetic":True})
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            self.assertEqual(p.parent.stat().st_mode&0o777,0o700)
            with self.assertRaises(g.PullError):
                g.private_output(str(p),{})

    def test_repo_and_public_directory_refused(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            parent=Path(tmp)
            (parent/".git").mkdir()
            (parent/".git"/"HEAD").write_text("ref: refs/heads/main\n")
            with self.assertRaises(g.PullError):
                g.private_output(str(parent/"result.json"),{})
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            parent=Path(tmp)
            parent.chmod(0o755)
            with self.assertRaises(g.PullError):
                g.private_output(str(parent/"result.json"),{})

    def test_environment_token_removed_from_process_environment(self):
        with patch.dict(os.environ,{"SYNTHETIC_TEST_TOKEN":SYNTHETIC_TOKEN}):
            token=g.read_token(argparse.Namespace(token_stdin=False,token_env="SYNTHETIC_TEST_TOKEN"))
            self.assertEqual(token,SYNTHETIC_TOKEN)
            self.assertNotIn("SYNTHETIC_TEST_TOKEN",os.environ)

    def test_cli_metadata_has_no_payload_or_token(self):
        client=Mock()
        client.get.return_value=[{"activityId":1,"privateExample":"synthetic-private-value"}]
        output=io.StringIO()
        with patch("garmin_pull.Client",return_value=client), patch("sys.stdin",io.StringIO(SYNTHETIC_TOKEN)), redirect_stdout(output):
            code=g.main(["--token-stdin","--approved-token-use","--metadata-only","activities","--start-date","2020-01-01","--end-date","2020-01-01","--page-size","1","--max-pages","1"])
        self.assertEqual(code,0)
        self.assertNotIn(SYNTHETIC_TOKEN,output.getvalue())
        self.assertNotIn("synthetic-private-value",output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["record_count"],1)

    def test_malformed_http_response_sanitized(self):
        opener=Mock()
        opener.open.side_effect=BadStatusLine(SYNTHETIC_TOKEN)
        with self.assertRaises(g.PullError) as caught:
            g.Client(SYNTHETIC_TOKEN,opener).get("/usersummary-service/usersummary/daily",{})
        self.assertNotIn(SYNTHETIC_TOKEN,str(caught.exception))

    def test_unexpected_failure_sanitized(self):
        output=io.StringIO()
        with patch("garmin_pull.Client",side_effect=RuntimeError(SYNTHETIC_TOKEN)), patch("sys.stdin",io.StringIO(SYNTHETIC_TOKEN)), redirect_stderr(output):
            code=g.main(["--token-stdin","--approved-token-use","--metadata-only","daily","--date","2020-01-21"])
        self.assertEqual(code,1)
        self.assertNotIn(SYNTHETIC_TOKEN,output.getvalue())

    def test_mismatching_health_date_rejected(self):
        client=Mock()
        client.get.return_value={"calendarDate":"2020-01-20"}
        with self.assertRaises(g.PullError):
            g.collect(client,argparse.Namespace(resource="daily",date="2020-01-21"))

    def test_health_resource_shape(self):
        client=Mock()
        client.get.return_value=[]
        with self.assertRaises(g.PullError):
            g.collect(client,argparse.Namespace(resource="daily",date="2020-01-21"))

    def test_activity_identifiers_must_be_positive_integers(self):
        for identity in (True,False,0,-1,"", "123", "arbitrary",1.5):
            client=Mock()
            client.get.return_value=[{"activityId":identity}]
            with self.assertRaises(g.PullError):
                g.collect(client,activity_args())

    def test_activity_local_dates_within_inclusive_scope(self):
        client=Mock()
        client.get.return_value=[{"activityId":1,"startTimeLocal":"2020-01-01 12:00:00"},{"activityId":2,"startTimeLocal":"2020-01-07T23:00:00"}]
        records,meta=g.collect(client,activity_args(max_pages=1))
        self.assertEqual(len(records),2)
        self.assertTrue(meta["date_range_verified"])
        self.assertEqual(meta["records_without_local_date"],0)

    def test_invalid_or_outside_activity_dates_rejected(self):
        for value in ("2019-12-31T23:59:59", "2020-01-08T00:00:00", "2020-02-30T12:00:00", "garbage",123):
            client=Mock()
            client.get.return_value=[{"activityId":1,"startTimeLocal":value}]
            with self.assertRaises(g.PullError):
                g.collect(client,activity_args())

    def test_missing_activity_local_dates_explicit(self):
        client=Mock()
        client.get.return_value=[{"activityId":1}]
        _,meta=g.collect(client,activity_args())
        self.assertEqual(meta["records_without_local_date"],1)
        self.assertFalse(meta["date_range_verified"])

    def test_unlisted_resource_refused(self):
        opener=Mock()
        with self.assertRaises(g.PullError):
            g.Client(SYNTHETIC_TOKEN,opener).get("/not-an-allowed-resource",{})
        opener.open.assert_not_called()

    def test_invalid_args_do_not_echo_secret(self):
        output=io.StringIO()
        with redirect_stderr(output), self.assertRaises(SystemExit):
            g.main(["--not-an-option",SYNTHETIC_TOKEN])
        self.assertNotIn(SYNTHETIC_TOKEN,output.getvalue())

    def test_symlink_output_refused(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            target=Path(tmp)/"target.json"
            alias=Path(tmp)/"alias.json"
            alias.symlink_to(target)
            with self.assertRaises(g.PullError):
                g.private_output(str(alias),{})
            self.assertFalse(target.exists())

    def test_no_approval_no_network(self):
        with patch("garmin_pull.Client") as client, redirect_stderr(io.StringIO()):
            code=g.main(["--token-stdin","--metadata-only","daily","--date","2020-01-01"])
        self.assertEqual(code,1)
        client.assert_not_called()


class ExchangeTests(unittest.TestCase):
    def test_plain_text_exchange_contract(self):
        opener=Mock()
        opener.open.return_value=Response(media="text/plain; charset=utf-8",raw=(SYNTHETIC_TOKEN+"\n").encode())
        token=g.exchange_api_key(SYNTHETIC_KEY,approved=True,opener=opener)
        self.assertEqual(token,SYNTHETIC_TOKEN)
        req=opener.open.call_args.args[0]
        self.assertEqual(req.full_url,g.ORIGIN+g.TOKEN_PATH)
        self.assertEqual(req.method,"POST")
        self.assertEqual(req.data,b"")
        self.assertEqual(req.get_header("Accept"),"*/*")
        self.assertEqual(req.get_header("Authorization"),"ApiKey "+SYNTHETIC_KEY)
        self.assertNotIn(SYNTHETIC_KEY,req.full_url)
        self.assertEqual(opener.open.call_count,1)

    def test_exchange_requires_actual_guard(self):
        opener=Mock()
        for approval in (False,None,"yes",1):
            with self.assertRaises(g.PullError):
                g.exchange_api_key(SYNTHETIC_KEY,approved=approval,opener=opener)
        opener.open.assert_not_called()

    def test_bad_key_not_sent(self):
        opener=Mock()
        for value in (None,"", "key with space", "key\r\nHost: example.com", "key-é", "x"*(g.MAX_TOKEN+1)):
            with self.assertRaises(g.PullError):
                g.exchange_api_key(value,approved=True,opener=opener)
        opener.open.assert_not_called()

    def test_non_plain_response_not_guessed(self):
        opener=Mock()
        opener.open.return_value=Response(data={"access_token":SYNTHETIC_TOKEN})
        with self.assertRaises(g.PullError):
            g.exchange_api_key(SYNTHETIC_KEY,approved=True,opener=opener)

    def test_invalid_plain_response_sanitized(self):
        for raw in (b"", json.dumps({"access_token":SYNTHETIC_TOKEN}).encode(), b"<html>private</html>", b"\xff"):
            opener=Mock()
            opener.open.return_value=Response(media="text/plain",raw=raw)
            with self.assertRaises(g.PullError) as caught:
                g.exchange_api_key(SYNTHETIC_KEY,approved=True,opener=opener)
            self.assertNotIn(SYNTHETIC_TOKEN,str(caught.exception))
            self.assertNotIn("private</html>",str(caught.exception))

    def test_oversize_response_refused(self):
        opener=Mock()
        opener.open.return_value=Response(media="text/plain",raw=b"x"*(g.MAX_TOKEN_RESPONSE+1))
        with self.assertRaises(g.PullError):
            g.exchange_api_key(SYNTHETIC_KEY,approved=True,opener=opener)

    def test_http_exchange_failure_not_retried(self):
        for status in (401,403,406,429,503):
            opener=Mock()
            opener.open.side_effect=HTTPError(g.ORIGIN,status,SYNTHETIC_KEY,{},io.BytesIO(SYNTHETIC_TOKEN.encode()))
            with self.assertRaises(g.PullError) as caught:
                g.exchange_api_key(SYNTHETIC_KEY,approved=True,opener=opener)
            self.assertNotIn(SYNTHETIC_KEY,str(caught.exception))
            self.assertNotIn(SYNTHETIC_TOKEN,str(caught.exception))
            self.assertEqual(opener.open.call_count,1)

    def test_exchange_transport_failure_is_uncertain(self):
        for failure in (URLError(SYNTHETIC_KEY),BadStatusLine(SYNTHETIC_TOKEN),TimeoutError(SYNTHETIC_KEY)):
            opener=Mock()
            opener.open.side_effect=failure
            with self.assertRaises(g.PullError) as caught:
                g.exchange_api_key(SYNTHETIC_KEY,approved=True,opener=opener)
            self.assertIn("uncertain",str(caught.exception))
            self.assertNotIn(SYNTHETIC_KEY,str(caught.exception))
            self.assertNotIn(SYNTHETIC_TOKEN,str(caught.exception))
            self.assertEqual(opener.open.call_count,1)

    def test_exchange_default_transport_blocks_redirects(self):
        transport=Mock()
        transport.open.return_value=Response(media="text/plain",raw=SYNTHETIC_TOKEN.encode())
        with patch("garmin_pull.request.build_opener",return_value=transport) as factory:
            g.exchange_api_key(SYNTHETIC_KEY,approved=True)
        self.assertIsInstance(factory.call_args.args[0],g.NoRedirect)

    def test_key_cli_stays_in_memory(self):
        client=Mock()
        client.get.return_value=[{"activityId":1,"privateSynthetic":"not-for-output"}]
        output=io.StringIO()
        args=["--key-stdin","--approved-key-exchange","--approved-token-use","--metadata-only","activities","--start-date","2020-01-21","--end-date","2020-01-22","--page-size","1","--max-pages","1"]
        with patch("garmin_pull.exchange_api_key",return_value=SYNTHETIC_TOKEN) as exchange, patch("garmin_pull.Client",return_value=client) as factory, patch("garmin_pull.private_output") as writer, patch("sys.stdin",io.StringIO(SYNTHETIC_KEY)), redirect_stdout(output):
            code=g.main(args)
        self.assertEqual(code,0)
        exchange.assert_called_once_with(SYNTHETIC_KEY,approved=True)
        factory.assert_called_once_with(SYNTHETIC_TOKEN)
        writer.assert_not_called()
        self.assertIsNone(client._token)
        self.assertNotIn(SYNTHETIC_KEY,output.getvalue())
        self.assertNotIn(SYNTHETIC_TOKEN,output.getvalue())
        self.assertNotIn("not-for-output",output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["record_count"],1)

    def test_missing_exchange_guard_does_not_read_key(self):
        args=["--key-stdin","--approved-token-use","--metadata-only","daily","--date","2020-01-21"]
        with patch("garmin_pull.read_secret") as reader, patch("garmin_pull.exchange_api_key") as exchange, redirect_stderr(io.StringIO()):
            code=g.main(args)
        self.assertEqual(code,1)
        reader.assert_not_called()
        exchange.assert_not_called()

    def test_key_environment_removed_from_child(self):
        client=Mock()
        client.get.return_value={"calendarDate":"2020-01-21"}
        with patch.dict(os.environ,{"SYNTHETIC_TEST_KEY":SYNTHETIC_KEY}), patch("garmin_pull.exchange_api_key",return_value=SYNTHETIC_TOKEN), patch("garmin_pull.Client",return_value=client), redirect_stdout(io.StringIO()):
            code=g.main(["--key-env","SYNTHETIC_TEST_KEY","--approved-key-exchange","--approved-token-use","--metadata-only","daily","--date","2020-01-21"])
            self.assertNotIn("SYNTHETIC_TEST_KEY",os.environ)
        self.assertEqual(code,0)

    def test_key_and_token_inputs_are_mutually_exclusive(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            g.parser().parse_args(["--key-stdin","--token-stdin","--metadata-only","daily","--date","2020-01-21"])


if __name__=="__main__":
    unittest.main()
