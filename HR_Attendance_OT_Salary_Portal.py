import streamlit as st
import pandas as pd
import sqlite3
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="HR Attendance, OT & Salary Portal",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_FILE = "attendance.db"

# ============================================================
# DATABASE
# ============================================================
def get_connection():
    return sqlite3.connect(DB_FILE)


def create_database():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS punching_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_date TEXT NOT NULL,
            punch_time TEXT NOT NULL,
            department TEXT,
            employee_code TEXT NOT NULL,
            employee_name TEXT,
            location_name TEXT,
            entry_exit TEXT,
            UNIQUE(transaction_date, punch_time, employee_code, location_name, entry_exit)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS salary_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE NOT NULL,
            monthly_salary REAL DEFAULT 0,
            working_days REAL DEFAULT 26,
            daily_wage REAL DEFAULT 0,
            ot_rate REAL DEFAULT 0,
            attendance_allowance REAL DEFAULT 0,
            food_allowance REAL DEFAULT 0,
            travel_allowance REAL DEFAULT 0,
            other_allowance REAL DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employee_salary (
            employee_code TEXT PRIMARY KEY,
            employee_name TEXT,
            category TEXT,
            extra_wages REAL DEFAULT 0,
            extra_allowance REAL DEFAULT 0,
            deduction REAL DEFAULT 0,
            remarks TEXT
        )
    """)
    conn.commit()
    conn.close()


def ensure_default_category():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM salary_categories")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO salary_categories
            (category, monthly_salary, working_days, daily_wage, ot_rate,
             attendance_allowance, food_allowance, travel_allowance, other_allowance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("General", 0, 26, 0, 0, 0, 0, 0, 0))
    conn.commit()
    conn.close()


def insert_punching_data(data):
    conn = get_connection()
    cur = conn.cursor()
    inserted = 0
    duplicates = 0
    for _, row in data.iterrows():
        try:
            cur.execute("""
                INSERT OR IGNORE INTO punching_data
                (transaction_date, punch_time, department, employee_code,
                 employee_name, location_name, entry_exit)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                str(row["Transaction Date"]), str(row["Time"]),
                str(row["Department"]), str(row["Employee Code"]),
                str(row["Employee Name"]), str(row["Location Name"]),
                str(row["ENTRY/EXIT"]),
            ))
            if cur.rowcount == 1:
                inserted += 1
            else:
                duplicates += 1
        except Exception:
            duplicates += 1
    conn.commit()
    conn.close()
    return inserted, duplicates


def load_data():
    conn = get_connection()
    df = pd.read_sql_query("""
        SELECT id, transaction_date, punch_time, department, employee_code,
               employee_name, location_name, entry_exit
        FROM punching_data
        ORDER BY transaction_date DESC, punch_time DESC
    """, conn)
    conn.close()
    if not df.empty:
        df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
        df["punch_time"] = df["punch_time"].astype(str)
    return df


def clear_punching_data():
    conn = get_connection()
    conn.execute("DELETE FROM punching_data")
    conn.commit()
    conn.close()


def load_categories():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM salary_categories ORDER BY category", conn)
    conn.close()
    return df


def save_category(row):
    conn = get_connection()
    conn.execute("""
        INSERT INTO salary_categories
        (category, monthly_salary, working_days, daily_wage, ot_rate,
         attendance_allowance, food_allowance, travel_allowance, other_allowance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(category) DO UPDATE SET
            monthly_salary=excluded.monthly_salary,
            working_days=excluded.working_days,
            daily_wage=excluded.daily_wage,
            ot_rate=excluded.ot_rate,
            attendance_allowance=excluded.attendance_allowance,
            food_allowance=excluded.food_allowance,
            travel_allowance=excluded.travel_allowance,
            other_allowance=excluded.other_allowance
    """, row)
    conn.commit()
    conn.close()


def delete_category(category):
    conn = get_connection()
    conn.execute("DELETE FROM salary_categories WHERE category=?", (category,))
    conn.commit()
    conn.close()


def load_employee_salary():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM employee_salary ORDER BY employee_code", conn)
    conn.close()
    return df


