import streamlit as st
import pandas as pd
import plotly.express as px
import streamlit.components.v1 as components
from datetime import datetime
import re
import math
import numpy as np
from pandas.tseries.offsets import MonthEnd

# Inject JavaScript to handle module fetch errors
components.html(
    """
    <script>
    window.addEventListener('error', function(e) {
        if (e.message.includes('Failed to fetch dynamically imported module')) {
            alert('Failed to load the app. Reloading the page...');
            window.location.reload();
        }
    });
    </script>
    """,
    height=0,
)

# Streamlit page configuration
st.set_page_config(page_title="GridMetrix", page_icon="⚡", layout="wide")

st.title("⚡ GridMetrix")
st.caption("Real-time Fault Analysis & Reliability Metrics Dashboard")


# -----------------------------
# Utility functions (unchanged)
# -----------------------------
def format_number(value, decimals=2):
    if pd.isna(value):
        return "NaN"
    try:
        if decimals == 0:
            return f"{int(value):,}"
        return f"{value:,.{decimals}f}"
    except (ValueError, TypeError):
        return "NaN"

def clean_load_loss(value):
    if not isinstance(value, str) or pd.isna(value):
        return value
    value = re.sub(r'[oO]', '0', value)
    match = re.match(r'^\s*(\d*\.?\d*)\s*(?:amps?|a|A)?\s*$', value, re.IGNORECASE)
    if match:
        return match.group(1)
    return value

def extract_feeder_from_dtname(dt_name):
    if pd.isna(dt_name):
        return None
    parts = str(dt_name).split('-')
    if len(parts) <= 1:
        return str(dt_name).strip()
    return '-'.join(parts[:-1]).strip()

def classify_fault(fault_str):
    if not isinstance(fault_str, str) or fault_str == 'Unknown':
        return 'Unknown'
    fault_str = fault_str.lower()
    if 'e/f' in fault_str or 'earth fault' in fault_str:
        return 'Earth Fault'
    elif 'o/c' in fault_str or 'over current' in fault_str:
        return 'Over Current'
    elif 'b/c' in fault_str or 'broken conductor' in fault_str:
        return 'Broken Conductor'
    elif 'cable' in fault_str:
        return 'Cable Fault'
    elif 'transformer' in fault_str:
        return 'Transformer Fault'
    elif 'breaker' in fault_str:
        return 'Breaker Fault'
    else:
        return 'Other'

def calculate_feeder_ratings(df_grouped):
    if len(df_grouped) < 2 or df_grouped['DOWNTIME_HOURS'].nunique() < 2:
        df_grouped['RATING'] = 'Unknown'
    else:
        try:
            n_bins = min(4, df_grouped['DOWNTIME_HOURS'].nunique())
            df_grouped['RATING'] = pd.qcut(df_grouped['DOWNTIME_HOURS'], q=n_bins, labels=['Excellent', 'Good', 'Fair', 'Poor'][:n_bins], duplicates='drop')
        except ValueError:
            df_grouped['RATING'] = 'Unknown'
    return df_grouped

def suggest_maintenance(fault_type):
    if not isinstance(fault_type, str) or fault_type == 'Unknown':
        return "Conduct root cause analysis for unspecified fault."
    fault_type = fault_type.lower()
    if 'e/f' in fault_type or 'earth fault' in fault_type:
        return "Inspect grounding systems and insulation; repair earth faults."
    elif 'o/c' in fault_type or 'over current' in fault_type:
        return "Check for overloads and short circuits; calibrate protective devices."
    elif 'b/c' in fault_type or 'broken conductor' in fault_type:
        return "Replace broken conductors; inspect for physical damage."
    elif 'cable' in fault_type:
        return "Inspect and replace damaged cables; check for water ingress."
    elif 'transformer' in fault_type:
        return "Schedule transformer maintenance; check oil levels and insulation."
    elif 'breaker' in fault_type:
        return "Test and calibrate circuit breakers; inspect for wear."
    else:
        return "Conduct root cause analysis and regular preventive maintenance."

def parse_phases(phase_str):
    if not isinstance(phase_str, str) or pd.isna(phase_str) or phase_str.lower() == 'nan':
        return []
    phase_str = re.sub(r'\s*AND\s*|\s*&\s*|,\s*', ',', phase_str, flags=re.IGNORECASE)
    phases = [p.strip().lower() for p in phase_str.split(',') if p.strip()]
    return phases

# Metric color card helper (returns HTML)
def metric_with_color(label, value_str, good):
    bg = "#d4f7d4" if good else "#f7d4d4"
    border = "#66c266" if good else "#e05252"
    html = f"""
    <div style="padding:12px;border-radius:6px;background:{bg};border:2px solid {border};">
        <div style="font-size:14px;color:#111;margin-bottom:6px;">{label}</div>
        <div style="font-size:20px;font-weight:600;color:#111;">{value_str}</div>
    </div>
    """
    return html

# -----------------------------
# Page selector
# -----------------------------
page = st.sidebar.radio("Select Page", ["Fault Analysis", "Reliability Indices"])

# instructions (keeps original feel)
st.markdown("Upload an Excel file with sheets '11kV Tripping Log' and 'Customer Info' to analyze fault clearance and reliability indices.")

# -----------------------------
# File uploader
# -----------------------------
uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])

if uploaded_file is None:
    st.warning("Please upload an Excel file to proceed.")
    st.stop()

# Read both sheets (trip log header=0 now, customer info header=0)
try:
    trip_df = pd.read_excel(uploaded_file, sheet_name="11kV Tripping Log", header=0)
except Exception as e:
    st.error(f"Error reading '11kV Tripping Log' sheet: {e}")
    st.stop()

try:
    cust_df = pd.read_excel(uploaded_file, sheet_name="Customer Info", header=0)
except Exception as e:
    st.error(f"Error reading 'Customer Info' sheet: {e}")
    st.stop()

# Validate some customer columns
if not {'ACCOUNT_NUMBER','DT_NAME','STATUS'}.issubset(set(cust_df.columns)):
    st.error("Customer Info sheet must contain ACCOUNT_NUMBER, DT_NAME and STATUS columns.")
    st.stop()

