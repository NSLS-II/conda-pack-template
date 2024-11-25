import argparse
import json
import os
import textwrap
import traceback
from urllib.parse import urlencode

import requests
import yaml
from tabulate import tabulate

ZENODO_SERVER = "https://zenodo.org/api"
ZENODO_SANDBOX_SERVER = "https://sandbox.zenodo.org/api"


def search_for_deposition(
    title,
    owner=None,
    zenodo_server=ZENODO_SANDBOX_SERVER,
    token=None,
    showindex=True,
):
    print(
        f"Searching for depositions with title='{title}' and "
        f"owner='{owner}'...\n"
    )
    search = f'title:"{title}"'
    if owner:
        search += f" owners:{owner}"

    # zenodo can't handle '/' in search query
    search = search.replace("/", " ")

    params = {
        "q": search,
        "sort": "mostrecent",
        "size": 20,
        "page": 1,
        "status": "published",
        "all_versions": True,
    }
    url = f"{zenodo_server}/deposit/depositions?{urlencode(params)}"
    print(f"Search URL: {url}\n")

    try:
        response = requests.get(
            url,
            params={"access_token": token},
        )
        response_json = response.json()
        if response.status_code != 200:
            raise RuntimeError(
                f"Connection to '{url}' finished with status code "
                f"{response.status_code}.\n\n"
                f"Error: {response_json['message']}\n"
            )

        records = [hit for hit in response_json]
    except Exception:
        print(
            f"No title matches found! here is what happened:\n"
            f"{traceback.format_exc()}"
        )
        return None, None

    if not records:
        print(f"No records found for search: '{title}'")
        return None, None

    print(f"Found ***{len(records)}*** depositions!")

    depositions = []
    data_dict = dict(
        ids=[],
        titles=[],
        versions=[],
        files=[],
        checksums=[],
        dates=[],
    )

    for deposition in records:
        if (deposition["metadata"]["title"] == title) or (
            deposition["owner"] == owner
        ):
            depositions.append(deposition)

        data = deposition
        meta = data["metadata"]
        data_dict["ids"].append(data["id"])
        title = meta["title"]
        wrapped_title = "\n".join(textwrap.wrap(title, width=30))
        data_dict["titles"].append(wrapped_title)
        data_dict["versions"].append(meta.get("version", "---"))
        data_dict["files"].append(
            "\n".join([f"{f['filename']}" for f in data.get("files", [])])
        )
        data_dict["checksums"].append(
            "\n".join([f"{f['checksum']}" for f in data.get("files", [])])
        )
        data_dict["dates"].append(meta["publication_date"])

    if showindex:
        counter = range(1, len(records) + 1)
    else:
        counter = False

    print(
        tabulate(data_dict, headers="keys", showindex=counter, tablefmt="grid")
    )

    if not depositions:
        print(f"No records found for search: '{title}'")
        return None, None

    deposition = sorted(
        depositions,
        key=lambda deposition: deposition["metadata"]["publication_date"],
        reverse=True,
    )[0]

    print(
        f"Best match is deposition: {deposition['id']}\n"
        f"Title: {deposition['metadata']['title']}\n"
        f"Publication date: {deposition['metadata']['publication_date']}\n"
    )

    print(
        deposition["id"],
        deposition["links"]["html"].replace("deposit", "record"),
    )

    return (
        deposition["id"],
        deposition["links"]["html"].replace("deposit", "record"),
    )


def create_new_version(
    deposition_id,
    token,
    zenodo_server=ZENODO_SANDBOX_SERVER,
):
    print(f"Creating new version of deposition: {deposition_id} ...")
    url = (
        f"{zenodo_server}/deposit/depositions/{deposition_id}/"
        f"actions/newversion"
    )
    r = requests.post(
        url,
        params={"access_token": token},
        headers={"Content-Type": "application/json"},
    )
    r.raise_for_status()

    deposition = r.json()
    new_deposition_url = deposition["links"]["latest_draft"]
    new_deposition_id = new_deposition_url.split("/")[-1]

    print(f"New version created with id: {new_deposition_id}!")

    r = requests.get(
        f"{zenodo_server}/deposit/depositions/{new_deposition_id}",
        params={"access_token": token},
    )
    r.raise_for_status()
    deposition = r.json()

    delete_deposition_files(deposition_id=new_deposition_id, token=token)

    return (
        deposition["id"],
        deposition["links"]["bucket"],
        deposition["links"]["html"].replace("deposit", "record"),
    )


def create_new_deposition(
    token,
    zenodo_server=ZENODO_SANDBOX_SERVER,
):
    print("Creating new deposition...")
    url = f"{zenodo_server}/deposit/depositions"
    r = requests.post(
        url,
        params={"access_token": token},
        json={},
        headers={"Content-Type": "application/json"},
    )
    r.raise_for_status()

    deposition = r.json()
    print(f"New deposition created with id: {deposition['id']}")

    return (
        deposition["id"],
        deposition["links"]["bucket"],
        deposition["links"]["html"].replace("deposit", "record"),
    )


