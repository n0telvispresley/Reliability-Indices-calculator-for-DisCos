import streamlit as st
import pandas as pd
import plotly.express as px
import streamlit.components.v1 as components
from datetime import datetime
import re

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
st.set_page_config(page_title="Ikeja Electric Fault Clearance Dashboard", layout="wide")

# Custom function for comma-separated number formatting
def format_number(value, decimals=2):
    if pd.isna(value):
        return "NaN"
    try:
        if decimals == 0:
            return f"{int(value):,}"
        return f"{value:,.{decimals}f}"
    except (ValueError, TypeError):
        return "NaN"

# Function to clean LOAD LOSS values
def clean_load_loss(value):
    if not isinstance(value, str) or pd.isna(value):
        return value
    # Replace 'o' or 'O' with '0' in numeric parts
    value = re.sub(r'[oO]', '0', value)
    # Extract numeric part, remove units like 'amps', 'a', etc.
    match = re.match(r'^\s*(\d*\.?\d*)\s*(?:amps?|a|A)?\s*$', value, re.IGNORECASE)
    if match:
        return match.group(1)
    return value

# feeder extraction from DT_NAME (everything except last '-' segment)
def extract_feeder_from_dtname(dt_name):
    if pd.isna(dt_name):
        return None
    parts = str(dt_name).split('-')
    if len(parts) <= 1:
        return str(dt_name)
    return '-'.join(parts[:-1]).strip()

# Classify faults (reuse your logic)
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

# Feeder rating function (reuse)
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

# Suggest maintenance (reuse)
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

# Parse phases (reuse)
def parse_phases(phase_str):
    if not isinstance(phase_str, str) or pd.isna(phase_str) or phase_str.lower() == 'nan':
        return []
    phase_str = re.sub(r'\s*AND\s*|\s*&\s*|,\s*', ',', phase_str, flags=re.IGNORECASE)
    phases = [p.strip().lower() for p in phase_str.split(',') if p.strip()]
    return phases

# Sidebar: page selector
page = st.sidebar.radio("Select Page", ["Fault Analysis", "Reliability Indices"])

# File uploader in main area (keep same place as original)
st.title("Ikeja Electric Monthly Fault Clearance Dashboard")
st.markdown("Upload an Excel file (must contain sheets: '11kV Tripping Log' and 'Customer Info').")

uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])

