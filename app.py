import calendar
from datetime import date, datetime, timedelta
from io import BytesIO
import sqlite3
import pandas as pd
import streamlit as st

# ============================================================
# CONFIGURATION & PAGE SETUP
# ============================================================
st.set_page_config(
    page_title="Employee Attendance & Overtime Portal",
    page_icon="🕒",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_FILE = "attendance.db"
DEFAULT_DUTY_HOURS = 8.0

# Pre-defined Users Credentials
USER_CREDENTIALS = {"admin": "admin123", "manager": "manager123"}


# ============================================================
# LOGIN SYSTEM FUNCTION
# ============================================================
def login_page():
    st.markdown(
        "<h2 style='text-align: center;'>🔒 Attendance Portal Login</h2>",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.info("Enter the login ID and Password")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("🔐 Login", type="primary", use_container_width=True):
            if (
                username in USER_CREDENTIALS
                and USER_CREDENTIALS[username] == password
            ):
                st.session_state["logged_in"] = True
                st.session_state["username"] = username
                st.success("Login safaltapoorvak ho gaya!")
                st.rerun()
            else:
                st.error("❌ Galat Username ya Password! Dobara koshish karein.")


def logout():
    st.session_state["logged_in"] = False
    st.session_state["username"] = None
    st.rerun()


# ============================================================
# DATABASE SETUP & HELPERS
# ============================================================
def get_connection():
    return sqlite3.connect(DB_FILE)


def create_database():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS punching_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_date TEXT NOT NULL,
            punch_time TEXT NOT NULL,
            department TEXT,
            employee_code TEXT NOT NULL,
            employee_name TEXT,
            location_name TEXT,
            entry_exit TEXT,
            UNIQUE(
                transaction_date,
                punch_time,
                employee_code,
                location_name,
                entry_exit
            )
        )
    """)
    conn.commit()
    conn.close()


def insert_data(df):
    conn = get_connection()
    cursor = conn.cursor()
    inserted = 0
    duplicates = 0

    cols = list(df.columns)

    def find_col(keywords):
        for c in cols:
            if any(k.lower() in str(c).lower() for k in keywords):
                return c
        return None

    date_col = find_col(["transaction date", "date"]) or "Transaction Date"
    time_col = find_col(["time", "punch time"]) or "Time"
    dept_col = find_col(["department", "dept"]) or "Department"
    emp_code_col = (
        find_col(["employee code", "emp code", "code"]) or "Employee Code"
    )
    emp_name_col = find_col(["employee name", "name"]) or "Employee Name"
    loc_col = find_col(["location name", "location"]) or "Location Name"
    entry_col = find_col(["entry/exit", "in/out", "entry", "exit"]) or "ENTRY/EXIT"

    for _, row in df.iterrows():
        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO punching_data
                (
                    transaction_date, punch_time, department,
                    employee_code, employee_name, location_name, entry_exit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(row.get(date_col, "")),
                    str(row.get(time_col, "")),
                    str(row.get(dept_col, "")),
                    str(row.get(emp_code_col, "")),
                    str(row.get(emp_name_col, "")),
                    str(row.get(loc_col, "")),
                    str(row.get(entry_col, "")),
                ),
            )
            if cursor.rowcount == 1:
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
    query = """
        SELECT id, transaction_date, punch_time, department,
               employee_code, employee_name, location_name, entry_exit
        FROM punching_data
        ORDER BY transaction_date DESC, punch_time DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    if not df.empty:
        df["transaction_date"] = pd.to_datetime(
            df["transaction_date"], errors="coerce"
        )
        df["punch_time"] = df["punch_time"].astype(str)

    return df


def delete_all_data():
    conn = get_connection()
    conn.execute("DELETE FROM punching_data")
    conn.commit()
    conn.close()


# ============================================================
# TIME & CALCULATION LOGIC
# ============================================================
def normalize_event(value):
    s = str(value).strip().upper()
    if s in {"ENTRY", "IN", "INWARD", "CHECK IN", "CHECK-IN", "1", "I"}:
        return "ENTRY"
    if s in {"EXIT", "OUT", "OUTWARD", "CHECK OUT", "CHECK-OUT", "0", "O"}:
        return "EXIT"
    return s


def parse_time(value):
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return datetime(
            2000, 1, 1, value.hour, value.minute, getattr(value, "second", 0)
        )

    s = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def minutes_to_hhmm(minutes):
    if minutes is None or pd.isna(minutes):
        return "00:00"
    minutes = max(0, int(round(float(minutes))))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def calculate_daily_attendance(data, duty_hours=DEFAULT_DUTY_HOURS):
    if data.empty:
        return pd.DataFrame()

    df = data.copy()
    df["transaction_date"] = pd.to_datetime(
        df["transaction_date"], errors="coerce"
    )
    df["event"] = df["entry_exit"].map(normalize_event)
    df["parsed_time"] = df["punch_time"].map(parse_time)
    df = df.dropna(subset=["transaction_date", "parsed_time", "employee_code"])

    records = []
    group_cols = ["employee_code", "transaction_date"]

    for (employee_code, trans_date), group in df.groupby(
        group_cols, sort=False
    ):
        group = group.sort_values("parsed_time")

        all_times = group["parsed_time"].tolist()
        events = group["event"].tolist()

        in_punches = [t for t, e in zip(all_times, events) if e == "ENTRY"]
        out_punches = [t for t, e in zip(all_times, events) if e == "EXIT"]

        first_in = in_punches[0] if in_punches else all_times[0]
        last_out = (
            out_punches[-1]
            if out_punches
            else (all_times[-1] if len(all_times) > 1 else None)
        )

        total_minutes = 0.0
        if first_in and last_out and last_out > first_in:
            total_minutes = (last_out - first_in).total_seconds() / 60.0

        duty_minutes = float(duty_hours) * 60.0
        ot_minutes = max(total_minutes - duty_minutes, 0)

        records.append({
            "Employee Code": str(employee_code),
            "Employee Name": str(group["employee_name"].dropna().iloc[0])
            if group["employee_name"].notna().any()
            else "",
            "Department": str(group["department"].dropna().iloc[0])
            if group["department"].notna().any()
            else "",
            "Date": trans_date.date(),
            "IN": first_in.strftime("%H:%M") if first_in else "-",
            "OUT": last_out.strftime("%H:%M") if last_out else "-",
            "Working Minutes": round(total_minutes),
            "Working Hours": minutes_to_hhmm(total_minutes),
            "OT Minutes": round(ot_minutes),
            "OT Hours": minutes_to_hhmm(ot_minutes),
            "Present": 1,
        })

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.sort_values(["Date", "Employee Code"])
    return result


# ============================================================
# MATRIX GENERATORS
# ============================================================
def build_monthly_attendance_matrix(daily, selected_month):
    if daily.empty:
        return pd.DataFrame()

    start = selected_month.replace(day=1)
    last_day = calendar.monthrange(start.year, start.month)[1]
    dates = [start.replace(day=d) for d in range(1, last_day + 1)]

    month_df = daily[
        pd.to_datetime(daily["Date"]).dt.to_period("M")
        == pd.Period(start, freq="M")
    ].copy()

    if month_df.empty:
        return pd.DataFrame()

    month_df["Date"] = pd.to_datetime(month_df["Date"])

    rows = []
    day_totals = {d.strftime("%Y-%m-%d"): 0 for d in dates}
    grand_all = 0

    for code, group in month_df.groupby("Employee Code", sort=True):
        name = (
            group["Employee Name"].dropna().iloc[0]
            if not group["Employee Name"].dropna().empty
            else ""
        )
        row = {"Employee Code": code, "Name": name}
        emp_total = 0

        for d in dates:
            d_str = d.strftime("%Y-%m-%d")
            day = group[group["Date"] == pd.Timestamp(d)]
            if not day.empty:
                row[d_str] = 1
                emp_total += 1
                day_totals[d_str] += 1
            else:
                row[d_str] = ""

        row["Grand Total"] = emp_total
        grand_all += emp_total
        rows.append(row)

    total_row = {"Employee Code": "Grand Total", "Name": ""}
    for d_str, count in day_totals.items():
        total_row[d_str] = count if count > 0 else ""
    total_row["Grand Total"] = grand_all
    rows.append(total_row)

    return pd.DataFrame(rows)


def build_monthly_ot_matrix(daily, selected_month):
    if daily.empty:
        return pd.DataFrame()

    start = selected_month.replace(day=1)
    last_day = calendar.monthrange(start.year, start.month)[1]
    dates = [start.replace(day=d) for d in range(1, last_day + 1)]

    month_df = daily[
        pd.to_datetime(daily["Date"]).dt.to_period("M")
        == pd.Period(start, freq="M")
    ].copy()

    if month_df.empty:
        return pd.DataFrame()

    month_df["Date"] = pd.to_datetime(month_df["Date"])

    rows = []
    day_ot_totals = {d.strftime("%Y-%m-%d"): 0 for d in dates}
    grand_all_ot = 0

    for code, group in month_df.groupby("Employee Code", sort=True):
        name = (
            group["Employee Name"].dropna().iloc[0]
            if not group["Employee Name"].dropna().empty
            else ""
        )
        row = {"Employee Code": code, "Name": name}
        emp_ot_mins = 0

        for d in dates:
            d_str = d.strftime("%Y-%m-%d")
            day = group[group["Date"] == pd.Timestamp(d)]
            mins = int(day["OT Minutes"].sum()) if not day.empty else 0

            if mins > 0:
                row[d_str] = minutes_to_hhmm(mins)
                emp_ot_mins += mins
                day_ot_totals[d_str] += mins
            else:
                row[d_str] = ""

        row["Grand Total"] = minutes_to_hhmm(emp_ot_mins)
        grand_all_ot += emp_ot_mins
        rows.append(row)

    total_row = {"Employee Code": "Grand Total", "Name": ""}
    for d_str, count_mins in day_ot_totals.items():
        total_row[d_str] = (
            minutes_to_hhmm(count_mins) if count_mins > 0 else ""
        )
    total_row["Grand Total"] = minutes_to_hhmm(grand_all_ot)
    rows.append(total_row)

    return pd.DataFrame(rows)


def dataframe_to_excel(sheets):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            frame.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    output.seek(0)
    return output.getvalue()


# ============================================================
# MAIN APPLICATION LOGIC WITH SESSION CONTROL
# ============================================================
create_database()

# Session State Check for Login
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    login_page()
else:
    # Sidebar for Logged-In Users
    st.sidebar.markdown(f"👤 **User:** `{st.session_state['username']}`")
    if st.sidebar.button("🚪 Logout"):
        logout()

    st.sidebar.divider()
    st.sidebar.markdown("## 🕒 Navigation")
    page = st.sidebar.radio(
        "Select Option",
        [
            "📤 Upload Data",
            "📑 Monthly Report",
            "📊 Dashboard",
            "📋 Punching Data",
        ],
    )

    df = load_data()

    # Upload Data Page
    if page == "📤 Upload Data":
        st.subheader("📤 Upload Punching Excel / CSV")

        uploaded = st.file_uploader(
            "Upload Excel File", type=["xlsx", "xls", "csv"]
        )

        if uploaded:
            try:
                if uploaded.name.lower().endswith(".csv"):
                    upload_df = pd.read_csv(uploaded)
                    sheet_selected = "CSV"
                else:
                    excel_file = pd.ExcelFile(uploaded)
                    sheet_names = excel_file.sheet_names

                    st.info(
                        f"Is Excel File mein **{len(sheet_names)} tabs** mile hain."
                    )
                    sheet_selected = st.selectbox(
                        "📌 Select the tab containing Raw Punch Data:",
                        sheet_names,
                    )

                    upload_df = pd.read_excel(
                        uploaded, sheet_name=sheet_selected
                    )

                st.success(
                    f"Sheet '{sheet_selected}' loaded successfully — **{len(upload_df):,} rows**"
                )
                st.dataframe(upload_df.head(10), use_container_width=True)

                if st.button("⬆️ Import Selected Sheet Data", type="primary"):
                    inserted, duplicates = insert_data(upload_df)
                    st.success(
                        f"Import completed — {inserted:,} new records added, {duplicates:,} duplicate/invalid records skipped."
                    )
                    st.rerun()
            except Exception as e:
                st.error(f"File padhne mein error aaya: {e}")

        st.divider()
        if st.button("🗑️ Clear All Saved Data"):
            delete_all_data()
            st.success("Database ka saara data clear kar diya gaya hai.")
            st.rerun()

    # Monthly Report Page
    elif page == "📑 Monthly Report":
        st.subheader("📑 Monthly Attendance & Overtime Matrix")

        if df.empty:
            st.info(
                "Koi data nahi hai. Pehle 'Upload Data' tab se file upload karein."
            )
        else:
            min_month = df["transaction_date"].min().date().replace(day=1)
            max_month = df["transaction_date"].max().date().replace(day=1)

            c1, c2 = st.columns([1.5, 1.5])
            selected_month = c1.date_input(
                "Select Month",
                value=max_month,
                min_value=min_month,
                max_value=max_month,
            )
            duty_hours = c2.number_input(
                "Standard Duty Hours / Day",
                min_value=1.0,
                max_value=24.0,
                value=DEFAULT_DUTY_HOURS,
                step=0.5,
            )

            daily = calculate_daily_attendance(df, duty_hours=duty_hours)

            attendance_matrix = build_monthly_attendance_matrix(
                daily, selected_month
            )
            ot_matrix = build_monthly_ot_matrix(daily, selected_month)

            if attendance_matrix.empty:
                st.warning(
                    "Selected month mein koi attendance record nahi mila."
                )
            else:
                tab1, tab2 = st.tabs(
                    ["📅 Attendance Matrix", "🕒 Overtime (OT) Matrix"]
                )

                with tab1:
                    st.markdown(
                        "### 📅 Monthly Attendance Report (Present Count)"
                    )
                    st.dataframe(
                        attendance_matrix,
                        use_container_width=True,
                        hide_index=True,
                    )

                with tab2:
                    st.markdown("### 🕒 Monthly Overtime Report (HH:MM)")
                    st.dataframe(
                        ot_matrix, use_container_width=True, hide_index=True
                    )

                st.divider()

                excel_data = dataframe_to_excel({
                    "Attendance Matrix": attendance_matrix,
                    "Overtime Matrix": ot_matrix,
                })

                st.download_button(
                    "📥 Download Both Matrix Tabs in Excel",
                    data=excel_data,
                    file_name=f"Monthly_Attendance_and_OT_{selected_month.strftime('%m_%Y')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                )

    elif page == "📊 Dashboard":
        st.subheader("📊 Summary Dashboard")
        if not df.empty:
            daily = calculate_daily_attendance(df)
            st.dataframe(daily.head(30), use_container_width=True)

    elif page == "📋 Punching Data":
        st.subheader("📋 Raw Punching Data")
        st.dataframe(df, use_container_width=True)
