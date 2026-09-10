import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

# The tests replace HTMLSession with a fixture-backed fake. This import shim
# avoids loading the incompatible bundled lxml binary on Python 3.13.
if "requests_html" not in sys.modules:
    requests_html_stub = types.ModuleType("requests_html")
    requests_html_stub.HTMLSession = object
    sys.modules["requests_html"] = requests_html_stub

import app as app_module
import util


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(*parts):
    return (FIXTURES.joinpath(*parts)).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, text="", status_code=200, json_data=None):
        self.text = text
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeElement:
    def __init__(self, node):
        self.node = node

    @property
    def text(self):
        return self.node.get_text()

    def find(self, selector, first=False):
        matches = self.node.select(selector)
        if first:
            return FakeElement(matches[0]) if matches else None
        return [FakeElement(match) for match in matches]

    def findChildren(self, selector):
        return [FakeElement(match) for match in self.node.select(selector)]


class FakeHTML:
    def __init__(self, html):
        from bs4 import BeautifulSoup

        self.soup = BeautifulSoup(html, "html.parser")

    def find(self, selector, first=False):
        matches = self.soup.select(selector)
        if first:
            return FakeElement(matches[0]) if matches else None
        return [FakeElement(match) for match in matches]


class FakeHTMLResponse:
    def __init__(self, html, status_code=200):
        self.status_code = status_code
        self.html = FakeHTML(html)


class FakeHTMLSession:
    def __init__(self, html, status_code=200):
        self.response = FakeHTMLResponse(html, status_code)

    def get(self, url, timeout=None):
        return self.response


class TestApiContract(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_supported_platform_names_are_dispatched(self):
        platforms = ["codechef", "codeforces", "leetcode", "atcoder", "spoj"]
        fake_user_data = Mock()
        fake_user_data.get_details.return_value = {"status": "OK"}
        with patch.object(app_module, "UserData", return_value=fake_user_data):
            for platform in platforms:
                response = self.client.get(f"/api/{platform}/example")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"status": "OK"})

    def test_unsupported_platform_is_a_http_200_failure_payload(self):
        response = self.client.get("/api/unknown/example")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "status": "Failed",
            "details": "Invalid Platform",
        })

    def test_username_error_is_a_http_200_failure_payload(self):
        fake_user_data = Mock()
        fake_user_data.get_details.side_effect = util.UsernameError()
        with patch.object(app_module, "UserData", return_value=fake_user_data):
            response = self.client.get("/api/codechef/missing")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "status": "Failed",
            "details": "Invalid username",
        })


