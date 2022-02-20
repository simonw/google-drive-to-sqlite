from click.testing import CliRunner
from google_drive_to_sqlite.cli import cli, DEFAULT_FIELDS
import httpx
import json
import pathlib
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
FOLDER_AND_CHILDREN_JSON_PATH = (
    pathlib.Path(__file__).parent / "folder-and-children.json"
)


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
    "auth_file_exists,revoke_response,expected_error",
    (
        (False, None, "Error: Could not find google-drive-to-sqlite in auth.json"),
        (True, {}, None),
        (True, {"error": "invalid_token"}, "Error: invalid_token"),
    ),
)
def test_revoke(httpx_mock, auth_file_exists, revoke_response, expected_error):
    runner = CliRunner()
    with runner.isolated_filesystem():
        if auth_file_exists:
            open("auth.json", "w").write(json.dumps(AUTH_JSON))
            httpx_mock.add_response(json=revoke_response)
        result = runner.invoke(cli, ["revoke"])
        if auth_file_exists:
            request = httpx_mock.get_request()
            assert (
                request.url
                == "https://accounts.google.com/o/oauth2/revoke?token=rtoken"
            )
        if expected_error:
            assert result.exit_code == 1
            assert result.output.strip().endswith(expected_error)
        else:
            assert result.exit_code == 0


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
            '[\n  {\n    "id": 1\n  },\n  {\n    "id": 2\n  },\n  '
            '{\n    "id": 3\n  },\n  {\n    "id": 4\n  }\n]\n',
        ),
        (
            ["--nl"],
            '{"id": 1}\n{"id": 2}\n{"id": 3}\n{"id": 4}\n',
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
        (["--starred"], "&q=starred+%3D+true"),
        (["--trashed"], "&q=trashed+%3D+true"),
        (["--shared-with-me"], "&q=sharedWithMe+%3D+true"),
        (
            ["--starred", "--trashed", "--shared-with-me"],
            "&q=starred+%3D+true+and+trashed+%3D+true+and+sharedWithMe+%3D+true",
        ),
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
        result = runner.invoke(cli, args + opts, catch_exceptions=False)
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
            rows = list(sqlite_utils.Database("test.db")["drive_files"].rows)
            assert rows == [
                {"id": "1", "_parent": None, "lastModifyingUser": None},
                {"id": "2", "_parent": None, "lastModifyingUser": None},
                {"id": "3", "_parent": None, "lastModifyingUser": None},
                {"id": "4", "_parent": None, "lastModifyingUser": None},
            ]
        else:
            results = json.loads(result.output)
            assert results == [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]


@pytest.mark.parametrize("verbosity_arg", ("-v", "--verbose"))
def test_files_basic_stop_after_also_test_verbose(httpx_mock, verbosity_arg):
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        json={"nextPageToken": None, "files": [{"id": 3}, {"id": 4}]},
    )
    runner = CliRunner(mix_stderr=False)
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        args = ["files", "--json", "--stop-after", "1", verbosity_arg]
        result = runner.invoke(cli, args)
        assert result.stderr == (
            "POST https://www.googleapis.com/oauth2/v4/token\n"
            "GET: https://www.googleapis.com/drive/v3/files "
            "{'fields': 'nextPageToken, files(kind,id,name,mimeType,starred,trashed,"
            "explicitlyTrashed,parents,spaces,version,webViewLink,iconLink,hasThumbnail,"
            "thumbnailVersion,viewedByMe,createdTime,modifiedTime,modifiedByMe,owners,"
            "lastModifyingUser,shared,ownedByMe,viewersCanCopyContent,"
            "copyRequiresWriterPermission,writersCanShare,folderColorRgb,quotaBytesUsed,"
            "isAppAuthorized,linkShareMetadata)'}\n"
        )
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
        json={"id": "folder1", "mimeType": "application/vnd.google-apps.folder"},
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
        (
            token_request,
            folder_details_request,
            folder1_request,
            folder2_request,
        ) = httpx_mock.get_requests()
        assert token_request.content == TOKEN_REQUEST_CONTENT
        assert folder_details_request.url == (
            "https://www.googleapis.com/drive/v3/files/folder1?fields="
            + "%2C".join(DEFAULT_FIELDS)
        )
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
            {"id": "folder1", "mimeType": "application/vnd.google-apps.folder"},
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


