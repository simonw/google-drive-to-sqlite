from click.testing import CliRunner
from google_drive_to_sqlite.cli import cli
import json
import pytest


@pytest.mark.parametrize(
    "response,expected_error",
    (
        ({"refresh_token": "rtoken"}, None),
        (
            {"error": "bad_error", "error_description": "description"},
            "Error: bad_error: description",
        ),
        (
            {"unexpected": "error"},
            "Error: No refresh_token in response",
        ),
    ),
)
def test_auth(httpx_mock, response, expected_error):
    httpx_mock.add_response(json=response)
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["auth"], input="my-token")
        if expected_error:
            assert result.exit_code == 1
            assert result.output.strip().endswith(expected_error)
        else:
            assert result.exit_code == 0
            auth = json.load(open("auth.json"))
            assert auth == {"google-drive-to-sqlite": "rtoken"}


def test_get_single(httpx_mock):
    about_data = {
        "kind": "drive#about",
        "user": {"kind": "drive#user", "displayName": "User"},
    }
    httpx_mock.add_response(
        url="https://www.googleapis.com/oauth2/v4/token",
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        url="https://www.googleapis.com/drive/v3/about?fields=*",
        method="GET",
        json=about_data,
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps({"google-drive-to-sqlite": "rtoken"}))
        result = runner.invoke(
            cli, ["get", "https://www.googleapis.com/drive/v3/about?fields=*"]
        )
        token_request, about_request = httpx_mock.get_requests()
        assert token_request.content == (
            b"grant_type=refresh_token&"
            b"refresh_token=rtoken&"
            b"client_id=148933860554-98i3hter1bsn24sa6fcq1tcrhcrujrnl.apps.googleusercontent.com&"
            b"client_secret=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"
        )
        assert about_request.url == "https://www.googleapis.com/drive/v3/about?fields=*"
        assert about_request.headers["authorization"] == "Bearer atoken"
        assert result.exit_code == 0
        assert json.loads(result.output) == about_data


@pytest.mark.parametrize(
    "opts,expected_output",
    (
        (
            [],
            (
                '[\n  {\n    "id": 1\n  },\n  {\n    "id": 2\n  },\n  '
                '{\n    "id": 3\n  },\n  {\n    "id": 4\n  }\n]\n'
            ),
        ),
        (
            ["--nl"],
            ('{"id": 1}\n{"id": 2}\n{"id": 3}\n{"id": 4}\n'),
        ),
    ),
)
def test_get_paginated(httpx_mock, opts, expected_output):
    httpx_mock.add_response(
        url="https://www.googleapis.com/oauth2/v4/token",
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        url="https://www.googleapis.com/page",
        json={"nextPageToken": "next", "files": [{"id": 1}, {"id": 2}]},
    )
    httpx_mock.add_response(
        url="https://www.googleapis.com/page?pageToken=next",
        json={"nextPageToken": None, "files": [{"id": 3}, {"id": 4}]},
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps({"google-drive-to-sqlite": "rtoken"}))
        result = runner.invoke(
            cli,
            ["get", "https://www.googleapis.com/page", "--paginate", "files"] + opts,
        )
        _, page1_request, page2_request = httpx_mock.get_requests()
        for request in (page1_request, page2_request):
            assert request.headers["authorization"] == "Bearer atoken"
        assert page2_request.url == "https://www.googleapis.com/page?pageToken=next"
        assert result.exit_code == 0
        assert result.output == expected_output
