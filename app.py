"""
MedLens: what people reported to the U.S. FDA about a medicine, in plain language.

Run from this folder:
    pip install -r requirements.txt
    streamlit run app.py

The app reads exports/medlens_data.json, which the export cell (section 9) of
medlens_dataset.ipynb writes. To use a file somewhere else, set MEDLENS_DATA=/path/to/file.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
DATA_FILES = [APP_DIR / "exports" / "medlens_data.json", APP_DIR / "data" / "medlens_data.json", APP_DIR / "medlens_data.json"]

SERIES_COLORS = ["#2a78d6", "#eb6834"]  # colorblind-safe pair, same as the notebook's charts
COLOR_ALL = "#6250d6"
INK_2, AXIS, SURFACE = "#52514e", "#c3c2b7", "#fcfcfb"
MIN_REPORTS = 30  # below this, shares jump around too much to compare
NONE = "none"
DEFAULT_PAIR = ("ADALIMUMAB", "ETANERCEPT")  # same pair as the notebook: TNF blockers used for the same conditions
MEDWATCH_URL = "https://www.fda.gov/safety/medwatch-fda-safety-information-and-adverse-event-reporting-program"
AEMS_URL = "https://www.fda.gov/drugs/surveillance-post-drug-approval-activities/fda-adverse-event-monitoring-system-aems"

st.set_page_config(page_title="MedLens", page_icon="💊", layout="wide")


# --------------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------------
def _check(data) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict) or not data.get("drugs"):
        raise ValueError("this doesn't look like medlens_data.json (it needs 'meta' and 'drugs').")
    return data


@st.cache_data(show_spinner="Loading MedLens data…")
def load_file(path: str, modified: float) -> dict:  # `modified` makes the cache reload when the file changes
    return _check(json.loads(Path(path).read_text(encoding="utf-8")))


@st.cache_data(show_spinner="Loading MedLens data…")
def load_upload(raw: bytes) -> dict:
    return _check(json.loads(raw.decode("utf-8")))


def load_data() -> tuple[dict, str]:
    env = os.environ.get("MEDLENS_DATA")
    path = next((p for p in ([Path(env)] if env else []) + DATA_FILES if p.is_file()), None)
    try:
        if path:
            return load_file(str(path), path.stat().st_mtime), path.name
        st.title("MedLens")
        st.warning("MedLens can't find its data file, `exports/medlens_data.json`.")
        st.markdown(
            "1. Put `fda_adverse_events_2015_2026_CLEAN.csv` in this folder or in `data/`.\n"
            "2. Open `medlens_dataset.ipynb` and run every cell (*Kernel → Restart & Run All*). "
            "The export in section 9 writes `exports/medlens_data.json`.\n"
            "3. Refresh this page."
        )
        upload = st.file_uploader("Or upload a medlens_data.json file", type=["json"])
        if upload is None:
            st.stop()
        return load_upload(upload.getvalue()), upload.name
    except (ValueError, UnicodeDecodeError) as err:  # json errors are ValueErrors
        st.error(f"Couldn't read the data file: {err}")
        st.stop()


data, SOURCE_NAME = load_data()
META, DRUGS = data["meta"], data["drugs"]
V2 = META.get("version", 1) >= 2  # older exports have only the top problems per group
TERMS = META.get("terms", {})
AGES = META.get("ages") or ["0–2", "3–12", "13–18", "19–40", "41–65", "66–80", "81+", "Not recorded"]
SEXES = META.get("sexes") or ["Female", "Male", "Not recorded"]
GROUP_MIN = META.get("min_reports", 20)
TOP_KEPT = META.get("top_health", 15)


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------
def pct(v, decimals=0) -> str:
    return "—" if v is None else f"{v:.{decimals}%}"


def age_text(age: str) -> str:
    return {"Any": "Any age", "Not recorded": "Age not recorded"}.get(age, f"{age} years")


def sex_text(sex: str) -> str:
    return {"Any": "Any sex", "Not recorded": "Sex not recorded"}.get(sex, sex)


def who(age="Any", sex="Any") -> str:
    noun = {"Any": "people", "Female": "female patients", "Male": "male patients",
            "Not recorded": "people with no recorded sex"}[sex]
    if age == "Any":
        return f"{noun} of any age"
    return f"{noun} with no recorded age" if age == "Not recorded" else f"{noun} aged {age}"


def drug_name(key: str) -> str:
    label = DRUGS[key].get("label") or key.lower()
    return label[:1].upper() + label[1:]


def brand_names(key: str, k=2) -> list[str]:
    seen, generic = [], drug_name(key).lower()
    for raw in DRUGS[key].get("brands", []):
        for part in str(raw).split(";"):
            name = part.strip().title()
            if name and name.lower() not in ("unknown", generic) and name not in seen:
                seen.append(name)
    return seen[:k]


def drug_option(key: str) -> str:
    brands = brand_names(key)
    return f"{drug_name(key)} ({', '.join(brands)})" if brands else drug_name(key)


def group(key: str, age="Any", sex="Any") -> dict | None:
    return DRUGS[key].get("groups", {}).get(f"{age}|{sex}")


def n_reports(key: str) -> int:
    g = group(key)
    return g["n"] if g else DRUGS[key].get("profile", {}).get("reports", 0)


def is_health(term: str) -> bool:
    info = TERMS.get(term)
    return info["health"] if info else True


def term_label(term: str, use_plain: bool, treated: set[str]) -> str:
    info = TERMS.get(term)
    name = info["plain"] if (use_plain and info) else term
    return name + ("  (condition treated)" if term.lower() in treated else "")


def unique_labels(labels: list[str], terms: list[str]) -> list[str]:
    """Two medical terms can share a plain-language name; keep chart rows distinct."""
    dupes = {l for l in labels if labels.count(l) > 1}
    return [f"{l} [{t}]" if l in dupes else l for l, t in zip(labels, terms)]


def hbar(long: pd.DataFrame, order: list[str], series: list[str], colors: list[str],
         description: str, fmt=".0%", tooltip_title="Share") -> alt.LayerChart:
    """Horizontal bars, grouped by series. `long` has columns label, series, value, reports.
    The legend and axis meaning go in text above the chart (see show_chart), so they wrap on phones."""
    k = len(series)
    height = len(order) * (k * 16 + 14 if k > 1 else 30) + 40  # rows plus room for the x axis
    vmax = float(long["value"].max()) if long["value"].notna().any() else 1.0
    enc = {"y": alt.Y("label:N", sort=order, title=None,
                      axis=alt.Axis(labelLimit=380, labelFontSize=13, ticks=False, domain=False))}
    if k > 1:
        enc["yOffset"] = alt.YOffset("series:N", sort=series)
    base = alt.Chart(long).encode(**enc)
    bars = base.mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("value:Q", title=None, scale=alt.Scale(domain=[0, vmax * 1.18]),
                axis=alt.Axis(format=fmt, tickCount=5, labelFontSize=12)),
        color=alt.Color("series:N", sort=series, scale=alt.Scale(domain=series, range=colors), legend=None),
        tooltip=[alt.Tooltip("series:N", title="Medicine"), alt.Tooltip("label:N", title="Item"),
                 alt.Tooltip("value:Q", title=tooltip_title, format=".1%"),
                 alt.Tooltip("reports:Q", title="Reports", format=",")],
    )
    text = base.mark_text(align="left", dx=4, fontSize=12, color=INK_2).encode(
        x="value:Q", text=alt.Text("value:Q", format=fmt))
    return alt.layer(bars, text).properties(height=height, description=description)


def show_chart(chart, note: str, series: list[str] | None = None, colors: list[str] | None = None):
    """A chart with its key above it: a color swatch per series (if more than one) and what the axis shows."""
    swatches = ""
    if series and len(series) > 1:
        swatches = " ".join(
            f'<span style="white-space:nowrap;margin-right:14px"><span aria-hidden="true" style="display:inline-block;'
            f'width:12px;height:12px;border-radius:2px;background:{c};margin-right:6px;vertical-align:-1px"></span>'
            f"<b>{s}</b></span>" for s, c in zip(series, colors))
    st.markdown(f'<div style="font-size:0.9rem;color:{INK_2};line-height:1.9">{swatches}{note}</div>',
                unsafe_allow_html=True)
    st.altair_chart(chart, width="stretch")


def needs_v2(what: str):
    st.info(f"{what} needs the newer data file. Re-run every cell of `medlens_dataset.ipynb` "
            "(the export is in section 9), then refresh this page.")


# --------------------------------------------------------------------------------------------
# Header and medicine pickers
# --------------------------------------------------------------------------------------------
with st.sidebar:
    st.header("Display options")
    use_plain = st.toggle("Plain-language names", value=True, key="plain", disabled=not TERMS,
                          help="Show 'Joint pain' instead of the medical term 'Arthralgia'.")
    hide_other = st.toggle("Hide entries that aren't health problems", value=True, key="hide", disabled=not TERMS,
                           help="Entries like 'Drug ineffective' or 'Off label use' describe how a medicine was used, "
                                "not a health problem.")
    if not V2:
        st.warning("This data file is from an older export, so some views are missing. "
                   "Re-run the notebook to update it.")
    st.divider()
    st.markdown(f"**Think a medicine caused you a problem?** Talk to your doctor or pharmacist. "
                f"You can also [report it to the FDA through MedWatch]({MEDWATCH_URL}).")
    st.caption(f"Data file: `{SOURCE_NAME}` · {META.get('reports', 0):,} reports")

st.title("MedLens")
st.markdown("#### See what people reported to the U.S. FDA about a medicine, in plain language, "
            "for people like you.")
st.info("**These are reports, not risk.** Anyone can send the FDA a report, and a report doesn't prove the medicine "
        "caused the problem. These numbers can't tell you how likely a side effect is. Don't change how you take a "
        "medicine without talking to a doctor or pharmacist.", icon="ℹ️")

keys = sorted(DRUGS, key=lambda k: drug_option(k).lower())
by_reports = sorted(DRUGS, key=n_reports, reverse=True)
default_a = DEFAULT_PAIR[0] if DEFAULT_PAIR[0] in DRUGS else by_reports[0]
default_b = DEFAULT_PAIR[1] if DEFAULT_PAIR[1] in DRUGS else (by_reports[1] if len(by_reports) > 1 else NONE)
qp = st.query_params  # links keep the chosen medicines and group, so a view can be shared
a0 = qp.get("a") if qp.get("a") in DRUGS else default_a
b0 = qp.get("b") if (qp.get("b") in DRUGS or qp.get("b") == NONE) else default_b
b_options = [NONE] + keys

pick_a, pick_b = st.columns(2)
a = pick_a.selectbox("Medicine", keys, index=keys.index(a0), format_func=drug_option, key="a",
                     help="Type a generic or brand name to search.")
b = pick_b.selectbox("Compare with", b_options, index=b_options.index(b0), key="b",
                     format_func=lambda k: "Nothing, show one medicine" if k == NONE else drug_option(k),
                     help="Comparing medicines used for the same condition is fairest.")
pick_a.caption(f"{n_reports(a):,} reports in this dataset")
if b == a:
    pick_b.caption("That's the same medicine. Pick a different one to compare.")
elif b != NONE:
    pick_b.caption(f"{n_reports(b):,} reports in this dataset")

selected = [a] + ([b] if b not in (NONE, a) else [])
names = [drug_name(k) for k in selected]
colors = SERIES_COLORS[: len(selected)]
treated = set().union(*(DRUGS[k].get("treated", []) for k in selected))

if len(selected) == 2 and V2:
    reasons = [{r.lower() for r in DRUGS[k].get("profile", {}).get("top_reasons", [])} for k in selected]
    if all(reasons) and not (reasons[0] & reasons[1]):
        st.caption("Heads-up: these two medicines are mostly taken for different conditions, so their reports come "
                   "from different groups of people. Differences may reflect the illness, not the medicine.")

tab_problems, tab_who, tab_signal, tab_time, tab_about = st.tabs(
    ["Reported problems", "Who the reports are about", "What stands out", "Over time", "About the data"])

# --------------------------------------------------------------------------------------------
# 1. Reported problems, with the population lens
# --------------------------------------------------------------------------------------------
with tab_problems:
    st.subheader("Which problems were reported?")
    st.markdown("Pick a group of people to see the reports about them.")
    age_options, sex_options = ["Any"] + AGES, ["Any"] + SEXES
    age0 = qp.get("age") if qp.get("age") in age_options else "Any"
    sex0 = qp.get("sex") if qp.get("sex") in sex_options else "Any"
    f_age, f_sex, f_top = st.columns(3)
    age = f_age.selectbox("Age group", age_options, index=age_options.index(age0), format_func=age_text, key="age")
    sex = f_sex.selectbox("Sex", sex_options, index=sex_options.index(sex0), format_func=sex_text, key="sex")
    top_k = f_top.slider("How many problems to show", 5, 20, 10, key="top")

    counts, ns = {}, {}
    for key in selected:
        g = group(key, age, sex)
        ns[key] = g["n"] if g else 0
        if ns[key] < MIN_REPORTS:
            shown = f"only {ns[key]:,}" if ns[key] >= GROUP_MIN else f"fewer than {GROUP_MIN}"
            st.warning(f"**{drug_name(key)}** has {shown} reports for {who(age, sex)}. That's too few to compare, "
                       "so it's left out. Try a wider group.")
            continue
        counts[key] = {t: c for t, c in g["top"] if not (hide_other and not is_health(t))}

    usable = [k for k in counts if counts[k]]
    terms = set().union(*(counts[k] for k in usable)) if usable else set()
    best = sorted(terms, key=lambda t: max(counts[k].get(t, 0) / ns[k] for k in usable), reverse=True)[:top_k]
    if counts and not best:
        st.info("No problems to show for this group.")
    if best:
        labels = unique_labels([term_label(t, use_plain, treated) for t in best], best)
        long = pd.DataFrame([
            {"label": lab, "series": drug_name(k), "reports": counts[k].get(t),
             "value": counts[k][t] / ns[k] if t in counts[k] else None}
            for t, lab in zip(best, labels) for k in usable])

        # Text summary first: the same sentence is the chart's description for screen readers
        tops = []
        for k in usable:
            sub = long[(long.series == drug_name(k)) & long.value.notna()]
            if len(sub):
                row = sub.loc[sub.value.idxmax()]
                tops.append((drug_name(k), row.label.replace("  (condition treated)", ", a condition these medicines treat"),
                             row.value))
        reports_txt = " and ".join(f"{ns[k]:,} reports with {drug_name(k)}" for k in usable)
        if not tops:
            most = ""
        elif len(tops) == 1:
            most = f'The most-listed problem was "{tops[0][1]}" ({tops[0][2]:.0%} of reports).'
        elif tops[0][1] == tops[1][1]:
            most = f'"{tops[0][1]}" was listed most for both ({tops[0][2]:.0%} and {tops[1][2]:.0%} of reports).'
        else:
            most = (f'The most-listed problem was "{tops[0][1]}" for {tops[0][0]} ({tops[0][2]:.0%}) '
                    f'and "{tops[1][1]}" for {tops[1][0]} ({tops[1][2]:.0%}).')
        summary = f"For {who(age, sex)}, there are {reports_txt} as the suspected medicine. {most}"
        st.markdown(f"**In short:** {summary}")

        usable_names, usable_colors = [drug_name(k) for k in usable], [SERIES_COLORS[selected.index(k)] for k in usable]
        show_chart(hbar(long, labels, usable_names, usable_colors, summary),
                   "Bars show the share of each medicine's reports that list the problem.", usable_names, usable_colors)

        notes = [f"Each report lists up to {META.get('max_listed', 5)} problems, so the shares don't add up to 100%."]
        if any("(condition treated)" in l for l in labels):
            notes.append("**(condition treated)** marks problems that match a reason people take these medicines. "
                         "People taking an arthritis medicine report arthritis, so these usually reflect the illness, "
                         "not a side effect.")
        if long.value.isna().any():
            notes.append(f"A missing bar means the problem wasn't among that medicine's {TOP_KEPT} most-listed "
                         "problems for this group, so its share is small but not zero.")
        st.caption(" ".join(notes))

        with st.expander("Show as a table"):
            table = pd.DataFrame({"Problem": labels})
            for k in usable:
                vals = [counts[k].get(t) for t in best]
                table[f"{drug_name(k)}: reports"] = [f"{v:,}" if v is not None else "—" for v in vals]
                table[f"{drug_name(k)}: share"] = [pct(v / ns[k], 1) if v is not None else "—" for v in vals]
            st.table(table.set_index("Problem"))
            st.download_button("Download this table (CSV)", table.to_csv(index=False).encode("utf-8"),
                               file_name=f"medlens_{'_vs_'.join(n.lower() for n in names)}.csv", mime="text/csv",
                               key="dl_problems")

# --------------------------------------------------------------------------------------------
# 2. Who the reports are about
# --------------------------------------------------------------------------------------------
with tab_who:
    st.subheader("Who are the reports about?")
    st.markdown("Each medicine's reports come from different people. Keep this in mind before comparing.")

    rows = []
    for key in selected:
        total = n_reports(key)
        for ag in AGES:
            g = group(key, ag, "Any")
            rows.append({"label": age_text(ag), "series": drug_name(key), "reports": g["n"] if g else None,
                         "value": g["n"] / total if g else None})
    ages_long = pd.DataFrame(rows)
    sentences = []
    for key in selected:
        sub = ages_long[(ages_long.series == drug_name(key)) & (ages_long.label != age_text("Not recorded"))]
        sub = sub[sub.value.notna()]
        missing_age = ages_long[(ages_long.series == drug_name(key)) & (ages_long.label == age_text("Not recorded"))].value.iloc[0]
        if len(sub):
            top = sub.loc[sub.value.idxmax()]
            sentences.append(f"{drug_name(key)}'s reports are most often about people aged {top.label} ({top.value:.0%})"
                             + (f", and {missing_age:.0%} don't record age." if pd.notna(missing_age) else "."))
    age_summary = " ".join(sentences)
    st.markdown(f"**In short:** {age_summary}")
    show_chart(hbar(ages_long, [age_text(x) for x in AGES], names, colors, age_summary),
               "Bars show the share of each medicine's reports in each age group.", names, colors)
    st.caption(f"Age groups with fewer than {GROUP_MIN} reports have no bar.")

    if V2:
        st.markdown("##### Profile of each medicine's reports")
        spec = [("Reports in this dataset", "reports", "int"), ("Female", "female", "pct"), ("Male", "male", "pct"),
                ("Sex not recorded", "sex_not_recorded", "pct"), ("Age not recorded", "age_not_recorded", "pct"),
                ("Median age", "median_age", "num"), ("Marked serious", "serious", "pct"),
                ("Person was hospitalized", "hospitalized", "pct"), ("Life-threatening", "life_threatening", "pct"),
                ("Person died", "died", "pct"), ("Person had recovered when reported", "recovered", "pct"),
                ("Report from the US", "from_us", "pct"), ("Median number of medicines on the report", "median_medicines", "num"),
                ("Most common reasons taken", "top_reasons", "list")]
        prof = {}
        for key in selected:
            p = DRUGS[key].get("profile", {})
            col = []
            for _, field, kind in spec:
                v = p.get(field)
                if v is None:
                    col.append("—")
                elif kind == "int":
                    col.append(f"{int(v):,}")
                elif kind == "pct":
                    col.append(pct(v, 1))
                elif kind == "num":
                    col.append(f"{v:.0f}")
                else:
                    col.append(", ".join(v) if v else "—")
            prof[drug_name(key)] = col
        st.table(pd.DataFrame(prof, index=[s[0] for s in spec]))
        st.caption("Careful with gaps in rows like **Marked serious** or **Person died**. They reflect who sent the "
                   "reports and how sick people already were, as much as the medicines. A gap is a question to ask, "
                   "not an answer. A death in a report doesn't mean the medicine caused it.")
    else:
        needs_v2("The full profile (sex, seriousness, reasons taken)")

# --------------------------------------------------------------------------------------------
# 3. What stands out (PRR)
# --------------------------------------------------------------------------------------------
with tab_signal:
    st.subheader("Which problems stand out?")
    st.markdown(
        "This compares how often a problem is listed for this medicine with how often it's listed for **every other "
        "medicine** in the dataset. **3×** means it's listed three times as often. A common screening rule flags "
        "problems listed at least **2×** as often, in at least 3 reports, with the whole uncertainty range above 1×.\n\n"
        "Standing out is **a reason to look closer, not proof of harm**. It covers all ages and sexes.")
    if not V2:
        needs_v2("This view")
    else:
        for key, color in zip(selected, colors):
            rows = DRUGS[key].get("prr", [])
            st.markdown(f"##### {drug_name(key)}")
            if not rows:
                st.write("Not enough reports to compute this.")
                continue
            d = pd.DataFrame(rows).sort_values("prr", ascending=False)
            if hide_other:
                d = d[[is_health(t) for t in d.term]]
            d["label"] = unique_labels([term_label(t, use_plain, treated) for t in d.term], d.term.tolist())
            d["meets"] = d.flag.map({True: "Yes", False: "No"})
            flagged = d[d.flag].label.str.replace("  (condition treated)", " (condition treated)").tolist()
            sig_summary = (f"For {drug_name(key)}, {len(flagged)} of its {len(d)} most-listed problems meet the screening "
                           f"rule" + (f": {', '.join(flagged)}." if flagged else "."))
            st.markdown(f"**In short:** {sig_summary}")

            lo = min(float(d.low.min()), 0.9) / 1.15
            hi = max(float(d.high.max()), 2.2) * 1.15
            ticks = [t for t in (0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096) if lo <= t <= hi]
            if len(ticks) > 9:  # very wide ranges: label every other tick
                ticks = ticks[::2] if 1 in ticks[::2] else ticks[1::2]
            x_scale = alt.Scale(type="log", domain=[lo, hi])
            x_axis = alt.Axis(values=ticks, labelExpr="datum.value + '×'", labelFontSize=12, title=None)
            y = alt.Y("label:N", sort=d.label.tolist(), title=None,
                      axis=alt.Axis(labelLimit=380, labelFontSize=13, ticks=False, domain=False))
            base = alt.Chart(d).encode(y=y)
            ref = alt.Chart(pd.DataFrame({"x": [1.0]})).mark_rule(color=AXIS, strokeDash=[4, 3]).encode(
                x=alt.X("x:Q", scale=x_scale, axis=x_axis))
            ci = base.mark_rule(strokeWidth=2.5, color=color).encode(
                x=alt.X("low:Q", scale=x_scale, axis=x_axis), x2="high:Q")
            dots = base.mark_point(shape="circle", size=120, strokeWidth=2.5, color=color, opacity=1, filled=False).encode(
                x=alt.X("prr:Q", scale=x_scale, axis=x_axis),
                fill=alt.condition("datum.flag", alt.value(color), alt.value(SURFACE)),
                tooltip=[alt.Tooltip("label:N", title="Problem"), alt.Tooltip("reports:Q", title="Reports", format=","),
                         alt.Tooltip("prr:Q", title="Times as often", format=".2f"),
                         alt.Tooltip("low:Q", title="Range from", format=".2f"),
                         alt.Tooltip("high:Q", title="Range to", format=".2f"),
                         alt.Tooltip("meets:N", title="Meets the screening rule")])
            chart = alt.layer(ref, ci, dots).properties(height=30 * len(d) + 40, description=sig_summary)
            show_chart(chart, "Dots show how many times as often each problem is listed as for other medicines "
                              "(log scale), and lines show the 95% range. <b>Filled dot</b>: meets the screening rule. "
                              "<b>Hollow dot</b>: doesn't. <b>Dashed line</b>: listed as often as for other medicines.")
            with st.expander("Show as a table"):
                st.table(pd.DataFrame({
                    "Problem": d.label, "Reports": d.reports.map("{:,}".format),
                    "Times as often": d.prr.map("{:.2f}×".format),
                    "95% range": [f"{l:.2f}× to {h:.2f}×" for l, h in zip(d.low, d.high)],
                    "Meets the screening rule": d.meets}).set_index("Problem"))
        st.caption("Spikes in reporting also distort this: one medicine's burst of reports makes its problems look "
                   "common in 'all other medicines'.")

# --------------------------------------------------------------------------------------------
# 4. Over time
# --------------------------------------------------------------------------------------------
with tab_time:
    st.subheader("When were these reports sent?")
    per_month = META.get("per_month", [4000, 4000])
    st.markdown(
        f"The dataset holds about {per_month[0]:,} reports every month, so we show each medicine's **share of each "
        "year's reports**. A sudden jump usually means a burst of reporting, often after lawsuits, news coverage or a "
        "new warning. It doesn't mean the medicine suddenly became riskier.")
    if not V2:
        needs_v2("This view")
    else:
        rows, sentences = [], []
        for key in selected:
            ys = {int(y): v for y, v in DRUGS[key].get("year_share", {}).items() if v is not None}
            rows += [{"year": y, "series": drug_name(key), "value": v} for y, v in ys.items()]
            if ys:
                peak = max(ys, key=ys.get)
                typical = float(pd.Series(list(ys.values())).median())
                s = f"{drug_name(key)}'s share peaked in {peak} at {ys[peak]:.1%} of that year's reports (typical year: {typical:.1%})."
                if typical > 0 and ys[peak] > 2 * typical:
                    s += " That's more than twice its usual level, which points to a burst of reporting."
                sentences.append(s)
        time_summary = " ".join(sentences)
        st.markdown(f"**In short:** {time_summary}")
        line = alt.Chart(pd.DataFrame(rows)).mark_line(point=alt.OverlayMarkDef(size=60), strokeWidth=2.5).encode(
            x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0, labelFontSize=12)),
            y=alt.Y("value:Q", title=None, axis=alt.Axis(format=".1~%", labelFontSize=12)),
            color=alt.Color("series:N", sort=names, scale=alt.Scale(domain=names, range=colors), legend=None),
            tooltip=[alt.Tooltip("series:N", title="Medicine"), alt.Tooltip("year:O", title="Year"),
                     alt.Tooltip("value:Q", title="Share of that year's reports", format=".2%")],
        ).properties(height=320, description=time_summary)
        show_chart(line, "Lines show each medicine's share of all the reports sent that year.", names, colors)

        spikes = META.get("spikes", [])
        if spikes:
            st.markdown("##### The biggest reporting bursts in the whole dataset")
            st.table(pd.DataFrame({
                "Medicine": [s["drug"] for s in spikes], "Year": [str(s["year"]) for s in spikes],
                "Share of all that year's reports": [pct(s["share"]) for s in spikes],
                "From the US": [pct(s["from_us"]) for s in spikes],
                "Most-listed problem that year": [s["top_problem"] for s in spikes]}).set_index("Medicine"))
            st.caption("Bursts that arrive in a few months, almost all from the US, and dominated by one problem have "
                       "the marks of stimulated reporting. More reports were filed; that alone doesn't show more harm.")

# --------------------------------------------------------------------------------------------
# 5. About the data
# --------------------------------------------------------------------------------------------
with tab_about:
    st.subheader("About the data")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Reports", f"{META.get('reports', 0):,}")
    if META.get("date_from"):
        m2.metric("Years covered", f"{META['date_from'][:4]}–{META['date_to'][:4]}")
    if META.get("from_us") is not None:
        m3.metric("From the US", pct(META["from_us"]))
    if META.get("serious") is not None:
        m4.metric("Marked serious", pct(META["serious"]))

    st.markdown(
        f"MedLens uses a sample of reports from the FDA Adverse Event Reporting System (FAERS), which the FDA now "
        f"calls the [Adverse Event Monitoring System (AEMS)]({AEMS_URL}): {META.get('source', 'FAERS sample')}. "
        "Patients, doctors, pharmacists and drug companies send these reports.")
    if META.get("source_url"):
        st.markdown(f"Dataset: [FDA Drug Adverse Event Reports on Kaggle]({META['source_url']})")

    missing = META.get("missing")
    if missing:
        miss_long = pd.DataFrame([{"label": k, "series": "Missing", "value": v, "reports": None}
                                  for k, v in sorted(missing.items(), key=lambda kv: -(kv[1] or 0))])
        miss_summary = ("Share of reports missing each detail: "
                        + ", ".join(f"{k.lower()} {pct(v)}" for k, v in sorted(missing.items(), key=lambda kv: -(kv[1] or 0))) + ".")
        st.markdown("##### How often is each detail missing?")
        show_chart(hbar(miss_long, miss_long.label.tolist(), ["Missing"], [COLOR_ALL], miss_summary,
                        tooltip_title="Missing"), "Bars show the share of all reports that leave out each detail.")
        st.caption("Reports missing a detail drop out when you filter on it, so a filtered view never shows everyone.")

    st.markdown("##### What this data can't tell you")
    more = META.get("more_than_listed")
    st.markdown(
        "- **How likely a side effect is.** Nobody knows how many people took each medicine without a problem.\n"
        "- **Whether the medicine caused it.** Reports aren't checked, and people often take several medicines.\n"
        "- **Which medicine is safer.** Report counts depend on how widely a medicine is used, news coverage, "
        "lawsuits and who sends reports.\n"
        f"- **Every problem in a report.** Up to {META.get('max_listed', 5)} problems are listed per report"
        + (f"; {more:.0%} of reports had more." if more is not None else ".") + "\n"
        "- **Every name for a medicine.** Names aren't fully matched across brands, salts and spellings.\n"
        "- **Everything.** This is a sample, not the full FDA database.")
    st.markdown(f"**If you think a medicine harmed you**, talk to your doctor or pharmacist. You can also report it "
                f"to the FDA through [MedWatch]({MEDWATCH_URL}).")
    st.caption("MedLens is a hackathon project about access to health information. It isn't medical advice.")

# Keep the URL in step with the choices, so the current view can be shared as a link
params = {"a": a, "b": b, "age": age, "sex": sex}
if {k: qp.get(k) for k in params} != params:
    st.query_params.from_dict(params)
