import json
import toml
import sys
from typing import Dict, List, Tuple, Any


def get_profiles(scheme_name: str) -> Dict:
    with open(f'{scheme_name}.json', 'r') as scheme_fh:
        return json.load(scheme_fh)


def read_input():
    json_str = ''
    for line in sys.stdin:
        json_str += line
    return json.loads(json_str)


def closest_profiles(code: str, profiles: Dict, mismatch_threshold=10) -> List[Dict[str, Any]]:
    query_profile = code.split('_')
    loci_count = len(query_profile)
    closest_matches = []
    current_closest_distance = loci_count
    for st in profiles.keys():
        st_profile = profiles[st]
        mismatches = 0
        matched = True
        compared_loci_count = 0
        for i in range(loci_count):
            # Skip positions that are blank. The match quality is shown by the number of compared loci.
            if query_profile[i] == '':
                continue
            compared_loci_count += 1
            if query_profile[i] != st_profile['profile'][i] and st_profile['profile'][i] != 'N':
                mismatches += 1
                if mismatches > current_closest_distance or mismatches > mismatch_threshold:
                    matched = False
                    break
        if matched and mismatches < current_closest_distance:
            closest_matches = [{
                'st': st,
                'mismatches': mismatches,
                'compared_loci': compared_loci_count,
                'LINcode': profiles[st]['LINcode'],
                'Sublineage': profiles[st]['Sublineage'],
                'Clonal Group': profiles[st]['Clonal Group']
            }]
            current_closest_distance = mismatches
        elif matched and mismatches == current_closest_distance:
            closest_matches.append({
                'st': st,
                'mismatches': mismatches,
                'compared_loci': compared_loci_count,
                'LINcode': profiles[st]['LINcode'],
                'Sublineage': profiles[st]['Sublineage'],
                'Clonal Group': profiles[st]['Clonal Group']})
            current_closest_distance = mismatches
    return closest_matches


def get_scheme_definition(scheme_name: str) -> Dict:
    with open('schemes.json', 'r') as sch_fh:
        schemes = json.load(sch_fh)
    for scheme in schemes:
        if scheme['name'] == scheme_name:
            return scheme


def get_exact_match(st, profiles):
    profile = profiles[st]
    return [{
        'st': st,
        'mismatches': 0,
        'compared_loci': len(profiles[st]['profile']),
        'LINcode': profiles[st]['LINcode'],
        'Sublineage': profiles[st]['Sublineage'],
        'Clonal Group': profiles[st]['Clonal Group']}]


def classify_profile():
    input_json = read_input()
    with open('profiles.json', 'r') as profiles_fh:
        profiles = json.load(profiles_fh)
    with open('scheme.toml', 'r') as scheme_fh:
        scheme = toml.load(scheme_fh)
    min_classification_threshold = scheme['levels'][0]['threshold']
    profile_length = len(input_json['code'].split('_'))
    best_matches = get_exact_match(input_json['st'], profiles) if input_json['st'].isdigit() else \
        closest_profiles(
            input_json['code'],
            profiles,
            min_classification_threshold)
    mismatches = best_matches[0]['mismatches']
    scheme_size = profile_length
    results = {
        'matches': [{'st': match['st'], 'LINcode': match['LINcode']} for match in best_matches],
        'schemeSize': scheme_size,
        'mismatches': mismatches,
        'comparedLoci': best_matches[0]['compared_loci']}
    if input_json['st'].isdigit():
        results['LINcode'] = best_matches[0]['LINcode']
        results['Clonal Group'] = best_matches[0]['Clonal Group']
        results['Sublineage'] = best_matches[0]['Sublineage']
        results['cgST'] = input_json['st']
    else:
        lincode = []
        for i in range(10):
            level = scheme['levels'][i]
            code = ""
            if mismatches <= level['threshold']:
                code = best_matches[0]['LINcode'][i]
                for match in best_matches:
                    if match['LINcode'][i] != code:
                        code = '*'
                        break
            lincode.append(code)
        results['LINcode'] = lincode
        if lincode[2] != '' and lincode[2] != '*':
            results['Clonal Group'] = best_matches[0]['Clonal Group']
        if lincode[3] != '' and lincode[2] != '*':
            results['Sublineage'] = best_matches[0]['Sublineage']
        if lincode[9] != '' and lincode[9] != '*':
            results['cgST'] = best_matches[0]['st']
        else:
            results['cgST'] = input_json['st']
    print(json.dumps(results), file=sys.stdout)


if __name__ == '__main__':
    classify_profile()
