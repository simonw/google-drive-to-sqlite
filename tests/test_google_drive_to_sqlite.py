from click.testing import CliRunner
from google_drive_to_sqlite.cli import cli, DEFAULT_FIELDS
import json
import pytest
import re
import sqlite_utils

TOKEN_REQUEST_CONTENT = (
    b"grant_type=refresh_token&"
    b"refresh_token=rtoken&"
    b"client_id=148933860554-98i3hter1bsn24sa6fcq1tcrhcrujrnl.apps.googleusercontent.com&"
    b"client_secret=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"
)

AUTH_JSON = {"google-drive-to-sqlite": {"refresh_token": "rtoken"}}


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
            assert auth == {"google-drive-to-sqlite": {"refresh_token": "rtoken"}}


@pytest.mark.parametrize(
    "opts,expected_content",
    (
        ([], {"refresh_token": "rtoken"}),
        (
            ["--google-client-id", "x", "--google-client-secret", "y"],
            {
                "refresh_token": "rtoken",
                "google_client_id": "x",
                "google_client_secret": "y",
            },
        ),
        (
            ["--scope", "SCOPE"],
            {
                "refresh_token": "rtoken",
                "scope": "SCOPE",
            },
        ),
    ),
)
def test_auth_custom_client(httpx_mock, opts, expected_content):
    httpx_mock.add_response(json={"refresh_token": "rtoken"})
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["auth"] + opts, input="my-token")
        assert result.exit_code == 0
        auth = json.load(open("auth.json"))
        assert auth == {"google-drive-to-sqlite": expected_content}


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
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        result = runner.invoke(
            cli, ["get", "https://www.googleapis.com/drive/v3/about?fields=*"]
        )
        token_request, about_request = httpx_mock.get_requests()
        assert token_request.content == TOKEN_REQUEST_CONTENT
        assert about_request.url == "https://www.googleapis.com/drive/v3/about?fields=*"
        assert about_request.headers["authorization"] == "Bearer atoken"
        assert result.exit_code == 0
        assert result.output.strip() == json.dumps(about_data, indent=4)


def test_get_plain_text(httpx_mock):
    url = "https://www.googleapis.com/drive/v3/files/123/export?mimeType=text/plain"
    httpx_mock.add_response(
        url="https://www.googleapis.com/oauth2/v4/token",
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        url=url,
        method="GET",
        content="This is plain text",
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        result = runner.invoke(cli, ["get", url])
        token_request, export_request = httpx_mock.get_requests()
        assert token_request.content == TOKEN_REQUEST_CONTENT
        assert export_request.url == url
        assert export_request.headers["authorization"] == "Bearer atoken"
        assert result.exit_code == 0
        assert result.output.strip() == "This is plain text"


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
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
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


@pytest.mark.parametrize(
    "opts,extra_qs",
    (
        ([], ""),
        (["-q", "starred = true"], "&q=starred+%3D+true"),
        (["--full-text", "search"], "&q=fullText+contains+%27search%27"),
    ),
)
@pytest.mark.parametrize("use_db", (True, False))
def test_files_basic(httpx_mock, opts, extra_qs, use_db):
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        json={"nextPageToken": "next", "files": [{"id": 1}, {"id": 2}]},
    )
    httpx_mock.add_response(
        json={"nextPageToken": None, "files": [{"id": 3}, {"id": 4}]},
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        args = ["files"]
        if use_db:
            args.append("test.db")
        else:
            args.append("--json")
        result = runner.invoke(cli, args + opts)
        token_request, page1_request, page2_request = httpx_mock.get_requests()
        assert token_request.content == TOKEN_REQUEST_CONTENT
        assert page1_request.url == (
            "https://www.googleapis.com/drive/v3/files?fields="
            + "nextPageToken%2C+files%28{}%29".format("%2C".join(DEFAULT_FIELDS))
            + extra_qs
        )
        assert page2_request.url == (
            "https://www.googleapis.com/drive/v3/files?fields="
            + "nextPageToken%2C+files%28{}%29".format("%2C".join(DEFAULT_FIELDS))
            + extra_qs
            + "&pageToken=next"
        )
        if use_db:
            results = list(sqlite_utils.Database("test.db")["files"].rows)
        else:
            results = json.loads(result.output)
        assert results == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]