def save_employee_salary(row):
    conn = get_connection()
    conn.execute("""
        INSERT INTO employee_salary
        (employee_code, employee_name, category, extra_wages, extra_allowance, deduction, remarks)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(employee_code) DO UPDATE SET
            employee_name=excluded.employee_name,
            category=excluded.category,
            extra_wages=excluded.extra_wages,
            extra_allowance=excluded.extra_allowance,
            deduction=excluded.deduction,
            remarks=excluded.remarks
    """, row)
    conn.commit()
    conn.close()


def delete_employee_salary(code):
    conn = get_connection()
    conn.execute("DELETE FROM employee_salary WHERE employee_code=?", (code,))
    conn.commit()
    conn.close()


create_database()
ensure_default_category()

# ============================================================
# HELPERS
# ============================================================
def normalize_direction(value):
    v = str(value).strip().lower()
    if v in {"entry", "in", "checkin", "check-in", "punch in"}:
        return "IN"
    if v in {"exit", "out", "checkout", "check-out", "punch out"}:
        return "OUT"
    return v.upper()


def parse_time(value):
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.time()
    if hasattr(value, "time") and not isinstance(value, str):
        try:
            return value.time()
        except Exception:
            pass
    if isinstance(value, (int, float)):
        # Excel time fraction
        seconds = int(round(float(value) * 24 * 3600)) % 86400
        return (datetime.min + timedelta(seconds=seconds)).time()
    s = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    try:
        return pd.to_datetime(s).time()
    except Exception:
        return None


def format_td(td):
    if pd.isna(td) or td is None:
        return ""
    total = max(0, int(td.total_seconds()))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def hours_float(td):
    if td is None or pd.isna(td):
        return 0.0
    return max(0.0, td.total_seconds() / 3600)


def normalize_punching(raw):
    data = raw.copy()
    mapping = {}
    for c in data.columns:
        key = str(c).strip().lower().replace("\n", " ")
        if key == "transaction date": mapping[c] = "Transaction Date"
        elif key == "time": mapping[c] = "Time"
        elif key == "department": mapping[c] = "Department"
        elif key == "employee code": mapping[c] = "Employee Code"
        elif key == "employee name": mapping[c] = "Employee Name"
        elif key == "location name": mapping[c] = "Location Name"
        elif "entry/exit" in key or ("entry" in key and "exit" in key) or key in {"in/out", "in out"}:
            mapping[c] = "ENTRY/EXIT"
    data = data.rename(columns=mapping)
    required = ["Transaction Date", "Time", "Employee Code", "Employee Name", "ENTRY/EXIT"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(missing))
    for c in ["Department", "Location Name"]:
        if c not in data.columns:
            data[c] = ""
    data["Transaction Date"] = pd.to_datetime(data["Transaction Date"], errors="coerce").dt.date
    data["Time Parsed"] = data["Time"].apply(parse_time)
    data["ENTRY/EXIT"] = data["ENTRY/EXIT"].apply(normalize_direction)
    data["Employee Code"] = data["Employee Code"].astype(str).str.strip()
    data["Employee Name"] = data["Employee Name"].fillna("").astype(str).str.strip()
    data = data.dropna(subset=["Transaction Date", "Time Parsed", "Employee Code"])
    return data


def build_daily_report(punches, duty_hours=8):
    if punches.empty:
        return pd.DataFrame()
    x = punches.copy()
    x["Date"] = pd.to_datetime(x["Transaction Date"])
    x["Time"] = x["Time Parsed"].apply(lambda t: datetime.combine(date.today(), t) if t else pd.NaT)
    rows = []
    for (code, dt), g in x.groupby(["Employee Code", "Date"]):
        g = g.sort_values("Time")
        ins = g.loc[g["ENTRY/EXIT"] == "IN", "Time"]
        outs = g.loc[g["ENTRY/EXIT"] == "OUT", "Time"]
        first_in = ins.min() if not ins.empty else pd.NaT
        last_out = outs.max() if not outs.empty else pd.NaT
        work = (last_out - first_in) if pd.notna(first_in) and pd.notna(last_out) else pd.NaT
        duty = timedelta(hours=float(duty_hours))
        ot = max(work - duty, timedelta(0)) if pd.notna(work) else timedelta(0)
        short = max(duty - work, timedelta(0)) if pd.notna(work) else timedelta(0)
        rows.append({
            "Employee Code": str(code),
            "Employee Name": g["Employee Name"].iloc[0],
            "Department": g["Department"].iloc[0],
            "Location": g["Location Name"].iloc[0],
            "Date": dt.date(),
            "First IN": first_in.time() if pd.notna(first_in) else None,
            "Last OUT": last_out.time() if pd.notna(last_out) else None,
            "Working Hours": work,
            "Duty Hours": duty,
            "OT Hours": ot,
            "Short Hours": short,
            "IN Punches": int((g["ENTRY/EXIT"] == "IN").sum()),
            "OUT Punches": int((g["ENTRY/EXIT"] == "OUT").sum()),
            "Status": "Present" if pd.notna(first_in) else "Absent/No IN",
        })
    out = pd.DataFrame(rows)
    for c in ["Working Hours", "Duty Hours", "OT Hours", "Short Hours"]:
        if c in out.columns:
            out[c] = out[c].apply(format_td)
    return out.sort_values(["Date", "Employee Code"])