# -----------------------------
# Prepare customer info mapping (active customers per feeder)
# -----------------------------
cust_df['FEEDER_NAME'] = cust_df['DT_NAME'].apply(extract_feeder_from_dtname).astype(str).str.strip()
cust_df['STATUS'] = cust_df['STATUS'].astype(str).str.strip()
active_cust_df = cust_df[cust_df['STATUS'].str.upper() == 'ACTIVE']
total_active_customers = int(active_cust_df['ACCOUNT_NUMBER'].nunique())
# Map feeder uppercase -> count
customers_per_feeder = active_cust_df.groupby(active_cust_df['FEEDER_NAME'].str.upper())['ACCOUNT_NUMBER'].nunique().to_dict()

# -----------------------------
# Begin: Original Fault Analysis Processing (kept intact, only header change applied above)
# -----------------------------
# Required columns
required_columns = [
    'BUSINESS UNIT',
    '11kV FEEDER',
    'LOAD LOSS',
    'DATE REPORTED',
    'TIME REPORTED',
    'DATE CLEARED',
    'TIME CLEARED',
    'DATE RESTORED',
    'TIME RESTORED',
    'FAULT/OPERATION',
    'PHASE AFFECTED'
]
optional_columns = ['RESPONSIBLE UNDERTAKINGS', 'FINDINGS/ACTION TAKEN']

missing_required = [col for col in required_columns if col not in trip_df.columns]
missing_optional = [col for col in optional_columns if col not in trip_df.columns]
if missing_required:
    st.error(f"Error: Missing required columns: {', '.join(missing_required)}. Please check the Excel file headers (row 1).")
    st.stop()
if missing_optional:
    st.warning(f"Missing optional columns: {', '.join(missing_optional)}. Some features may be disabled.")

# Clean LOAD LOSS before conversion
trip_df['LOAD LOSS'] = trip_df['LOAD LOSS'].apply(clean_load_loss)

# Date & time conversions (keeps your original expected formats)
date_time_cols = ['DATE REPORTED', 'TIME REPORTED', 'DATE CLEARED', 'TIME CLEARED', 'DATE RESTORED', 'TIME RESTORED']
for col in date_time_cols:
    if col in trip_df.columns:
        if 'DATE' in col:
            trip_df[col] = pd.to_datetime(trip_df[col], errors='coerce')
        else:
            # try flexible parsing but keep your expected format
            trip_df[col] = pd.to_datetime(trip_df[col], errors='coerce', format='%H:%M:%S')

# Combine date and time for full timestamps
try:
    trip_df['REPORTED_TIMESTAMP'] = trip_df['DATE REPORTED'] + pd.to_timedelta(trip_df['TIME REPORTED'].dt.strftime('%H:%M:%S'))
    trip_df['RESTORED_TIMESTAMP'] = trip_df['DATE RESTORED'] + pd.to_timedelta(trip_df['TIME RESTORED'].dt.strftime('%H:%M:%S'))
    trip_df['CLEARED_TIMESTAMP'] = trip_df['DATE CLEARED'] + pd.to_timedelta(trip_df['TIME CLEARED'].dt.strftime('%H:%M:%S'))
except Exception as e:
    st.error(f"Error creating timestamps: {str(e)}. Check date/time column formats.")
    st.stop()

# Downtime and clearance time
trip_df['DOWNTIME_HOURS'] = (trip_df['RESTORED_TIMESTAMP'] - trip_df['REPORTED_TIMESTAMP']).dt.total_seconds() / 3600
trip_df['DOWNTIME_HOURS'] = trip_df['DOWNTIME_HOURS'].abs()
trip_df['CLEARANCE_TIME_HOURS'] = (trip_df['CLEARED_TIMESTAMP'] - trip_df['REPORTED_TIMESTAMP']).dt.total_seconds() / 3600
trip_df['CLEARANCE_TIME_HOURS'] = trip_df['CLEARANCE_TIME_HOURS'].abs()

# Filter out OE faults
trip_df['FAULT/OPERATION'] = trip_df['FAULT/OPERATION'].astype(str).replace('nan', 'Unknown')
initial_count = len(trip_df)
trip_df = trip_df[~trip_df['FAULT/OPERATION'].str.lower().str.contains('opened on emergency|oe|emergency', na=False)]
filtered_count = initial_count - len(trip_df)
if filtered_count > 0:
    st.info(f"Excluded {filtered_count} faults labeled 'Opened on Emergency', 'OE', or 'emergency' as they are handled by CHQ.")

# Debug expander (retain)
with st.expander("Debug Data (For Validation)"):
    st.write("**Columns in DataFrame**")
    st.write(trip_df.columns.tolist())
    st.write("**LOAD LOSS (Current in Amps) Column**")
    st.write("Raw sample values:", trip_df['LOAD LOSS'].head().to_list())
    st.write("Data type:", trip_df['LOAD LOSS'].dtype)
    st.write("Any non-numeric values after cleaning:", trip_df['LOAD LOSS'].apply(lambda x: not isinstance(x, (int, float)) and pd.notna(x)).sum())
    st.write("**FAULT/OPERATION Column**")
    st.write("Sample values:", trip_df['FAULT/OPERATION'].head().to_list())
    st.write("Data type:", trip_df['FAULT/OPERATION'].dtype)
    st.write("Any non-string values:", trip_df['FAULT/OPERATION'].apply(lambda x: not isinstance(x, str) and pd.notna(x)).sum())
    st.write("**PHASE AFFECTED Column**")
    st.write("Sample values:", trip_df['PHASE AFFECTED'].head().to_list())
    st.write("Data type:", trip_df['PHASE AFFECTED'].dtype)
    st.write("**11kV FEEDER Column**")
    st.write("Sample values:", trip_df['11kV FEEDER'].head().to_list())
    st.write("**BUSINESS UNIT Column**")
    st.write("Sample values:", trip_df['BUSINESS UNIT'].head().to_list())
    if 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns:
        st.write("**RESPONSIBLE UNDERTAKINGS Column**")
        st.write("Sample values:", trip_df['RESPONSIBLE UNDERTAKINGS'].head().to_list())
    if 'FINDINGS/ACTION TAKEN' in trip_df.columns:
        st.write("**FINDINGS/ACTION TAKEN Column**")
        st.write("Sample values:", trip_df['FINDINGS/ACTION TAKEN'].head().to_list())

