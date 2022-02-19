from contextlib import contextmanager
import click
import httpx
import itertools


class FilesError(Exception):
    pass


def get_file(client, file_id, fields=None):
    file_url = "https://www.googleapis.com/drive/v3/files/{}".format(file_id)
    params = {}
    if fields is not None:
        params["fields"] = ",".join(fields)
    return client.get(
        file_url,
        params=params,
    ).json()


def paginate_files(client, *, corpora=None, q=None, fields=None):
    pageToken = None
    files_url = "https://www.googleapis.com/drive/v3/files"
    params = {}
    if corpora is not None:
        params["corpora"] = corpora
    if fields is not None:
        params["fields"] = "nextPageToken, files({})".format(",".join(fields))
    if q:
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
            timeout=self.timeout,
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


def save_files_and_folders(db, all):
    # Ensure tables with foreign keys exist
    with db.conn:
        if not db["drive_users"].exists():
            db["drive_users"].create({"permissionId": str}, pk="permissionId")
        for table in ("drive_folders", "drive_files"):
            if not db[table].exists():
                db[table].create(
                    {"id": str, "_parent": str, "lastModifyingUser": str},
                    pk="id",
                )
                # Gotta add foreign key after table is created, to avoid
                # AlterError: No such column: drive_folders.id
                db[table].add_foreign_key("_parent", "drive_folders", "id")
                db[table].add_foreign_key(
                    "lastModifyingUser", "drive_users", "permissionId"
                )
            # Create owners table too
            owners_table = "{}_owners".format(table)
            if not db[owners_table].exists():
                db[owners_table].create(
                    {
                        "item_id": str,
                        "user_id": str,
                    },
                    foreign_keys=(
                        ("user_id", "drive_users", "permissionId"),
                        ("item_id", table, "id"),
                    ),
                    pk=("item_id", "user_id"),
                )

    # Commit every 100 records
    users_seen = set()
    for chunk in chunks(all, 100):
        # Add `_parent` columns
        files = []
        folders = []
        for file in chunk:
            file["_parent"] = file["parents"][0] if file.get("parents") else None
            if file.get("mimeType") == "application/vnd.google-apps.folder":
                folders.append(file)
            else:
                files.append(file)
        # Convert "lastModifyingUser" JSON into a foreign key reference to drive_users
        drive_folders_owners_to_insert = []
        drive_files_owners_to_insert = []
        for to_insert_list, sequence in (
            (drive_folders_owners_to_insert, folders),
            (drive_files_owners_to_insert, files),
        ):
            for file in sequence:
                if file.get("lastModifyingUser"):
                    file["lastModifyingUser"] = (
                        db["drive_users"]
                        .insert(
                            file["lastModifyingUser"],
                            replace=True,
                            pk="permissionId",
                            alter=True,
                        )
                        .last_pk
                    )
                owners = file.pop("owners", None)
                if owners:
                    # Insert any missing ones
                    missing_users = [
                        user
                        for user in owners
                        if user["permissionId"] not in users_seen
                    ]
                    if missing_users:
                        db["drive_users"].insert_all(
                            missing_users,
                            replace=True,
                            alter=True,
                        )
                        users_seen.update(u["permissionId"] for u in missing_users)
                    for owner in owners:
                        to_insert_list.append(
                            {"item_id": file["id"], "user_id": owner["permissionId"]}
                        )

        with db.conn:
            db["drive_folders"].insert_all(
                folders,
                pk="id",
                replace=True,
                alter=True,
            )
            db["drive_files"].insert_all(
                files,
                pk="id",
                replace=True,
                alter=True,
            )
            if drive_folders_owners_to_insert:
                db["drive_folders_owners"].insert_all(
                    drive_folders_owners_to_insert, replace=True
                )
            if drive_files_owners_to_insert:
                db["drive_files_owners"].insert_all(
                    drive_files_owners_to_insert, replace=True
                )


def chunks(sequence, size):
    iterator = iter(sequence)
    for item in iterator:
        yield itertools.chain([item], itertools.islice(iterator, size - 1))
