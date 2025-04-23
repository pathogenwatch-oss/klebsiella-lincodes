import logging
import csv
import dataclasses
import json
import sys
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Callable

import requests
import toml
import typer
from rauth import OAuth1Session

from plincer.keycache import KeyCache

app = typer.Typer()


@app.command()
def build(
    scheme_toml: Annotated[
        Path,
        typer.Option(
            "-s",
            "--scheme-file",
            help="Input scheme TOML file path",
            file_okay=True,
            exists=True,
            dir_okay=False,
        ),
    ] = Path("scheme.toml"),
    profiles_json: Annotated[
        Path,
        typer.Option(
            "-o",
            "--profiles-file",
            help="Output Profiles JSON file path",
            file_okay=True,
            dir_okay=False,
        ),
    ] = Path("profiles.json"),
    secrets_file: Annotated[
        Path,
        typer.Option(
            "-s",
            "--secrets-file",
            help="Path to the secrets file containing (at least) the user credentials and consumer key+secret",
            exists=True,
            file_okay=True,
            dir_okay=False,
        ),
    ] = Path("secrets.json"),
    secrets_cache_file: Annotated[
        Path,
        typer.Option(
            "-c",
            "--secrets-cache-file",
            help="Path to the secrets cache file (default: secrets_cache.json)",
            file_okay=True,
            dir_okay=False,
        ),
    ] = Path("secrets_cache.json"),
    host_config_file: Annotated[
        Path,
        typer.Option(
            "-h",
            "--host-config-file",
            help="Path to the host configuration file (default: host_config.json)",
            file_okay=True,
            dir_okay=False,
            exists=True,
        ),
    ] = Path("host_config.json"),
    log_level: Annotated[
        str,
        typer.Option(
            "-l",
            "--log-level",
            help="Set the logging level",
            case_sensitive=False,
        ),
    ] = "INFO",
):
    # Set up logging
    logging.basicConfig(level=log_level.upper(), format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    logger.info(f"Starting build process with scheme file: {scheme_toml}")

    keycache = KeyCache(secrets_file, host_config_file, secrets_cache_file)
    logger.debug("KeyCache initialized")

    with open(scheme_toml, "r") as sch_fh, open(profiles_json, "w") as out_f:
        scheme = toml.load(sch_fh)
        logger.info(f"Fetching scheme {scheme['name']}")

        downloader = Downloader(
            scheme["host"], scheme["host_path"], scheme["scheme_id"], keycache
        )
        logger.debug(f"Downloader initialized for host: {scheme['host']}")

        logger.info("Downloading profiles...")
        raw_profiles = downloader.download_profiles()
        logger.info(f"Downloaded {len(raw_profiles)} profiles")
        profiles = parse_profile_csv(raw_profiles)
        logger.debug(f"Parsed {len(profiles)} profiles")

        logger.info("Converting LINcodes and writing to output file...")
        json.dump(convert_lincodes(profiles), out_f)
        logger.info(f"Profiles written to {profiles_json}")

    logger.info("Build process completed successfully")


@dataclasses.dataclass
class Downloader:
    host: str
    host_path: str
    scheme_id: int
    keycache: KeyCache

    def __post_init__(self):
        self.database = (
            f"{self.host_path.replace('pubmlst_', '').replace('_seqdef','')}"
        )
        self.name = f"{self.host_path.replace('_seqdef','')}_{self.scheme_id}"
        self.base_url = f"{self.keycache.get_rest_url(self.host)}/{self.host_path}"
        self.scheme_url = f"{self.base_url}/schemes/{self.scheme_id}"
        self.loci_url = f"{self.scheme_url}/loci"
        self.alleles_url = f"{self.base_url}/loci"
        self.__retry_oauth_fetch: Callable[[str], requests.Response] = partial(
            oauth_fetch, self.host, self.keycache, self.database
        )

    def download_profiles(self) -> str:
        response = self.__retry_oauth_fetch(f"{self.scheme_url}/profiles_csv")
        if response.status_code == 200:
            logging.debug(f"Downloaded profiles successfully")
            return response.text
        else:
            raise Exception(
                f"Failed to download profiles: HTTP status {response.status_code}"
            )


def oauth_fetch(
    host: str, keycache: KeyCache, database: str, url: str
) -> requests.Response:
    logging.debug(f"Fetching data from authenticated {host} - {database}...")
    consumer_key = keycache.get_consumer_key(host)
    session_key = keycache.get_session_key(host, database)
    session = OAuth1Session(
        consumer_key[0],
        consumer_key[1],
        access_token=session_key[0],
        access_token_secret=session_key[1],
    )
    response = session.get(url)
    if response.status_code == 301 or response.status_code == 401:
        logging.error(
            f"Session access denied. Attempting to regenerate keys as needed for {host}"
        )
        keycache.delete_key("session", host)
        oauth_fetch(host, keycache, database, url)
    else:
        response.raise_for_status()
    return response


def parse_profile_csv(profile_csv: str) -> dict[str, dict[str, str]]:
    reader = csv.reader(profile_csv.splitlines()[1:], delimiter="\t")
    profiles: dict[str, dict[str, str]] = dict()
    for row in reader:
        st = row[0]
        profile = row[1:-4]
        lincode, phylogroup, sublineage, clonal_group = row[-4:]
        if lincode != "":
            profiles[st] = {
                "ST": st,
                "profile": profile,
                "LINcode": lincode,
                "Phylogroup": phylogroup,
                "Clonal Group": clonal_group.replace("CG", ""),
                "Sublineage": sublineage.replace("SL", ""),
            }
    return profiles


def convert_lincodes(profiles: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for profile in profiles.values():
        profile["LINcode"] = profile["LINcode"].split("_")
    return profiles
