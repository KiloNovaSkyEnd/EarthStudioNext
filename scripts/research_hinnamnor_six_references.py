"""Read-only visual research: preserve original pixels, label unmatched views."""
import argparse
import hashlib
import html
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
IDS = ['000082', '000007', '000019', '000046', '000064', '000070']
# Normalized, explicitly selected visual ROIs; not meteorological classifications.
BOXES = {
    '000082': {'eye': (.32, .43, .64, .77), 'lights': (.20, .01, .52, .24)},
    '000007': {'blue': (.61, .03, .90, .34), 'oblique': (.77, .38, .99, .76)},
    '000019': {'ocean_clouds': (.04, .28, .34, .58)},
    '000046': {'eyewall': (.32, .37, .61, .67)},
    '000064': {'fine_clouds': (.68, .65, .96, .95)},
    '000070': {'twilight': (.51, .25, .80, .56)},
}
PROJECT = {
    '000082': 'hinnamnor_targeted_v1/details/combined_screened_4k.png',
    '000007': 'hinnamnor_targeted_v1/render_screened/1130_oblique.png',
    '000019': 'hinnamnor_ocean_v1/diagnostics/0830_legacy.png',
    '000046': 'hinnamnor_geocolor_v1/0830/A_geo_color.png',
    '000064': 'hinnamnor_ocean_v1/diagnostics/0830_candidate.png',
    '000070': 'hinnamnor_ocean_v1/video/0950_candidate_4k.png',
}


def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def dump(p, v):
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding='utf-8')


def protected(output):
    records = {}
    for name in ['data/raw', 'data/processed', 'exports']:
        for p in (ROOT / name).rglob('*'):
            if p.is_file() and not p.is_relative_to(output):
                s = p.stat()
                records[p.relative_to(ROOT).as_posix()] = [s.st_size, s.st_mtime_ns]
    return records


