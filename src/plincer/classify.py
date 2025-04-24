import json
import lzma
import math
import sqlite3
import sys
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Callable

import toml
import typer

from plincer.allelestore import connect_db, lookup_st

app = typer.Typer()


@app.command()
def classify(
    input: Annotated[
        str,
        typer.Argument(
            help="Input JSON file path with a Pathogenwatch cgMLST profile. Provide a '-' to read from stdin.",
    )],
    scheme_toml: Annotated[
        Path,
        typer.Option(
            "-s",
            "--scheme-file",
            help="Scheme TOML file path",
            file_okay=True,
            exists=True,
            dir_okay=False,
        ),
    ] = Path("scheme.toml"),
    profiles_json: Annotated[
        Path,
        typer.Option(
            "-p",
            "--profiles-file",
            help="Profiles JSON file path",
            file_okay=True,
            exists=True,
            dir_okay=False,
        ),
    ] = Path("profiles.json.xz"),
    allele_db: Annotated[
        Path,
        typer.Option(
            "-a",
            "--alleles-db",
            help="Alleles DB file path",
            file_okay=True,
            exists=True,
            dir_okay=False,
        ),
    ] = Path("alleles.sqlite"),
    hash_size: int = 15,
):
    if input == "-":
        input_json: dict[str, Any] = read_input()
    else:
        infile = Path(input)
        if not infile.is_file():
            typer.echo(f"Error: Input file '{infile}' does not exist.")
            sys.exit(1)
        with open(infile, "r") as infile_fh:
            input_json: dict[str, Any] = json.load(infile_fh)

    db: sqlite3.Connection = connect_db(str(allele_db))
    cursor: sqlite3.Cursor = db.cursor()
    lookup: Callable[[str, int], int] = partial(lookup_st, cursor)

    profile: list[str] = []
    for index, locus in enumerate(input_json["code"].split("_")):
        if locus.isdigit():
            profile.append(locus)
        elif locus == "":
            profile.append("")
        elif len(locus) == 40:
            result: int | None = lookup(locus[0:hash_size], index)
            if result:
                profile.append(str(result))
            else:
                profile.append(str(sys.maxsize))

    st: str = input_json["st"]
    with lzma.open(profiles_json, "rt") as profiles_fh:
        profiles: dict[str, Any] = json.load(profiles_fh)
    with open(scheme_toml, "r") as scheme_fh:
        scheme: dict[str, Any] = toml.load(scheme_fh)
    best_matches: list[dict[str, Any]] = (
        get_exact_match(input_json["st"], profiles)
        if input_json["st"].isdigit()
        else closest_profiles(profile, profiles)
    )

    output = partial(build_result, len(profile))

    if len(best_matches) == 0:
        print(json.dumps(output(input_json["st"])))
    elif input_json["st"].isdigit():
        match: dict[str, Any] = best_matches[0]
        print(
            json.dumps(
                output(
                    cgst=st,
                    matches=best_matches,
                    identical=0,
                    identity=100,
                    closest_cgst=st,
                    lincode=match["LINcode"],
                    clonal_group=match["Clonal Group"],
                    sublineage=match["Sublineage"],
                )
            )
        )
    else:
        identity: float = best_matches[0]["identity"]
        lincode_bin: int = assign_bin(identity, scheme["levels"])
        lincode: list[str] = ["*"] * 10
        for i in range(lincode_bin + 1):
            lincode[i] = best_matches[0]["LINcode"][i]
        print(
            json.dumps(
                output(
                    cgst=best_matches[0]["st"] if 9 == lincode_bin else st,
                    matches=best_matches,
                    identical=best_matches[0]["identical"],
                    identity=best_matches[0]["identity"],
                    closest_cgst="/".join(
                        sorted([match["st"] for match in best_matches])
                    ),
                    lincode=lincode,
                    clonal_group=best_matches[0]["Clonal Group"]
                    if 2 < lincode_bin
                    else "",
                    sublineage=best_matches[0]["Sublineage"] if 1 < lincode_bin else "",
                )
            ),
            file=sys.stdout,
        )


def get_profiles(scheme_name: str) -> dict[str, Any]:
    with open(f"{scheme_name}.json", "r") as scheme_fh:
        return json.load(scheme_fh)