def test_export_two_files(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        content="this is pdf",
        headers={"content-type": "application/pdf"},
    )
    httpx_mock.add_response(
        content="this is also pdf",
        headers={"content-type": "application/pdf"},
    )
    runner = CliRunner()
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        result = runner.invoke(cli, ["export", "pdf", "file1", "file2"])
        assert result.exit_code == 0
        assert open("file1-export.pdf").read() == "this is pdf"
        assert open("file2-export.pdf").read() == "this is also pdf"
    _, file1_request, file2_request = httpx_mock.get_requests()
    assert (
        file1_request.url
        == "https://www.googleapis.com/drive/v3/files/file1/export?mimeType=application%2Fpdf"
    )
    assert (
        file2_request.url
        == "https://www.googleapis.com/drive/v3/files/file2/export?mimeType=application%2Fpdf"
    )


def test_refresh_access_token_once_if_it_expires(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken"},
    )
    httpx_mock.add_response(
        url="https://www.googleapis.com/drive/v3/about?fields=*",
        json={
            "error": {
                "errors": [
                    {
                        "domain": "global",
                        "reason": "authError",
                        "message": "Invalid Credentials",
                        "locationType": "header",
                        "location": "Authorization",
                    }
                ],
                "code": 401,
                "message": "Invalid Credentials",
            }
        },
        status_code=401,
    )
    httpx_mock.add_response(
        method="POST",
        json={"access_token": "atoken2"},
    )
    about_data = {
        "kind": "drive#about",
        "user": {"kind": "drive#user", "displayName": "User"},
    }
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
        assert result.exit_code == 0

    assert json.loads(result.output) == about_data

    token1, about_denied, token2, about_success = httpx_mock.get_requests()
    for request in (token1, token2):
        assert request.method == "POST"
        assert request.url == "https://www.googleapis.com/oauth2/v4/token"
    for request2 in (about_denied, about_success):
        assert request2.method == "GET"
        assert request2.url == "https://www.googleapis.com/drive/v3/about?fields=*"
    assert about_denied.headers["Authorization"] == "Bearer atoken"
    assert about_success.headers["Authorization"] == "Bearer atoken2"


@pytest.mark.parametrize(
    "opt,input",
    (
        ("--import-json", '[{"id": "one"}, {"id": "two"}]'),
        ("--import-nl", '{"id": "one"}\n{"id": "two"}'),
    ),
)
def test_files_input(httpx_mock, opt, input):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["files", "test.db", opt, "-"], input=input)
        assert len(httpx_mock.get_requests()) == 0
        assert result.exit_code == 0
        db = sqlite_utils.Database("test.db")
        assert set(db.table_names()) == {
            "drive_folders",
            "drive_files",
            "drive_users",
            "drive_folders_owners",
            "drive_files_owners",
        }
        rows = list(db["drive_files"].rows)
        assert rows == [
            {"id": "one", "_parent": None, "lastModifyingUser": None},
            {"id": "two", "_parent": None, "lastModifyingUser": None},
        ]


