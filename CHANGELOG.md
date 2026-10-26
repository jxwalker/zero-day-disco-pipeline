# Changelog

All notable changes are listed here. Versions follow semantic versioning and are tagged `vX.Y.Z`.

## v1.1.0
- Documentation, prompts and code comments rewritten as present-tense requirements.
- Postiz integration IDs moved to the local config (`POSTIZ_TIKTOK_ID`, `POSTIZ_YOUTUBE_ID`).
- Private values (hosts, keys, account IDs) live only in a local `config.env`; see `config.example.env`.

## v1.0.0
- First public release of the pipeline: lyrics generation and lint, karaoke video build, local and Runway clip
  generation, strict QC, and posting scripts.