class TestPlatformCharacterization(unittest.TestCase):
    def test_codechef_current_response_fields(self):
        html = fixture_text("codechef", "profile.html")
        with patch.object(util.requests, "get", return_value=FakeResponse(text=html)):
            result = util.UserData("als1510").get_details("codechef")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["rating"], 1500)
        self.assertEqual(result["stars"], "3 star")
        self.assertEqual(result["highest_rating"], 1600)
        self.assertEqual(result["global_rank"], 10)
        self.assertEqual(result["country_rank"], 20)
        self.assertEqual(result["contest_ratings"], [{"name": "Contest One", "rating": 1500}])
        self.assertEqual(result["fully_solved"]["count"], 2)
        self.assertEqual(result["partially_solved"]["count"], 1)
        self.assertEqual(result["user_details"]["username"], "als1510")

    def test_codeforces_current_response_fields(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        rating = json.loads(fixture_text("codeforces", "user_rating.json"))
        responses = [FakeResponse(status_code=200, json_data=user_info),
                     FakeResponse(status_code=200, json_data=rating)]
        with patch.object(util.requests, "get", side_effect=responses) as get_mock:
            result = util.UserData("als1510").get_details("codeforces")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["handle"], "als1510")
        self.assertEqual(result["rating"], 1500)
        self.assertEqual(result["contests"], [{
            "contest": "Example Contest One",
            "rank": "42",
            "solved": "NA",
            "ratingChange": "+100",
            "newRating": "1600",
        }, {
            "contest": "Example Contest Two",
            "rank": "21",
            "solved": "NA",
            "ratingChange": "-50",
            "newRating": "1550",
        }])
        requested_urls = [request.args[0] for request in get_mock.call_args_list]
        self.assertIn("https://codeforces.com/api/user.rating?handle=als1510",
                      requested_urls)
        self.assertNotIn("https://codeforces.com/contests/with/als1510",
                         requested_urls)

    def test_leetcode_current_graphql_response_fields(self):
        graphql = json.loads(fixture_text("leetcode", "profile.json"))
        responses = [FakeResponse(status_code=200), FakeResponse(status_code=200, json_data=graphql)]
        with patch.object(util.requests, "get", side_effect=responses[:1]), patch.object(
            util.requests, "post", return_value=responses[1]
        ):
            result = util.UserData("als1510").get_details("leetcode")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["ranking"], "50000")
        self.assertEqual(result["reputation"], "10")
        self.assertEqual(result["total_problems_solved"], "100")
        self.assertEqual(result["total_problems_submitted"], "150")
        self.assertEqual(result["acceptance_rate"], "66.67%")
        self.assertEqual(result["easy_questions_solved"], "50")
        self.assertEqual(result["total_hard_questions"], "700")
        self.assertEqual(result["contribution_points"], "25")

    def test_atcoder_current_response_fields(self):
        html = fixture_text("atcoder", "current_profile.html")
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession(html)), patch.object(
            util.requests, "get", return_value=FakeResponse(text=html)
        ):
            result = util.UserData("als1510").get_details("atcoder")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["rating"], "NA")
        self.assertEqual(result["highest"], "NA")
        self.assertEqual(result["rank"], "NA")
        self.assertEqual(result["level"], "NA")
        self.assertEqual(result["other"]["Country/Region"], "India")
        self.assertEqual(result["other"]["Birth Year"], "2001")

    def test_atcoder_semantic_fields_ignore_table_order(self):
        html = fixture_text("atcoder", "profile_reordered.html")
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession(html)), patch.object(
            util.requests, "get", return_value=FakeResponse(text=html)
        ):
            result = util.UserData("als1510").get_details("atcoder")
        self.assertEqual(result["rating"], 1500)
        self.assertEqual(result["highest"], 1600)
        self.assertEqual(result["rank"], 123)
        self.assertEqual(result["level"], "Silver")

    def test_spoj_current_response_fields(self):
        html = fixture_text("spoj", "profile.html")
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession(html)), patch.object(
            util.requests, "get", return_value=FakeResponse(text=html)
        ):
            result = util.UserData("als1510").get_details("spoj")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["fullname"], "Example User")
        self.assertEqual(result["location"], "Exampleland")
        self.assertEqual(result["points"], 12.5)
        self.assertEqual(result["rank"], 42)
        self.assertEqual(result["solved"], ["TEST1"])
        self.assertEqual(result["todo"], ["TODO1"])
        self.assertEqual(result["problems_solved"], "25")
        self.assertEqual(result["solution_submitted"], "40")


class TestDiagnosticLogging(unittest.TestCase):
    def test_codechef_logs_gate_without_response_body(self):
        html = fixture_text("codechef", "profile.html")
        with patch.object(util.requests, "get", return_value=FakeResponse(text=html)):
            with self.assertLogs(util.logger, level="WARNING") as captured:
                util.UserData("als1510").get_details("codechef")
        output = "\n".join(captured.output)
        self.assertIn("'operation': 'profile'", output)
        self.assertIn("'expected_selector_present': True", output)
        self.assertIn("<redacted>", output)
        self.assertNotIn("Example User", output)

    def test_codeforces_logs_both_upstream_operations_and_gates(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        rating = json.loads(fixture_text("codeforces", "user_rating.json"))
        responses = [FakeResponse(json_data=user_info),
                     FakeResponse(json_data=rating)]
        with patch.object(util.requests, "get", side_effect=responses):
            with self.assertLogs(util.logger, level="WARNING") as captured:
                util.UserData("als1510").get_details("codeforces")
        output = "\n".join(captured.output)
        self.assertIn("'operation': 'user.info'", output)
        self.assertIn("'operation': 'user.rating'", output)
        self.assertIn("'result_present': True", output)

    def test_leetcode_logs_profile_graphql_and_json_stages(self):
        graphql = json.loads(fixture_text("leetcode", "profile.json"))
        with patch.object(util.requests, "get", return_value=FakeResponse()), patch.object(
            util.requests, "post", return_value=FakeResponse(json_data=graphql)
        ):
            with self.assertLogs(util.logger, level="WARNING") as captured:
                util.UserData("als1510").get_details("leetcode")
        output = "\n".join(captured.output)
        self.assertIn("'operation': 'profile'", output)
        self.assertIn("'operation': 'graphql'", output)
        self.assertIn("'operation': 'graphql_parser'", output)
        self.assertIn("'matched_user_present': True", output)
        self.assertNotIn("Example User", output)

    def test_atcoder_logs_table_counts_and_na_branch(self):
        html = "<table class='dl-table'><tr><th>Country/Region</th><td>India</td></tr></table>"
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession(html)), patch.object(
            util.requests, "get", return_value=FakeResponse(text=html)
        ):
            with self.assertLogs(util.logger, level="WARNING") as captured:
                util.UserData("als1510").get_details("atcoder")
        output = "\n".join(captured.output)
        self.assertIn("'dl_table_count': 1", output)
        self.assertIn("'rating_fields_present': False", output)

    def test_spoj_logs_profile_container_and_second_request(self):
        html = fixture_text("spoj", "profile.html")
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession(html)), patch.object(
            util.requests, "get", return_value=FakeResponse(text=html)
        ):
            with self.assertLogs(util.logger, level="WARNING") as captured:
                util.UserData("als1510").get_details("spoj")
        output = "\n".join(captured.output)
        self.assertIn("'operation': 'profile'", output)
        self.assertIn("'operation': 'profile_parser'", output)
        self.assertIn("'profile_container_present': True", output)
        self.assertIn("'operation': 'profile_details'", output)


