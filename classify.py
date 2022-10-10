import json
import math

import toml
import sys
from typing import Dict, List, Tuple, Any

SCHEME_SIZE = 629


def get_profiles(scheme_name: str) -> Dict[str, Any]:
    with open(f'{scheme_name}.json', 'r') as scheme_fh:
        return json.load(scheme_fh)


def get_scheme_definition(scheme_name: str) -> Dict[str, Any]:
    with open('schemes.json', 'r') as sch_fh:
        schemes = json.load(sch_fh)
    for scheme in schemes:
        if scheme['name'] == scheme_name:
            return scheme


def read_input() -> Dict[str, Any]:
    json_str = ''
    for line in sys.stdin:
        json_str += line
    return json.loads(json_str)


def calculate_identity(identical: int, skipped_loci: int, loci_count=SCHEME_SIZE) -> float:
    return round((identical / (loci_count - skipped_loci)) * 100, 4)


def build_match(st: str, identical: int, identity: float, skipped_loci: int, profile) -> Dict[str, Any]:
    return {
        'st': st,
        'identical': identical,
        'identity': identity,
        'compared_loci': SCHEME_SIZE - skipped_loci,
        'LINcode': profile['LINcode'],
        'Sublineage': profile['Sublineage'],
        'Clonal Group': profile['Clonal Group']
    }


def compare_profiles(query: List[str], reference: List[str], gathering_threshold, max_missing_loci=29) -> Tuple[
    bool, int, int]:
    identical = 0
    mismatches = 0
    matched = True
    skipped_loci = 0
    for i in range(SCHEME_SIZE):
        # Skip positions that are blank. The match quality is shown by the number of compared loci.
        if query[i] == '' or reference[i] == 'N':
            skipped_loci += 1
            if max_missing_loci < skipped_loci:
                return False, 0, 0
            continue
        if query[i] == reference[i]:
            identical += 1
        else:
            mismatches += 1
            if mismatches > gathering_threshold:
                matched = False
                return False, 0, 0,
    return True, identical, skipped_loci


def closest_profiles(code: str, profiles: Dict) -> List[Dict[str, Any]]:
    closest_matches = []
    current_closest_identity = 0
    current_closest_mismatches = SCHEME_SIZE
    current_gathering_threshold = SCHEME_SIZE  # Reduce number of identity calculations
    query_profile = code.split('_')
    for st in profiles.keys():
        matched, identical, skipped_loci = compare_profiles(query_profile, profiles[st]['profile'],
                                                             current_gathering_threshold)
        if not matched:
            continue
        identity = calculate_identity(identical, skipped_loci)
        mismatches = SCHEME_SIZE - skipped_loci - identical
        if current_closest_identity < identity:
            closest_matches = [build_match(st, identical, identity, skipped_loci, profiles[st])]
            current_closest_identity = identity
            current_closest_mismatches = mismatches
            current_gathering_threshold = math.ceil(current_closest_mismatches * 1.05)
        elif current_closest_identity == identity:
            closest_matches.append(build_match(st, identical, identity, skipped_loci, profiles[st]))
            if mismatches < current_closest_mismatches:
                current_closest_mismatches = mismatches
                current_gathering_threshold = math.ceil(current_closest_mismatches * 1.05)
    return closest_matches


def get_exact_match(st, profiles):
    profile = profiles[st]
    return [build_match(st, 0, 100, 0, profiles[st])]


def assign_bin(identity, levels):
    for i in range(len(levels)):
        level = 9 - i
        if levels[level]['min'] < identity:
            return level


def build_result(cgst, matches=[], identical=0, compared_loci=SCHEME_SIZE, identity=0, closest_cgst='',
                 lincode=[], clonal_group='', sublineage='') -> Dict[str, Any]:
    return {
        'matches': [{'st': match['st'], 'LINcode': match['LINcode']} for match in matches],
        'identical': identical,
        'identity': identity,
        'comparedLoci': compared_loci,
        'cgST': cgst,
        'Closest cgST': closest_cgst,
        'LINcode': lincode,
        'Clonal Group': clonal_group,
        'Sublineage': sublineage
    }


def classify_profile():
    input_json = read_input()
    st = input_json['st']
    with open('profiles.json', 'r') as profiles_fh:
        profiles = json.load(profiles_fh)
    with open('scheme.toml', 'r') as scheme_fh:
        scheme = toml.load(scheme_fh)
    best_matches = get_exact_match(input_json['st'], profiles) if input_json['st'].isdigit() else \
        closest_profiles(input_json['code'], profiles)
    if len(best_matches) == 0:
        print(json.dumps(build_result(input_json['st'])))
    elif input_json['st'].isdigit():
        match = best_matches[0]
        print(json.dumps(build_result(st, closest_cgst=st, matches=best_matches, identity=100, identical=0,
                                      compared_loci=match['compared_loci'], lincode=match['LINcode'],
                                      sublineage=match['Sublineage'], clonal_group=match['Clonal Group'])))
    else:
        identity = best_matches[0]['identity']
        lincode_bin = assign_bin(identity, scheme['levels'])
        lincode = ['*'] * 10
        for i in range(lincode_bin + 1):
            level = scheme['levels'][i]
            lincode[i] = best_matches[0]['LINcode'][i]
        print(json.dumps(
            build_result(
                best_matches[0]['st'] if 9 == lincode_bin else st,
                best_matches,
                best_matches[0]['identical'],
                best_matches[0]['compared_loci'],
                best_matches[0]['identity'],
                '/'.join(sorted([match['st'] for match in best_matches])),
                lincode,
                best_matches[0]['Clonal Group'] if 2 < lincode_bin else '',
                best_matches[0]['Sublineage'] if 1 < lincode_bin else ''
            )), file=sys.stdout)


if __name__ == '__main__':
    classify_profile()
