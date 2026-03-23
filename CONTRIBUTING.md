# Contributing

Thanks for taking a look at OpenBioSignal.

## Development Setup

1. Create and activate a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and configure local values.
4. Start the app with `uvicorn app.main:app --reload`.

## Project Approach

This project is intentionally:

- local-first
- small in scope
- inspectable
- conservative about new dependencies and infrastructure

When contributing, prefer readable incremental improvements over large abstractions.

## Good First Contributions

- improve retrieval, extraction, or evaluation quality
- improve prompt clarity
- improve UI readability for research review
- improve local documentation and examples
- fix bugs in persistence or schema alignment

## Before Opening a PR

- keep changes focused
- avoid unrelated refactors
- run the app locally if your change affects runtime behavior
- note any limitations or trade-offs honestly in your PR description
