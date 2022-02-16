from os import access
import click
import httpx
import itertools
import json
import textwrap
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


@cli.command()
@click.argument("url")
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True),
    default="auth.json",
    help="Path to auth.json token file",
)
@click.option("--paginate", help="Paginate through all results in this key")
@click.option(
    "--nl", is_flag=True, help="Output paginated data as newline-delimited JSON"
)
@click.option("--stop-after", type=int, help="Stop paginating after X results")
def get(url, auth, paginate, nl, stop_after):
    "Make an authenticated HTTP GET to the specified URL"
    if not url.startswith("https://www.googleapis.com/"):
        if url.startswith("/"):
            url = "https://www.googleapis.com" + url
        else:
            raise click.ClickException(
                "url must start with / or https://www.googleapis.com/"
            )
    access_token = load_token(auth)

    if not paginate:
        response = httpx.get(
            url,
            headers={"Authorization": "Bearer {}".format(access_token)},
        )
        data = response.json()
        if response.status_code != 200:
            raise click.ClickException(json.dumps(data, indent=4))
        click.echo(json.dumps(data, indent=4))

    else:

        def paginate_all():
            i = 0
            next_page_token = None
            while True:
                params = {}
                if next_page_token is not None:
                    params["pageToken"] = next_page_token
                response = httpx.get(
                    url,
                    params=params,
                    headers={"Authorization": "Bearer {}".format(access_token)},
                )
                data = response.json()
                if response.status_code != 200:
                    raise click.ClickException(json.dumps(data, indent=4))
                # Paginate using the specified key and nextPageToken
                if paginate not in data:
                    raise click.ClickException(
                        "paginate key {} not found in {}".format(
                            repr(paginate), repr(list(data.keys()))
                        )
                    )
                for item in data[paginate]:
                    yield item
                    i += 1
                    if stop_after is not None and i >= stop_after:
                        return

                next_page_token = data.get("nextPageToken")
                if not next_page_token:
                    break

        if nl:
            for item in paginate_all():
                click.echo(json.dumps(item))
        else:
            for line in stream_indented_json(paginate_all()):
                click.echo(line)


def load_token(auth):
    try:
        refresh_token = json.load(open(auth))["google-drive-to-sqlite"]
    except (KeyError, FileNotFoundError):
        raise click.ClickException("Could not find google-drive-to-sqlite in auth.json")
    # Exchange refresh_token for access_token
    data = httpx.post(
        "https://www.googleapis.com/oauth2/v4/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
        },
    ).json()
    if "error" in data:
        raise click.ClickException(str(data))
    return data["access_token"]


def stream_indented_json(iterator, indent=2):
    # We have to iterate two-at-a-time so we can know if we
    # should output a trailing comma or if we have reached
    # the last item.
    current_iter, next_iter = itertools.tee(iterator, 2)
    next(next_iter, None)
    first = True
    for item, next_item in itertools.zip_longest(current_iter, next_iter):
        is_last = next_item is None
        data = item
        line = "{first}{serialized}{separator}{last}".format(
            first="[\n" if first else "",
            serialized=textwrap.indent(
                json.dumps(data, indent=indent, default=repr), " " * indent
            ),
            separator="," if not is_last else "",
            last="\n]" if is_last else "",
        )
        yield line
        first = False
    if first:
        # We didn't output anything, so yield the empty list
        yield "[]"
