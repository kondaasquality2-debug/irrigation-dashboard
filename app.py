import streamlit as st
import pandas as pd
from datetime import date
from sqlalchemy import create_engine, text

# ================= PAGE CONFIG =================
st.set_page_config(page_title="Irrigation Dashboard", layout="wide")

# ================= DATABASE =================
@st.cache_resource
def get_engine():
    return create_engine("sqlite:///data.db", echo=False)

engine = get_engine()

def run_query(query, params=None):
    with engine.begin() as conn:
        conn.execute(text(query), params or {})

def read_df(query):
    return pd.read_sql(query, engine)

# ================= CREATE TABLES =================
run_query("""
CREATE TABLE IF NOT EXISTS excel_data (
    valve TEXT,
    motor TEXT,
    crop TEXT,
    excel_flow TEXT,
    date DATE,
    PRIMARY KEY (valve, motor, date)
)
""")

run_query("""
CREATE TABLE IF NOT EXISTS supervisor_data (
    valve TEXT,
    motor TEXT,
    date DATE,
    supervisor_flow TEXT,
    remarks TEXT,
    image BLOB,
    PRIMARY KEY (valve, motor, date)
)
""")

# ================= CONSTANTS =================
REMARK_OPTIONS = ["Pipe Leakage", "Extra", "Other"]

# ================= HELPERS =================
def norm_crop(v):
    return "NO CROP" if "NO" in str(v).upper() else "CROP AVAILABLE"

def time_to_flow(v):
    if pd.isna(v):
        return "NO"
    v = str(v).strip()
    return "NO" if v in ["-", "0", "00:00"] else "YES"

def get_status(crop, excel_flow, sup_flow):
    if crop == "CROP AVAILABLE" and excel_flow == "YES" and not sup_flow:
        return "YELLOW"
    if not sup_flow:
        return ""
    if crop == "CROP AVAILABLE" and excel_flow == "YES" and sup_flow == "YES":
        return "GREEN"
    if crop == "CROP AVAILABLE" and excel_flow == "NO" and sup_flow == "YES":
        return "BLUE"
    if crop == "NO CROP" and sup_flow == "YES":
        return "RED"
    return ""

def df_excel():
    return read_df("SELECT * FROM excel_data")

def df_sup():
    return read_df("SELECT * FROM supervisor_data")

# ================= SIDEBAR =================
st.sidebar.title("Menu")
role = st.sidebar.selectbox("Role", ["Admin", "Supervisor", "Dashboard"])

today_str = date.today().strftime("%Y-%m-%d")

if role == "Supervisor":
    sel_date_str = today_str
else:
    sel_date = st.sidebar.date_input("Date", date.today())
    sel_date_str = sel_date.strftime("%Y-%m-%d")

# ================= ADMIN =================
if role == "Admin":
    st.title("⬆️ Upload Irrigation Excel")

    files = st.file_uploader(
        "Upload Excel files (Motor wise)",
        type=["xlsx"],
        accept_multiple_files=True
    )

    for file in files:
        motor = file.name.replace(".xlsx", "")
        df = pd.read_excel(file)

        valve_col, crop_col = df.columns[:2]
        date_cols = df.columns[2:]

        for _, r in df.iterrows():
            for d in date_cols:
                parsed_date = pd.to_datetime(d, dayfirst=True, errors="coerce")
                if pd.isna(parsed_date):
                    continue

                run_query("""
                    INSERT INTO excel_data
                    VALUES (:valve, :motor, :crop, :flow, :date)
                    ON CONFLICT (valve, motor, date)
                    DO UPDATE SET excel_flow = EXCLUDED.excel_flow
                """, {
                    "valve": r[valve_col],
                    "motor": motor,
                    "crop": norm_crop(r[crop_col]),
                    "flow": time_to_flow(r[d]),
                    "date": parsed_date.date()
                })

    if files:
        st.success("Excel uploaded and stored successfully")

