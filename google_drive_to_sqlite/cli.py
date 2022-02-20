from os import access
import click
import httpx
import itertools
import json
import pathlib
import sqlite_utils
import sys
import textwrap
import urllib.parse
from .utils import (
    APIClient,
    get_file,
    files_in_folder_recursive,
    paginate_files,
    save_files_and_folders,
)

# https://github.com/simonw/google-drive-to-sqlite/issues/2
GOOGLE_CLIENT_ID = (
    "148933860554-98i3hter1bsn24sa6fcq1tcrhcrujrnl.apps.googleusercontent.com"
)
# It's OK to publish this secret in application source code
GOOGLE_CLIENT_SECRET = "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"
DEFAULT_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

FORMAT_SHORTCUTS = {
    "html": "text/html",
    "txt": "text/plain",
    "rtf": "application/rtf",
    "pdf": "application/pdf",
    "doc": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "zip": "application/zip",
    "epub": "application/epub+zip",
    "xls": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "ppt": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "svg": "image/svg+xml",
}
# .ext defaults to the bit after the / - e.g. "application/pdf" becomes "pdf",
# unless there is an explicit override here:
FILE_EXTENSIONS = {
    "image/svg+xml": "svg",
    "application/epub+zip": "epub",
    "text/plain": "txt",
    "text/tab-separated-values": "tsv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xls",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "ppt",
}


def start_auth_url(google_client_id, scope):
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "access_type": "offline",
            "client_id": google_client_id,
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "response_type": "code",
            "scope": scope,
        }
    )