# Numeric conversion & voltage extraction (retain logic)
trip_df['LOAD LOSS'] = pd.to_numeric(trip_df['LOAD LOSS'], errors='coerce')

def extract_voltage(feeder_name):
    if not isinstance(feeder_name, str) or pd.isna(feeder_name):
        return None
    try:
        voltage_kv = float(feeder_name.split('-')[0].strip())
        return voltage_kv * 1000
    except (ValueError, IndexError):
        return None

trip_df['VOLTAGE_V'] = trip_df['11kV FEEDER'].apply(extract_voltage)

# Warnings
if trip_df['LOAD LOSS'].isna().sum() > 0:
    st.warning(f"Found {trip_df['LOAD LOSS'].isna().sum()} non-numeric or missing values in LOAD LOSS (current) after cleaning. These have been converted to NaN.")
if trip_df['VOLTAGE_V'].isna().sum() > 0:
    st.warning(f"Found {trip_df['VOLTAGE_V'].isna().sum()} invalid voltage values derived from 11kV FEEDER. Ensure feeder names start with '11-' or '33-'. These have been converted to NaN.")
if trip_df['CLEARANCE_TIME_HOURS'].isna().sum() > 0:
    st.warning(f"Found {trip_df['CLEARANCE_TIME_HOURS'].isna().sum()} invalid clearance times due to missing or incorrect date/time data.")
if trip_df['BUSINESS UNIT'].isna().sum() > 0:
    st.warning(f"Found {trip_df['BUSINESS UNIT'].isna().sum()} missing values in BUSINESS UNIT. These may affect filtering.")
if 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns and trip_df['RESPONSIBLE UNDERTAKINGS'].isna().sum() > 0:
    st.warning(f"Found {trip_df['RESPONSIBLE UNDERTAKINGS'].isna().sum()} missing values in RESPONSIBLE UNDERTAKINGS. These may affect filtering.")
if 'FINDINGS/ACTION TAKEN' in trip_df.columns and trip_df['FINDINGS/ACTION TAKEN'].isna().sum() > 0:
    st.warning(f"Found {trip_df['FINDINGS/ACTION TAKEN'].isna().sum()} missing values in FINDINGS/ACTION TAKEN. These may affect outlier analysis.")

# Undertakings list
if 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns:
    def split_undertakings(undertakings):
        if not isinstance(undertakings, str) or pd.isna(undertakings):
            return []
        undertakings = re.sub(r'\s*(?:AND|&|and)\s*', '/', undertakings, flags=re.IGNORECASE)
        return [u.strip().lower() for u in undertakings.split('/') if u.strip()]
    trip_df['UNDERTAKINGS_LIST'] = trip_df['RESPONSIBLE UNDERTAKINGS'].apply(split_undertakings)

# Energy & monetary loss
trip_df['ENERGY_LOSS_WH'] = trip_df['LOAD LOSS'] * trip_df['VOLTAGE_V'] * trip_df['DOWNTIME_HOURS']
trip_df['ENERGY_LOSS_MWH'] = trip_df['ENERGY_LOSS_WH'] / 1_000_000
trip_df['MONETARY_LOSS_NGN_MILLIONS'] = (trip_df['ENERGY_LOSS_MWH'] * 1000 * 209.5) / 1_000_000

# Fault classification
trip_df['FAULT_TYPE'] = trip_df['FAULT/OPERATION'].apply(classify_fault)

# Feeder ratings & other original computations
feeder_downtime = trip_df.groupby('11kV FEEDER')['DOWNTIME_HOURS'].mean().reset_index()
feeder_downtime = calculate_feeder_ratings(feeder_downtime)
feeder_trips = trip_df['11kV FEEDER'].value_counts().reset_index()
feeder_trips.columns = ['11kV FEEDER', 'TRIP_COUNT']
frequent_trippers = feeder_trips[feeder_trips['TRIP_COUNT'] > 2]
trip_df['MAINTENANCE_SUGGESTION'] = trip_df['FAULT/OPERATION'].apply(suggest_maintenance)
trip_df['PHASE_AFFECTED_LIST'] = trip_df['PHASE AFFECTED'].apply(parse_phases)

phase_types = ['red', 'yellow', 'blue', 'earth fault', 'neutral']
phase_counts = {phase: 0 for phase in phase_types}
for phases in trip_df['PHASE_AFFECTED_LIST']:
    for phase in phases:
        if phase in phase_counts:
            phase_counts[phase] += 1
phase_faults = pd.DataFrame({'Phase Affected': phase_counts.keys(), 'Fault Count': phase_counts.values()})
phase_faults = phase_faults[phase_faults['Fault Count'] > 0]

# Priority score
trip_df['PRIORITY_SCORE'] = (
    0.4 * (trip_df['CLEARANCE_TIME_HOURS'] / trip_df['CLEARANCE_TIME_HOURS'].max()) +
    0.4 * (trip_df['ENERGY_LOSS_MWH'] / trip_df['ENERGY_LOSS_MWH'].max()) +
    0.2 * trip_df['11kV FEEDER'].map(feeder_trips.set_index('11kV FEEDER')['TRIP_COUNT']) / feeder_trips['TRIP_COUNT'].max()
).fillna(0)

outlier_columns = ['11kV FEEDER', 'FAULT_TYPE', 'CLEARANCE_TIME_HOURS']
if 'FINDINGS/ACTION TAKEN' in trip_df.columns:
    outlier_columns.append('FINDINGS/ACTION TAKEN')
clearance_outliers = trip_df[trip_df['CLEARANCE_TIME_HOURS'] > 48][outlier_columns]
clearance_outliers['CLEARANCE_TIME_HOURS'] = clearance_outliers['CLEARANCE_TIME_HOURS'].round(2)

