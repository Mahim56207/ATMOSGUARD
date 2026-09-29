# One-word commands for the things people ask for. Windows users: run the commands under each target by hand.
PY ?= python

.PHONY: setup test api dashboard replay results report assets clean-cache

setup:            ## install the pinned requirements
	$(PY) -m pip install -r requirements.txt

test:             ## the whole test suite (400+ tests, includes the C++ edge-parity tests; needs g++)
	$(PY) -m pytest -q

api:              ## the API on :8000 with the six committed station models
	$(PY) -m uvicorn api:app --port 8000

dashboard:        ## the dashboard on :8501 (start `make api` first)
	$(PY) -m streamlit run dashboard.py

replay:           ## replay Cyclone Vardah (Chennai) through the running API
	$(PY) replay.py data/demo/vardah_MAA_2016-12.csv --speed 0

results:          ## rebuild the tables, README blocks and Q&A numbers from the committed result files
	$(PY) make_summary.py results/dev_run4.json results/holdout_run2.json results/fresh_run1.json --scale results/scale.json --coldstart results/coldstart.json --readme README.md --numbers docs/JUDGE_QA.md docs/SUBMISSION_TEXT.md

report: results   ## figures, the technical report (Markdown and Word, needs pypandoc_binary for the Word file) and the offline replay page
	$(PY) make_figures.py
	$(PY) make_report.py --docx
	$(PY) make_offline_demo.py

assets:           ## diagrams, the one-page PDF and dashboard screenshots (needs Playwright and a Chromium)
	$(PY) make_diagrams.py
	$(PY) make_onepager.py
	$(PY) capture_dashboard.py

clean-cache:      ## remove Python caches
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