def test_files_input_real_example(httpx_mock):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli, ["files", "test.db", "--import-json", FOLDER_AND_CHILDREN_JSON_PATH]
        )
        assert len(httpx_mock.get_requests()) == 0
        assert result.exit_code == 0
        db = sqlite_utils.Database("test.db")
        assert set(db.table_names()) == {
            "drive_folders",
            "drive_files",
            "drive_users",
            "drive_files_owners",
            "drive_folders_owners",
        }
        schema = db.schema
        assert (
            schema
            == "CREATE TABLE [drive_users] (\n   [permissionId] TEXT PRIMARY KEY\n,"
            " [kind] TEXT, [displayName] TEXT, [photoLink] TEXT, [me] INTEGER,"
            " [emailAddress] TEXT);\nCREATE TABLE [drive_folders] (\n   [id] TEXT"
            " PRIMARY KEY,\n   [_parent] TEXT,\n   [lastModifyingUser] TEXT, [kind]"
            " TEXT, [name] TEXT, [mimeType] TEXT, [starred] INTEGER, [trashed]"
            " INTEGER, [explicitlyTrashed] INTEGER, [parents] TEXT, [spaces] TEXT,"
            " [version] TEXT, [webViewLink] TEXT, [iconLink] TEXT, [hasThumbnail]"
            " INTEGER, [thumbnailVersion] TEXT, [viewedByMe] INTEGER, [createdTime]"
            " TEXT, [modifiedTime] TEXT, [modifiedByMe] INTEGER, [shared] INTEGER,"
            " [ownedByMe] INTEGER, [viewersCanCopyContent] INTEGER,"
            " [copyRequiresWriterPermission] INTEGER, [writersCanShare] INTEGER,"
            " [folderColorRgb] TEXT, [quotaBytesUsed] TEXT, [isAppAuthorized]"
            " INTEGER, [linkShareMetadata] TEXT,\n   FOREIGN KEY([_parent])"
            " REFERENCES [drive_folders]([id]),\n   FOREIGN KEY([lastModifyingUser])"
            " REFERENCES [drive_users]([permissionId])\n);\nCREATE TABLE"
            " [drive_folders_owners] (\n   [item_id] TEXT REFERENCES"
            " [drive_folders]([id]),\n   [user_id] TEXT REFERENCES"
            " [drive_users]([permissionId]),\n   PRIMARY KEY ([item_id],"
            " [user_id])\n);\nCREATE TABLE [drive_files] (\n   [id] TEXT PRIMARY"
            " KEY,\n   [_parent] TEXT,\n   [lastModifyingUser] TEXT, [kind] TEXT,"
            " [name] TEXT, [mimeType] TEXT, [starred] INTEGER, [trashed] INTEGER,"
            " [explicitlyTrashed] INTEGER, [parents] TEXT, [spaces] TEXT, [version]"
            " TEXT, [webViewLink] TEXT, [iconLink] TEXT, [hasThumbnail] INTEGER,"
            " [thumbnailVersion] TEXT, [viewedByMe] INTEGER, [createdTime] TEXT,"
            " [modifiedTime] TEXT, [modifiedByMe] INTEGER, [shared] INTEGER,"
            " [ownedByMe] INTEGER, [viewersCanCopyContent] INTEGER,"
            " [copyRequiresWriterPermission] INTEGER, [writersCanShare] INTEGER,"
            " [quotaBytesUsed] TEXT, [isAppAuthorized] INTEGER, [linkShareMetadata]"
            " TEXT,\n   FOREIGN KEY([_parent]) REFERENCES [drive_folders]([id]),\n  "
            " FOREIGN KEY([lastModifyingUser]) REFERENCES"
            " [drive_users]([permissionId])\n);\nCREATE TABLE [drive_files_owners]"
            " (\n   [item_id] TEXT REFERENCES [drive_files]([id]),\n   [user_id]"
            " TEXT REFERENCES [drive_users]([permissionId]),\n   PRIMARY KEY"
            " ([item_id], [user_id])\n);"
        )
        files_rows = list(db["drive_files"].rows)
        folders_rows = list(db["drive_folders"].rows)
        users_rows = list(db["drive_users"].rows)
        drive_folders_owners_rows = list(db["drive_folders_owners"].rows)
        drive_files_owners_rows = list(db["drive_files_owners"].rows)
        assert files_rows == [
            {
                "id": "1Xdqfeoi8B8YJJR0y-_oQlHYpjHHzD5a-",
                "_parent": "113Wb_KLL1dtgx3vpeRfSTOYIUDf3QnnN",
                "lastModifyingUser": "16974643384157631322",
                "kind": "drive#file",
                "name": "sample.csv",
                "mimeType": "text/csv",
                "starred": 0,
                "trashed": 0,
                "explicitlyTrashed": 0,
                "parents": '["113Wb_KLL1dtgx3vpeRfSTOYIUDf3QnnN"]',
                "spaces": '["drive"]',
                "version": "2",
                "webViewLink": "https://drive.google.com/file/d/1Xdqfeoi8B8YJJR0y-_oQlHYpjHHzD5a-/view?usp=drivesdk",
                "iconLink": (
                    "https://drive-thirdparty.googleusercontent.com/16/type/text/csv"
                ),
                "hasThumbnail": 0,
                "thumbnailVersion": "0",
                "viewedByMe": 1,
                "createdTime": "2022-02-19T04:25:16.517Z",
                "modifiedTime": "2020-11-11T18:10:31.000Z",
                "modifiedByMe": 1,
                "shared": 0,
                "ownedByMe": 1,
                "viewersCanCopyContent": 1,
                "copyRequiresWriterPermission": 0,
                "writersCanShare": 1,
                "quotaBytesUsed": "1070506",
                "isAppAuthorized": 0,
                "linkShareMetadata": (
                    '{"securityUpdateEligible": false, "securityUpdateEnabled": true}'
                ),
            }
        ]
        assert folders_rows == [
            {
                "id": "1dbccBzomcvEUGdnoj8-9QG1yHxS0R-_j",
                "_parent": "0AK1CICIR8ECDUk9PVA",
                "lastModifyingUser": "16974643384157631322",
                "kind": "drive#file",
                "name": "test-folder",
                "mimeType": "application/vnd.google-apps.folder",
                "starred": 0,
                "trashed": 0,
                "explicitlyTrashed": 0,
                "parents": '["0AK1CICIR8ECDUk9PVA"]',
                "spaces": '["drive"]',
                "version": "4",
                "webViewLink": "https://drive.google.com/drive/folders/1dbccBzomcvEUGdnoj8-9QG1yHxS0R-_j",
                "iconLink": "https://drive-thirdparty.googleusercontent.com/16/type/application/vnd.google-apps.folder",
                "hasThumbnail": 0,
                "thumbnailVersion": "0",
                "viewedByMe": 1,
                "createdTime": "2022-02-19T04:22:24.589Z",
                "modifiedTime": "2022-02-19T04:22:24.589Z",
                "modifiedByMe": 1,
                "shared": 0,
                "ownedByMe": 1,
                "viewersCanCopyContent": 1,
                "copyRequiresWriterPermission": 0,
                "writersCanShare": 1,
                "folderColorRgb": "#8f8f8f",
                "quotaBytesUsed": "0",
                "isAppAuthorized": 0,
                "linkShareMetadata": (
                    '{"securityUpdateEligible": false, "securityUpdateEnabled": true}'
                ),
            },
            {
                "id": "1FYLDMMXi1-gGjxg8dLmvbiixDuR8-FZ3",
                "_parent": "1dbccBzomcvEUGdnoj8-9QG1yHxS0R-_j",
                "lastModifyingUser": "16974643384157631322",
                "kind": "drive#file",
                "name": "two",
                "mimeType": "application/vnd.google-apps.folder",
                "starred": 0,
                "trashed": 0,
                "explicitlyTrashed": 0,
                "parents": '["1dbccBzomcvEUGdnoj8-9QG1yHxS0R-_j"]',
                "spaces": '["drive"]',
                "version": "1",
                "webViewLink": "https://drive.google.com/drive/folders/1FYLDMMXi1-gGjxg8dLmvbiixDuR8-FZ3",
                "iconLink": "https://drive-thirdparty.googleusercontent.com/16/type/application/vnd.google-apps.folder",
                "hasThumbnail": 0,
                "thumbnailVersion": "0",
                "viewedByMe": 1,
                "createdTime": "2022-02-19T04:22:38.714Z",
                "modifiedTime": "2022-02-19T04:22:38.714Z",
                "modifiedByMe": 1,
                "shared": 0,
                "ownedByMe": 1,
                "viewersCanCopyContent": 1,
                "copyRequiresWriterPermission": 0,
                "writersCanShare": 1,
                "folderColorRgb": "#8f8f8f",
                "quotaBytesUsed": "0",
                "isAppAuthorized": 0,
                "linkShareMetadata": (
                    '{"securityUpdateEligible": false, "securityUpdateEnabled": true}'
                ),
            },
            {
                "id": "113Wb_KLL1dtgx3vpeRfSTOYIUDf3QnnN",
                "_parent": "1dbccBzomcvEUGdnoj8-9QG1yHxS0R-_j",
                "lastModifyingUser": "16974643384157631322",
                "kind": "drive#file",
                "name": "one",
                "mimeType": "application/vnd.google-apps.folder",
                "starred": 0,
                "trashed": 0,
                "explicitlyTrashed": 0,
                "parents": '["1dbccBzomcvEUGdnoj8-9QG1yHxS0R-_j"]',
                "spaces": '["drive"]',
                "version": "2",
                "webViewLink": "https://drive.google.com/drive/folders/113Wb_KLL1dtgx3vpeRfSTOYIUDf3QnnN",
                "iconLink": "https://drive-thirdparty.googleusercontent.com/16/type/application/vnd.google-apps.folder",
                "hasThumbnail": 0,
                "thumbnailVersion": "0",
                "viewedByMe": 1,
                "createdTime": "2022-02-19T04:22:33.581Z",
                "modifiedTime": "2022-02-19T04:22:33.581Z",
                "modifiedByMe": 1,
                "shared": 0,
                "ownedByMe": 1,
                "viewersCanCopyContent": 1,
                "copyRequiresWriterPermission": 0,
                "writersCanShare": 1,
                "folderColorRgb": "#8f8f8f",
                "quotaBytesUsed": "0",
                "isAppAuthorized": 0,
                "linkShareMetadata": (
                    '{"securityUpdateEligible": false, "securityUpdateEnabled": true}'
                ),
            },
        ]
        assert users_rows == [
            {
                "permissionId": "16974643384157631322",
                "kind": "drive#user",
                "displayName": "Simon Willison",
                "photoLink": "https://lh3.googleusercontent.com/a-/AOh14Gg9Loyxove5ocfBp0mg0u2afcTpM1no8QJnwbWnxw=s64",
                "me": 1,
                "emailAddress": "...@gmail.com",
            }
        ]
        assert drive_folders_owners_rows == [
            {
                "item_id": "1dbccBzomcvEUGdnoj8-9QG1yHxS0R-_j",
                "user_id": "16974643384157631322",
            },
            {
                "item_id": "1FYLDMMXi1-gGjxg8dLmvbiixDuR8-FZ3",
                "user_id": "16974643384157631322",
            },
            {
                "item_id": "113Wb_KLL1dtgx3vpeRfSTOYIUDf3QnnN",
                "user_id": "16974643384157631322",
            },
        ]
        assert drive_files_owners_rows == [
            {
                "item_id": "1Xdqfeoi8B8YJJR0y-_oQlHYpjHHzD5a-",
                "user_id": "16974643384157631322",
            }
        ]