# ================= SUPERVISOR =================
elif role == "Supervisor":
    st.title("👨‍🌾 Supervisor Entry")
    st.info(f"📅 Today Only: {sel_date_str}")

    df = df_excel()
    df = df[(df.date == sel_date_str) & (df.crop == "CROP AVAILABLE")]

    for _, r in df.iterrows():
        st.subheader(f"{r.valve} | {r.motor}")

        flow = st.radio(
            "Water Flow",
            ["YES", "NO"],
            horizontal=True,
            key=f"f{r.valve}{r.motor}"
        )

        remark = st.selectbox(
            "Remark",
            ["None"] + REMARK_OPTIONS,
            key=f"r{r.valve}{r.motor}"
        )

        extra = ""
        if remark in ["Extra", "Other"]:
            extra = st.text_input("Specify", key=f"e{r.valve}{r.motor}")

        image_bytes = None
        if remark != "None":
            img = st.file_uploader(
                "Upload Photo (Mandatory)",
                type=["jpg", "png"],
                key=f"i{r.valve}{r.motor}"
            )
            if img:
                image_bytes = img.getvalue()

        if st.button("Save", key=f"s{r.valve}{r.motor}"):
            if remark != "None" and not image_bytes:
                st.error("Image required")
            else:
                final_remark = f"{remark} - {extra}" if extra else remark

                run_query("""
                    INSERT INTO supervisor_data
                    VALUES (:valve, :motor, :date, :flow, :remarks, :image)
                    ON CONFLICT (valve, motor, date)
                    DO UPDATE SET
                        supervisor_flow = EXCLUDED.supervisor_flow,
                        remarks = EXCLUDED.remarks,
                        image = EXCLUDED.image
                """, {
                    "valve": r.valve,
                    "motor": r.motor,
                    "date": sel_date_str,
                    "flow": flow,
                    "remarks": final_remark if remark != "None" else "",
                    "image": image_bytes
                })

                st.success("Saved successfully")

# ================= DASHBOARD =================
else:
    st.title("📊 Irrigation Dashboard")

    ex = df_excel()
    su = df_sup()

    col1, col2 = st.columns(2)
    with col1:
        remark_filter = st.selectbox("Filter Remark", ["All"] + REMARK_OPTIONS)
    with col2:
        show_history = st.checkbox("Show Remark History", True)

    if remark_filter != "All":
        su = su[su.remarks.str.contains(remark_filter, na=False)]

    st.subheader("📌 Remark Count")
    if not su.empty:
        counts = su.remarks.str.extract(
            r"(Pipe Leakage|Extra|Other)"
        )[0].value_counts()
        st.dataframe(counts.rename("Count"))

    if show_history and not su.empty:
        st.subheader("📜 Remark History")
        st.dataframe(su[["date", "valve", "motor", "remarks"]])

    st.subheader("🟢 Daily Status")

    ex = ex[ex.date == sel_date_str]
    su_today = su[su.date == sel_date_str]

    valves = sorted(ex.valve.unique())
    motors = sorted(ex.motor.unique())

    header = st.columns(len(motors) + 1)
    header[0].markdown("### Valve")
    for i, m in enumerate(motors):
        header[i + 1].markdown(f"### {m}")

    for valve in valves:
        row = st.columns(len(motors) + 1)
        row[0].markdown(f"**{valve}**")

        for i, motor in enumerate(motors):
            e = ex[(ex.valve == valve) & (ex.motor == motor)]
            s = su_today[(su_today.valve == valve) & (su_today.motor == motor)]

            if e.empty:
                row[i + 1].write("—")
                continue

            status = get_status(
                e.iloc[0].crop,
                e.iloc[0].excel_flow,
                s.iloc[0].supervisor_flow if not s.empty else ""
            )

            if status == "GREEN":
                row[i + 1].markdown("🟢")
            elif status == "YELLOW":
                row[i + 1].markdown("🟡")
            elif status == "RED":
                row[i + 1].markdown("🔴")
            elif status == "BLUE":
                if row[i + 1].button("🔵", key=f"{valve}{motor}"):
                    st.info(s.iloc[0].remarks)
                    if s.iloc[0].image:
                        st.image(s.iloc[0].image, width=300)
