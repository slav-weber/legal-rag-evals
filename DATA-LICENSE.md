# Data licence

This repository ships no corpus. The statute texts the system indexes are Ukrainian open data:

- Source: the Verkhovna Rada of Ukraine open-data portal (`data.rada.gov.ua`, act cards and texts)
  and the legislation site (`zakon.rada.gov.ua`).
- Terms: open data of the Verkhovna Rada of Ukraine, reusable with attribution to the source.
- The author claims no rights to the texts of the acts.

What this repository does contain:

- `eval/data/*.jsonl`: reference questions written for this project, citations by act number and
  article, and 193 public FAQ items harvested from an official government FAQ page as raw material
  (`eval/harvest/army_qa.py` is the harvester; the items are not gold data).
- `eval/baselines/*.jsonl`: per-question top-k retrieval baselines with act numbers, unit paths and
  citation stems, no article texts.
- `tests/fixtures/rada_r_sample.txt`: an excerpt of a Rada edition text used as a parser fixture.

Editions and dates of the acts used for the measurements are recorded in the baseline header and in
the run outputs under `eval/results/`.