class TestFailureCharacterization(unittest.TestCase):
    def test_codechef_forbidden_is_shared_access_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=403)):
            with self.assertRaises(util.UpstreamAccessError):
                util.UserData("als1510").get_details("codechef")

    def test_codechef_rate_limit_is_shared_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=429)):
            with self.assertRaises(util.UpstreamRateLimitError):
                util.UserData("als1510").get_details("codechef")

    def test_codechef_server_error_is_shared_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=503)):
            with self.assertRaises(util.UpstreamServerError):
                util.UserData("als1510").get_details("codechef")

    def test_codechef_transport_error_is_shared_error(self):
        with patch.object(util.requests, "get", side_effect=requests.Timeout()):
            with self.assertRaises(util.UpstreamTransportError):
                util.UserData("als1510").get_details("codechef")

    def test_codechef_missing_rating_is_structure_error(self):
        html = "<html><body><div class='rating-header'></div></body></html>"
        with patch.object(util.requests, "get", return_value=FakeResponse(text=html)):
            with self.assertRaises(util.StructureError):
                util.UserData("missing").get_details("codechef")

    def test_codeforces_empty_api_result_raises_index_error(self):
        api_error = {"status": "FAILED", "comment": "not found", "result": []}
        responses = [FakeResponse(json_data=api_error), FakeResponse(text="<html></html>")]
        with patch.object(util.requests, "get", side_effect=responses):
            with self.assertRaises(IndexError):
                util.UserData("missing").get_details("codeforces")

    def test_codeforces_missing_contest_table_is_structure_error(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        responses = [FakeResponse(json_data=user_info), FakeResponse(text="<html></html>")]
        with patch.object(util.requests, "get", side_effect=responses):
            with self.assertRaises(util.StructureError):
                util.UserData("als1510").get_details("codeforces")

    def test_codeforces_empty_rating_history_is_valid(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        responses = [
            FakeResponse(json_data=user_info),
            FakeResponse(json_data={"status": "OK", "result": []}),
        ]
        with patch.object(util.requests, "get", side_effect=responses):
            result = util.UserData("als1510").get_details("codeforces")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["contests"], [])

    def test_codeforces_rating_access_error_is_not_username_error(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        responses = [FakeResponse(json_data=user_info), FakeResponse(status_code=403)]
        with patch.object(util.requests, "get", side_effect=responses):
            with self.assertRaises(util.UpstreamAccessError):
                util.UserData("als1510").get_details("codeforces")

    def test_codeforces_rating_rate_limit_is_shared_error(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        responses = [FakeResponse(json_data=user_info), FakeResponse(status_code=429)]
        with patch.object(util.requests, "get", side_effect=responses):
            with self.assertRaises(util.UpstreamRateLimitError):
                util.UserData("als1510").get_details("codeforces")

    def test_codeforces_rating_server_error_is_shared_error(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        responses = [FakeResponse(json_data=user_info), FakeResponse(status_code=503)]
        with patch.object(util.requests, "get", side_effect=responses):
            with self.assertRaises(util.UpstreamServerError):
                util.UserData("als1510").get_details("codeforces")

    def test_codeforces_rating_transport_error_is_shared_error(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        responses = [FakeResponse(json_data=user_info), requests.Timeout()]
        with patch.object(util.requests, "get", side_effect=responses):
            with self.assertRaises(util.UpstreamTransportError):
                util.UserData("als1510").get_details("codeforces")

    def test_codeforces_malformed_rating_json_is_structure_error(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        responses = [FakeResponse(json_data=user_info), FakeResponse(text="not json")]
        with patch.object(util.requests, "get", side_effect=responses):
            with self.assertRaises(util.StructureError):
                util.UserData("als1510").get_details("codeforces")

    def test_codeforces_unexpected_rating_status_is_structure_error(self):
        user_info = json.loads(fixture_text("codeforces", "user_info.json"))
        responses = [
            FakeResponse(json_data=user_info),
            FakeResponse(json_data={"status": "FAILED", "comment": "error"}),
        ]
        with patch.object(util.requests, "get", side_effect=responses):
            with self.assertRaises(util.StructureError):
                util.UserData("als1510").get_details("codeforces")

    def test_leetcode_missing_matched_user_is_structure_error(self):
        graphql = {"data": {"allQuestionsCount": [], "matchedUser": None}}
        with patch.object(util.requests, "get", return_value=FakeResponse()), patch.object(
            util.requests, "post", return_value=FakeResponse(json_data=graphql)
        ):
            with self.assertRaises(util.StructureError):
                util.UserData("missing").get_details("leetcode")

    def test_leetcode_graphql_http_error_is_upstream_server_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse()), patch.object(
            util.requests, "post", return_value=FakeResponse(status_code=500)
        ):
            with self.assertRaises(util.UpstreamServerError):
                util.UserData("als1510").get_details("leetcode")

    def test_leetcode_profile_forbidden_is_access_error_and_stops_before_graphql(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=403)), patch.object(
            util.requests, "post"
        ) as post_mock:
            with self.assertRaises(util.UpstreamAccessError):
                util.UserData("als1510").get_details("leetcode")
        post_mock.assert_not_called()

    def test_leetcode_profile_rate_limit_is_shared_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=429)):
            with self.assertRaises(util.UpstreamRateLimitError):
                util.UserData("als1510").get_details("leetcode")

    def test_leetcode_profile_server_error_is_shared_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=503)):
            with self.assertRaises(util.UpstreamServerError):
                util.UserData("als1510").get_details("leetcode")

    def test_leetcode_profile_transport_error_is_shared_error(self):
        with patch.object(util.requests, "get", side_effect=requests.Timeout()):
            with self.assertRaises(util.UpstreamTransportError):
                util.UserData("als1510").get_details("leetcode")

    def test_leetcode_malformed_graphql_json_is_structure_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse()), patch.object(
            util.requests, "post", return_value=FakeResponse(text="not json")
        ):
            with self.assertRaises(util.StructureError):
                util.UserData("als1510").get_details("leetcode")

    def test_atcoder_missing_profile_table_is_structure_error(self):
        html = "<html><body></body></html>"
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession(html)), patch.object(
            util.requests, "get", return_value=FakeResponse(text=html)
        ):
            with self.assertRaises(util.StructureError):
                util.UserData("missing").get_details("atcoder")

    def test_atcoder_forbidden_is_shared_access_error(self):
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession("", status_code=403)):
            with self.assertRaises(util.UpstreamAccessError):
                util.UserData("als1510").get_details("atcoder")

    def test_atcoder_rate_limit_is_shared_error(self):
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession("", status_code=429)):
            with self.assertRaises(util.UpstreamRateLimitError):
                util.UserData("als1510").get_details("atcoder")

    def test_atcoder_server_error_is_shared_error(self):
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession("", status_code=503)):
            with self.assertRaises(util.UpstreamServerError):
                util.UserData("als1510").get_details("atcoder")

    def test_atcoder_transport_error_is_shared_error(self):
        session = Mock()
        session.get.side_effect = requests.Timeout()
        with patch.object(util, "HTMLSession", return_value=session):
            with self.assertRaises(util.UpstreamTransportError):
                util.UserData("als1510").get_details("atcoder")

    def test_atcoder_fewer_than_two_tables_preserves_na_response(self):
        html = "<table class='dl-table'><tr><th>Country/Region</th><td>Japan</td></tr></table>"
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession(html)), patch.object(
            util.requests, "get", return_value=FakeResponse(text=html)
        ):
            result = util.UserData("als1510").get_details("atcoder")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["rating"], "NA")
        self.assertEqual(result["other"]["Country/Region"], "Japan")

    def test_spoj_missing_profile_is_structure_error(self):
        html = "<html><body></body></html>"
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession(html)), patch.object(
            util.requests, "get", return_value=FakeResponse(text=html)
        ):
            with self.assertRaises(util.StructureError):
                util.UserData("missing").get_details("spoj")

    def test_spoj_forbidden_is_shared_access_error(self):
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession("", status_code=403)):
            with self.assertRaises(util.UpstreamAccessError):
                util.UserData("als1510").get_details("spoj")

    def test_spoj_rate_limit_is_shared_error(self):
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession("", status_code=429)):
            with self.assertRaises(util.UpstreamRateLimitError):
                util.UserData("als1510").get_details("spoj")

    def test_spoj_server_error_is_shared_error(self):
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession("", status_code=503)):
            with self.assertRaises(util.UpstreamServerError):
                util.UserData("als1510").get_details("spoj")

    def test_spoj_transport_error_is_shared_error(self):
        session = Mock()
        session.get.side_effect = requests.Timeout()
        with patch.object(util, "HTMLSession", return_value=session):
            with self.assertRaises(util.UpstreamTransportError):
                util.UserData("als1510").get_details("spoj")

    def test_spoj_missing_todo_table_returns_none(self):
        html = fixture_text("spoj", "profile.html").replace(
            '<table class="table"><tr><td><a>TODO1</a></td></tr></table>', ""
        )
        with patch.object(util, "HTMLSession", return_value=FakeHTMLSession(html)), patch.object(
            util.requests, "get", return_value=FakeResponse(text=html)
        ):
            result = util.UserData("als1510").get_details("spoj")
        self.assertIsNone(result["todo"])


