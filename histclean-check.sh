#! /usr/bin/env /bin/bash

/opt/homebrew/bin/uv run --with=ruff ruff format ./src/hist/histclean.py --preview
/opt/homebrew/bin/uv run --with=ruff ruff check --fix ./src/hist/histclean.py --ignore=PLW1514 --preview --unsafe-fixes
