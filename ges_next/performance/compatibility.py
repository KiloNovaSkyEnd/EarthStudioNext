"""Allow only a qualified execution-only upgrade for an existing frozen profile."""
import json
from pathlib import Path


def legacy_permits(previous,current,profile):
    path=Path(__file__).resolve().parents[2]/'resources/performance/execution_qualification.json'
    if not path.exists():return False
    proof=json.loads(path.read_text(encoding='utf-8'))
    approved=[proof.get('previous_runtime'),*proof.get('additional_previous_runtimes',[])]
    expected=dict(Format='jpeg',HimawariDiskSize=11000,JpegQuality=95,NightLightMetres=1000)
    roles={'stock-clouds-day-without-ground-background','shared-static-night-background',
           'stock-ground-transmission','actual-observation-support'}
    return (previous in approved and current==proof.get('runtime') and proof.get('profile')==expected and
        all(profile.get(k)==v for k,v in expected.items()) and
        {row.get('role') for row in proof.get('asset_comparison',[])}==roles and
        all(row['baseline_sha256']==row['candidate_sha256'] for row in proof['asset_comparison']) and
        proof.get('grid')==[11000,11000] and proof.get('quality')==95)


def prior_permits(previous,current,profile):
    if legacy_permits(previous,current,profile):return True
    if profile.get('NightMode') not in ('ai-vis','ai-vis-ir'):return False
    path=Path(__file__).resolve().parents[2]/'resources/performance/night_demand_qualification.json'
    if not path.exists():return False
    proof=json.loads(path.read_text(encoding='utf-8'))
    expected=dict(Format='jpeg',HimawariDiskSize=11000,JpegQuality=95,NightLightMetres=1000)
    roles={'stock-clouds-day-without-ground-background','shared-static-night-background','stock-ground-transmission','actual-observation-support'}
    return (proof.get('schema')=='earthstudio.night_demand.qualification.v1' and
            previous in proof.get('previous_runtimes',[]) and current==proof.get('runtime') and
            all(profile.get(k)==v for k,v in expected.items()) and
            proof.get('both_modes_11k_jpeg_exact') is True and proof.get('strict_blender_anchor') is True and
            {x.get('role') for x in proof.get('asset_comparison',[])}==roles and
            all(x['baseline_sha256']==x['candidate_sha256'] for x in proof['asset_comparison']))


def permits(previous,current,profile):
    if prior_permits(previous,current,profile):return True
    if profile.get('NightMode') not in ('ai-vis','ai-vis-ir'):return False
    path=Path(__file__).resolve().parents[2]/'resources/performance/neutral_reference_qualification.json'
    if not path.exists():return False
    proof=json.loads(path.read_text(encoding='utf-8'))
    expected=dict(Format='jpeg',HimawariDiskSize=11000,JpegQuality=95,NightLightMetres=1000)
    return (proof.get('schema')=='earthstudio.neutral_reference.qualification.v1'
            and previous in proof.get('previous_runtimes',[])
            and current in proof.get('qualified_runtimes',[])
            and all(profile.get(k)==v for k,v in expected.items())
            and proof.get('all_121million_neutral_pixels_exact') is True
            and proof.get('final_neutral_jpeg_exact') is True
            and proof.get('other_science_and_encoding_unchanged') is True)
