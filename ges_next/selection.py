"""Precise operational boundaries plus mandatory independent archive evidence.

Candidate names alone NEVER establish availability, pixel support or quality.
Role intervals are a versioned prior, not a substitute for provider catalogues.
"""
from dataclasses import dataclass
from datetime import datetime,timezone


def utc(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    if result.tzinfo is None or result.utcoffset().total_seconds()!=0:
        raise ValueError('Explicit UTC required')
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class Candidate:
    satellite: str
    instrument: str
    operational: bool
    reason: str


def candidates(when,region):
    t=utc(when)
    if t<utc('2018-01-01T00:00:00Z'):raise ValueError('Supported archive starts in 2018')
    reason='Official role boundary; actual archive and pixel quality still required'
    if region=='asia_pacific':
        primary='himawari8' if t<utc('2022-12-13T05:00:00Z') else 'himawari9'
        return [Candidate(primary,'ahi',True,reason)]
    if region=='americas_east':
        new=t>=utc('2025-04-07T15:10:00Z')
        result=[Candidate('goes19' if new else 'goes16','abi',True,reason)]
        if new:result.append(Candidate('goes16','abi',False,'Archive-only fallback; storage status is not a data guarantee'))
        return result
    if region=='americas_west':
        new=t>=utc('2023-01-04T18:00:00Z')
        result=[Candidate('goes18' if new else 'goes17','abi',True,reason)]
        if new:result.append(Candidate('goes17','abi',False,'Archive-only fallback; availability must be probed'))
        elif t>=utc('2022-03-01T00:00:00Z'):
            result.append(Candidate('goes18','abi',False,'Test/interleave candidate only; not presumed present'))
        return result
    if region=='europe_africa':
        if t>=utc('2025-06-17T00:00:00Z'):
            return [Candidate('meteosat12','fci',True,'Prime service documented June 2025; exact transition-day role requires provider audit')]
        return [Candidate('meteosat_zero','seviri',False,'Historical slot; platform identity/role must come from provider metadata')]
    if region=='indian_ocean':
        return [Candidate('meteosat_iodc','seviri',False,'IODC slot; verify actual platform, position and quality from catalogue')]
    raise ValueError('Unknown region')


def select(when,region,probe,tolerance_seconds=600,allowed_satellites=None):
    when=utc(when)
    if not 0<=tolerance_seconds<=900:raise ValueError('Bounded scan tolerance required')
    attempts=[]
    for candidate in candidates(when,region):
        if allowed_satellites is not None and candidate.satellite not in allowed_satellites: continue
        record={'satellite':candidate.satellite,'instrument':candidate.instrument,
                'operational_prior':candidate.operational,'role_reason':candidate.reason}
        try:
            evidence=probe(candidate,when)
            if not evidence or not evidence.get('complete'):
                record['state']='missing';record['reason']='Required bands/segments not proven complete'
            else:
                actual=utc(evidence['observed_utc'])
                if abs((actual-when).total_seconds())>tolerance_seconds:
                    record.update(state='rejected',reason='Scan outside requested UTC tolerance')
                elif not evidence.get('keys') or int(evidence.get('total_bytes',0))<=0:
                    record.update(state='rejected',reason='No actual objects and positive size evidence')
                elif evidence.get('satellite')!=candidate.satellite:
                    record.update(state='rejected',reason='Platform identity differs from candidate')
                else:
                    record.update(state='catalog_available',evidence=evidence,
                        reason='Actual L1 bands present; calibration/navigation/pixel quality not yet accepted')
        except FileNotFoundError:
            record.update(state='missing',reason='No matching archive objects')
        except Exception:
            record.update(state='unavailable',reason='Provider request/adapter failed; not equivalent to no data')
        attempts.append(record)
        if record['state']=='catalog_available':
            return {'selected':record,'attempts':attempts,'pixel_quality_verified':False}
    return {'selected':None,'attempts':attempts,'pixel_quality_verified':False}
