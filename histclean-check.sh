#! /usr/bin/env /bin/bash

/opt/homebrew/bin/uv run --with=rich,textual,pygments,ruff --script histclean.py

ruff format ./histclean.py --preview
ruff check --fix histclean.py --ignore=RUF012 --preview



