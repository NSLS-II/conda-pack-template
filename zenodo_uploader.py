import os

import argparse
import requests
import yaml
import json
from urllib.parse import urlencode


def search_for_deposition(
    title,
    owner=None,
    creators=None,
    zenodo_server="https://sandbox.zenodo.org/api/",
):
    print(f"Searching for depositions...\n")
    search = f'metadata.title:"{title}"'
    if owner:
        search += f" owners:{owner}"
    if creators:
        creators_query = '"' + '" OR "'.join(creators) + '"'
        search += f" metadata.creators.name:{creators_query}"
    search = search.replace("/", " ")  # zenodo can't handle '/' in search query

    params = {"q": search, "sort": "bestmatch"}
    url = zenodo_server + "records?" + urlencode(params)

    records = [hit for hit in requests.get(url).json()["hits"]["hits"]]

    if not records:
        print(f"No records found for search: '{title}'")
        return None, None, None

    print(f"Found `{len(records)}` depositions!")

    deposition = records[0]
    print(f"Best match is deposition: {deposition['id']}")
    return (
        deposition["id"],
        deposition["links"]["bucket"],
        deposition["links"]["html"].replace("deposit", "record"),
    )


def create_new_version(
    deposition_id, token, zenodo_server="https://sandbox.zenodo.org/api/"
):
    url = f"{zenodo_server}deposit/depositions/{deposition_id}/actions/newversion"
    r = requests.post(
        url,
        params={"access_token": token},
    )
    r.raise_for_status()

    deposition = r.json()
    new_deposition_url = deposition["links"]["latest_draft"]
    new_deposition_id = new_deposition_url.split("/")[-1]

    r = requests.get(
        f"{zenodo_server}deposit/depositions/{new_deposition_id}",
        params={"access_token": token},
    )
    r.raise_for_status()
    deposition = r.json()

    return (
        deposition["id"],
        deposition["links"]["bucket"],
        deposition["links"]["html"].replace("deposit", "record"),
    )


def create_new_deposition(token, zenodo_server="https://sandbox.zenodo.org/api/"):
    url = f"{zenodo_server}deposit/depositions"
    r = requests.post(
        url,
        params={"access_token": token},
        json={},
        headers={"Content-Type": "application/json"},
    )
    r.raise_for_status()

    deposition = r.json()

    return (
        deposition["id"],
        deposition["links"]["bucket"],
        deposition["links"]["html"].replace("deposit", "record"),
    )


def upload_to_zenodo(
    filename,
    bucket_url,
    file_url,
    filebase,
    token,
):

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
    zenodo_server="https://sandbox.zenodo.org/api/",
):
    print(f"Uploading metadata for {filename} ...")

    r = requests.put(
        f"{zenodo_server}deposit/depositions/{deposition_id}",
        params={"access_token": token},
        data=json.dumps(meta_data),
        headers={"Content-Type": "application/json"},
    )

    r.raise_for_status()


def publish_file(
    deposition_id,
    filebase,
    token,
    zenodo_server="https://sandbox.zenodo.org/api/",
):
    print(f"Publishing {filebase}...")
    r = requests.post(
        f"{zenodo_server}/{deposition_id}/actions/publish",
        params={"access_token": token},
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

    config_file = os.path.abspath(args.config_file)
    if not os.path.isfile(config_file):
        raise FileNotFoundError(
            f"The file with metadata, specified for uploading does not exist: {config_file}"
        )

    with open(config_file) as fp:

        try:
            meta_data = yaml.safe_load(fp)["zenodo_metadata"]
        except:
            exit(f"Please add metadata to the config file: {config_file}")

    for file in args.files_to_upload:
        filename = os.path.abspath(file)
        filebase = os.path.basename(filename)
        if not os.path.isfile(filename):
            raise FileNotFoundError(
                f"The file, specified for uploading does not exist or is a directory: {filename}"
            )

        deposition_id, bucket_url, file_url = search_for_deposition(
            title=meta_data["metadata"]["title"],
            creators=(creator["name"] for creator in meta_data["metadata"]["creators"]),
        )

        if not deposition_id:
            deposition_id, bucket_url, file_url = create_new_deposition(token=token)
            upload_to_zenodo(
                filename=file,
                bucket_url=bucket_url,
                file_url=file_url,
                filebase=filebase,
                token=token,
            )
            add_meta_data(
                deposition_id=deposition_id,
                meta_data=meta_data,
                token=token,
            )

            if args.publish:
                publish_file(
                    deposition_id=deposition_id, filebase=filebase, token=token
                )
        else:
            deposition_id, bucket_url, file_url = create_new_version(
                deposition_id=deposition_id,
                token=token,
            )
            upload_to_zenodo(
                filename=file,
                bucket_url=bucket_url,
                file_url=file_url,
                filebase=filebase,
                token=token,
            )
            if args.publish:
                publish_file(
                    deposition_id=deposition_id, filebase=filebase, token=token
                )
