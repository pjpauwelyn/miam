# Restaurant Data

This directory holds local restaurant dataset files.

## Expected Files (Phase 3+)

- `restaurants_all.json` — Full Foursquare OS Places dump (food & beverage venues)
  Download from: https://opensource.foursquare.com/os-places/
  Required by: `services/adapters/fsq_os.py` and `scripts/generate_restaurants.py`

## Format

Files should be either:
- A JSON array of venue objects (`[{...}, {...}]`)
- Newline-delimited JSON (one venue per line)

Each venue record is normalised into the `Restaurant` model by `FoursquareOSAdapter`.
