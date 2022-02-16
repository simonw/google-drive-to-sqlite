import click
import httpx
import json
import urllib.parse

# https://github.com/simonw/google-drive-to-sqlite/issues/2
GOOGLE_CLIENT_ID = (
    "148933860554-98i3hter1bsn24sa6fcq1tcrhcrujrnl.apps.googleusercontent.com"
)
# It's OK to publish this secret in application source code
GOOGLE_CLIENT_SECRET = "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"

START_AUTH_URL = (
    "https://accounts.google.com/o/oauth2/v2/auth?"
    + urllib.parse.urlencode(
        {
            "access_type": "offline",
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.readonly",
        }
    )
)


@click.group()
@click.version_option()
def cli():
    "Create a SQLite database of metadata from a Google Drive folder"


@cli.command()
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default="auth.json",
    help="Path to save token, defaults to auth.json",
)
def auth(auth):
    "Authenticate user and save credentials"
    click.echo("Visit the following URL to authenticate with Google Drive")
    click.echo("")
    click.echo(START_AUTH_URL)
    click.echo("")
    click.echo("Then return here and paste in the resulting code:")
    copied_code = click.prompt("Paste code here", hide_input=True)
    response = httpx.post(
        "https://www.googleapis.com/oauth2/v4/token",
        data={
            "code": copied_code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "grant_type": "authorization_code",
        },
    )
    tokens = response.json()
    if "error" in tokens:
        message = "{error}: {error_description}".format(**tokens)
        raise click.ClickException(message)
    if "refresh_token" not in tokens:
        raise click.ClickException("No refresh_token in response")
    # Read existing file and add refresh_token to it
    try:
        auth_data = json.load(open(auth))
    except (ValueError, FileNotFoundError):
        auth_data = {}
    auth_data["google-drive-to-sqlite"] = tokens["refresh_token"]
    open(auth, "w").write(json.dumps(auth_data, indent=4))
