import csv
import subprocess

import toml
import json
import re
import sys
from typing import Dict, List

import requests as requests
from retry import retry


@retry(backoff=2, delay=1, max_delay=1200)
def fetch_json(url: str) -> Dict:
    r = requests.get(f"{url}?return_all=1")
    if r.status_code != 200:
        print(f"Failed to retrieve url: {url} {r.status_code} - {r.text}")
        raise IOError
    return r.json()


def extract_name(url: str):
    match = re.search("\\d+$", url)
    return match.group(0)


@retry(backoff=2, delay=1, max_delay=1200)
def fetch_profile_csv(url: str) -> str:
    p = subprocess.Popen(['curl', url], stdout=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode!= 0:
        raise IOError
    return out.decode("utf-8")

    # r = requests.get(url)
    # if r.status_code != 200:
    #     print(f"Failed to retrieve url: {url} {r.status_code} - {r.text}")
    #     raise IOError
    # return r.text


def parse_profile_csv(profile_csv: str) -> Dict:
    reader = csv.reader(profile_csv.splitlines()[1:], delimiter='\t')
    profiles = dict()
    for row in reader:
        st = row[0]
        profile = row[1:-4]
        lincode, phylogroup, sublineage, clonal_group = row[-4:]
        if lincode != '':
            profiles[st] = {'ST': st, 'profile': profile, 'LINcode': lincode, 'Phylogroup': phylogroup,
                            'Clonal Group': clonal_group.replace('CG', ''), 'Sublineage': sublineage.replace('SL', '')}
    return profiles


def download_profiles(base_url: str, scheme: str) -> Dict:
    profile_csv = fetch_profile_csv(f"{base_url}/schemes/{scheme}/profiles_csv")
    return parse_profile_csv(profile_csv)


def extract_group_name(scheme_info: Dict) -> str:
    if 'fields' in scheme_info['group'].keys():
        return list(scheme_info['group']['fields'].keys())[0] + list(scheme_info['group']['fields'].values())[0]
    return ''


def download_scheme(scheme: Dict) -> Dict:
    print(f"Fetching {scheme['name']} profile list", file=sys.stderr)
    profiles = download_profiles(scheme['url'],  scheme['scheme'])
    return profiles


def convert_lincodes(profiles: Dict):
    for profile in profiles.values():
        profile['LINcode'] = profile['LINcode'].split('_')
    return profiles


def build_scheme():
    with open('scheme.toml', 'r') as sch_fh:
        scheme = toml.load(sch_fh)
    print(f"Fetching scheme {scheme['name']}", file=sys.stderr)
    profiles = download_scheme(scheme)
    converted = convert_lincodes(profiles)
    with open('profiles.json', 'w') as out_fh:
        print(json.dumps(converted), file=out_fh)


if __name__ == '__main__':
    build_scheme()
