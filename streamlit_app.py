"""Facebook ADAS Customer Voice - Dashboard V2

Membaca langsung hasil pipeline v2 di data/output/by_vehicle_v2 (tanpa angka
hardcode). Tidak ada ranking antar kendaraan yang menyiratkan 'terbaik'.

Jalankan:
    streamlit run streamlit_app.py
"""
import os
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

import v2_common as vc  # noqa: E402

MASTER = os.path.join(vc.MASTER_DIR, "processing_summary.json")
CLEAN = os.path.join(vc.COMBINED_DIR, "all_vehicles_clean.csv")
RELEVANT = os.path.join(vc.COMBINED_DIR, "all_vehicles_analyzed.csv")
REVIEW = os.path.join(vc.OUTPUT_ROOT, "unknown_or_review.csv")
VSUM = os.path.join(vc.OUTPUT_ROOT, "vehicle_summary.csv")

PALETTE = px.colors.qualitative.Safe
FEATURE_ORDER = ["PDA", "ACC", "PDA+ACC", "ADAS_OTHER", "UNKNOWN"]
EVIDENCE_ORDER = ["direct_experience", "opinion", "question", "hearsay",
                  "specification", "uncertain"]
SENTIMENT_ORDER = ["positive", "neutral", "negative", "mixed"]


