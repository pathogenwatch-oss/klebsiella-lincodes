import csv
import dataclasses
import gzip
import io
import json
import logging
import lzma
import re
import shutil
from datetime import datetime
from functools import partial
from hashlib import sha1
from pathlib import Path
from typing import Annotated, Any, Callable, Iterable, Iterator, Optional, TextIO

import requests
import toml
import typer
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from rauth import OAuth1Session

from plincer.allelestore import finalise_db, initialise_db
from plincer.keycache import KeyCache

BAD_CHAR: re.Pattern = re.compile(r"[^ACGT]")

app: typer.Typer = typer.Typer()


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
    ] = Path("profiles.json.xz"),
    scheme_metadata: Annotated[
        Path,
        typer.Option(
            "-m",
            "--metadata-file",
            help="Output metadata JSON file path",
            file_okay=True,
            dir_okay=False,
        ),
    ] = "metadata.json",
    dbfile: Annotated[
        Path,
        typer.Option(
            "-a",
            "--alleles-db",
            help="Output location of the sqlite allele DB",
            file_okay=True,
            dir_okay=False,
        ),
    ] = Path("alleles.sqlite"),
    secrets_file: Annotated[
        Path,
        typer.Option(
            "-x",
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
    scratch_dir: Annotated[
        Path,
        typer.Option(
            "-d",
            "--scratch-dir",
            help="Directory for scratch files (default: scratch)",
            file_okay=False,
            dir_okay=True,
        ),
    ] = Path("scratch"),
    hash_size: Annotated[
        int,
        typer.Option(
            "-z",
            "--hash-size",
            help="Size of the hash to generate (default: 15)",
        ),
    ] = 15,
    clean: Annotated[
        bool,
        typer.Option(
            help="Clean the scratch directory after building",
            is_flag=True,
        ),
    ] = True,
    log_level: Annotated[
        str,
        typer.Option(
            "-l",
            "--log-level",
            help="Set the logging level",
            case_sensitive=False,
        ),
    ] = "INFO",
) -> None:
    # Set up logging
    logging.basicConfig(
        level=log_level.upper(), format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logger: logging.Logger = logging.getLogger(__name__)

    logger.info(f"Starting build process with scheme file: {scheme_toml}")

    keycache: KeyCache = KeyCache(secrets_file, host_config_file, secrets_cache_file)
    logger.debug("KeyCache initialized")

    # Set up work space
    if scratch_dir.exists():
        logger.info(
            f"Scratch directory {str(scratch_dir)} already exists. Deleting existing files..."
        )
        shutil.rmtree(scratch_dir)
    scratch_dir.mkdir(parents=True)

    with open(scheme_toml, "r") as sch_fh, lzma.open(
        profiles_json, "w"
    ) as profiles_fh, open(scheme_metadata, "w") as metadata_fh:
        scheme: dict[str, Any] = toml.load(sch_fh)
        logger.info(f"Fetching scheme {scheme['name']}")

        downloader: Downloader = Downloader(
            scheme["host"], scheme["host_path"], scheme["scheme_id"], keycache
        )
        logger.debug(f"Downloader initialized for host: {scheme['host']}")

        logger.info("Fetching loci...")
        loci: list[str] = downloader.download_loci()
        logger.debug(f"Found {len(loci)} loci")
        scheme_metadata: dict[str, Any] = downloader.build_metadata(loci)
        json.dump(scheme_metadata, metadata_fh)
        logger.debug(f"Metadata written to {scheme_metadata}")

        logger.info(f"Downloading alleles for {len(loci)} loci ...")
        downloader.download_alleles(loci, scratch_dir)
        logger.debug(f"Done: {json.dumps(scheme_metadata, indent=4)}")
        logger.info(f"Creating allele DB at {dbfile} with hash size {hash_size}...")
        create_allele_db(loci, scratch_dir, dbfile, hash_size)
        logger.debug(f"Allele DB created at {dbfile}")

        logger.info("Downloading profiles...")
        raw_profiles: str = downloader.download_profiles()
        logger.debug(f"Downloaded profiles: {len(raw_profiles)} bytes")
        with open(f"{scratch_dir}/profiles.tsv", "w") as temp_fh:
            temp_fh.write(raw_profiles)
        profiles: dict[str, dict[str, str]] = parse_profile_csv(raw_profiles)
        logger.debug(f"Parsed {len(profiles)} profiles")

        logger.debug("Converting LIN codes and writing to output file...")
        profiles_fh.write(json.dumps(profiles).encode("utf-8"))
        logger.debug(f"Profiles written to {str(profiles_json)}")

    if clean:
        logger.info(f"Cleaning scratch directory {str(scratch_dir)}")
        shutil.rmtree(scratch_dir)

    logger.info("Build process completed successfully")


def normalise_fasta(input_text: str, output_stream: TextIO) -> list[str]:
    contig_names: list[str] = []

    for record in SeqIO.parse(io.StringIO(input_text), "fasta"):
        name: str = record.id
        sequence: str = str(record.seq).upper()

        m: Optional[re.Match] = re.match(r"^(.+[_-])?([0-9]+(\\.[0-9]+)?)$", name)
        if m is None:
            print(f"Skipping badly formatted allele '{name}'")
            continue

        if BAD_CHAR.search(sequence):
            # Some schemes had non-ACGT characters
            continue

        if len(sequence.strip()) == 0:
            # pubmlst_neisseria_62/NEIS1690.fa.gz has an allele with
            # no content. I assume it is because it needs to be removed
            continue

        normalized_record: SeqRecord = SeqRecord(Seq(sequence), id=m[2], description="")
        SeqIO.write(normalized_record, output_stream, "fasta")
        contig_names.append(m[2])

    if len(contig_names) == 0:
        raise ValueError("Expected there to be some contigs")

    return contig_names


@dataclasses.dataclass
class Downloader:
    host: str
    host_path: str
    scheme_id: int
    keycache: KeyCache

    def __post_init__(self) -> None:
        self.database: str = (
            f"{self.host_path.replace('pubmlst_', '').replace('_seqdef','')}"
        )
        self.name: str = f"{self.host_path.replace('_seqdef','')}_{self.scheme_id}"
        self.base_url: str = f"{self.keycache.get_rest_url(self.host)}/{self.host_path}"
        self.scheme_url: str = f"{self.base_url}/schemes/{self.scheme_id}"
        self.loci_url: str = f"{self.scheme_url}/loci"
        self.alleles_url: str = f"{self.base_url}/loci"
        self.__oauth_fetch: Callable[[str], requests.Response] = partial(
            oauth_fetch, self.host, self.keycache, self.database
        )

    def download_profiles(self) -> str:
        response: requests.Response = self.__oauth_fetch(
            f"{self.scheme_url}/profiles_csv"
        )
        if response.status_code == 200:
            logging.debug("Downloaded profiles successfully")
            return response.text
        else:
            raise Exception(
                f"Failed to download profiles: HTTP status {response.status_code}"
            )

    def download_loci(self) -> list[str]:
        logging.debug(f"Downloading loci for {self.name}...")
        r: requests.Response = self.__oauth_fetch(self.loci_url)
        loci: list[str] = []
        stem: str = f"{self.alleles_url}/"
        for locus in json.loads(r.text)["loci"]:
            loci.append(locus.replace(stem, ""))
        return loci

    def fetch_timestamp(self) -> str:
        logging.debug(f"Fetching timestamp for {self.name}...")
        url: str = self.scheme_url
        r: requests.Response = self.__oauth_fetch(url)
        scheme_metadata: dict[str, Any] = json.loads(r.text)
        return (
            scheme_metadata["last_updated"]
            if "last_updated" in scheme_metadata
            else datetime.today().strftime("%Y-%m-%d")
        )

    def build_metadata(self, loci: list[str]) -> dict[str, str | list[str]]:
        scheme_metadata: dict[str, str | list[str]] = {
            "last_updated": self.fetch_timestamp(),
            "genes": [locus.replace("_", " ") for locus in loci],
        }
        return scheme_metadata

    def download_alleles(self, loci: list[str], out_dir: Path) -> None:
        for locus in loci:
            alleles_url: str = f"{self.alleles_url}/{locus}/alleles_fasta"
            logging.debug(f"Downloading alleles for {locus} from {alleles_url}")

            # PubMLST puts an apostrophe in front of RNA genes, it seems
            clean_locus: str = locus.replace("'", "")
            allele_file: Path = Path(f"{out_dir}/{clean_locus}.fa.gz")
            # Remove any existing file to deal with failed downloads.
            allele_file.unlink(missing_ok=True)
            with gzip.open(allele_file, "wt") as out_f:
                response = self.__oauth_fetch(alleles_url)
                normalise_fasta(response.text, out_f)


def create_allele_db(
    genes: list[str], alleles_dir: Path, dbfile: Path, hash_size: int = 20
) -> None:
    db = initialise_db(dbfile)
    cursor = db.cursor()
    for idx, gene in enumerate(genes):
        filename: Path = alleles_dir / f"{gene}.fa.gz"
        cursor.executemany(
            "INSERT INTO alleles(checksum, position, code) VALUES(?,?,?)",
            hash_alleles(filename, idx, hash_size),
        )
    db.commit()
    cursor.close()
    finalise_db(db)


def hash_alleles(
    filename: Path, idx: int, hash_size: int = 20
) -> Iterator[tuple[str, int, int]]:
    with gzip.open(filename, "rt", encoding="utf-8") as fasta_fh:
        for record in SeqIO.parse(fasta_fh, "fasta"):
            code: int = int(record.id)
            sequence: str = str(record.seq).lower()
            yield sha1(sequence.encode()).hexdigest()[:hash_size], idx, code


def oauth_fetch(
    host: str, keycache: KeyCache, database: str, url: str
) -> requests.Response:
    logging.debug(f"Fetching data from authenticated {host} - {database}...")
    consumer_key: tuple[str, str] = keycache.get_consumer_key(host)
    session_key: tuple[str, str] = keycache.get_session_key(host, database)
    session: OAuth1Session = OAuth1Session(
        consumer_key[0],
        consumer_key[1],
        access_token=session_key[0],
        access_token_secret=session_key[1],
    )
    response: requests.Response = session.get(url)
    if response.status_code == 301 or response.status_code == 401:
        logging.error(
            f"Session access denied. Attempting to regenerate keys as needed for {host}"
        )
        keycache.delete_key("session", host)
        response = oauth_fetch(host, keycache, database, url)
    else:
        response.raise_for_status()
    return response


def parse_profile_csv(profile_csv: str) -> dict[str, dict[str, str]]:
    reader: Iterable[list[str]] = csv.reader(
        profile_csv.splitlines()[1:], delimiter="\t"
    )
    profiles: dict[str, dict[str, str]] = dict()
    for row in reader:
        st: str = row[0]
        profile: list[str] = row[1:-4]
        lincode: str
        phylogroup: str
        sublineage: str
        clonal_group: str
        lincode, phylogroup, sublineage, clonal_group = row[-4:]
        if lincode != "":
            profiles[st] = {
                "ST": st,
                "profile": profile,
                "LINcode": lincode.split("_"),
                "Phylogroup": phylogroup,
                "Clonal Group": clonal_group.replace("CG", ""),
                "Sublineage": sublineage.replace("SL", ""),
            }
    return profiles
