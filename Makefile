EVENT ?= events/2026-11-23-jensen.toml
RUN := uv run

.PHONY: all data processed figures notebooks test

all: data processed figures notebooks

data:         ## pull missing raw source files (never refetches existing ones)
	$(RUN) python -m newsflow fetch $(EVENT)

processed:    ## raw -> data/processed/<event>/*.csv
	$(RUN) python -m newsflow process $(EVENT)

figures:      ## reports/figures/<event>-{zoom,full}.png
	$(RUN) python -m newsflow figures $(EVENT)

notebooks:    ## re-execute notebooks in place (outputs are committed)
	$(RUN) jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=600 notebooks/*.ipynb

test:
	$(RUN) pytest -q