DEFAULT_FIELDS = [
    "kind",
    "id",
    "name",
    "mimeType",
    "starred",
    "trashed",
    "explicitlyTrashed",
    "parents",
    "spaces",
    "version",
    "webViewLink",
    "iconLink",
    "hasThumbnail",
    "thumbnailVersion",
    "viewedByMe",
    "createdTime",
    "modifiedTime",
    "modifiedByMe",
    "owners",
    "lastModifyingUser",
    "shared",
    "ownedByMe",
    "viewersCanCopyContent",
    "copyRequiresWriterPermission",
    "writersCanShare",
    "folderColorRgb",
    "quotaBytesUsed",
    "isAppAuthorized",
    "linkShareMetadata",
]


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
@click.option("--google-client-id", help="Custom Google client ID")
@click.option("--google-client-secret", help="Custom Google client secret")
@click.option("--scope", help="Custom token scope")
def auth(auth, google_client_id, google_client_secret, scope):
    "Authenticate user and save credentials"
    if google_client_id is None:
        google_client_id = GOOGLE_CLIENT_ID
    if google_client_secret is None:
        google_client_secret = GOOGLE_CLIENT_SECRET
    if scope is None:
        scope = DEFAULT_SCOPE
    click.echo("Visit the following URL to authenticate with Google Drive")
    click.echo("")
    click.echo(start_auth_url(google_client_id, scope))
    click.echo("")
    click.echo("Then return here and paste in the resulting code:")
    copied_code = click.prompt("Paste code here", hide_input=True)
    response = httpx.post(
        "https://www.googleapis.com/oauth2/v4/token",
        data={
            "code": copied_code,
            "client_id": google_client_id,
            "client_secret": google_client_secret,
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
    info = {"refresh_token": tokens["refresh_token"]}
    if google_client_id != GOOGLE_CLIENT_ID:
        info["google_client_id"] = google_client_id
    if google_client_secret != GOOGLE_CLIENT_SECRET:
        info["google_client_secret"] = google_client_secret
    if scope != DEFAULT_SCOPE:
        info["scope"] = scope
    auth_data["google-drive-to-sqlite"] = info
    with open(auth, "w") as fp:
        fp.write(json.dumps(auth_data, indent=4))
    # chmod 600 to avoid other users on the shared machine reading it
    pathlib.Path(auth).chmod(0o600)


@cli.command()
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default="auth.json",
    help="Path to load token, defaults to auth.json",
)
def revoke(auth):
    "Revoke the token stored in auth.json"
    tokens = load_tokens(auth)
    response = httpx.get(
        "https://accounts.google.com/o/oauth2/revoke",
        params={
            "token": tokens["refresh_token"],
        },
    )
    if "error" in response.json():
        raise click.ClickException(response.json()["error"])


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
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Send verbose output to stderr",
)
def get(url, auth, paginate, nl, stop_after, verbose):
    "Make an authenticated HTTP GET to the specified URL"
    if not url.startswith("https://www.googleapis.com/"):
        if url.startswith("/"):
            url = "https://www.googleapis.com" + url
        else:
            raise click.ClickException(
                "url must start with / or https://www.googleapis.com/"
            )

    kwargs = load_tokens(auth)
    if verbose:
        kwargs["logger"] = lambda s: click.echo(s, err=True)
    client = APIClient(**kwargs)

    if not paginate:
        response = client.get(url)
        if verbose:
            click.echo(
                "{}, headers: {}".format(response.status_code, repr(response.headers))
            )
        if response.status_code != 200:
            raise click.ClickException(
                "{}: {}\n\n{}".format(response.url, response.status_code, response.text)
            )
        if "json" in response.headers.get("content-type", ""):
            click.echo(json.dumps(response.json(), indent=4))
        else:
            click.echo(response.text)

    else:

        def paginate_all():
            i = 0
            next_page_token = None
            while True:
                params = {}
                if next_page_token is not None:
                    params["pageToken"] = next_page_token
                response = client.get(
                    url,
                    params=params,
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


@cli.command()
@click.argument(
    "database",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    required=False,
)
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True),
    default="auth.json",
    help="Path to auth.json token file",
)
@click.option("--folder", help="Files in this folder ID and its sub-folders")
@click.option("-q", help="Files matching this query")
@click.option("--full-text", help="Search for files with text match")
@click.option("--starred", is_flag=True, help="Files you have starred")
@click.option("--trashed", is_flag=True, help="Files in the trash")
@click.option(
    "--shared-with-me", is_flag=True, help="Files that have been shared with you"
)
@click.option(
    "--apps",
    is_flag=True,
    help="Google Apps docs, spreadsheets, presentations and drawings",
)
@click.option("--docs", is_flag=True, help="Google Apps docs")
@click.option("--sheets", is_flag=True, help="Google Apps spreadsheets")
@click.option("--presentations", is_flag=True, help="Google Apps presentations")
@click.option("--drawings", is_flag=True, help="Google Apps drawings")
@click.option(
    "json_", "--json", is_flag=True, help="Output JSON rather than write to DB"
)
@click.option(
    "--nl", is_flag=True, help="Output newline-delimited JSON rather than write to DB"
)
@click.option("--stop-after", type=int, help="Stop paginating after X results")
@click.option(
    "--import-json",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True),
    help="Import from this JSON file instead of the API",
)
@click.option(
    "--import-nl",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True),
    help="Import from this newline-delimited JSON file",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Send verbose output to stderr",
)
def files(
    database,
    auth,
    folder,
    q,
    full_text,
    starred,
    trashed,
    shared_with_me,
    apps,
    docs,
    sheets,
    presentations,
    drawings,
    json_,
    nl,
    stop_after,
    import_json,
    import_nl,
    verbose,
):
    """
    Retrieve metadata for files in Google Drive, and write to a SQLite database
    or output as JSON.

        google-drive-to-sqlite files files.db

    Use --json to output JSON, --nl for newline-delimited JSON:

        google-drive-to-sqlite files files.db --json

    Use a folder ID to recursively fetch every file in that folder and its
    sub-folders:

        google-drive-to-sqlite files files.db --folder 1E6Zg2X2bjjtPzVfX8YqdXZDCoB3AVA7i

    Fetch files you have starred:

        google-drive-to-sqlite files starred.db --starred
    """
    if not database and not json_ and not nl:
        raise click.ClickException("Must either provide database or use --json or --nl")
    q_bits = []
    if q:
        q_bits.append(q)
    if full_text:
        q_bits.append("fullText contains '{}'".format(full_text.replace("'", "")))
    if starred:
        q_bits.append("starred = true")
    if trashed:
        q_bits.append("trashed = true")
    if shared_with_me:
        q_bits.append("sharedWithMe = true")

    mime_types = []
    if apps:
        docs = True
        sheets = True
        presentations = True
        drawings = True
    if docs:
        mime_types.append("application/vnd.google-apps.document")
    if sheets:
        mime_types.append("application/vnd.google-apps.spreadsheet")
    if presentations:
        mime_types.append("application/vnd.google-apps.presentation")
    if drawings:
        mime_types.append("application/vnd.google-apps.drawing")
    if mime_types:
        q_bits.append(
            "({})".format(
                " or ".join(
                    "mimeType = '{}'".format(mime_type) for mime_type in mime_types
                )
            )
        )

    q = " and ".join(q_bits)

    if q and verbose:
        click.echo("?q= query: {}".format(q), err=True)

    client = None
    if not (import_json or import_nl):
        kwargs = load_tokens(auth)
        if verbose:
            kwargs["logger"] = lambda s: click.echo(s, err=True)
        client = APIClient(**kwargs)

    if import_json or import_nl:
        if "-" in (import_json, import_nl):
            fp = sys.stdin
        else:
            fp = open(import_json or import_nl)
        if import_json:
            all = json.load(fp)
        else:

            def _nl():
                for line in fp:
                    line = line.strip()
                    if line:
                        yield json.loads(line)

            all = _nl()
    else:
        if folder:
            all_in_folder = files_in_folder_recursive(
                client, folder, fields=DEFAULT_FIELDS
            )
            # Fetch details of that folder first
            folder_details = get_file(client, folder, fields=DEFAULT_FIELDS)

            def folder_details_then_all():
                yield folder_details
                yield from all_in_folder

            all = folder_details_then_all()
        else:
            all = paginate_files(client, q=q, fields=DEFAULT_FIELDS)

    if stop_after:
        prev_all = all

        def stop_after_all():
            i = 0
            for file in prev_all:
                yield file
                i += 1
                if i >= stop_after:
                    break

        all = stop_after_all()

    if nl:
        for file in all:
            click.echo(json.dumps(file))
        return
    if json_:
        for line in stream_indented_json(all):
            click.echo(line)
        return

    db = sqlite_utils.Database(database)
    save_files_and_folders(db, all)