# -----------------------------
# Fault Analysis Page (UNCHANGED logic & layout)
# -----------------------------
if page == "Fault Analysis":
    # Dynamic filters
    st.subheader("Filter Data")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        bu_filter = st.selectbox("Select Business Unit", ['All'] + sorted(trip_df['BUSINESS UNIT'].unique().astype(str).tolist()))
    with col2:
        if 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns:
            all_undertakings = set()
            for undertakings in trip_df['UNDERTAKINGS_LIST']:
                all_undertakings.update(undertakings)
            undertaking_options = sorted(list(all_undertakings))
            undertaking_filter = st.multiselect("Select Responsible Undertakings", undertaking_options, default=undertaking_options)
        else:
            undertaking_filter = []
            st.write("Responsible Undertakings filter disabled (column not found).")
    with col3:
        feeder_filter = st.selectbox("Select Feeder", ['All'] + sorted(trip_df['11kV FEEDER'].unique().astype(str).tolist()))
    with col4:
        trip_df['YEAR'] = trip_df['DATE REPORTED'].dt.year
        year_filter = st.selectbox("Select Year", ['All'] + sorted(trip_df['YEAR'].unique().tolist()))
        trip_df['MONTH'] = trip_df['DATE REPORTED'].dt.month
        month_filter = st.selectbox("Select Month", ['All'] + sorted(trip_df['MONTH'].unique().tolist()))

    # Apply filters
    filtered_df = trip_df
    if bu_filter != 'All':
        filtered_df = filtered_df[filtered_df['BUSINESS UNIT'].astype(str) == bu_filter]
    if undertaking_filter and 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns:
        filtered_df = filtered_df[filtered_df['UNDERTAKINGS_LIST'].apply(lambda x: any(u in undertaking_filter for u in x))]
    if feeder_filter != 'All':
        filtered_df = filtered_df[filtered_df['11kV FEEDER'].astype(str) == feeder_filter]
    if year_filter != 'All':
        filtered_df = filtered_df[filtered_df['YEAR'] == year_filter]
    if month_filter != 'All':
        filtered_df = filtered_df[filtered_df['MONTH'] == month_filter]

    if filtered_df.empty:
        st.warning("No data matches the selected filters. Try different options.")
        st.stop()

    # Update metrics and visuals based on filtered data
    fault_counts_filtered = filtered_df['FAULT_TYPE'].value_counts().reset_index()
    fault_counts_filtered.columns = ['Fault Type', 'Count']
    feeder_downtime_filtered = filtered_df.groupby('11kV FEEDER')['DOWNTIME_HOURS'].mean().reset_index()
    feeder_downtime_filtered = calculate_feeder_ratings(feeder_downtime_filtered)
    def get_short_feeder_name(feeder_name):
        if not isinstance(feeder_name, str) or pd.isna(feeder_name):
            return "Unknown"
        return feeder_name.split('-')[-1].strip()
    feeder_downtime_filtered['SHORT_FEEDER_NAME'] = feeder_downtime_filtered['11kV FEEDER'].apply(get_short_feeder_name)
    frequent_trippers_filtered = filtered_df['11kV FEEDER'].value_counts().reset_index()
    frequent_trippers_filtered.columns = ['11kV FEEDER', 'TRIP_COUNT']
    frequent_trippers_filtered = frequent_trippers_filtered[frequent_trippers_filtered['TRIP_COUNT'] > 2]
    phase_counts_filtered = {phase: 0 for phase in phase_types}
    for phases in filtered_df['PHASE_AFFECTED_LIST']:
        for phase in phases:
            if phase in phase_counts_filtered:
                phase_counts_filtered[phase] += 1
    phase_faults_filtered = pd.DataFrame({
        'Phase Affected': phase_counts_filtered.keys(),
        'Fault Count': phase_counts_filtered.values()
    })
    phase_faults_filtered = phase_faults_filtered[phase_faults_filtered['Fault Count'] > 0]
    outlier_columns_filtered = ['11kV FEEDER', 'FAULT_TYPE', 'CLEARANCE_TIME_HOURS']
    if 'FINDINGS/ACTION TAKEN' in trip_df.columns:
        outlier_columns_filtered.append('FINDINGS/ACTION TAKEN')
    clearance_outliers_filtered = filtered_df[filtered_df['CLEARANCE_TIME_HOURS'] > 48][outlier_columns_filtered]
    clearance_outliers_filtered['CLEARANCE_TIME_HOURS'] = clearance_outliers_filtered['CLEARANCE_TIME_HOURS'].round(2)

    # Dashboard layout (same as original)
    st.subheader("Key Metrics")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Faults", format_number(len(filtered_df), decimals=0))
    with col2:
        st.metric("Total Energy Loss (MWh)", format_number(filtered_df['ENERGY_LOSS_MWH'].sum(), decimals=2))
    with col3:
        st.metric("Total Monetary Loss (M NGN)", format_number(filtered_df['MONETARY_LOSS_NGN_MILLIONS'].sum(), decimals=2))

    st.subheader("Total Downtime")
    st.metric("Total Downtime (Hours)", format_number(filtered_df['DOWNTIME_HOURS'].sum(), decimals=2))

    # Alerts for outliers
    if not clearance_outliers_filtered.empty:
        st.warning(f"Critical: {len(clearance_outliers_filtered)} faults took over 48 hours to clear. Review outliers table.")
    if not frequent_trippers_filtered.empty:
        st.warning(f"Critical: {len(frequent_trippers_filtered)} feeders tripped more than twice. Review frequent trippers table.")

    st.subheader("Fault Classification")
    fig_faults = px.bar(fault_counts_filtered, x='Fault Type', y='Count', title="Fault Types Distribution")
    st.plotly_chart(fig_faults, use_container_width=True)

    st.subheader("Daily Fault Trend")
    daily_faults = filtered_df.groupby(filtered_df['DATE REPORTED'].dt.date)['FAULT_TYPE'].count().reset_index()
    daily_faults.columns = ['Date', 'Fault Count']
    fig_trend = px.line(daily_faults, x='Date', y='Fault Count', title="Daily Fault Trend")
    st.plotly_chart(fig_trend, use_container_width=True)

    st.subheader("Average Downtime by Feeder")
    if feeder_downtime_filtered.empty:
        st.warning("No feeder data available for the selected filters. Adjust the business unit, undertakings, feeder, year, or month filters.")
    else:
        feeder_options = sorted(feeder_downtime_filtered['SHORT_FEEDER_NAME'].unique())
        selected_feeders = st.multiselect(
            "Select Feeders to Display (uses short names)",
            options=feeder_options,
            default=feeder_options,
            help="Choose one or more feeders to compare their average downtime. Short names are shown (last part of feeder name)."
        )
        if selected_feeders:
            chart_data = feeder_downtime_filtered[feeder_downtime_filtered['SHORT_FEEDER_NAME'].isin(selected_feeders)]
        else:
            chart_data = feeder_downtime_filtered
            st.warning("No feeders selected. Displaying all feeders.")
        rating_colors = {
            'Excellent': '#006400',
            'Good': '#32CD32',
            'Fair': '#FFFF00',
            'Poor': '#FF0000'
        }
        fig_downtime = px.bar(
            chart_data,
            x='SHORT_FEEDER_NAME',
            y='DOWNTIME_HOURS',
            color='RATING',
            title="Average Downtime by Feeder",
            color_discrete_map=rating_colors
        )
        st.plotly_chart(fig_downtime, use_container_width=True)

    st.subheader("Frequent Tripping Feeders (>2 Trips)")
    st.dataframe(frequent_trippers_filtered)

    st.subheader("Maintenance Suggestions")
    cols_to_show = ['BUSINESS UNIT', '11kV FEEDER', 'FAULT/OPERATION', 'FAULT_TYPE', 'MAINTENANCE_SUGGESTION']
    if 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns:
        cols_to_show.insert(1, 'RESPONSIBLE UNDERTAKINGS')
    st.dataframe(filtered_df[cols_to_show].drop_duplicates())

    st.subheader("High-Priority Faults")
    cols_to_show = ['BUSINESS UNIT', '11kV FEEDER', 'FAULT_TYPE', 'CLEARANCE_TIME_HOURS', 'ENERGY_LOSS_MWH', 'PRIORITY_SCORE']
    if 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns:
        cols_to_show.insert(1, 'RESPONSIBLE UNDERTAKINGS')
    st.dataframe(filtered_df[cols_to_show].sort_values('PRIORITY_SCORE', ascending=False).head(10))

    st.subheader("Additional Insights")
    st.write("1. **Fault Clearance Time Distribution (0-48 Hours)**: Distribution of clearance times up to 48 hours.")
    filtered_clearance = filtered_df[(filtered_df['CLEARANCE_TIME_HOURS'] >= 0) & (filtered_df['CLEARANCE_TIME_HOURS'] <= 48)]
    fig_clearance = px.histogram(filtered_clearance, x='CLEARANCE_TIME_HOURS', nbins=24, title="Fault Clearance Time Distribution (0-48 Hours)")
    st.plotly_chart(fig_clearance, use_container_width=True)

    st.write("2. **Clearance Time Outliers (>48 Hours)**: Faults taking more than 48 hours to clear, with findings.")
    st.dataframe(clearance_outliers_filtered)

    st.write("3. **Phase-Specific Faults**: Fault counts by affected phase.")
    fig_phase = px.bar(phase_faults_filtered, x='Phase Affected', y='Fault Count', title="Faults by Phase Affected")
    st.plotly_chart(fig_phase, use_container_width=True)

    # Export report as CSV
    st.subheader("Download Report")
    cols_to_export = ['BUSINESS UNIT', '11kV FEEDER', 'FAULT/OPERATION', 'FAULT_TYPE', 'ENERGY_LOSS_MWH', 'MONETARY_LOSS_NGN_MILLIONS', 'DOWNTIME_HOURS', 'CLEARANCE_TIME_HOURS', 'MAINTENANCE_SUGGESTION', 'PRIORITY_SCORE']
    if 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns:
        cols_to_export.insert(1, 'RESPONSIBLE UNDERTAKINGS')
    if 'FINDINGS/ACTION TAKEN' in trip_df.columns:
        cols_to_export.append('FINDINGS/ACTION TAKEN')
    report_df = filtered_df[cols_to_export]
    report_df = report_df.merge(feeder_downtime_filtered[['11kV FEEDER', 'RATING']], on='11kV FEEDER', how='left')
    report_df['ENERGY_LOSS_MWH'] = report_df['ENERGY_LOSS_MWH'].apply(lambda x: format_number(x, decimals=2) if pd.notnull(x) else "NaN")
    report_df['MONETARY_LOSS_NGN_MILLIONS'] = report_df['MONETARY_LOSS_NGN_MILLIONS'].apply(lambda x: format_number(x, decimals=2) if pd.notnull(x) else "NaN")
    report_df['DOWNTIME_HOURS'] = report_df['DOWNTIME_HOURS'].apply(lambda x: format_number(x, decimals=2) if pd.notnull(x) else "NaN")
    report_df['CLEARANCE_TIME_HOURS'] = report_df['CLEARANCE_TIME_HOURS'].apply(lambda x: format_number(x, decimals=2) if pd.notnull(x) else "NaN")
    report_df['PRIORITY_SCORE'] = report_df['PRIORITY_SCORE'].apply(lambda x: format_number(x, decimals=2) if pd.notnull(x) else "NaN")
    csv = report_df.to_csv(index=False)
    st.download_button("Download CSV Report", csv, "fault_clearance_report.csv", "text/csv")

