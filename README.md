# google-drive-to-sqlite

[![PyPI](https://img.shields.io/pypi/v/google-drive-to-sqlite.svg)](https://pypi.org/project/google-drive-to-sqlite/)
[![Changelog](https://img.shields.io/github/v/release/simonw/google-drive-to-sqlite?include_prereleases&label=changelog)](https://github.com/simonw/google-drive-to-sqlite/releases)
[![Tests](https://github.com/simonw/google-drive-to-sqlite/workflows/Test/badge.svg)](https://github.com/simonw/google-drive-to-sqlite/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/google-drive-to-sqlite/blob/master/LICENSE)

Create a SQLite database containing metadata from [Google Drive](https://www.google.com/drive)

If you use Google Drive, and especially if you have shared drives with other people there's a good chance you have hundreds or even thousands of files that you may not be fully aware of.

This tool can download metadata about those files - their names, sizes, folders, content types, permissions, creation dates and more - and store them in a SQLite database.

This lets you use SQL to analyze your Google Drive contents, using [Datasette](https://datasette.io/) or the SQLite command-line tool or any other SQLite database browsing software.

## Installation

Install this tool using `pip`:

    $ pip install google-drive-to-sqlite

## Authentication

> :warning: **This application has not yet been verified by Google** - you may find you are unable to authenticate until that verification is complete. [#10](https://github.com/simonw/google-drive-to-sqlite/issues/10)

First, authenticate with Google Drive using the `auth` command:

    % google-drive-to-sqlite auth
    Visit the following URL to authenticate with Google Drive

    https://accounts.google.com/o/oauth2/v2/auth?...

    Then return here and paste in the resulting code:
    Paste code here: 

Follow the link, sign in with Google Drive and then copy and paste the resulting code back into the tool.

This will save an authentication token to the file called `auth.json` in the current directory.

To specify a different location for that file, use the `--auth` option:

    google-drive-to-sqlite auth --auth ~/google-drive-auth.json

The `auth` command also provides options for using a different scope, Google client ID and Google client secret. You can use these to create your own custom authentication tokens that can work with other Google APIs, see [issue #5](https://github.com/simonw/google-drive-to-sqlite/issues/5) for details.

Full `--help`:

<!-- [[[cog
import cog
from google_drive_to_sqlite import cli
from click.testing import CliRunner
runner = CliRunner()
result = runner.invoke(cli.cli, ["auth", "--help"])
help = result.output.replace("Usage: cli", "Usage: google-drive-to-sqlite")
cog.out(
    "```\n{}\n```\n".format(help)
)
]]] -->
```
Usage: google-drive-to-sqlite auth [OPTIONS]

  Authenticate user and save credentials

Options:
  -a, --auth FILE              Path to save token, defaults to auth.json
  --google-client-id TEXT      Custom Google client ID
  --google-client-secret TEXT  Custom Google client secret
  --scope TEXT                 Custom token scope
  --help                       Show this message and exit.

```
<!-- [[[end]]] -->

## google-drive-to-sqlite files

To retrieve metadata about the files in your Google Drive, or a folder or search within it, use the `google-drive-to-sqlite files` command.

This will default to writing details about every file in your Google Drive to a SQLite database:

    google-drive-to-sqlite files files.db

Files will be written to a `files` table, which will be created if it does not yet exist.

If a file already exists in that table, based on a matching `id`, it will be replaced with fresh data.

Instead of writing to SQLite you can use `--json` to output as JSON, or `--nl` to output as newline-delimited JSON:

    google-drive-to-sqlite files --nl

Use `--folder ID` to retrieve everything in a specified folder and its sub-folders:

    google-drive-to-sqlite files files.db --folder 1E6Zg2X2bjjtPzVfX8YqdXZDCoB3AVA7i

Use `--q QUERY` to use a [custom search query](https://developers.google.com/drive/api/v3/reference/query-ref):

    google-drive-to-sqlite files files.db -q 'starred = true'

Use `--full-text TEXT` to search for files where the full text matches a search term:

    google-drive-to-sqlite files files.db --full-text 'datasette'

Use `--stop-after X` to stop after retrieving X files.

Full `--help`:

<!-- [[[cog
result = runner.invoke(cli.cli, ["files", "--help"])
help = result.output.replace("Usage: cli", "Usage: google-drive-to-sqlite")
cog.out(
    "```\n{}\n```\n".format(help)
)
]]] -->
```
Usage: google-drive-to-sqlite files [OPTIONS] [DATABASE]

  Retrieve metadata for files in Google Drive, and write to a SQLite database or
  output as JSON.

      google-drive-to-sqlite files files.db

  Use --json to output JSON, --nl for newline-delimited JSON:

      google-drive-to-sqlite files files.db --json

  Use a folder ID to recursively fetch every file in that folder and its sub-
  folders:

      google-drive-to-sqlite files files.db --folder
      1E6Zg2X2bjjtPzVfX8YqdXZDCoB3AVA7i

Options:
  -a, --auth FILE       Path to auth.json token file
  --folder TEXT         Files in this folder ID and its sub-folders
  -q TEXT               Files matching this query
  --full-text TEXT      Search for files with text match
  --json                Output JSON rather than write to DB
  --nl                  Output newline-delimited JSON rather than write to DB
  --stop-after INTEGER  Stop paginating after X results
  --help                Show this message and exit.

```
<!-- [[[end]]] -->

## google-drive-to-sqlite download FILE_ID

The `download` command can be used to download files from Google Drive.

You'll need one or more file IDs, which look something like `0B32uDVNZfiEKLUtIT1gzYWN2NDI4SzVQYTFWWWxCWUtvVGNB`.

To download the file, run this:

    google-drive-to-sqlite download 0B32uDVNZfiEKLUtIT1gzYWN2NDI4SzVQYTFWWWxCWUtvVGNB

This will detect the content type of the file and use that as the extension - so if this file is a JPEG the file would be downloaded as:

    0B32uDVNZfiEKLUtIT1gzYWN2NDI4SzVQYTFWWWxCWUtvVGNB.jpeg

You can pass multiple file IDs to the command at once.

To hide the progress bar and filename output, use `-s` or `--silent`.

If you are downloading a single file you can use the `-o` output to specify a filename and location:

    google-drive-to-sqlite download 0B32uDVNZfiEKLUtIT1gzYWN2NDI4SzVQYTFWWWxCWUtvVGNB \
      -o my-image.jpeg

Use `-o -` to write the file contents to standard output:

    google-drive-to-sqlite download 0B32uDVNZfiEKLUtIT1gzYWN2NDI4SzVQYTFWWWxCWUtvVGNB \
      -o - > my-image.jpeg

Full `--help`:

<!-- [[[cog
result = runner.invoke(cli.cli, ["download", "--help"])
help = result.output.replace("Usage: cli", "Usage: google-drive-to-sqlite")
cog.out(
    "```\n{}\n```\n".format(help)
)
]]] -->
```
Usage: google-drive-to-sqlite download [OPTIONS] FILE_IDS...

  Download one or more file IDs to disk

Options:
  -a, --auth FILE    Path to auth.json token file
  -o, --output FILE  File to write to, or - for standard output
  -s, --silent       Hide progress bar and filename
  --help             Show this message and exit.

```
<!-- [[[end]]] -->

## google-drive-to-sqlite get URL

The `get` command makes authenticated requests to the specified URL, using credentials derived from the `auth.json` file.

For example:

    % google-drive-to-sqlite get 'https://www.googleapis.com/drive/v3/about?fields=*'
    {
        "kind": "drive#about",
        "user": {
            "kind": "drive#user",
            "displayName": "Simon Willison",
    # ...

If the resource you are fetching supports pagination you can use `--paginate key` to paginate through all of the rows in a specified key. For example, the following API has a `nextPageToken` key and a `files` list, suggesting it supports pagination:

    % google-drive-to-sqlite get https://www.googleapis.com/drive/v3/files
    {
        "kind": "drive#fileList",
        "nextPageToken": "~!!~AI9...wogHHYlc=",
        "incompleteSearch": false,
        "files": [
            {
                "kind": "drive#file",
                "id": "1YEsITp_X8PtDUJWHGM0osT-TXAU1nr0e7RSWRM2Jpyg",
                "name": "Title of a spreadsheet",
                "mimeType": "application/vnd.google-apps.spreadsheet"
            },

To paginate through everything in the `files` list you would use `--paginate files` lyike this:

    % google-drive-to-sqlite get https://www.googleapis.com/drive/v3/files --paginate files
    [
      {
        "kind": "drive#file",
        "id": "1YEsITp_X8PtDUJWHGM0osT-TXAU1nr0e7RSWRM2Jpyg",
        "name": "Title of a spreadsheet",
        "mimeType": "application/vnd.google-apps.spreadsheet"
      },
      # ...

Add `--nl` to stream paginated data as newline-delimited JSON:

    % google-drive-to-sqlite get https://www.googleapis.com/drive/v3/files --paginate files --nl
    {"kind": "drive#file", "id": "1YEsITp_X8PtDUJWHGM0osT-TXAU1nr0e7RSWRM2Jpyg", "name": "Title of a spreadsheet", "mimeType": "application/vnd.google-apps.spreadsheet"}
    {"kind": "drive#file", "id": "1E6Zg2X2bjjtPzVfX8YqdXZDCoB3AVA7i", "name": "Subfolder", "mimeType": "application/vnd.google-apps.folder"}

Add `--stop-after 5` to stop after 5 records - useful for testing.

Full `--help`:

<!-- [[[cog
result = runner.invoke(cli.cli, ["get", "--help"])
help = result.output.replace("Usage: cli", "Usage: google-drive-to-sqlite")
cog.out(
    "```\n{}\n```\n".format(help)
)
]]] -->
```
Usage: google-drive-to-sqlite get [OPTIONS] URL

  Make an authenticated HTTP GET to the specified URL

Options:
  -a, --auth FILE       Path to auth.json token file
  --paginate TEXT       Paginate through all results in this key
  --nl                  Output paginated data as newline-delimited JSON
  --stop-after INTEGER  Stop paginating after X results
  --help                Show this message and exit.

```
<!-- [[[end]]] -->

## Privacy policy

This tool requests access to your Google Drive account in order to retrieve metadata about your files there. It also offers a feature that can download the content of those files.

The credentials used to access your account are stored in the auth.json file on your computer. The metadata and content retrieved from Google Drive is also stored only on your own personal computer.

At no point to the developers of this tool gain access to any of your data.

## Development

To contribute to this tool, first checkout the code. Then create a new virtual environment:

    cd google-drive-to-sqlite
    python -m venv venv
    source venv/bin/activate

Or if you are using `pipenv`:

    pipenv shell

Now install the dependencies and test dependencies:

    pip install -e '.[test]'

To run the tests:

    pytest