@pytest.mark.parametrize(
    "exception", (httpx.TransportError, httpx.RemoteProtocolError, httpx.ConnectError)
)
@pytest.mark.parametrize(
    "num_exceptions,should_succeed",
    (
        (3, False),
        (2, True),
        (1, True),
        (0, True),
    ),
)
def test_files_retry_on_transport_error(
    httpx_mock, mocker, num_exceptions, should_succeed, exception
):
    mocker.patch("google_drive_to_sqlite.utils.sleep")
    about_data = {
        "kind": "drive#about",
        "user": {"kind": "drive#user", "displayName": "User"},
    }
    httpx_mock.add_response(
        url="https://www.googleapis.com/oauth2/v4/token",
        method="POST",
        json={"access_token": "atoken"},
    )
    for _ in range(min(num_exceptions, 3)):
        httpx_mock.add_exception(exception("Error"))

    if should_succeed:
        httpx_mock.add_response(
            url="https://www.googleapis.com/drive/v3/about?fields=*",
            method="GET",
            json=about_data,
        )

    runner = CliRunner(mix_stderr=False)
    with runner.isolated_filesystem():
        open("auth.json", "w").write(json.dumps(AUTH_JSON))
        result = runner.invoke(
            cli, ["get", "https://www.googleapis.com/drive/v3/about?fields=*", "-v"]
        )
        if should_succeed:
            assert result.exit_code == 0
        else:
            assert result.exit_code == 1
        requests = httpx_mock.get_requests()
        num_expected = num_exceptions + 1
        if should_succeed:
            num_expected += 1
        assert len(requests) == num_expected

    # Test log output for num_exceptions = 2
    if num_exceptions == 2:
        assert result.stderr == (
            "POST https://www.googleapis.com/oauth2/v4/token\n"
            "GET: https://www.googleapis.com/drive/v3/about?fields=*\n"
            + "  Got {}, retrying\n".format(exception.__name__)
            + "GET: https://www.googleapis.com/drive/v3/about?fields=*\n"
            + "  Got {}, retrying\n".format(exception.__name__)
            + "GET: https://www.googleapis.com/drive/v3/about?fields=*\n"
        )