if uploaded_file is not None:
    # Read both sheets: trip log (header=0 now) and customer info
    try:
        df = pd.read_excel(uploaded_file, sheet_name="11kV Tripping Log", header=0)
    except Exception as e:
        st.error(f"Error reading '11kV Tripping Log' sheet: {e}")
        st.stop()
    try:
        cust_df = pd.read_excel(uploaded_file, sheet_name="Customer Info", header=0)
    except Exception as e:
        st.error(f"Error reading 'Customer Info' sheet: {e}")
        st.stop()

    # Validate customer sheet columns minimally (DT_NAME required)
    if 'DT_NAME' not in cust_df.columns or 'ACCOUNT_NUMBER' not in cust_df.columns or 'STATUS' not in cust_df.columns:
        st.error("Customer Info sheet must contain ACCOUNT_NUMBER, DT_NAME and STATUS columns.")
        st.stop()

    # Prepare customer info for feeder mapping and counting
    cust_df['FEEDER_NAME'] = cust_df['DT_NAME'].apply(extract_feeder_from_dtname)
    # Normalize feeder names for matching
    cust_df['FEEDER_NAME'] = cust_df['FEEDER_NAME'].astype(str).str.strip()
    cust_df['STATUS'] = cust_df['STATUS'].astype(str).str.strip()
    # Count active customers
    active_cust_df = cust_df[cust_df['STATUS'].str.upper() == 'ACTIVE']
    total_active_customers = active_cust_df['ACCOUNT_NUMBER'].nunique()
    customers_per_feeder = active_cust_df.groupby('FEEDER_NAME')['ACCOUNT_NUMBER'].nunique().to_dict()

    # ---------- Begin: Keep your Fault Analysis code (unchanged logic) ----------
    # CLEAN & PROCESS TRIPPING LOG (we only changed header reading above)
    # Validate required columns
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

    missing_required = [col for col in required_columns if col not in df.columns]
    missing_optional = [col for col in optional_columns if col not in df.columns]
    if missing_required:
        st.error(f"Error: Missing required columns: {', '.join(missing_required)}. Please check the Excel file headers (row 1).")
        st.stop()
    if missing_optional:
        st.warning(f"Missing optional columns: {', '.join(missing_optional)}. Some features may be disabled.")

    # Clean LOAD LOSS before conversion
    df['LOAD LOSS'] = df['LOAD LOSS'].apply(clean_load_loss)

    # Ensure date and time columns are in datetime format
    date_time_cols = ['DATE REPORTED', 'TIME REPORTED', 'DATE CLEARED', 'TIME CLEARED', 'DATE RESTORED', 'TIME RESTORED']
    for col in date_time_cols:
        if col in df.columns:
            if 'DATE' in col:
                df[col] = pd.to_datetime(df[col], errors='coerce')
            else:
                # try flexible parsing; keep your original expected format but allow coercion
                df[col] = pd.to_datetime(df[col], errors='coerce', format='%H:%M:%S')

    # Combine date and time for full timestamps
    # (Your original logic used .dt.strftime which worked for you; keep it)
    try:
        df['REPORTED_TIMESTAMP'] = df['DATE REPORTED'] + pd.to_timedelta(df['TIME REPORTED'].dt.strftime('%H:%M:%S'))
        df['RESTORED_TIMESTAMP'] = df['DATE RESTORED'] + pd.to_timedelta(df['TIME RESTORED'].dt.strftime('%H:%M:%S'))
        df['CLEARED_TIMESTAMP'] = df['DATE CLEARED'] + pd.to_timedelta(df['TIME CLEARED'].dt.strftime('%H:%M:%S'))
    except Exception as e:
        st.error(f"Error creating timestamps: {str(e)}. Check date/time column formats.")
        st.stop()

    # Calculate downtime (in hours) and ensure positive
    df['DOWNTIME_HOURS'] = (df['RESTORED_TIMESTAMP'] - df['REPORTED_TIMESTAMP']).dt.total_seconds() / 3600
    df['DOWNTIME_HOURS'] = df['DOWNTIME_HOURS'].abs()

    # Calculate clearance time (in hours) and ensure positive
    df['CLEARANCE_TIME_HOURS'] = (df['CLEARED_TIMESTAMP'] - df['REPORTED_TIMESTAMP']).dt.total_seconds() / 3600
    df['CLEARANCE_TIME_HOURS'] = df['CLEARANCE_TIME_HOURS'].abs()

    # Filter out faults labeled "Opened on Emergency", "OE", or "emergency"
    df['FAULT/OPERATION'] = df['FAULT/OPERATION'].astype(str).replace('nan', 'Unknown')
    initial_count = len(df)
    df = df[~df['FAULT/OPERATION'].str.lower().str.contains('opened on emergency|oe|emergency', na=False)]
    filtered_count = initial_count - len(df)
    if filtered_count > 0:
        st.info(f"Excluded {filtered_count} faults labeled 'Opened on Emergency', 'OE', or 'emergency' as they are handled by CHQ.")

    # Debug outputs in expander
    with st.expander("Debug Data (For Validation)"):
        st.write("**Columns in DataFrame**")
        st.write(df.columns.tolist())
        st.write("**LOAD LOSS (Current in Amps) Column**")
        st.write("Raw sample values:", df['LOAD LOSS'].head().to_list())
        st.write("Data type:", df['LOAD LOSS'].dtype)
        st.write("Any non-numeric values after cleaning:", df['LOAD LOSS'].apply(lambda x: not isinstance(x, (int, float)) and pd.notna(x)).sum())
        st.write("**FAULT/OPERATION Column**")
        st.write("Sample values:", df['FAULT/OPERATION'].head().to_list())
        st.write("Data type:", df['FAULT/OPERATION'].dtype)
        st.write("Any non-string values:", df['FAULT/OPERATION'].apply(lambda x: not isinstance(x, str) and pd.notna(x)).sum())
        st.write("**PHASE AFFECTED Column**")
        st.write("Sample values:", df['PHASE AFFECTED'].head().to_list())
        st.write("Data type:", df['PHASE AFFECTED'].dtype)
        st.write("**11kV FEEDER Column**")
        st.write("Sample values:", df['11kV FEEDER'].head().to_list())
        st.write("**BUSINESS UNIT Column**")
        st.write("Sample values:", df['BUSINESS UNIT'].head().to_list())
        if 'RESPONSIBLE UNDERTAKINGS' in df.columns:
            st.write("**RESPONSIBLE UNDERTAKINGS Column**")
            st.write("Sample values:", df['RESPONSIBLE UNDERTAKINGS'].head().to_list())
        if 'FINDINGS/ACTION TAKEN' in df.columns:
            st.write("**FINDINGS/ACTION TAKEN Column**")
            st.write("Sample values:", df['FINDINGS/ACTION TAKEN'].head().to_list())

    # Convert LOAD LOSS to numeric, coercing invalid values to NaN
    df['LOAD LOSS'] = pd.to_numeric(df['LOAD LOSS'], errors='coerce')

    # Extract voltage (11 kV or 33 kV) from the first part of 11kV FEEDER
    def extract_voltage(feeder_name):
        if not isinstance(feeder_name, str) or pd.isna(feeder_name):
            return None
        try:
            voltage_kv = float(feeder_name.split('-')[0].strip())
            return voltage_kv * 1000
        except (ValueError, IndexError):
            return None

    df['VOLTAGE_V'] = df['11kV FEEDER'].apply(extract_voltage)

    # Check for NaN values in critical columns
    if df['LOAD LOSS'].isna().sum() > 0:
        st.warning(f"Found {df['LOAD LOSS'].isna().sum()} non-numeric or missing values in LOAD LOSS (current) after cleaning. These have been converted to NaN.")
    if df['VOLTAGE_V'].isna().sum() > 0:
        st.warning(f"Found {df['VOLTAGE_V'].isna().sum()} invalid voltage values derived from 11kV FEEDER. Ensure feeder names start with '11-' or '33-'. These have been converted to NaN.")
    if df['CLEARANCE_TIME_HOURS'].isna().sum() > 0:
        st.warning(f"Found {df['CLEARANCE_TIME_HOURS'].isna().sum()} invalid clearance times due to missing or incorrect date/time data.")
    if df['BUSINESS UNIT'].isna().sum() > 0:
        st.warning(f"Found {df['BUSINESS UNIT'].isna().sum()} missing values in BUSINESS UNIT. These may affect filtering.")
    if 'RESPONSIBLE UNDERTAKINGS' in df.columns and df['RESPONSIBLE UNDERTAKINGS'].isna().sum() > 0:
        st.warning(f"Found {df['RESPONSIBLE UNDERTAKINGS'].isna().sum()} missing values in RESPONSIBLE UNDERTAKINGS. These may affect filtering.")
    if 'FINDINGS/ACTION TAKEN' in df.columns and df['FINDINGS/ACTION TAKEN'].isna().sum() > 0:
        st.warning(f"Found {df['FINDINGS/ACTION TAKEN'].isna().sum()} missing values in FINDINGS/ACTION TAKEN. These may affect outlier analysis.")

    # Handle multiple undertakings by creating a list column for filtering
    if 'RESPONSIBLE UNDERTAKINGS' in df.columns:
        def split_undertakings(undertakings):
            if not isinstance(undertakings, str) or pd.isna(undertakings):
                return []
            # Replace multiple separators with /
            undertakings = re.sub(r'\s*(?:AND|&|and)\s*', '/', undertakings, flags=re.IGNORECASE)
            # Split on / and normalize (lowercase, strip whitespace)
            return [u.strip().lower() for u in undertakings.split('/') if u.strip()]
        df['UNDERTAKINGS_LIST'] = df['RESPONSIBLE UNDERTAKINGS'].apply(split_undertakings)

    # Calculate energy loss using E = I * V * t (in watt-hours, then convert to MWh)
    df['ENERGY_LOSS_WH'] = df['LOAD LOSS'] * df['VOLTAGE_V'] * df['DOWNTIME_HOURS']
    df['ENERGY_LOSS_MWH'] = df['ENERGY_LOSS_WH'] / 1_000_000

    # Monetary loss (using 209.5 NGN/kWh for Band A feeders, convert to millions)
    df['MONETARY_LOSS_NGN_MILLIONS'] = (df['ENERGY_LOSS_MWH'] * 1000 * 209.5) / 1_000_000

    # Fault classification (reuse)
    df['FAULT_TYPE'] = df['FAULT/OPERATION'].apply(classify_fault)

    # Feeder ratings
    feeder_downtime = df.groupby('11kV FEEDER')['DOWNTIME_HOURS'].mean().reset_index()
    feeder_downtime = calculate_feeder_ratings(feeder_downtime)

    # Frequent tripping feeders
    feeder_trips = df['11kV FEEDER'].value_counts().reset_index()
    feeder_trips.columns = ['11kV FEEDER', 'TRIP_COUNT']
    frequent_trippers = feeder_trips[feeder_trips['TRIP_COUNT'] > 2]

    # Maintenance suggestions
    df['MAINTENANCE_SUGGESTION'] = df['FAULT/OPERATION'].apply(suggest_maintenance)

    # Phase-specific faults
    df['PHASE_AFFECTED_LIST'] = df['PHASE AFFECTED'].apply(parse_phases)
    phase_types = ['red', 'yellow', 'blue', 'earth fault', 'neutral']
    phase_counts = {phase: 0 for phase in phase_types}
    for phases in df['PHASE_AFFECTED_LIST']:
        for phase in phases:
            if phase in phase_counts:
                phase_counts[phase] += 1
    phase_faults = pd.DataFrame({
        'Phase Affected': phase_counts.keys(),
        'Fault Count': phase_counts.values()
    })
    phase_faults = phase_faults[phase_faults['Fault Count'] > 0]

    # Maintenance priority score
    df['PRIORITY_SCORE'] = (
        0.4 * (df['CLEARANCE_TIME_HOURS'] / df['CLEARANCE_TIME_HOURS'].max()) +
        0.4 * (df['ENERGY_LOSS_MWH'] / df['ENERGY_LOSS_MWH'].max()) +
        0.2 * df['11kV FEEDER'].map(feeder_trips.set_index('11kV FEEDER')['TRIP_COUNT']) / feeder_trips['TRIP_COUNT'].max()
    ).fillna(0)

    # Identify clearance time outliers (>48 hours)
    outlier_columns = ['11kV FEEDER', 'FAULT_TYPE', 'CLEARANCE_TIME_HOURS']
    if 'FINDINGS/ACTION TAKEN' in df.columns:
        outlier_columns.append('FINDINGS/ACTION TAKEN')
    clearance_outliers = df[df['CLEARANCE_TIME_HOURS'] > 48][outlier_columns]
    clearance_outliers['CLEARANCE_TIME_HOURS'] = clearance_outliers['CLEARANCE_TIME_HOURS'].round(2)

    # ---------- Fault Analysis Page UI (unchanged logic and layout) ----------
    if page == "Fault Analysis":
        # Dynamic filters (same as original)
        st.subheader("Filter Data")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            bu_filter = st.selectbox("Select Business Unit", ['All'] + sorted(df['BUSINESS UNIT'].unique().astype(str).tolist()))
        with col2:
            if 'RESPONSIBLE UNDERTAKINGS' in df.columns:
                # Get unique undertakings by splitting multi-undertaking entries
                all_undertakings = set()
                for undertakings in df['UNDERTAKINGS_LIST']:
                    all_undertakings.update(undertakings)
                undertaking_options = sorted(list(all_undertakings))
                undertaking_filter = st.multiselect("Select Responsible Undertakings", undertaking_options, default=undertaking_options)
            else:
                undertaking_filter = []
                st.write("Responsible Undertakings filter disabled (column not found).")
        with col3:
            feeder_filter = st.selectbox("Select Feeder", ['All'] + sorted(df['11kV FEEDER'].unique().astype(str).tolist()))
        with col4:
            df['YEAR'] = df['DATE REPORTED'].dt.year
            year_filter = st.selectbox("Select Year", ['All'] + sorted(df['YEAR'].unique().tolist()))
            df['MONTH'] = df['DATE REPORTED'].dt.month
            month_filter = st.selectbox("Select Month", ['All'] + sorted(df['MONTH'].unique().tolist()))

        # Apply filters
        filtered_df = df
        if bu_filter != 'All':
            filtered_df = filtered_df[filtered_df['BUSINESS UNIT'].astype(str) == bu_filter]
        if undertaking_filter and 'RESPONSIBLE UNDERTAKINGS' in df.columns:
            filtered_df = filtered_df[filtered_df['UNDERTAKINGS_LIST'].apply(lambda x: any(u in undertaking_filter for u in x))]
        if feeder_filter != 'All':
            filtered_df = filtered_df[filtered_df['11kV FEEDER'].astype(str) == feeder_filter]
        if year_filter != 'All':
            filtered_df = filtered_df[filtered_df['YEAR'] == year_filter]
        if month_filter != 'All':
            filtered_df = filtered_df[filtered_df['MONTH'] == month_filter]

        # Check if filtered data is empty
        if filtered_df.empty:
            st.warning("No data matches the selected filters. Try different options.")
            st.stop()

        # Update metrics and visuals based on filtered data (same as your original)
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
        if 'FINDINGS/ACTION TAKEN' in df.columns:
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
        if 'RESPONSIBLE UNDERTAKINGS' in df.columns:
            cols_to_show.insert(1, 'RESPONSIBLE UNDERTAKINGS')
        st.dataframe(filtered_df[cols_to_show].drop_duplicates())

        st.subheader("High-Priority Faults")
        cols_to_show = ['BUSINESS UNIT', '11kV FEEDER', 'FAULT_TYPE', 'CLEARANCE_TIME_HOURS', 'ENERGY_LOSS_MWH', 'PRIORITY_SCORE']
        if 'RESPONSIBLE UNDERTAKINGS' in df.columns:
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
        if 'RESPONSIBLE UNDERTAKINGS' in df.columns:
            cols_to_export.insert(1, 'RESPONSIBLE UNDERTAKINGS')
        if 'FINDINGS/ACTION TAKEN' in df.columns:
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

    # ---------- Reliability Indices Page ----------
    elif page == "Reliability Indices":
        st.subheader("Reliability Indices")

        # replicate filters (same UX as Fault Analysis)
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            bu_filter_r = st.selectbox("Select Business Unit", ['All'] + sorted(df['BUSINESS UNIT'].unique().astype(str).tolist()), key="ri_bu")
        with col2:
            if 'RESPONSIBLE UNDERTAKINGS' in df.columns:
                # Get unique undertakings
                all_undertakings = set()
                for undertakings in df['UNDERTAKINGS_LIST']:
                    all_undertakings.update(undertakings)
                undertaking_options = sorted(list(all_undertakings))
                undertaking_filter_r = st.multiselect("Select Responsible Undertakings", undertaking_options, default=undertaking_options, key="ri_undertaking")
            else:
                undertaking_filter_r = []
                st.write("Responsible Undertakings filter disabled (column not found).")
        with col3:
            feeder_filter_r = st.selectbox("Select Feeder", ['All'] + sorted(df['11kV FEEDER'].unique().astype(str).tolist()), key="ri_feeder")
        with col4:
            df['YEAR'] = df['DATE REPORTED'].dt.year
            year_filter_r = st.selectbox("Select Year", ['All'] + sorted(df['YEAR'].unique().tolist()), key="ri_year")
            df['MONTH_NAME'] = df['DATE REPORTED'].dt.month_name()
            month_filter_r = st.selectbox("Select Month", ['All'] + sorted(df['MONTH_NAME'].unique().tolist(), key=lambda x: datetime.strptime(x, "%B").month), key="ri_month")

        # Apply filters to get reliability_df
        reliability_df = df.copy()
        if bu_filter_r != 'All':
            reliability_df = reliability_df[reliability_df['BUSINESS UNIT'].astype(str) == bu_filter_r]
        if undertaking_filter_r and 'RESPONSIBLE UNDERTAKINGS' in df.columns:
            reliability_df = reliability_df[reliability_df['UNDERTAKINGS_LIST'].apply(lambda x: any(u in undertaking_filter_r for u in x))]
        if feeder_filter_r != 'All':
            reliability_df = reliability_df[reliability_df['11kV FEEDER'].astype(str) == feeder_filter_r]
        if year_filter_r != 'All':
            reliability_df = reliability_df[reliability_df['YEAR'] == year_filter_r]
        if month_filter_r != 'All':
            reliability_df = reliability_df[reliability_df['MONTH_NAME'] == month_filter_r]

        if reliability_df.empty:
            st.warning("No data matches the selected filters for Reliability Indices.")
            st.stop()

        # Map customers affected per trip using FEEDER mapping derived from Customer Info
        # Here we assume trip's '11kV FEEDER' equals cust_df FEEDER_NAME
        def customers_for_feeder(feeder_name):
            if pd.isna(feeder_name):
                return 0
            return customers_per_feeder.get(str(feeder_name).strip(), 0)

        reliability_df['CUSTOMERS_AFFECTED'] = reliability_df['11kV FEEDER'].apply(customers_for_feeder)

        # Total customers (active) from cust_df
        total_customers = total_active_customers if total_active_customers > 0 else 0

        # Total customer interruptions (sum of customers affected per trip)
        total_customer_interruptions = reliability_df['CUSTOMERS_AFFECTED'].sum()

        # Customer minutes sustained (DURATION in minutes * customers affected)
        # Use restored - reported in minutes
        reliability_df['DURATION_MINUTES'] = ((reliability_df['RESTORED_TIMESTAMP'] - reliability_df['REPORTED_TIMESTAMP']).dt.total_seconds() / 60).abs()
        customer_minutes_sustained = (reliability_df['DURATION_MINUTES'] * reliability_df['CUSTOMERS_AFFECTED']).sum()

        # SAIFI, SAIDI (minutes), CAIDI (minutes)
        saifi = (total_customer_interruptions / total_customers) if total_customers > 0 else 0
        saidi_minutes = (customer_minutes_sustained / total_customers) if total_customers > 0 else 0
        caidi_minutes = (saidi_minutes / saifi) if saifi > 0 else 0

        # Convert SAIDI & CAIDI to hours for display where appropriate
        saidi_hours = saidi_minutes / 60
        caidi_hours = caidi_minutes / 60

        # ENS = sum of ENERGY_LOSS_MWH in filtered dataset
        ens_mwh = reliability_df['ENERGY_LOSS_MWH'].sum()

        # Standards
        SAIFI_STD = 5.0
        SAIDI_STD_HOURS = 20.0  # hours
        CAIDI_STD_HOURS = 4.0   # hours
        ENS_STD_MWH = 100000.0  # MWh

        # Color-coded metric helper (HTML)
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

        # Determine good/bad
        saifi_good = saifi <= SAIFI_STD
        saidi_good = saidi_hours <= SAIDI_STD_HOURS
        caidi_good = caidi_hours <= CAIDI_STD_HOURS
        ens_good = ens_mwh <= ENS_STD_MWH

        # Display metrics in same style (3 or 4 columns)
        st.markdown("### Key Reliability Metrics")
        mcol1, mcol2, mcol3, mcol4 = st.columns(4)
        with mcol1:
            st.markdown(metric_with_color("SAIFI (Interruptions/Customer)", f"{saifi:.3f}", saifi_good), unsafe_allow_html=True)
            st.caption(f"Standard: {SAIFI_STD}")
        with mcol2:
            st.markdown(metric_with_color("SAIDI (Minutes/Customer)", f"{saidi_minutes:.2f} min ({saidi_hours:.2f} hrs)", saidi_good), unsafe_allow_html=True)
            st.caption(f"Standard: {SAIDI_STD_HOURS} hrs")
        with mcol3:
            st.markdown(metric_with_color("CAIDI (Minutes/Interruption)", f"{caidi_minutes:.2f} min ({caidi_hours:.2f} hrs)", caidi_good), unsafe_allow_html=True)
            st.caption(f"Standard: {CAIDI_STD_HOURS} hrs")
        with mcol4:
            st.markdown(metric_with_color("ENS (MWh)", f"{ens_mwh:,.2f}", ens_good), unsafe_allow_html=True)
            st.caption(f"Standard: {ENS_STD_MWH:,.0f} MWh")

        st.write(f"**Total Active Customers (used for indices):** {total_customers:,}")
        st.write(f"**Total customer interruptions (sum of customers affected across selected trips):** {int(total_customer_interruptions):,}")
        st.write(f"**Customer minutes interrupted (sum):** {customer_minutes_sustained:,.2f} minutes")

        # Monthly SAIFI & SAIDI (cumulative) for selected filtered range
        # Build month order January..December
        month_order = ['January','February','March','April','May','June','July','August','September','October','November','December']

        monthly = []
        # loop through months in order but only include those present in data (or all months with zeros)
        for m in month_order:
            month_df = reliability_df[reliability_df['DATE REPORTED'].dt.month_name() == m]
            cust_interruptions_month = (month_df['11kV FEEDER'].apply(customers_for_feeder)).sum()
            duration_minutes_month = ((month_df['RESTORED_TIMESTAMP'] - month_df['REPORTED_TIMESTAMP']).dt.total_seconds() / 60).abs().fillna(0)
            cust_minutes_month = (duration_minutes_month * month_df['11kV FEEDER'].apply(customers_for_feeder)).sum()
            saifi_m = (cust_interruptions_month / total_customers) if total_customers > 0 else 0
            saidi_m = (cust_minutes_month / total_customers) if total_customers > 0 else 0
            monthly.append({
                'Month': m,
                'SAIFI': saifi_m,
                'SAIDI_minutes': saidi_m,
                'SAIDI_hours': saidi_m / 60.0
            })

        monthly_df = pd.DataFrame(monthly)
        # Filter months to those present in selection (or keep all months; show zeros)
        # We'll show all months for consistency
        monthly_df = monthly_df.set_index('Month').loc[month_order]

        # Show SAIFI monthly bar chart (st.bar_chart expects numeric index)
        st.subheader("Monthly SAIFI (selected filters)")
        st.bar_chart(monthly_df['SAIFI'])

        st.subheader("Monthly SAIDI (Hours) (selected filters)")
        st.bar_chart(monthly_df['SAIDI_hours'])

        # Feeder -> customer counts expander
        with st.expander("Feeder → Active Customer Counts (from Customer Info)"):
            feeder_counts_df = pd.DataFrame([
                {'FEEDER_NAME': k, 'ACTIVE_CUSTOMERS': v} for k,v in customers_per_feeder.items()
            ]).sort_values('FEEDER_NAME')
            st.dataframe(feeder_counts_df)

else:
    st.warning("Please upload an Excel file to proceed.")
