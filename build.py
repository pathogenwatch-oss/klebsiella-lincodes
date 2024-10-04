import csv
import json
import re
import subprocess
import sys
from typing import Any, Dict

import requests as requests
import toml
from tenacity import retry, wait_exponential


@retry(wait=wait_exponential(multiplier=1, min=10, max=7200))
def fetch_json(url: str) -> dict[str, Any]:
    r = requests.get(f"{url}?return_all=1")
    if r.status_code != 200:
        print(f"Failed to retrieve url: {url} {r.status_code} - {r.text}")
        raise IOError
    return r.json()


def extract_name(url: str):
    match = re.search("\\d+$", url)
    return match.group(0)


@retry(wait=wait_exponential(multiplier=1, min=10, max=7200))
def fetch_profile_csv(url: str) -> str:
    p = subprocess.Popen(['curl', url], stdout=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        raise IOError
    return out.decode("utf-8")


def download_scheme(scheme: dict[str, Any]) -> dict[str, dict[str, str]]:
    print(f"Fetching {scheme['name']} profile list", file=sys.stderr)
    url: str = f"{scheme['url']}/schemes/{scheme['scheme']}/profiles_csv"
    profiles_csv = fetch_profile_csv(url)
    return parse_profile_csv(profiles_csv)


def parse_profile_csv(profile_csv: str) -> dict[str, dict[str, str]]:
    reader = csv.reader(profile_csv.splitlines()[1:], delimiter='\t')
    profiles: dict[str, dict[str, str]] = dict()
    for row in reader:
        st = row[0]
        profile = row[1:-4]
        lincode, phylogroup, sublineage, clonal_group = row[-4:]
        if lincode != '':
            profiles[st] = {'ST': st, 'profile': profile, 'LINcode': lincode, 'Phylogroup': phylogroup,
                            'Clonal Group': clonal_group.replace('CG', ''), 'Sublineage': sublineage.replace('SL', '')}
    return profiles


def extract_group_name(scheme_info: dict[str, Any]) -> str:
    if 'fields' in scheme_info['group'].keys():
        return list(scheme_info['group']['fields'].keys())[0] + list(scheme_info['group']['fields'].values())[0]
    return ''


def convert_lincodes(profiles: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for profile in profiles.values():
        profile['LINcode'] = profile['LINcode'].split('_')
    return profiles


def read_scheme(filepath: str) -> dict[str, Any]:
    with open(filepath, 'r') as sch_fh:
        lines = sch_fh.readlines()
    return parse_profile_csv("\n".join(lines))


def build_scheme():
    with open('scheme.toml', 'r') as sch_fh, open('profiles.json', 'w') as out_f:
        scheme = toml.load(sch_fh)
        print(f"Fetching scheme {scheme['name']}", file=sys.stderr)
        profiles: dict[str, dict[str, Any]] = download_scheme(scheme)
        # profiles = read_scheme("BIGSdb_cgMLST_profiles_40000_49378.txt")
        converted: dict[str, dict[str, Any]] = convert_lincodes(profiles)
        print(json.dumps(converted), file=out_f)


if __name__ == '__main__':
    build_scheme()
