#! /usr/bin/env /bin/bash

/opt/homebrew/bin/uv run --with=ruff ruff format ./histclean.py --preview
/opt/homebrew/bin/uv run --with=ruff ruff check --fix histclean.py --ignore=RUF012 --preview