def read_input() -> dict[str, Any]:
    json_str: str = ""
    for line in sys.stdin:
        json_str += line
    return json.loads(json_str)


def calculate_identity(loci_count: int, identical: int, skipped_loci: int) -> float:
    return round((identical / (loci_count - skipped_loci)) * 100, 4)


def build_match(
    st: str, identical: int, identity: float, skipped_loci: int, profile: dict[str, Any]
) -> dict[str, Any]:
    return {
        "st": st,
        "identical": identical,
        "identity": identity,
        "compared_loci": len(profile["profile"]) - skipped_loci,
        "LINcode": profile["LINcode"],
        "Sublineage": profile["Sublineage"],
        "Clonal Group": profile["Clonal Group"],
    }


def compare_profiles(
    query: list[str],
    reference: list[str],
    gathering_threshold: int,
    max_missing_loci: int = 29,
) -> tuple[bool, int, int]:
    identical: int = 0
    mismatches: int = 0
    skipped_loci: int = 0
    for i, q_allele in enumerate(query):
        # Skip positions that are blank. The match quality is shown by the number of compared loci.
        if q_allele == "" or reference[i] == "N":
            skipped_loci += 1
            if max_missing_loci < skipped_loci:
                return False, 0, 0
            continue
        if q_allele == reference[i]:
            identical += 1
        else:
            mismatches += 1
            if mismatches > gathering_threshold:
                return (
                    False,
                    0,
                    0,
                )
    return True, identical, skipped_loci


def closest_profiles(
    query_profile: list[str], profiles: dict[str, Any]
) -> list[dict[str, Any]]:
    scheme_size = len(query_profile)
    closest_matches: list[dict[str, Any]] = []
    current_closest_identity: float = 0
    current_closest_mismatches: int = scheme_size
    current_gathering_threshold: int = (
        scheme_size  # Reduce the number of identity calculations
    )
    percent_id = partial(calculate_identity, scheme_size)
    for st in profiles.keys():
        matched: bool
        identical: int
        skipped_loci: int
        matched, identical, skipped_loci = compare_profiles(
            query_profile, profiles[st]["profile"], current_gathering_threshold
        )
        if not matched:
            continue
        identity: float = percent_id(identical, skipped_loci)
        mismatches: int = scheme_size - skipped_loci - identical
        if current_closest_identity < identity:
            closest_matches = [
                build_match(st, identical, identity, skipped_loci, profiles[st])
            ]
            current_closest_identity = identity
            current_closest_mismatches = mismatches
            current_gathering_threshold = math.ceil(current_closest_mismatches * 1.05)
        elif current_closest_identity == identity:
            closest_matches.append(
                build_match(st, identical, identity, skipped_loci, profiles[st])
            )
            if mismatches < current_closest_mismatches:
                current_closest_mismatches = mismatches
                current_gathering_threshold = math.ceil(
                    current_closest_mismatches * 1.05
                )
    return closest_matches


def get_exact_match(st: str, profiles: dict[str, Any]) -> list[dict[str, Any]]:
    return [build_match(st, 0, 100, 0, profiles[st])]


def assign_bin(identity: float, levels: list[dict[str, float]]) -> int:
    for i in range(len(levels)):
        level: int = 9 - i
        if identity >= levels[level]["max"]:
            return level
    return -1


def build_result(
    compared_loci: int,
    cgst: str,
    matches: list[dict[str, Any]] = None,
    identical: int = 0,
    identity: float = 0,
    closest_cgst: str = "",
    lincode: list[str] = None,
    clonal_group: str = "",
    sublineage: str = "",
) -> dict[str, Any]:
    if matches is None:
        matches = []
    if lincode is None:
        lincode = []
    return {
        "matches": [
            {"st": match["st"], "LINcode": match["LINcode"]} for match in matches
        ],
        "identical": identical,
        "identity": identity,
        "comparedLoci": compared_loci,
        "cgST": cgst,
        "Closest cgST": closest_cgst,
        "LINcode": lincode,
        "Clonal Group": clonal_group,
        "Sublineage": sublineage,
    }