def build_salary_report(daily, categories, employee_master, duty_hours=8):
    if daily.empty:
        return pd.DataFrame()
    d = daily.copy()
    d["Date"] = pd.to_datetime(d["Date"])
    d["OT Hours Decimal"] = d["OT Hours"].apply(lambda x: hours_float(pd.to_timedelta(x)))
    attendance = d.groupby(["Employee Code", "Employee Name"], as_index=False).agg(
        Present_Days=("Date", "nunique"),
        OT_Hours=("OT Hours Decimal", "sum"),
    )
    emp = employee_master.copy() if not employee_master.empty else pd.DataFrame(columns=["employee_code", "employee_name", "category", "extra_wages", "extra_allowance", "deduction", "remarks"])
    emp = emp.rename(columns={"employee_code":"Employee Code", "employee_name":"Master Name", "category":"Category", "extra_wages":"Extra Wages", "extra_allowance":"Extra Allowance", "deduction":"Deduction", "remarks":"Remarks"})
    result = attendance.merge(emp, on="Employee Code", how="left")
    result["Employee Name"] = result["Employee Name"].fillna(result.get("Master Name", ""))
    result["Category"] = result["Category"].fillna("General")
    cats = categories.rename(columns={
        "category":"Category", "monthly_salary":"Monthly Salary", "working_days":"Working Days",
        "daily_wage":"Daily Wage", "ot_rate":"OT Rate", "attendance_allowance":"Attendance Allowance",
        "food_allowance":"Food Allowance", "travel_allowance":"Travel Allowance", "other_allowance":"Other Allowance"
    })
    result = result.merge(cats[["Category","Monthly Salary","Working Days","Daily Wage","OT Rate","Attendance Allowance","Food Allowance","Travel Allowance","Other Allowance"]], on="Category", how="left")
    for c in ["Monthly Salary","Working Days","Daily Wage","OT Rate","Attendance Allowance","Food Allowance","Travel Allowance","Other Allowance","Extra Wages","Extra Allowance","Deduction"]:
        if c not in result.columns:
            result[c] = 0.0
        result[c] = pd.to_numeric(result[c], errors="coerce").fillna(0.0)
    result["Daily Wage"] = result.apply(lambda r: r["Daily Wage"] if r["Daily Wage"] > 0 else (r["Monthly Salary"] / r["Working Days"] if r["Working Days"] > 0 else 0), axis=1)
    result["Regular Wages"] = result["Present_Days"] * result["Daily Wage"]
    result["OT Wages"] = result["OT_Hours"] * result["OT Rate"]
    result["Attendance Allowance Total"] = result["Present_Days"] * result["Attendance Allowance"]
    result["Food Allowance Total"] = result["Present_Days"] * result["Food Allowance"]
    result["Travel Allowance Total"] = result["Present_Days"] * result["Travel Allowance"]
    result["Other Allowance Total"] = result["Other Allowance"]
    result["Gross Wages"] = (result["Regular Wages"] + result["OT Wages"] + result["Attendance Allowance Total"] + result["Food Allowance Total"] + result["Travel Allowance Total"] + result["Other Allowance Total"] + result["Extra Wages"] + result["Extra Allowance"])
    result["Net Payable"] = result["Gross Wages"] - result["Deduction"]
    result = result.rename(columns={"Present_Days":"Present Days", "OT_Hours":"OT Hours"})
    cols = ["Employee Code","Employee Name","Category","Present Days","Daily Wage","Regular Wages","OT Hours","OT Rate","OT Wages","Attendance Allowance Total","Food Allowance Total","Travel Allowance Total","Other Allowance Total","Extra Wages","Extra Allowance","Gross Wages","Deduction","Net Payable","Remarks"]
    return result[cols].sort_values(["Category","Employee Code"])


