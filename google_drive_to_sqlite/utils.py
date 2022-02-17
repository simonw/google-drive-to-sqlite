from contextlib import contextmanager
import click
import httpx


class FilesError(Exception):
    pass


def paginate_files(client, *, corpora=None, q=None, fields=None):
    pageToken = None
    files_url = "https://www.googleapis.com/drive/v3/files"
    params = {}
    if corpora is not None:
        params["corpora"] = corpora
    if fields is not None:
        params["fields"] = "nextPageToken, files({})".format(",".join(fields))
    if q is not None:
        params["q"] = q
    while True:
        if pageToken is not None:
            params["pageToken"] = pageToken
        else:
            params.pop("pageToken", None)
        data = client.get(
            files_url,
            params=params,
        ).json()
        if "error" in data:
            raise FilesError(data)
        yield from data["files"]
        pageToken = data.get("nextPageToken", None)
        if pageToken is None:
            break


def files_in_folder_recursive(client, folder_id, fields):
    for file in paginate_files(
        client, q='"{}" in parents'.format(folder_id), fields=fields
    ):
        yield file
        if file["mimeType"] == "application/vnd.google-apps.folder":
            yield from files_in_folder_recursive(client, file["id"], fields)


class APIClient:
    class Error(click.ClickException):
        pass

    timeout = 30.0

    def __init__(self, refresh_token, client_id, client_secret):
        self.refresh_token = refresh_token
        self.access_token = None
        self.client_id = client_id
        self.client_secret = client_secret

    def get_access_token(self, force_refresh=False):
        if self.access_token and not force_refresh:
            return self.access_token
        data = httpx.post(
            "https://www.googleapis.com/oauth2/v4/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        ).json()
        if "error" in data:
            raise self.Error(str(data))
        self.access_token = data["access_token"]
        return self.access_token

    def get(self, url, params=None, headers=None, allow_retry=True):
        headers = headers or {}
        headers["Authorization"] = "Bearer {}".format(self.get_access_token())
        response = httpx.get(url, params=params, headers=headers, timeout=self.timeout)
        if response.status_code == 401 and allow_retry:
            # Try again after refreshing the token
            self.get_access_token(force_refresh=True)
            return self.get(url, params, headers, allow_retry=False)
        return response

    def post(self, url, data=None, headers=None, allow_retry=True):
        headers = headers or {}
        headers["Authorization"] = "Bearer {}".format(self.get_access_token())
        response = httpx.post(url, data=data, headers=headers, timeout=self.timeout)
        if response.status_code == 403 and allow_retry:
            self.get_access_token(force_refresh=True)
            return self.post(url, data, headers, allow_retry=False)
        return response

    @contextmanager
    def stream(self, method, url):
        with httpx.stream(
            method,
            url,
            headers={"Authorization": "Bearer {}".format(self.get_access_token())},
        ) as stream:
            yield stream
