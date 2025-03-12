from contextlib import contextmanager
import click
import httpx
import itertools
from time import sleep


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

    def __init__(self, bearer_token, logger=None):
        self.bearer_token = bearer_token
        self.log = logger or (lambda s: None)

    def get(
        self,
        url,
        params=None,
        headers=None,
        transport_retries=2,
    ):
        headers = headers or {}
        headers["Authorization"] = "Bearer {}".format(self.bearer_token)
        self.log("GET: {} {}".format(url, params or "").strip())
        try:
            response = httpx.get(
                url, params=params, headers=headers, timeout=self.timeout
            )
        except httpx.TransportError as ex:
            if transport_retries:
                sleep(2)
                self.log("  Got {}, retrying".format(ex.__class__.__name__))
                return self.get(
                    url,
                    params,
                    headers,
                    transport_retries=transport_retries - 1,
                )
            else:
                raise
        return response

    def post(self, url, data=None, headers=None):
        headers = headers or {}
        headers["Authorization"] = "Bearer {}".format(self.bearer_token)
        self.log("POST: {}".format(url))
        response = httpx.post(url, data=data, headers=headers, timeout=self.timeout)
        return response

    @contextmanager
    def stream(self, method, url, params=None):
        with httpx.stream(
            method,
            url,
            params=params,
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
                    {
                        "id": str,
                        "_parent": str,
                        "_owner": str,
                        "lastModifyingUser": str,
                    },
                    pk="id",
                )
                # Gotta add foreign key after table is created, to avoid
                # AlterError: No such column: drive_folders.id
                db.add_foreign_keys(
                    (
                        (table, "_parent", "drive_folders", "id"),
                        (table, "_owner", "drive_users", "permissionId"),
                        (table, "lastModifyingUser", "drive_users", "permissionId"),
                    )
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
                last_modifying_user = file.get("lastModifyingUser")
                # This can be {'displayName': '', 'kind': 'drive#user', 'me': False}
                if last_modifying_user and last_modifying_user.get("permissionId"):
                    user_id = last_modifying_user["permissionId"]
                    if user_id not in users_seen:
                        db["drive_users"].insert(
                            last_modifying_user,
                            replace=True,
                            pk="permissionId",
                            alter=True,
                        )
                        users_seen.add(user_id)
                    file["lastModifyingUser"] = user_id
                else:
                    file["lastModifyingUser"] = None
                owners = file.pop("owners", None)
                file["_owner"] = None
                if owners and owners[0].get("permissionId"):
                    owner_user_id = owners[0]["permissionId"]
                    if owner_user_id not in users_seen:
                        db["drive_users"].insert(
                            owners[0],
                            replace=True,
                            pk="permissionId",
                            alter=True,
                        )
                        users_seen.add(owner_user_id)
                    file["_owner"] = owner_user_id

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
