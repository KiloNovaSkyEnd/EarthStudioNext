# Real AHI B13 regression fixtures

Retrieved 2026-10-18 from NOAA's anonymous S3 archive. No generated pixels.

- `himawari8_20201029_1640_b13.json`: B13 keys and exact byte sizes returned by
  `https://noaa-himawari8.s3.amazonaws.com/?list-type=2&prefix=AHI-L1b-FLDK/2020/10/29/1640/`.
- `ahi_b13_dateline.npz`: real calibrated brightness temperatures in kelvin,
  produced by Satpy 0.60.0 `ahi_hsd` from that scene's ten B13 HSD segments.
  Array selection before reprojection: `y[2686:2814], x[4650:4778]` (zero based).
  The 128x128 array and its exact geostationary extent are stored in the NPZ.
  It includes real observations west of the date line, lost by the old global
  source-area reduction. The regression replaces only HSD decoding; it runs
  actual Satpy nearest-neighbor reprojection on these observed values.

Original projection: geos, lon_0=140.7, h=35785863 m, a=6378137 m,
rf=298.257024882273. Source full disk: 5500x5500, 2000 m nominal resolution.
Catalog scene UTC: 2020-10-29T16:40:00Z. This is a scan timestamp, not a claim
that all full-disk pixels were observed simultaneously.

Fixtures are offline test data, not finished imagery or cloud reconstruction.

## GOES-16 MCMIP C13 subset

`OR_ABI-L2-MCMIPF-M6_G16_s20203031640189_e20203031649508_c20203031650020.nc`
is a 57,820-byte crop of a real NOAA object (430,144,438 bytes originally).
`goes16_subset.json` records the original object key and zero-based crop:
`y[1469:1597], x[5089:5217]`. Retrieved 2026-10-18 UTC.

Only C13, DQF_C13, original x/y coordinates, projection, time, band identifiers
and nominal satellite position variables were retained. Original packed values,
scale/offset/fill definitions and global attributes were copied unchanged;
no pixels were synthesized. Global attributes still describe the original full
disk; this fixture is a crop and is not a complete production MCMIP file.

CMI_C13 is top-of-atmosphere brightness temperature in K, nominal 2 km at
nadir; Satpy exposes C13 with central wavelength 10.35 micrometers.
Scan UTC: 2020-10-29T16:40:18.9Z through 2020-10-29T16:49:50.8Z.
The crop contains 8,244 good, 7 conditionally usable, 3 no-value and 8,130 fill
DQF pixels. Tests exercise the actual NetCDF/Satpy reader and verify that
only good_pixel_qf observations survive the explicit per-band quality filter.

## Meteosat historical catalog responses

`meteosat_zero_20201029.json` and `meteosat_iodc_20201029.json` are actual
anonymous EUMETSAT OpenSearch responses, retrieved 2026-10-18, for collections
`EO:EUM:DAT:MSG:HRSEVIRI` and `EO:EUM:DAT:MSG:HRSEVIRI-IODC`.
Query interval: 2020-10-29T16:20Z–17:00Z, c=100, format=json, endpoint
`https://api.eumetsat.int/data/search-products/1.0.0/os`.
Each contains three catalog records, not satellite pixels. Tests distinguish
the true scan interval from the filename's end time, preserve historical MSG
platform IDs, and explicitly avoid claiming the unlabelled size field is bytes.
# Real paired ABI fixture

`ahi_l2_cloud_evidence_20201029.npz` contains actual NOAA AHI L2 fields cropped
to three 64x64 regions (East China Sea, Sea of Japan, Goni clouds). Its JSON
records exact original object keys, native pixel ranges, units, timestamp and
SHA256. The legacy singleton trailing phase-quality dimension is explicitly
selected. Values are unchanged decoded floats with missing values represented
by NaN. This is an algorithm-evidence fixture, not independent cloud truth.

`goes_multispectral/*.nc` retains the original packed C07/C13 and each band's
DQF, x[5089:5217], y[1469:1597], from the downloaded 2020-10-29 16:40 GOES-16
MCMIPF object. Its JSON records the official NOAA URL, subset, size and SHA256.
This tests real dual-band Kelvin decoding and independent DQF filtering, not
cloud-type accuracy. No synthetic radiances are used in this fixture.

`ahi_china_probable_low_20201029.npz` is an actual 64x64 native China crop
with calibrated B13/B07 and decoded L2 mask, phase, pressure, error and quality.
Its JSON records native row/column ranges, time, units, manifests and SHA256.
The tile was selected to exercise the probable-mask exclusion regression;
it is not a random or independent accuracy sample. Exactly 3,779 pixels have
original low spectral signal >0.3 plus all class-6 retrieval guards.

`seviri_grib_navigation_20201029.json` retains actual ecCodes longitude/
latitude samples for the CLM/CTH/quality fields, original reversed Satpy area
and projection WKT. It reproduces the legacy orientation and coarse-cell
offset failure and verifies the held-out navigation after correction.
`seviri_cloud_support_20201029.npz` (993 bytes) is an actual 64x64 native
cloud-mask tile with nearest sampled 9 km height/quality; all 4096 pixels
meet class 9. Its JSON records source, coordinates, time, mapping and SHA256.
This is a deliberately selected low-top regression tile, not random accuracy
validation or a new fine-resolution height retrieval.

`ahi_china_weak_btd_low_20201029.npz` (69,547 bytes) is a real 64x64 China
crop with L1 Kelvin and delivered L2 fields. Exactly 3,844 pixels have a
supported low-cloud class but zero old LW-SW blue signal. Its JSON records
native row/column ranges, original manifests, UTC, units and SHA256. This
targets a display-veto regression, not a new cloud-type retrieval or truth
sample. It is deliberately separate from the earlier strong-BTD fixture.

# ABI daylight reflective channels, 2020-10-29

`abi_daylight_20201029.npz` is a real 32x32 MCMIP native crop near 90W/30N,
with delivered dimensionless C01/C02/C03 reflectance factors and per-band DQF.
Computed source-scan solar angles are identified separately. JSON records the
actual file, native row/column bounds, units, UTC, byte size and SHA256. No
satellite data downloads occur in tests; this is not independent cloud truth.
