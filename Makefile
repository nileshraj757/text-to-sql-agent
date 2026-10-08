.PHONY: data db testset test redteam ladder demo up
data: ; ./scripts/download_data.sh
db: ; python scripts/build_db.py
testset: ; python eval/build_testset.py && python eval/verify_gold.py
test: ; pytest -q
redteam: ; python eval/redteam/run_redteam.py && python eval/check_redteam.py eval/results/redteam_offline.json
ladder: ; python eval/run_ladder.py --run --split dev && python eval/plots.py   # needs an LLM key
demo: ; streamlit run app/streamlit_app.py
up: ; docker compose up --build