def test_files_basic_stop_after(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        json={"nextPageToken": None, "files": [{"id": 3}, {"id": 4}]},
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        args = ["files", "--json", "--stop-after", "1"]
        result = runner.invoke(cli, args)
        token_request, page1_request = httpx_mock.get_requests()
        assert token_request.content == TOKEN_REQUEST_CONTENT
        assert page1_request.url == (
            "https://www.googleapis.com/drive/v3/files?fields="
            + "nextPageToken%2C+files%28{}%29".format("%2C".join(DEFAULT_FIELDS))
        )
        results = json.loads(result.output)
        assert results == [{"id": 3}]


def test_files_folder(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        json={
            "nextPageToken": None,
            "files": [
                {"id": "doc1", "mimeType": "doc"},
                {"id": "folder2", "mimeType": "application/vnd.google-apps.folder"},
            ],
        }
    )
    httpx_mock.add_response(
        url=re.compile(".*folder2.*"),
        json={
            "nextPageToken": None,
            "files": [
                {"id": "doc2", "mimeType": "doc"},
            ],
        },
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        args = ["files", "--folder", "folder1", "--json"]
        result = runner.invoke(cli, args)
        token_request, folder1_request, folder2_request = httpx_mock.get_requests()
        assert token_request.content == TOKEN_REQUEST_CONTENT
        assert folder1_request.url == (
            "https://www.googleapis.com/drive/v3/files?fields="
            + "nextPageToken%2C+files%28{}%29".format("%2C".join(DEFAULT_FIELDS))
            + "&q=%22folder1%22+in+parents"
        )
        assert folder2_request.url == (
            "https://www.googleapis.com/drive/v3/files?fields="
            + "nextPageToken%2C+files%28{}%29".format("%2C".join(DEFAULT_FIELDS))
            + "&q=%22folder2%22+in+parents"
        )
        results = json.loads(result.output)
        assert results == [
            {"id": "doc1", "mimeType": "doc"},
            {"id": "folder2", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "doc2", "mimeType": "doc"},
        ]


def test_download_two_files(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        content="this is text",
        headers={"content-type": "text/plain"},
    )
    httpx_mock.add_response(
        content="this is gif",
        headers={"content-type": "image/gif"},
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        result = runner.invoke(cli, ["download", "file1", "file2"])
        assert result.exit_code == 0
        # Should be file1.plain and file2.gif
        assert open("file1.plain").read() == "this is text"
        assert open("file2.gif").read() == "this is gif"
    _, file1_request, file2_request = httpx_mock.get_requests()
    assert (
        file1_request.url == "https://www.googleapis.com/drive/v3/files/file1?alt=media"
    )
    assert (
        file2_request.url == "https://www.googleapis.com/drive/v3/files/file2?alt=media"
    )


def test_download_output_two_files_error():
    runner = CliRunner()
    result = runner.invoke(cli, ["download", "file1", "file2", "-o", "out.txt"])
    assert result.exit_code == 1
    assert result.output == "Error: --output option only works with a single file\n"


def test_download_output_stdout(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        content="this is text",
        headers={"content-type": "text/plain"},
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        result = runner.invoke(cli, ["download", "file1", "-o", "-"])
        assert result.exit_code == 0
        assert result.output == "this is text"


def test_download_output_path(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        content="this is text",
        headers={"content-type": "text/plain"},
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        result = runner.invoke(cli, ["download", "file1", "-o", "out.txt"])
        assert result.exit_code == 0
        assert open("out.txt").read() == "this is text"