def money(x):
    return f"₹{float(x):,.2f}"


def export_excel(sheets):
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        for name, data in sheets.items():
            data.to_excel(writer, index=False, sheet_name=name[:31])
    bio.seek(0)
    return bio

# ============================================================
# LOGIN
# ============================================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.markdown("""
    <style>
    .login-wrap{max-width:520px;margin:8vh auto;padding:35px;border-radius:24px;background:rgba(255,255,255,.92);border:1px solid #e5e7eb;box-shadow:0 20px 60px rgba(15,23,42,.12)}
    .login-logo{font-size:42px;text-align:center}.login-title{text-align:center;font-size:30px;font-weight:800;color:#111827}.login-sub{text-align:center;color:#64748b;margin-bottom:25px}
    </style>
    <div class="login-wrap"><div class="login-logo">💼</div><div class="login-title">HR Attendance & Salary Portal</div><div class="login-sub">Secure employee attendance, OT and wage management</div></div>
    """, unsafe_allow_html=True)
    with st.form("login_form"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        remember = st.checkbox("Remember Me", value=True)
        submit = st.form_submit_button("🔐 Login", use_container_width=True)
        if submit:
            if u == "admin" and p == "password":
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Invalid username or password")
    st.stop()

# ============================================================
# STYLE / SIDEBAR
# ============================================================
st.markdown("""
<style>
.block-container{padding-top:1.25rem;padding-bottom:2rem}
div[data-testid="stMetric"]{background:#fff;border:1px solid #e5e7eb;padding:15px;border-radius:14px}
.section-card{padding:18px;border:1px solid #e5e7eb;border-radius:16px;background:#fff;margin-bottom:12px}
</style>
""", unsafe_allow_html=True)

st.sidebar.title("💼 HR Payroll Portal")
st.sidebar.caption("Attendance • OT • Salary • Wages")
page = st.sidebar.radio("Navigation", [
    "📊 Dashboard", "📋 Punching Data", "📤 Upload Data", "👤 Employee View",
    "⏱️ Attendance & OT", "💰 Salary & Wages", "⚙️ Salary Master", "📑 Reports"
])
st.sidebar.divider()
duty_hours = st.sidebar.number_input("Standard Duty Hours / Day", min_value=1.0, max_value=24.0, value=8.0, step=0.5)
if st.sidebar.button("Logout", use_container_width=True):
    st.session_state.logged_in = False
    st.rerun()

# ============================================================
# LOAD
# ============================================================
df = load_data()

# ============================================================
# UPLOAD
# ============================================================
if page == "📤 Upload Data":
    st.title("📤 Upload Punching Data")
    st.info("Upload Excel/CSV. Entry/in are treated as IN; Exit/out are treated as OUT. Multiple punches are retained, but salary/OT uses first IN and last OUT for each employee/day.")
    uploaded = st.file_uploader("Upload Excel or CSV", type=["xlsx","xls","csv"])
    if uploaded:
        try:
            if uploaded.name.lower().endswith(".csv"):
                raw = pd.read_csv(uploaded)
            else:
                book = pd.ExcelFile(uploaded)
                preferred = next((s for s in book.sheet_names if "puching" in s.lower() or "punch" in s.lower()), book.sheet_names[0])
                raw = pd.read_excel(uploaded, sheet_name=preferred)
            normalized = normalize_punching(raw)
            st.success(f"Detected {len(normalized):,} valid punch records.")
            st.dataframe(normalized.drop(columns=["Time Parsed"], errors="ignore").head(100), use_container_width=True)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Import / Append Data", type="primary", use_container_width=True):
                    n, dups = insert_punching_data(normalized)
                    st.success(f"Imported {n:,} records. Duplicates skipped: {dups:,}.")
                    st.rerun()
            with c2:
                if st.button("Clear All Punching Data", use_container_width=True):
                    clear_punching_data()
                    st.warning("All punching data cleared.")
                    st.rerun()
        except Exception as e:
            st.error(f"Import error: {e}")
    st.stop()

# ============================================================
# COMMON DERIVED DATA
# ============================================================
if not df.empty:
    normalized_db = df.rename(columns={
        "transaction_date":"Transaction Date", "punch_time":"Time", "department":"Department",
        "employee_code":"Employee Code", "employee_name":"Employee Name", "location_name":"Location Name",
        "entry_exit":"ENTRY/EXIT"
    })
    normalized_db["Time Parsed"] = normalized_db["Time"].apply(parse_time)
    normalized_db["ENTRY/EXIT"] = normalized_db["ENTRY/EXIT"].apply(normalize_direction)
    daily = build_daily_report(normalized_db, duty_hours)
else:
    normalized_db = pd.DataFrame()
    daily = pd.DataFrame()

categories = load_categories()
employee_master = load_employee_salary()

# ============================================================
# DASHBOARD
# ============================================================
if page == "📊 Dashboard":
    st.title("📊 HR Attendance Dashboard")
    if df.empty:
        st.info("No punching data available. Go to Upload Data to import your Excel file.")
    else:
        c = st.columns(5)
        c[0].metric("Punch Records", f"{len(df):,}")
        c[1].metric("Employees", f"{df['employee_code'].nunique():,}")
        c[2].metric("Present Days", f"{daily.shape[0]:,}")
        ot_total = sum(hours_float(pd.to_timedelta(x)) for x in daily["OT Hours"])
        c[3].metric("OT Hours", f"{ot_total:,.2f}")
        c[4].metric("Categories", f"{categories['category'].nunique():,}")
        st.subheader("Latest Punching Data")
        st.dataframe(df.head(100), use_container_width=True, hide_index=True)

# ============================================================
# PUNCHING DATA
# ============================================================
elif page == "📋 Punching Data":
    st.title("📋 Punching Data")
    if df.empty:
        st.info("No data available.")
    else:
        q = st.text_input("Search Employee Code / Name")
        x = df.copy()
        if q:
            mask = x["employee_code"].astype(str).str.contains(q, case=False, na=False) | x["employee_name"].astype(str).str.contains(q, case=False, na=False)
            x = x[mask]
        st.dataframe(x, use_container_width=True, hide_index=True)

# ============================================================
# EMPLOYEE VIEW
# ============================================================
elif page == "👤 Employee View":
    st.title("👤 Employee View")
    if daily.empty:
        st.info("No attendance data available.")
    else:
        employees = daily["Employee Code"].astype(str).unique().tolist()
        code = st.selectbox("Select Employee", employees)
        x = daily[daily["Employee Code"].astype(str) == str(code)].copy()
        if not x.empty:
            st.write(f"**Employee:** {x['Employee Name'].iloc[0]}")
            st.dataframe(x, use_container_width=True, hide_index=True)

# ============================================================
# ATTENDANCE & OT
# ============================================================
elif page == "⏱️ Attendance & OT":
    st.title("⏱️ Attendance & Overtime")
    if daily.empty:
        st.info("No attendance data available.")
    else:
        st.caption("Calculation: First IN + Last OUT for each employee/date. Middle punches are ignored for working-hour and OT calculation.")
        st.dataframe(daily, use_container_width=True, hide_index=True)
        att = daily.pivot_table(index=["Employee Code","Employee Name"], columns="Date", values="Status", aggfunc="first")
        att = att.applymap(lambda x: 1 if x == "Present" else 0)
        att["Grand Total"] = att.sum(axis=1)
        st.subheader("Attendance Matrix")
        st.dataframe(att, use_container_width=True)
        ot = daily.copy()
        ot["OT Hours Decimal"] = ot["OT Hours"].apply(lambda x: hours_float(pd.to_timedelta(x)))
        otm = ot.pivot_table(index=["Employee Code","Employee Name"], columns="Date", values="OT Hours Decimal", aggfunc="sum", fill_value=0)
        otm["OT Grand Total Hours"] = otm.sum(axis=1)
        st.subheader("OT Matrix")
        st.dataframe(otm, use_container_width=True)

# ============================================================
# SALARY MASTER
# ============================================================
elif page == "⚙️ Salary Master":
    st.title("⚙️ Salary & Wage Master")
    st.caption("Create category-wise wage rules and employee-specific extra wages/allowances. These values are saved in SQLite.")
    st.subheader("Category-wise Wage Rules")
    with st.form("category_form"):
        c1,c2,c3,c4 = st.columns(4)
        cat = c1.text_input("Category", placeholder="Skilled / Semi-Skilled / Helper")
        monthly = c2.number_input("Monthly Salary", min_value=0.0, step=100.0)
        workdays = c3.number_input("Working Days / Month", min_value=1.0, value=26.0, step=1.0)
        daily_rate = c4.number_input("Daily Wage (0 = auto)", min_value=0.0, step=10.0)
        c5,c6,c7,c8 = st.columns(4)
        ot_rate = c5.number_input("OT Rate / Hour", min_value=0.0, step=10.0)
        att_allow = c6.number_input("Attendance Allowance / Day", min_value=0.0, step=10.0)
        food = c7.number_input("Food Allowance / Day", min_value=0.0, step=10.0)
        travel = c8.number_input("Travel Allowance / Day", min_value=0.0, step=10.0)
        other = st.number_input("Other Monthly Allowance", min_value=0.0, step=50.0)
        save = st.form_submit_button("💾 Save / Update Category", type="primary")
        if save:
            if not cat.strip():
                st.error("Enter a category name.")
            else:
                effective_daily = daily_rate if daily_rate > 0 else (monthly / workdays if workdays else 0)
                save_category((cat.strip(), monthly, workdays, effective_daily, ot_rate, att_allow, food, travel, other))
                st.success("Category saved.")
                st.rerun()
    cats_show = load_categories()
    st.dataframe(cats_show, use_container_width=True, hide_index=True)
    if not cats_show.empty:
        delcat = st.selectbox("Delete Category", cats_show["category"].tolist())
        if st.button("Delete Selected Category"):
            if delcat != "General":
                delete_category(delcat)
                st.success("Category deleted.")
                st.rerun()
            else:
                st.warning("General category cannot be deleted.")

    st.divider()
    st.subheader("Employee-specific Extra Wages / Allowances")
    employee_options = []
    if not df.empty:
        employee_options = df[["employee_code","employee_name"]].drop_duplicates().astype(str)
    if employee_options:
        selected = st.selectbox("Employee", employee_options.apply(lambda r: f"{r['employee_code']} — {r['employee_name']}", axis=1).tolist())
        code, name = selected.split(" — ", 1)
        existing = employee_master[employee_master["employee_code"].astype(str) == code]
        old = existing.iloc[0] if not existing.empty else None
        with st.form("employee_salary_form"):
            category_list = load_categories()["category"].tolist()
            default_cat = str(old["category"]) if old is not None and str(old["category"]) in category_list else category_list[0]
            ec1,ec2 = st.columns(2)
            category = ec1.selectbox("Category", category_list, index=category_list.index(default_cat))
            extra_w = ec2.number_input("Extra Wages", min_value=0.0, value=float(old["extra_wages"]) if old is not None else 0.0, step=50.0)
            ec3,ec4,ec5 = st.columns(3)
            extra_a = ec3.number_input("Extra Allowance", min_value=0.0, value=float(old["extra_allowance"]) if old is not None else 0.0, step=50.0)
            deduction = ec4.number_input("Deduction", min_value=0.0, value=float(old["deduction"]) if old is not None else 0.0, step=50.0)
            remarks = ec5.text_input("Remarks", value=str(old["remarks"]) if old is not None else "")
            if st.form_submit_button("💾 Save Employee Salary Setup"):
                save_employee_salary((code, name, category, extra_w, extra_a, deduction, remarks))
                st.success("Employee salary setup saved.")
                st.rerun()
    else:
        st.info("Import punching data first to create the employee list.")
    em = load_employee_salary()
    if not em.empty:
        st.subheader("Employee Salary Setup")
        st.dataframe(em, use_container_width=True, hide_index=True)

# ============================================================
# SALARY & WAGES
# ============================================================
elif page == "💰 Salary & Wages":
    st.title("💰 Salary & Wages")
    st.caption("Category-wise wages + attendance-based pay + OT + extra wages + allowances = gross wages. Deductions are subtracted to show net payable.")
    if daily.empty:
        st.info("Import punching data first.")
    else:
        date_series = pd.to_datetime(daily["Date"])
        min_d, max_d = date_series.min().date(), date_series.max().date()
        c1,c2,c3 = st.columns(3)
        from_d = c1.date_input("From Date", min_d)
        to_d = c2.date_input("To Date", max_d)
        selected_category = c3.selectbox("Category Filter", ["All"] + load_categories()["category"].tolist())
        if from_d > to_d:
            st.error("From Date cannot be after To Date.")
        else:
            period_daily = daily[(pd.to_datetime(daily["Date"]).dt.date >= from_d) & (pd.to_datetime(daily["Date"]).dt.date <= to_d)].copy()
            if selected_category != "All":
                codes = load_employee_salary().query("category == @selected_category")["employee_code"].astype(str).tolist()
                period_daily = period_daily[period_daily["Employee Code"].astype(str).isin(codes)]
            salary = build_salary_report(period_daily, load_categories(), load_employee_salary(), duty_hours)
            if salary.empty:
                st.warning("No employee records match the selected period/category.")
            else:
                c = st.columns(6)
                c[0].metric("Employees", len(salary))
                c[1].metric("Present Days", int(salary["Present Days"].sum()))
                c[2].metric("OT Hours", f"{salary['OT Hours'].sum():,.2f}")
                c[3].metric("Regular Wages", money(salary["Regular Wages"].sum()))
                c[4].metric("OT Wages", money(salary["OT Wages"].sum()))
                c[5].metric("Net Payable", money(salary["Net Payable"].sum()))
                st.subheader("Employee-wise Salary / Wage Calculation")
                display = salary.copy()
                for col in ["Daily Wage","Regular Wages","OT Rate","OT Wages","Attendance Allowance Total","Food Allowance Total","Travel Allowance Total","Other Allowance Total","Extra Wages","Extra Allowance","Gross Wages","Deduction","Net Payable"]:
                    display[col] = display[col].map(lambda x: round(float(x),2))
                st.dataframe(display, use_container_width=True, hide_index=True)
                st.subheader("Category-wise Wage Summary")
                cat_summary = salary.groupby("Category", as_index=False).agg(
                    Employees=("Employee Code","nunique"),
                    Present_Days=("Present Days","sum"),
                    OT_Hours=("OT Hours","sum"),
                    Regular_Wages=("Regular Wages","sum"),
                    OT_Wages=("OT Wages","sum"),
                    Allowances=("Attendance Allowance Total","sum"),
                    Extra_Wages=("Extra Wages","sum"),
                    Extra_Allowance=("Extra Allowance","sum"),
                    Gross_Wages=("Gross Wages","sum"),
                    Deduction=("Deduction","sum"),
                    Net_Payable=("Net Payable","sum"),
                )
                st.dataframe(cat_summary, use_container_width=True, hide_index=True)
                xlsx = export_excel({"Salary Wages": salary, "Category Summary": cat_summary, "Daily Attendance": period_daily})
                st.download_button("📥 Download Salary & Wages Excel", xlsx, file_name=f"Salary_Wages_{from_d}_{to_d}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ============================================================
# REPORTS
# ============================================================
elif page == "📑 Reports":
    st.title("📑 Reports & Export")
    if daily.empty:
        st.info("No data available.")
    else:
        att = daily.pivot_table(index=["Employee Code","Employee Name"], columns="Date", values="Status", aggfunc="first")
        att = att.applymap(lambda x: 1 if x == "Present" else 0)
        att["Grand Total"] = att.sum(axis=1)
        ot = daily.copy()
        ot["OT Hours Decimal"] = ot["OT Hours"].apply(lambda x: hours_float(pd.to_timedelta(x)))
        otm = ot.pivot_table(index=["Employee Code","Employee Name"], columns="Date", values="OT Hours Decimal", aggfunc="sum", fill_value=0)
        otm["OT Grand Total Hours"] = otm.sum(axis=1)
        salary = build_salary_report(daily, load_categories(), load_employee_salary(), duty_hours)
        xlsx = export_excel({"Daily Attendance": daily, "Attendance Matrix": att.reset_index(), "OT Matrix": otm.reset_index(), "Salary Wages": salary})
        st.download_button("📥 Download Complete HR Excel Report", xlsx, file_name="HR_Attendance_OT_Salary_Report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.write("The Excel contains Daily Attendance, Attendance Matrix, OT Matrix and Salary/Wages.")

st.sidebar.divider()
st.sidebar.caption("Login: admin / password")