@st.cache_data(show_spinner=False)
def load_summary():
    import json
    with open(MASTER, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def load_clean() -> pd.DataFrame:
    return vc.load_df(CLEAN)


@st.cache_data(show_spinner=False)
def load_relevant() -> pd.DataFrame:
    return vc.load_df(RELEVANT)


@st.cache_data(show_spinner=False)
def load_review() -> pd.DataFrame:
    if not os.path.exists(REVIEW):
        return pd.DataFrame()
    return vc.load_df(REVIEW)


@st.cache_data(show_spinner=False)
def load_vehicle_summary() -> pd.DataFrame:
    if not os.path.exists(VSUM):
        return pd.DataFrame()
    return vc.load_df(VSUM)


def downloader(df: pd.DataFrame, label: str, file_base: str) -> None:
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(f"Unduh {label} (.csv)",
                           df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{file_base}.csv", mime="text/csv")
    with col2:
        try:
            xlsx = df.to_excel  # only when openpyxl available; else skip silently
            import io
            buf = io.BytesIO()
            df.to_excel(buf, index=False, engine="openpyxl")
            st.download_button(f"Unduh {label} (.xlsx)", buf.getvalue(),
                               file_name=f"{file_base}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception:
            pass


def bar_counts(df: pd.DataFrame, col: str, title: str, order=None):
    counts = df[col].value_counts()
    if order:
        counts = counts.reindex([o for o in order if o in counts.index]).dropna()
    fig = px.bar(counts, x=counts.index.astype(str), y=counts.values,
                 title=title, color=counts.index.astype(str),
                 color_discrete_sequence=PALETTE)
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="jumlah catatan",
                      height=380)
    return fig


def donut(df: pd.DataFrame, col: str, title: str, order=None):
    counts = df[col].value_counts()
    if order:
        counts = counts.reindex([o for o in order if o in counts.index]).dropna()
    fig = px.pie(counts, names=counts.index.astype(str), values=counts.values,
                 title=title, hole=0.45, color_discrete_sequence=PALETTE)
    fig.update_layout(height=340)
    return fig


def kpis(summary: dict, clean: pd.DataFrame, relevant: pd.DataFrame):
    m = summary.get("master", {})
    adas = summary.get("adas", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total unik (deduplicated)", m.get("deduplicated_rows", len(clean)))
    c2.metric("Kandidat ADAS", adas.get("candidate_records", 0))
    c3.metric("Relevan ADAS", adas.get("relevant_records", len(relevant)))
    c4.metric("Perlu review (kendaraan)", summary.get("unknown_or_review", 0))
    c5.metric("Deduplikasi naik", f"{m.get('dedup_report', {}).get('dedup_rate_pct', 0):.1f}%")


def sidebar_filters(clean: pd.DataFrame):
    st.sidebar.header("Filter")
    vehicles = sorted(clean["vehicle_v2"].dropna().unique()) if "vehicle_v2" in clean else []
    sel_veh = st.sidebar.multiselect("Kendaraan", vehicles, default=vehicles)
    feats = [f for f in FEATURE_ORDER if f in clean["feature"].dropna().unique()]
    sel_feat = st.sidebar.multiselect("Fitur", feats, default=feats)
    sents = [s for s in SENTIMENT_ORDER if s in clean["sentiment"].dropna().unique()]
    sel_sent = st.sidebar.multiselect("Sentimen", sents, default=sents)
    evs = [e for e in EVIDENCE_ORDER if e in clean["evidence_type"].dropna().unique()]
    sel_ev = st.sidebar.multiselect("Tipe bukti", evs, default=evs)
    keyword = st.sidebar.text_input("Kata kunci (di teks)")
    return {"vehicles": sel_veh, "feature": sel_feat, "sentiment": sel_sent,
            "evidence": sel_ev, "keyword": keyword}


def apply_filters(df: pd.DataFrame, sel) -> pd.DataFrame:
    out = df.copy()
    if sel["vehicles"]:
        out = out[out["vehicle_v2"].isin(sel["vehicles"])]
    if sel["feature"]:
        out = out[out["feature"].isin(sel["feature"])]
    if sel["sentiment"]:
        out = out[out["sentiment"].isin(sel["sentiment"])]
    if sel["evidence"]:
        out = out[out["evidence_type"].isin(sel["evidence"])]
    if sel["keyword"]:
        k = sel["keyword"].strip().lower()
        out = out[out["text_clean"].fillna("").str.lower().str.contains(k, na=False)
                  | out["text_raw"].fillna("").str.lower().str.contains(k, na=False)]
    return out


def page_overview(summary, clean, relevant, sel):
    st.header("Overview")
    kpis(summary, clean, relevant)
    st.markdown("Sumber: hasil pipeline V2 (`data/output/by_vehicle_v2`) — "
                "dibangun dari scraper Facebook, tanpa angka hardcode.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(bar_counts(clean, "vehicle_v2",
                                   "Jumlah catatan unik per kendaraan"), use_container_width=True)
    with col_b:
        st.plotly_chart(donut(clean, "feature",
                              "Distribusi fitur (semua kandidat)", FEATURE_ORDER),
                        use_container_width=True)

    col_c, col_d = st.columns(2)
    with col_c:
        cand = clean[clean["candidate_adas"].eq("True")]
        st.plotly_chart(bar_counts(cand, "adas_relevance",
                                   "Relevansi ADAS (kandidat)"), use_container_width=True)
    with col_d:
        st.plotly_chart(donut(relevant, "evidence_type", "Tipe bukti (relevan)",
                              EVIDENCE_ORDER), use_container_width=True)
    downloader(clean, "master clean", "all_vehicles_clean")


def page_vehicle(summary, clean, relevant, sel):
    st.header("Detail Kendaraan")
    vehicles = sorted(clean["vehicle_v2"].dropna().unique())
    veh = st.selectbox("Kendaraan", vehicles)
    sub = clean[clean["vehicle_v2"].eq(veh)]
    rel = relevant[relevant["vehicle_v2"].eq(veh)]
    sm = summary.get("vehicles", {}).get(veh, {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Catatan unik", sm.get("raw_records", len(sub)))
    c2.metric("Relevan ADAS", sm.get("relevant_records", len(rel)))
    c3.metric("Komunitas", sm.get("communities", 0))
    c4.metric("Post unik", sm.get("unique_posts", 0))

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(donut(sub, "feature", f"Fitur - {veh}", FEATURE_ORDER),
                        use_container_width=True)
    with col_b:
        st.plotly_chart(bar_counts(sub, "community", "Catatan per komunitas"),
                        use_container_width=True)
    if not rel.empty:
        st.plotly_chart(donut(rel, "sentiment", "Sentimen suara pelanggan",
                              SENTIMENT_ORDER), use_container_width=True)
    st.subheader("Catatan relevan")
    st.dataframe(rel[["date", "community", "feature", "subfeature", "evidence_type",
                      "sentiment", "text_clean", "url"]], use_container_width=True)
    downloader(rel, "relevan", f"{veh}_relevant")


def page_feature(summary, clean, sel, feature_tag):
    st.header(feature_tag)
    tags = {"PDA": ["PDA", "PDA+ACC"], "ACC": ["ACC", "PDA+ACC"]}[feature_tag]
    sub = clean[clean["feature"].isin(tags)]
    if sub.empty:
        st.info("Belum ada catatan untuk fitur ini.")
        return
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(bar_counts(sub, "vehicle_v2", f"Mention {feature_tag} per kendaraan"),
                        use_container_width=True)
    with c2:
        st.plotly_chart(donut(sub, "evidence_type", "Tipe bukti", EVIDENCE_ORDER),
                        use_container_width=True)
    st.plotly_chart(donut(sub, "sentiment", "Sentimen", SENTIMENT_ORDER),
                    use_container_width=True)
    st.subheader(f"Catatan {feature_tag}")
    st.dataframe(sub[["vehicle_v2", "community", "date", "subfeature", "evidence_type",
                      "sentiment", "smoothness", "expectation_mismatch", "text_clean", "url"]],
                 use_container_width=True)
    downloader(sub, feature_tag, f"feature_{feature_tag.lower()}")


def quote_card(row: pd.Series):
    tag = row.get("feature", "")
    if tag not in ("PDA+ACC", "ACC", "PDA"):
        tag = "ADAS"
    st.markdown(
        f"**[{tag}]** {row.get('vehicle_v2', '')} · {row.get('community', '')} · "
        f"{row.get('sentiment', '')} · {row.get('evidence_type', '')}")
    st.write(row.get("text_clean", ""))
    if row.get("url"):
        st.caption(f"Sumber: {row.get('url', '')}")
    st.markdown("---")


def page_customer_voice(clean, relevant, sel):
    st.header("Customer Voice")
    st.markdown("Hanya catatan yang **relevan** (suara pelanggan) — question/opinion/"
                "direct_experience tetap dibedakan agar jumlah komentar tidak dibaca "
                "sebagai kualitas ADAS.")
    rel = apply_filters(relevant, sel)
    c1, c2, c3 = st.columns(3)
    c1.metric("Kutipan relevan", len(rel))
    c2.metric("Direct experience", int(rel["evidence_type"].eq("direct_experience").sum()))
    c3.metric("Pertanyaan", int(rel["evidence_type"].eq("question").sum()))
    st.plotly_chart(donut(rel, "evidence_type", "Tipe bukti", EVIDENCE_ORDER),
                    use_container_width=True)
    st.subheader("Representasi sentimen")
    st.plotly_chart(donut(rel, "sentiment", "Sentimen", SENTIMENT_ORDER),
                    use_container_width=True)
    st.subheader("Kutipan")
    for _, row in rel.iterrows():
        quote_card(row)
    downloader(rel, "customer_voice", "customer_voice")


def page_data_quality(clean, relevant, summary, sel):
    st.header("Data Quality")
    cand = clean[clean["candidate_adas"].eq("True")]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total unik", len(clean))
    c2.metric("Kandidat ADAS", len(cand))
    c3.metric("Relevan", len(relevant))
    c4.metric("Low confidence (review)", summary.get("unknown_or_review", 0))

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(donut(clean, "vehicle_confidence", "Confidence kendaraan"),
                        use_container_width=True)
    with col_b:
        reasons = cand["relevance_reason"].value_counts()
        st.plotly_chart(px.bar(reasons, x=reasons.index.astype(str), y=reasons.values,
                               title="Alasan relevansi", color=reasons.index.astype(str),
                               color_discrete_sequence=PALETTE)
                        .update_layout(showlegend=False, xaxis_title="", height=380),
                        use_container_width=True)

    st.subheader("Duplikasi konten (teks identik di beda thread/post)")
    dup = clean.assign(_t=clean["text_normalized"])
    dup = dup[dup["_t"].ne("")]
    dup_count = dup["_t"].value_counts()
    dup_frame = dup_count[dup_count > 1]
    if not dup_frame.empty:
        st.plotly_chart(px.bar(dup_frame.head(15), x=dup_frame.head(15).index, y=dup_frame.head(15).values,
                               title="15 teks paling sering terulang (jumlah baris)",
                               color_discrete_sequence=PALETTE)
                        .update_layout(showlegend=False, xaxis_title="", height=400),
                        use_container_width=True)
    st.write("Teks identik yang berulang antar-thread tetap dihitung sebagai baris "
             "terpisah (dedup berbasis post/comment identity, bukan isi teks).")

    st.subheader("Perlu review (identitas kendaraan ambigu)")
    review = load_review()
    st.metric("Baris review", len(review))
    st.dataframe(review[["record_id", "vehicle", "community", "vehicle_v2",
                         "vehicle_confidence", "vehicle_reason", "text_clean"]],
                 use_container_width=True)
    downloader(review, "review", "unknown_or_review")


def main() -> None:
    st.set_page_config(page_title="Facebook ADAS Customer Voice",
                       layout="wide",
                       page_icon="🚗")
    st.title("Facebook ADAS Customer Voice — V2")

    summary = load_summary()
    clean = load_clean()
    clean["feature"] = clean.get("feature", "UNKNOWN").fillna("UNKNOWN")
    relevant = load_relevant()
    if relevant.empty and os.path.exists(RELEVANT):
        relevant = clean[clean["adas_relevance"].eq("relevant")]
    sel = sidebar_filters(clean)

    page = st.radio("Halaman", ["Overview", "Detail Kendaraan", "PDA", "ACC",
                                "Customer Voice", "Data Quality"],
                    horizontal=True)
    if page == "Overview":
        page_overview(summary, clean, relevant, sel)
    elif page == "Detail Kendaraan":
        page_vehicle(summary, clean, relevant, sel)
    elif page == "PDA":
        page_feature(summary, apply_filters(clean, sel), sel, "PDA")
    elif page == "ACC":
        page_feature(summary, apply_filters(clean, sel), sel, "ACC")
    elif page == "Customer Voice":
        page_customer_voice(clean, relevant, sel)
    else:
        page_data_quality(clean, relevant, summary, sel)


if __name__ == "__main__":
    main()