def load_tokens(auth):
    try:
        token_info = json.load(open(auth))["google-drive-to-sqlite"]
    except (KeyError, FileNotFoundError):
        raise click.ClickException("Could not find google-drive-to-sqlite in auth.json")
    return {
        "refresh_token": token_info["refresh_token"],
        "client_id": token_info.get("google_client_id", GOOGLE_CLIENT_ID),
        "client_secret": token_info.get("google_client_secret", GOOGLE_CLIENT_SECRET),
    }


@cli.command()
@click.argument("file_ids", nargs=-1, required=True)
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True),
    default="auth.json",
    help="Path to auth.json token file",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True, writable=True),
    help="File to write to, or - for standard output",
)
@click.option(
    "-s",
    "--silent",
    is_flag=True,
    help="Hide progress bar and filename",
)
def download(file_ids, auth, output, silent):
    """
    Download one or more files to disk, based on their file IDs.

    The file content will be saved to a file with the name:

        FILE_ID.ext

    Where the extension is automatically picked based on the type of file.

    If you are downloading a single file you can specify a filename with -o:

        google-drive-to-sqlite download MY_FILE_ID -o myfile.txt
    """
    if output:
        if len(file_ids) != 1:
            raise click.ClickException("--output option only works with a single file")
    tokens = load_tokens(auth)
    client = APIClient(**tokens)
    for file_id in file_ids:
        with client.stream(
            "GET",
            "https://www.googleapis.com/drive/v3/files/{}?alt=media".format(file_id),
        ) as response:
            streaming_download(response, file_id, output, silent)


@cli.command()
@click.argument("format")
@click.argument("file_ids", nargs=-1, required=True)
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True),
    default="auth.json",
    help="Path to auth.json token file",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True, writable=True),
    help="File to write to, or - for standard output",
)
@click.option(
    "-s",
    "--silent",
    is_flag=True,
    help="Hide progress bar and filename",
)
def export(format, file_ids, auth, output, silent):
    """
    Export one or more files to the specified format.

    Usage:

        google-drive-to-sqlite export pdf FILE_ID_1 FILE_ID_2

    The file content will be saved to a file with the name:

        FILE_ID-export.ext

    Where the extension is based on the format you specified.

    Available export formats can be seen here:
    https://developers.google.com/drive/api/v3/ref-export-formats

    Or you can use one of the following shortcuts:

    \b
    - Google Docs: html, txt, rtf, pdf, doc, zip, epub
    - Google Sheets: xls, pdf, csv, tsv, zip
    - Presentations: ppt, pdf, txt
    - Drawings: jpeg, png, svg

    "zip" returns a zip file of HTML.

    If you are exporting a single file you can specify a filename with -o:

        google-drive-to-sqlite export zip MY_FILE_ID -o myfile.zip
    """
    format = FORMAT_SHORTCUTS.get(format, format)
    if output:
        if len(file_ids) != 1:
            raise click.ClickException("--output option only works with a single file")
    tokens = load_tokens(auth)
    client = APIClient(**tokens)
    for file_id in file_ids:
        with client.stream(
            "GET",
            "https://www.googleapis.com/drive/v3/files/{}/export".format(file_id),
            params={"mimeType": format},
        ) as response:
            filestem = "{}-export".format(file_id)
            streaming_download(response, filestem, output, silent)


def streaming_download(response, filestem, output, silent):
    if response.status_code != 200:
        raise click.ClickException(response.read().decode("utf-8"))
    fp = None
    if output:
        filename = pathlib.Path(output).name
        if output == "-":
            fp = sys.stdout.buffer
            silent = True
        else:
            fp = open(output, "wb")
    else:
        # Use file ID + extension
        ext = response.headers.get("content-type", "/bin")
        if ext in FILE_EXTENSIONS:
            ext = FILE_EXTENSIONS[ext]
        else:
            ext = ext.split("/")[-1]
        filename = "{}.{}".format(filestem, ext)
        fp = open(filename, "wb")
    length = int(response.headers.get("content-length", "0"))
    if not silent:
        click.echo(
            "Writing {}to {}".format(
                "{:,} bytes ".format(length) if length else "", filename
            ),
            err=True,
        )
    if length and not silent:
        with click.progressbar(
            length=int(response.headers["content-length"]), label="Downloading"
        ) as bar:
            for data in response.iter_bytes():
                fp.write(data)
                bar.update(len(data))
    else:
        for data in response.iter_bytes():
            fp.write(data)


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
