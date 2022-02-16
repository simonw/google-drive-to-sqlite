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