# -----------------------------
# Reliability Indices Page
# -----------------------------
elif page == "Reliability Indices":
    st.subheader("Reliability Indices")

    # replicate filters for consistent UX
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        bu_filter_r = st.selectbox("Select Business Unit", ['All'] + sorted(trip_df['BUSINESS UNIT'].unique().astype(str).tolist()), key="ri_bu")
    with col2:
        if 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns:
            all_undertakings = set()
            for undertakings in trip_df['UNDERTAKINGS_LIST']:
                all_undertakings.update(undertakings)
            undertaking_options = sorted(list(all_undertakings))
            undertaking_filter_r = st.multiselect("Select Responsible Undertakings", undertaking_options, default=undertaking_options, key="ri_undertaking")
        else:
            undertaking_filter_r = []
            st.write("Responsible Undertakings filter disabled (column not found).")
    with col3:
        feeder_filter_r = st.selectbox("Select Feeder", ['All'] + sorted(trip_df['11kV FEEDER'].unique().astype(str).tolist()), key="ri_feeder")
    with col4:
        # compute year and month defaults
        trip_df['YEAR'] = trip_df['DATE REPORTED'].dt.year
        min_year = int(trip_df['YEAR'].min())
        max_year = int(trip_df['YEAR'].max())
        year_options = ['All'] + list(range(min_year, max_year+1))
        year_filter_r = st.selectbox("Select Year (quick)", ['All'] + list(range(min_year, max_year+1)), key="ri_year_quick")

    # Time range selectors: start year, end year, start month, end month
    # defaults: start year = min_year, end year = max_year; start & end months default to month of earliest DATE REPORTED
    min_date = trip_df['DATE REPORTED'].min()
    max_date = trip_df['DATE REPORTED'].max()
    default_start_year = min_year
    default_end_year = max_year
    default_start_month_num = int(min_date.month) if pd.notna(min_date) else 1
    default_end_month_num = default_start_month_num

    st.markdown("### Select Time Range for Reliability Calculations")
    colA, colB, colC, colD = st.columns(4)
    with colA:
        start_year = st.selectbox("Start Year", options=list(range(min_year, max_year+1)), index=0, key="ri_start_year")
    with colB:
        end_year = st.selectbox("End Year", options=list(range(min_year, max_year+1)), index=(max_year-min_year), key="ri_end_year")
    with colC:
        month_names = ['January','February','March','April','May','June','July','August','September','October','November','December']
        start_month_name = st.selectbox("Start Month", month_names, index=default_start_month_num-1, key="ri_start_month")
    with colD:
        end_month_name = st.selectbox("End Month", month_names, index=default_end_month_num-1, key="ri_end_month")

    # Build start and end timestamps (start at beginning of start month, end at month end of end month)
    start_month_num = datetime.strptime(start_month_name, "%B").month
    end_month_num = datetime.strptime(end_month_name, "%B").month
    start_ts = pd.Timestamp(year=int(start_year), month=int(start_month_num), day=1)
    end_ts = (pd.Timestamp(year=int(end_year), month=int(end_month_num), day=1) + MonthEnd(1))

    # Apply page-level filters to form reliability_df
    reliability_df = trip_df.copy()
    if bu_filter_r != 'All':
        reliability_df = reliability_df[reliability_df['BUSINESS UNIT'].astype(str) == bu_filter_r]
    if undertaking_filter_r and 'RESPONSIBLE UNDERTAKINGS' in trip_df.columns:
        reliability_df = reliability_df[reliability_df['UNDERTAKINGS_LIST'].apply(lambda x: any(u in undertaking_filter_r for u in x))]
    if feeder_filter_r != 'All':
        reliability_df = reliability_df[reliability_df['11kV FEEDER'].astype(str) == feeder_filter_r]

    # Time range filter
    reliability_df = reliability_df[(reliability_df['DATE REPORTED'] >= start_ts) & (reliability_df['DATE REPORTED'] <= end_ts)]

    if reliability_df.empty:
        st.warning("No data matches the selected filters and time range for Reliability Indices.")
        st.stop()

    # -----------------------------
    # Persistent thresholds (session_state)
    # -----------------------------
    default_thresholds = {
        "SAIFI": 10.0,
        "SAIDI_hours": 40.0,
        "CAIDI_hours": 2.0,
        "Failure Rate": 0.1,   # failures per hour
        "MTBF_hours": 500.0,
        "MTTR_hours": 2.0,
        "Reliability": 0.9,
        "Availability": 0.95,
        "ASAI": 0.95,
        "ASUI": 0.05,
        "ENS_MWh": 100000.0
    }

    for key, val in default_thresholds.items():
        if key not in st.session_state:
            st.session_state[key] = val

    with st.expander("⚙️ Set Performance Thresholds (persist until refresh)"):
        st.write("Adjust thresholds used to color-code the metric cards.")
        # Note: we store multiple keys; use distinct widget keys to avoid collisions
        st.session_state["SAIFI"] = st.number_input("SAIFI threshold (interruptions/customer)", value=float(st.session_state["SAIFI"]), step=0.1, key="thr_saifi")
        st.session_state["SAIDI_hours"] = st.number_input("SAIDI threshold (hours/customer)", value=float(st.session_state["SAIDI_hours"]), step=0.1, key="thr_saidi")
        st.session_state["CAIDI_hours"] = st.number_input("CAIDI threshold (hours/interruption)", value=float(st.session_state["CAIDI_hours"]), step=0.1, key="thr_caidi")
        st.session_state["Failure Rate"] = st.number_input("Failure Rate λ threshold (failures/hour)", value=float(st.session_state["Failure Rate"]), step=0.0001, key="thr_lambda")
        st.session_state["MTBF_hours"] = st.number_input("MTBF threshold (hours)", value=float(st.session_state["MTBF_hours"]), step=1.0, key="thr_mtbf")
        st.session_state["MTTR_hours"] = st.number_input("MTTR threshold (hours)", value=float(st.session_state["MTTR_hours"]), step=0.1, key="thr_mttr")
        st.session_state["Reliability"] = st.number_input("Reliability R(t) threshold (0-1)", value=float(st.session_state["Reliability"]), min_value=0.0, max_value=1.0, step=0.01, key="thr_reliability")
        st.session_state["Availability"] = st.number_input("Availability threshold (0-1)", value=float(st.session_state["Availability"]), min_value=0.0, max_value=1.0, step=0.01, key="thr_availability")
        st.session_state["ASAI"] = st.number_input("ASAI threshold (0-1)", value=float(st.session_state["ASAI"]), min_value=0.0, max_value=1.0, step=0.01, key="thr_asai")
        st.session_state["ASUI"] = st.number_input("ASUI threshold (0-1)", value=float(st.session_state["ASUI"]), min_value=0.0, max_value=1.0, step=0.01, key="thr_asui")
        st.session_state["ENS_MWh"] = st.number_input("ENS threshold (MWh)", value=float(st.session_state["ENS_MWh"]), step=100.0, key="thr_ens")

    # -----------------------------
    # Map customers affected per trip & compute totals
    # -----------------------------
    # Normalize mapping keys (uppercase no leading/trailing spaces)
    cust_map = {k.upper().strip(): v for k, v in customers_per_feeder.items()}

    def customers_for_feeder(feeder_name):
        if pd.isna(feeder_name):
            return 0
        key = str(feeder_name).upper().strip()
        return cust_map.get(key, 0)

    reliability_df = reliability_df.copy()
    reliability_df['CUSTOMERS_AFFECTED'] = reliability_df['11kV FEEDER'].apply(customers_for_feeder)

    # If selected feeders have zero customers (mapping missing), fallback to total_active_customers
    selected_feeders_list = reliability_df['11kV FEEDER'].dropna().unique().tolist()
    total_customers_for_selection = sum(customers_for_feeder(f) for f in selected_feeders_list)
    if total_customers_for_selection == 0:
        total_customers_for_selection = total_active_customers

    # total customer interruptions (sum customers affected across trips)
    total_customer_interruptions = reliability_df['CUSTOMERS_AFFECTED'].sum()

    # duration minutes per trip
    reliability_df['DURATION_MINUTES'] = ((reliability_df['RESTORED_TIMESTAMP'] - reliability_df['REPORTED_TIMESTAMP']).dt.total_seconds() / 60).abs().fillna(0)
    customer_minutes_sustained = (reliability_df['DURATION_MINUTES'] * reliability_df['CUSTOMERS_AFFECTED']).sum()

    # SAIFI, SAIDI (in minutes), CAIDI (minutes)
    saifi = (total_customer_interruptions / total_customers_for_selection) if total_customers_for_selection > 0 else 0
    saidi_minutes = (customer_minutes_sustained / total_customers_for_selection) if total_customers_for_selection > 0 else 0
    caidi_minutes = (saidi_minutes / saifi) if saifi > 0 else 0
    saidi_hours = saidi_minutes / 60.0
    caidi_hours = caidi_minutes / 60.0

    # ENS
    ens_mwh = reliability_df['ENERGY_LOSS_MWH'].sum()

    # Failure rate, MTBF, MTTR, Availability, Reliability
    # Compute operating hours in selected range: difference between start_ts and end_ts in hours
    operating_hours_period = (end_ts - start_ts).total_seconds() / 3600.0
    # Number of outages (trips) in the selected range
    num_outages = len(reliability_df)
    # Number of feeders considered (use unique feeders in selection)
    feeders_considered_count = len(selected_feeders_list) if len(selected_feeders_list) > 0 else max(1, len(cust_map))

    total_operating_hours_for_feeders = operating_hours_period * feeders_considered_count

    # Failure rate (lambda) = number of outages / total operating hours
    failure_rate = (num_outages / total_operating_hours_for_feeders) if total_operating_hours_for_feeders > 0 else 0.0
    mtbf_hours = (total_operating_hours_for_feeders / num_outages) if num_outages > 0 else 0.0
    mttr_hours = (reliability_df['DOWNTIME_HOURS'].sum() / num_outages) if num_outages > 0 else 0.0
    # Reliability over the period t = operating_hours_period (hours)
    reliability_val = math.exp(-failure_rate * operating_hours_period) if operating_hours_period > 0 else 0.0
    availability_val = mtbf_hours / (mtbf_hours + mttr_hours) if (mtbf_hours + mttr_hours) > 0 else 0.0

    # ASAI / ASUI
    customer_hours_demanded = total_customers_for_selection * operating_hours_period
    customer_hours_interrupted = customer_minutes_sustained / 60.0
    asai = ((customer_hours_demanded - customer_hours_interrupted) / customer_hours_demanded) if customer_hours_demanded > 0 else 0.0
    asui = 1.0 - asai if customer_hours_demanded > 0 else 0.0

    # -----------------------------
    # Metric selection dropdown
    # -----------------------------
    metric_option = st.selectbox(
        "Select Reliability Metric to View",
        [
            "SAIDI/SAIFI/CAIDI",
            "Failure Rate (λ)",
            "MTBF",
            "MTTR",
            "Reliability (R(t))",
            "Availability (A)",
            "ASAI",
            "ASUI",
            "ENS"
        ]
    )

    # Determine good/bad based on session thresholds
    # SAIFI: lower is better => good if <= threshold
    saifi_good = saifi <= float(st.session_state["SAIFI"])
    saidi_good = saidi_hours <= float(st.session_state["SAIDI_hours"])
    caidi_good = caidi_hours <= float(st.session_state["CAIDI_hours"])
    failure_rate_good = failure_rate <= float(st.session_state["Failure Rate"])
    mtbf_good = mtbf_hours >= float(st.session_state["MTBF_hours"])
    mttr_good = mttr_hours <= float(st.session_state["MTTR_hours"])
    reliability_good = reliability_val >= float(st.session_state["Reliability"])
    availability_good = availability_val >= float(st.session_state["Availability"])
    asai_good = asai >= float(st.session_state["ASAI"])
    asui_good = asui <= float(st.session_state["ASUI"])
    ens_good = ens_mwh <= float(st.session_state["ENS_MWh"])

    # Display metrics/cards
    st.markdown("### Key Reliability Metrics")
    mcol1, mcol2, mcol3, mcol4 = st.columns(4)
    if metric_option == "SAIDI/SAIFI/CAIDI":
        with mcol1:
            st.markdown(metric_with_color("SAIFI (Interruptions/Customer)", f"{saifi:.3f}", saifi_good), unsafe_allow_html=True)
            st.caption(f"Threshold: {st.session_state['SAIFI']}")
        with mcol2:
            st.markdown(metric_with_color("SAIDI (Minutes/Customer)", f"{saidi_minutes:.2f} min ({saidi_hours:.2f} hrs)", saidi_good), unsafe_allow_html=True)
            st.caption(f"Threshold: {st.session_state['SAIDI_hours']} hrs")
        with mcol3:
            st.markdown(metric_with_color("CAIDI (Minutes/Interruption)", f"{caidi_minutes:.2f} min ({caidi_hours:.2f} hrs)", caidi_good), unsafe_allow_html=True)
            st.caption(f"Threshold: {st.session_state['CAIDI_hours']} hrs")
        with mcol4:
            st.markdown(metric_with_color("ENS (MWh)", f"{ens_mwh:,.2f}", ens_good), unsafe_allow_html=True)
            st.caption(f"Threshold: {st.session_state['ENS_MWh']:,.0f} MWh")
    else:
        # Show the selected metric in the first column card and summary in others
        with mcol1:
            if metric_option == "Failure Rate (λ)":
                st.markdown(metric_with_color("Failure Rate λ (failures/hour)", f"{failure_rate:.6f}", failure_rate_good), unsafe_allow_html=True)
                st.caption(f"Threshold: {st.session_state['Failure Rate']}")
            elif metric_option == "MTBF":
                st.markdown(metric_with_color("MTBF (hrs)", f"{mtbf_hours:.2f}", mtbf_good), unsafe_allow_html=True)
                st.caption(f"Threshold: {st.session_state['MTBF_hours']} hrs")
            elif metric_option == "MTTR":
                st.markdown(metric_with_color("MTTR (hrs)", f"{mttr_hours:.2f}", mttr_good), unsafe_allow_html=True)
                st.caption(f"Threshold: {st.session_state['MTTR_hours']} hrs")
            elif metric_option == "Reliability (R(t))":
                st.markdown(metric_with_color("Reliability R(t)", f"{reliability_val:.6f}", reliability_good), unsafe_allow_html=True)
                st.caption(f"Threshold: {st.session_state['Reliability']}")
            elif metric_option == "Availability (A)":
                st.markdown(metric_with_color("Availability A", f"{availability_val:.6f}", availability_good), unsafe_allow_html=True)
                st.caption(f"Threshold: {st.session_state['Availability']}")
            elif metric_option == "ASAI":
                st.markdown(metric_with_color("ASAI", f"{asai:.6f}", asai_good), unsafe_allow_html=True)
                st.caption(f"Threshold: {st.session_state['ASAI']}")
            elif metric_option == "ASUI":
                st.markdown(metric_with_color("ASUI", f"{asui:.6f}", asui_good), unsafe_allow_html=True)
                st.caption(f"Threshold: {st.session_state['ASUI']}")
            elif metric_option == "ENS":
                st.markdown(metric_with_color("ENS (MWh)", f"{ens_mwh:,.2f}", ens_good), unsafe_allow_html=True)
                st.caption(f"Threshold: {st.session_state['ENS_MWh']:,} MWh")
        # Show quick additional stats
        with mcol2:
            st.markdown(f"**Total Active Customers (used)**: {total_customers_for_selection:,}")
        with mcol3:
            st.markdown(f"**Number of outages in range**: {num_outages:,}")
        with mcol4:
            st.markdown(f"**Operating hours period**: {operating_hours_period:,.2f} hours")

    # Monthly SAIFI & SAIDI charts (for the selected time range)
    st.subheader("Monthly SAIFI & SAIDI (for selected time range and filters)")

    # month range list between start_ts and end_ts inclusive
    month_periods = pd.period_range(start=start_ts, end=end_ts, freq='M')
    months_list = [p.strftime('%B %Y') for p in month_periods]

    saifi_months = []
    saidi_months = []
    for p in month_periods:
        month_start = p.to_timestamp(how='start')
        month_end = p.to_timestamp(how='end')
        mdf = reliability_df[(reliability_df['DATE REPORTED'] >= month_start) & (reliability_df['DATE REPORTED'] <= month_end)]
        if mdf.empty:
            saifi_months.append(0.0)
            saidi_months.append(0.0)
            continue
        # customer interruptions in month
        cust_interruptions_month = mdf['CUSTOMERS_AFFECTED'].sum()
        duration_minutes_month = ( (mdf['RESTORED_TIMESTAMP'] - mdf['REPORTED_TIMESTAMP']).dt.total_seconds() / 60 ).abs().fillna(0)
        cust_minutes_month = (duration_minutes_month * mdf['CUSTOMERS_AFFECTED']).sum()
        saifi_m = (cust_interruptions_month / total_customers_for_selection) if total_customers_for_selection > 0 else 0.0
        saidi_m = (cust_minutes_month / total_customers_for_selection) if total_customers_for_selection > 0 else 0.0
        saifi_months.append(saifi_m)
        saidi_months.append(saidi_m / 60.0)  # convert to hours for chart

    monthly_df = pd.DataFrame({
        'Month': months_list,
        'SAIFI': saifi_months,
        'SAIDI_hours': saidi_months
    }).set_index('Month')

    st.markdown("**Monthly SAIFI**")
    st.bar_chart(monthly_df['SAIFI'])
    st.markdown("**Monthly SAIDI (hours)**")
    st.bar_chart(monthly_df['SAIDI_hours'])

    # Feeder counts expander
    with st.expander("Feeder → Active Customer Counts (from Customer Info)"):
        feeder_counts_df = pd.DataFrame([
            {'FEEDER_NAME': k, 'ACTIVE_CUSTOMERS': v} for k, v in customers_per_feeder.items()
        ]).sort_values('FEEDER_NAME')
        st.dataframe(feeder_counts_df)

st.markdown(
    """
    <hr style="margin-top:2em;margin-bottom:0.5em;">
    <div style="text-align:center; color:gray;">
        Developed by <b>Elvis Ebenuwah</b> | ⚡ Powered by GridMetrix
    </div>
    """,
    unsafe_allow_html=True
)


# End of app
