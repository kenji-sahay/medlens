# MedLens

See what people reported to the U.S. FDA about a medicine, in plain language, for people like you.

MedLens turns a sample of 528,000 FDA adverse-event reports (2015–2025) into something a non-expert can read. You pick a medicine, optionally a second one to compare, and a group of people (age and sex). The app shows what problems were reported, with clear warnings about what reports can and can't tell you.

**These are reports, not risk.** A report doesn't prove a medicine caused a problem, and report counts can't tell anyone how likely a side effect is. MedLens isn't medical advice.

## What's in this folder

| File | What it does |
|---|---|
| `medlens_dataset.ipynb` | The analysis. Its export (section 9) writes `exports/medlens_data.json`, the app's data file. |
| `app.py` | The Streamlit web app. It reads only `exports/medlens_data.json`. |
| `requirements.txt` | What the app needs (Streamlit, pandas, Altair). |
| `requirements-notebook.txt` | What the notebook needs. |
| `.streamlit/config.toml` | The app's colors, which match the notebook's charts. |
| `.gitignore` | Keeps the big CSV out of GitHub but keeps the app's data file. |

## Set it up (about 5 minutes)

You need Python 3.11 or newer (current Streamlit requires it).

```bash
# 1. Make a virtual environment (optional, but it keeps things tidy)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install everything
pip install -r requirements.txt -r requirements-notebook.txt
```

**3. Add the dataset.** Download `fda_adverse_events_2015_2026_CLEAN.csv` from the [Kaggle dataset](https://www.kaggle.com/datasets/kanchana1990/fda-drug-adverse-event-reports-2015-to-2026-faers) and put it in this folder or in a `data/` subfolder.

**4. Run the notebook.** Open `medlens_dataset.ipynb` and choose *Kernel → Restart & Run All* (or *Run All* in VS Code). It takes about a minute. The last code cell prints something like:

```
Wrote exports/medlens_data.json (2.5 MB) with 150 drugs
```

**5. Start the app.**

```bash
streamlit run app.py
```

It opens at http://localhost:8501. If you change the notebook or the data, re-run the notebook and refresh the page.

> **Already ran the notebook before getting this version?** Your old `medlens_data.json` still works, but the app will show only the problems chart and the age chart. Run all the notebook cells again to get everything.

## What the app shows

- **Reported problems.** The top problems for one or two medicines, for any age group and sex. Problems that are really the condition being treated are flagged, entries that aren't health problems (like "Drug ineffective") are hidden, and medical terms are shown in plain words.
- **Who the reports are about.** Age mix, sex, how serious the reports were, and the most common reasons the medicine was taken.
- **What stands out.** PRR: which problems are listed much more often than for other medicines. It's a reason to look closer, not proof.
- **Over time.** Each medicine's share of each year's reports, plus the biggest reporting bursts in the dataset.
- **About the data.** Where the data comes from, how much is missing, and what it can't tell you.

### Accessibility and information-access features

- Every chart has a plain-English **"In short"** sentence above it. The same sentence is the chart's description for screen readers.
- Every chart has a **"Show as a table"** option, and the problem table can be downloaded as a CSV.
- Medical terms are shown in **plain language** by default ("Joint pain", not "Arthralgia"). You can switch this off in the sidebar.
- **Colorblind-safe colors.** The legend and the table give the same information in text.
- **Shareable links.** The address bar keeps the chosen medicines and group, so you can send someone the exact view.
- Groups with fewer than 30 reports aren't compared, and the app says why.
- It works on phones and offline, with no API key, because everything comes from one ~2–3 MB file.

## Put it online (free, Streamlit Community Cloud)

1. Make a GitHub repository and push this folder to it. The `.gitignore` leaves out the CSV, which is too big for GitHub, but keeps `exports/medlens_data.json`. Check that the JSON is committed:
   ```bash
   git add -A && git status    # exports/medlens_data.json should be listed
   ```
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, create a new app from your repository, and set the main file to `app.py`.
3. It installs `requirements.txt` and gives you a public link to put in your submission.

## Demo flow (about 2 minutes)

1. **Reported problems**, default pair (Humira vs Enbrel): point out the "(condition treated)" flags. Several top "side effects" are the illness itself.
2. Change the group to **Female, 66–80**. The picture changes for this group, which is the population lens.
3. **Over time**: the biggest bursts table. One drug took up a fifth of a whole year's reports, nearly all from the US. That's reporting, not risk.
4. **About the data**: how much is missing, and what this can't tell you.

## How the data file is built

`exports/medlens_data.json` covers the 150 most-reported drugs. For each drug it stores:

- the top problems for every age group × sex (top 25 health problems plus up to 5 other entries; groups under 20 reports are left out)
- a profile
- the conditions it's taken for
- PRR for its 15 most-listed problems
- its share of each year's reports

It also stores plain-language names for every term and the dataset-wide facts. To cover more drugs, change `build_app_data(n_drugs=150)` in the notebook's export cell. The file grows by roughly 15–20 KB per drug.

## Data source and limits

The data comes from a third-party sample on Kaggle: 4,000 reports a month from the FDA Adverse Event Reporting System (FAERS), which the FDA now calls the Adverse Event Monitoring System (AEMS). Reports are unverified. Each report lists at most 5 problems. Medicine names aren't fully matched across brands and spellings. The sample isn't the full FDA database.
