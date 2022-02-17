import httpx


class FilesError(Exception):
    pass


def paginate_files(access_token, *, corpora=None, q=None, fields=None):
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
        data = httpx.get(
            files_url,
            params=params,
            headers={"Authorization": "Bearer {}".format(access_token)},
            timeout=30.0,
        ).json()
        if "error" in data:
            raise FilesError(data)
        yield from data["files"]
        pageToken = data.get("nextPageToken", None)
        if pageToken is None:
            break


def files_in_folder_recursive(access_token, folder_id, fields):
    for file in paginate_files(
        access_token, q='"{}" in parents'.format(folder_id), fields=fields
    ):
        yield file
        if file["mimeType"] == "application/vnd.google-apps.folder":
            yield from files_in_folder_recursive(access_token, file["id"], fields)
