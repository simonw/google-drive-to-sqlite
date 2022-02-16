# google-drive-to-sqlite

[![PyPI](https://img.shields.io/pypi/v/google-drive-to-sqlite.svg)](https://pypi.org/project/google-drive-to-sqlite/)
[![Changelog](https://img.shields.io/github/v/release/simonw/google-drive-to-sqlite?include_prereleases&label=changelog)](https://github.com/simonw/google-drive-to-sqlite/releases)
[![Tests](https://github.com/simonw/google-drive-to-sqlite/workflows/Test/badge.svg)](https://github.com/simonw/google-drive-to-sqlite/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/simonw/google-drive-to-sqlite/blob/master/LICENSE)

Create a SQLite database containing metadata from Google Drive

## Installation

Install this tool using `pip`:

    $ pip install google-drive-to-sqlite

## Authentication

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
