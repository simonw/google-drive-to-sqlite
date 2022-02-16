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