class TestSharedUpstreamErrors(unittest.TestCase):
    def test_forbidden_is_upstream_access_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=403)):
            with self.assertRaises(util.UpstreamAccessError) as raised:
                util._request_get("https://example.test/profile", "test", "profile")
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.public_message, "Upstream access failure")

    def test_not_found_is_distinguishable_and_profile_lookup_can_map_to_username(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=404)):
            with self.assertRaises(util.UpstreamMissingError) as resource_error:
                util._request_get("https://example.test/contest", "test", "contest")
        self.assertFalse(resource_error.exception.username_lookup)
        self.assertEqual(resource_error.exception.public_message,
                         "Upstream resource not found")

        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=404)):
            with self.assertRaises(util.UpstreamMissingError) as profile_error:
                util._request_get(
                    "https://example.test/profile", "test", "profile",
                    username_lookup=True)
        self.assertTrue(profile_error.exception.username_lookup)
        self.assertEqual(profile_error.exception.public_message, "Invalid username")

    def test_rate_limit_is_upstream_rate_limit_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(status_code=429)):
            with self.assertRaises(util.UpstreamRateLimitError):
                util._request_get("https://example.test/profile", "test", "profile")

    def test_server_errors_are_upstream_server_errors(self):
        for status_code in (500, 502, 503):
            with self.subTest(status_code=status_code), patch.object(
                util.requests, "get", return_value=FakeResponse(status_code=status_code)
            ):
                with self.assertRaises(util.UpstreamServerError):
                    util._request_get("https://example.test/profile", "test", "profile")

    def test_transport_errors_are_distinguishable(self):
        for error in (requests.Timeout(), requests.ConnectionError()):
            with self.subTest(error=type(error).__name__), patch.object(
                util.requests, "get", side_effect=error
            ):
                with self.assertRaises(util.UpstreamTransportError) as raised:
                    util._request_get("https://example.test/profile", "test", "profile")
                self.assertIs(raised.exception.cause, error)

    def test_success_returns_original_response(self):
        response = FakeResponse(status_code=200, text="success")
        with patch.object(util.requests, "get", return_value=response):
            self.assertIs(
                util._request_get("https://example.test/profile", "test", "profile"),
                response,
            )

    def test_successful_unexpected_structure_is_structure_error(self):
        with patch.object(util.requests, "get", return_value=FakeResponse(text="<html></html>")):
            with self.assertRaises(util.StructureError):
                util.UserData("als1510").get_details("codechef")


if __name__ == "__main__":
    unittest.main()