def panel(paths, labels, target, width=800):
    font = ImageFont.load_default(size=16)
    board = Image.new('RGB', (width * len(paths), 500), '#101622')
    draw = ImageDraw.Draw(board)
    for i, (p, label) in enumerate(zip(paths, labels)):
        with Image.open(p) as src:
            im = src.convert('RGB')
            im.thumbnail((width, 450), Image.Resampling.LANCZOS)
            board.paste(im, (i * width + (width - im.width) // 2, 50))
        draw.text((i * width + 8, 8), label, font=font, fill='white')
    board.save(target)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reference-dir', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'crops').mkdir()
    before = protected(out)
    dump(out / 'protected_before.json', before)
    sources = {}
    for name in ['ges', 'scripts', 'tests']:
        for p in (ROOT / name).rglob('*'):
            if p.is_file() and p.suffix in ['.py', '.frag', '.yaml', '.json']:
                sources[p.relative_to(ROOT).as_posix()] = digest(p)
    dump(out / 'source_before.json', sources)
    manifest, evidence, sections = [], {}, []
    originals = []
    for ident in IDS:
        p = args.reference_dir / f'10月19日_{ident}.png'
        originals.append(p)
        with Image.open(p) as im:
            im.load()  # Decode every full-resolution original, not just metadata.
            item = dict(id=ident, path=str(p.resolve()), bytes=p.stat().st_size,
                        size=list(im.size), mode=im.mode, sha256=digest(p),
                        observation_utc=None, crops={})
            for name, relative in BOXES[ident].items():
                box = tuple(round(v * im.size[i % 2]) for i, v in enumerate(relative))
                crop = out / 'crops' / f'{ident}_{name}.png'
                im.crop(box).save(crop)
                item['crops'][name] = dict(original_pixel_box=box, output=crop.relative_to(out).as_posix(),
                                           processing='native pixels, no resizing or colour adjustment')
            manifest.append(item)
        project = ROOT / 'data/processed' / PROJECT[ident]
        evidence[project.relative_to(ROOT).as_posix()] = digest(project)
        pair = out / f'pair_{ident}.jpg'
        panel([p, project], [f'SDK {ident}: UTC/camera unknown',
              ('Satpy A 2022-08-31 08:30 UTC; flat map' if ident == '000046' else
               f'Project: {PROJECT[ident].split("/")[0]}')], pair)
        sections.append(f'<section><h2>{ident}</h2><p>Theme comparison only: different UTC, view, grid and scale. No pixel similarity score.</p><img src="{pair.name}"><p><a href="{html.escape(p.as_uri())}">Original reference</a> | <a href="{project.as_uri()}">Original project/Satpy output</a></p>' + ''.join(
            f'<a href="{c["output"]}"><img class="crop" src="{c["output"]}"></a>' for c in item['crops'].values()) + '</section>')
    # Two rows, six original references; thumbnail resampling is for this sheet only.
    sheet = Image.new('RGB', (1920, 800), '#101622')
    for index, (p, ident) in enumerate(zip(originals, IDS)):
        thumb = out / f'thumb_{ident}.jpg'
        panel([p], [f'SDK {ident} | unknown observation UTC'], thumb, width=640)
        with Image.open(thumb) as im:
            im.thumbnail((640, 400))
            sheet.paste(im, ((index % 3) * 640, (index // 3) * 400))
    sheet.save(out / 'six_reference_contact.jpg')
    dump(out / 'reference_manifest.json', manifest)
    dump(out / 'comparison_source_sha256.json', evidence)
    (out / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Six reference study</title><style>body{background:#111827;color:#eee;font:16px sans-serif;max-width:1640px;margin:30px auto}img{max-width:100%}.crop{max-width:46%;margin:1%}a{color:#9ed2ff}section{margin:50px 0}</style><h1>Six actual SDK references / Hinnamnor evidence study</h1><p>Research only. No renderer/default changes, downloads, weather interpolation, generated texture, saturation or sharpening. Crops preserve native pixels; overview panels are labelled display thumbnails.</p><p><a href="' + (ROOT / 'docs/HINNAMNOR_SIX_REFERENCE_STUDY_V1.md').as_uri() + '">Chinese diagnosis report</a> | <a href="reference_manifest.json">Original provenance and crop coordinates</a></p><img src="six_reference_contact.jpg">' + ''.join(sections), encoding='utf-8')
    # This is a material transfer diagnostic, not an additional satellite observation.
    import numpy as np
    from ges.goni_lowcloud import night_material
    t = np.array([190, 210, 230, 250, 270, 290, 300, 310], dtype=np.float32)
    rgb, alpha = night_material(t, np.ones_like(t), np.zeros_like(t))
    dump(out / 'ir_transfer_diagnostic.json', dict(
        description='Analytical input Kelvin, probability=1, low confidence=0; not a weather retrieval. Official enhancement normalized before alpha/compositing.',
        kelvin=t.tolist(), project_neutral_rgb=rgb[:, 0].tolist(), project_alpha=alpha.tolist(),
        satpy_gray_190_310=np.clip((310-t)/120, 0, 1).tolist(),
        neutral_project_slope_per_K=0.43/130, official_gray_slope_per_K=1/120))
    final = protected(out)
    changes = [p for p, v in before.items() if final.get(p) != v]
    changed_sources = [p for p, sha in sources.items() if digest(ROOT / p) != sha]
    changed_refs = [r['id'] for r in manifest if digest(Path(r['path'])) != r['sha256']]
    dump(out / 'verification.json', dict(full_originals_decoded=len(manifest),
        protected_existing_file_count=len(before), protected_size_mtime_changes=changes,
        code_files_sha256_checked=len(sources), code_sha256_changes=changed_sources,
        reference_sha256_changes=changed_refs, new_download_bytes=0,
        new_gpu_render=False, production_changes=False))
    assert not changes and not changed_sources and not changed_refs
    print(json.dumps(dict(output=str(out), references=len(manifest), protected=len(before), sources=len(sources))))


if __name__ == '__main__':
    main()