def upload_to_zenodo(
    deposition_id,
    filename,
    bucket_url,
    file_url,
    filebase,
    env_name,
    token,
    zenodo_server=ZENODO_SANDBOX_SERVER,
):
    if filename.endswith(".tar.gz"):
        response = requests.get(
            f"{zenodo_server}/deposit/depositions/{deposition_id}",
            params={"access_token": token},
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        print(f"Comparing {filename} checksum with files on zenodo...")
        files_checksums = [
            file["checksum"] for file in response.json()["files"]
        ]
        md5sum_file = f"{os.path.dirname(filename)}/{env_name}-md5sum.txt"
        with open(md5sum_file, "r") as fp:
            content = fp.read()
            current_file_checksum = content.split("=")[-1].strip()

        if current_file_checksum in files_checksums:
            print(
                f"File: {filename} with md5 checksum "
                f"({current_file_checksum}) is already uploaded!\n"
            )
            return
        else:
            print("No conflicting files!\n")

    print(f"Uploading {filename} to Zenodo. This may take some time...")
    with open(filename, "rb") as fp:
        r = requests.put(
            f"{bucket_url}/{filebase}", data=fp, params={"access_token": token}
        )
        r.raise_for_status()
        print(f"\nFile Uploaded successfully!\nFile link: {file_url}")


def add_meta_data(
    deposition_id,
    meta_data,
    token,
    zenodo_server=ZENODO_SANDBOX_SERVER,
):
    print(f"Uploading metadata for {filename} ...")

    r = requests.put(
        f"{zenodo_server}/deposit/depositions/{deposition_id}",
        params={"access_token": token},
        data=json.dumps(meta_data),
        headers={"Content-Type": "application/json"},
    )

    r.raise_for_status()


def delete_deposition_files(
    deposition_id,
    token,
    zenodo_server=ZENODO_SANDBOX_SERVER,
):
    print("Deleting old files...")
    r = requests.get(
        f"{zenodo_server}/deposit/depositions/{deposition_id}/files",
        params={"access_token": token},
    )
    r.raise_for_status()
    files = r.json()
    for file in files:
        r = requests.delete(
            f"{zenodo_server}/deposit/depositions/"
            f"{deposition_id}/files/{file['id']}",
            params={"access_token": token},
        )
        r.raise_for_status()
    print("All files deleted!")


def publish_deposition(
    deposition_id,
    token,
    zenodo_server=ZENODO_SANDBOX_SERVER,
):
    print(f"Publishing deposition: {deposition_id}...")
    r = requests.post(
        f"{zenodo_server}/deposit/depositions/{deposition_id}/actions/publish",
        params={"access_token": token},
    )
    if "errors" in r.json():
        exit(
            f"Error: Couldn't publish deposition! Here is what happened:\n"
            f"{r.json()['errors'][0]['message']}"
        )
    r.raise_for_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=("Upload files to Zenodo."))
    parser.add_argument(
        "-f",
        "--file",
        dest="files_to_upload",
        help="path to the file to be uploaded",
        required=True,
        action="append",
    )
    parser.add_argument(
        "-c",
        "--config-file",
        dest="config_file",
        help="config file with metadata information",
        required=True,
    )
    parser.add_argument(
        "-p",
        "--publish",
        dest="publish",
        action="store_true",
        help="Whether to publish file or not",
    )
    args = parser.parse_args()

    token = os.getenv("ZENODO_ACCESS_TOKEN")
    if not token:
        exit(
            "No access token provided!\n"
            "Please create an environment variable with the token.\n"
            "Variable Name: `ZENODO_ACCESS_TOKEN`"
        )
    owner = os.getenv("ZENODO_OWNER_ID")
    if not owner:
        exit(
            "No owner ID provided!\n"
            "Please create an environment variable with the owner ID.\n"
            "Variable Name: `ZENODO_OWNER_ID`"
        )

    config_file = os.path.abspath(args.config_file)
    if not os.path.isfile(config_file):
        raise FileNotFoundError(
            f"The file with metadata, specified for uploading does not exist: "
            f"{config_file}"
        )

    with open(config_file) as fp:
        try:
            content = yaml.safe_load(fp)
            meta_data = content["zenodo_metadata"]
            env_name = content["env_name"]
        except Exception:
            exit(f"Please add metadata to the config file: {config_file}")

    deposition_id, file_url = search_for_deposition(
        title=meta_data["metadata"]["title"],
        owner=owner,
        token=token,
    )
    if not deposition_id:
        deposition_id, bucket_url, file_url = create_new_deposition(
            token=token
        )

        for file in args.files_to_upload:
            filename = os.path.abspath(file)
            filebase = os.path.basename(filename)
            if not os.path.isfile(filename):
                raise FileNotFoundError(
                    f"The file, specified for uploading does not exist "
                    f"or is a directory: {filename}"
                )

            upload_to_zenodo(
                deposition_id=deposition_id,
                filename=file,
                bucket_url=bucket_url,
                file_url=file_url,
                filebase=filebase,
                token=token,
                env_name=env_name,
            )
            add_meta_data(
                deposition_id=deposition_id,
                meta_data=meta_data,
                token=token,
            )

        if args.publish:
            publish_deposition(deposition_id=deposition_id, token=token)
    else:
        deposition_id, bucket_url, file_url = create_new_version(
            deposition_id=deposition_id,
            token=token,
        )

        for file in args.files_to_upload:
            filename = os.path.abspath(file)
            filebase = os.path.basename(filename)
            if not os.path.isfile(filename):
                raise FileNotFoundError(
                    f"The file, specified for uploading does not exist "
                    f"or is a directory: {filename}"
                )

            upload_to_zenodo(
                deposition_id=deposition_id,
                filename=file,
                bucket_url=bucket_url,
                file_url=file_url,
                filebase=filebase,
                env_name=env_name,
                token=token,
            )
        if args.publish:
            publish_deposition(deposition_id=deposition_id, token=token)
