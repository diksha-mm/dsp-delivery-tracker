import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import numpy as np
import re

# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="DSP Delivery Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stDeployButton { display: none !important; }
    .stMetric > div { background-color: #f8f9fa; border-radius: 8px; padding: 10px; }
    div[data-testid="stMetricValue"] { font-size: 22px; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("📊 DSP Delivery Tracker")
    st.caption("Team Dashboard")
    st.markdown("---")

    # Report Name
    st.subheader("📝 Report Name")
    report_name = st.text_input("Name this report", value="", placeholder="e.g. June Week 3 Report")

    st.markdown("---")

    st.subheader("📁 Upload Files")
    uploaded_file = st.file_uploader(
        "1️⃣ Overall Data (Full YTD-MTD)",
        type=['csv', 'xlsx', 'xls'],
        help="Full YTD-MTD Entity Order Summary from DSP Console"
    )

    uploaded_3day = st.file_uploader(
        "2️⃣ Last 3 Days Data (for DRR)",
        type=['csv', 'xlsx', 'xls'],
        help="Same Entity Order Summary but filtered to last 3 days only"
    )

    st.markdown("---")
    st.subheader("📅 Projection")
    projection_date = st.date_input("Projection Date (Future)", datetime(2026, 6, 30), help="Select future date to see projected spend")

    st.markdown("---")
    st.subheader("⚙️ Pacing Thresholds")
    under_threshold = st.slider("Under-delivering below (%)", 80, 100, 98)
    over_threshold = st.slider("Over-delivering above (%)", 100, 120, 105)

    st.markdown("---")
    st.subheader("🔍 Filters")
    show_only_delivering = st.checkbox("Show only 'Delivering' orders", value=True)


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

# Use today's date automatically
TODAY = datetime.today()

def extract_budget_from_name(order_name):
    if pd.isna(order_name):
        return 0
    name = str(order_name)
    all_matches = []
    for match in re.finditer(r'(\d+\.?\d*)\s*([KkLl])', name):
        value = float(match.group(1))
        unit = match.group(2).upper()
        position = match.start()
        if unit == 'L':
            all_matches.append((position, value * 100000))
        elif unit == 'K':
            all_matches.append((position, value * 1000))
    if all_matches:
        all_matches.sort(key=lambda x: x[0])
        return all_matches[-1][1]
    return 0


def parse_file(uploaded):
    if uploaded.name.endswith('.csv'):
        return pd.read_csv(uploaded)
    else:
        return pd.read_excel(uploaded)


def standardize_columns(df):
    col_map = {}
    used_names = set()
    for col in df.columns:
        cl = col.lower().strip()
        mapped_name = None
        if 'order status' in cl:
            mapped_name = 'Order Status'
        elif 'campaign name' in cl:
            mapped_name = 'Order Name'
        elif 'advertiser' in cl and 'account' in cl:
            mapped_name = 'Account'
        elif 'start' in cl and 'date' in cl:
            mapped_name = 'Start Date'
        elif 'end' in cl and 'date' in cl:
            mapped_name = 'End Date'
        elif 'budget' in cl:
            mapped_name = 'Budget'
        elif 'total cost' in cl:
            mapped_name = 'Total Spend'
        elif cl == 'impressions':
            mapped_name = 'Impressions'
        elif 'click' in cl:
            mapped_name = 'Clicks'
        elif cl == 'ctr':
            mapped_name = 'CTR'
        elif 'total roas' in cl and 'click' not in cl:
            mapped_name = 'ROAS'
        elif 'total dpvr' in cl:
            mapped_name = 'DPVR'
        elif 'total purchases' in cl:
            mapped_name = 'Purchases'
        elif 'ecpm' in cl:
            mapped_name = 'eCPM'
        elif 'new-to-brand' in cl or 'ntb' in cl:
            mapped_name = 'NTB'

        if mapped_name and mapped_name not in used_names:
            col_map[col] = mapped_name
            used_names.add(mapped_name)

    df = df.rename(columns=col_map)
    df = df.loc[:, ~df.columns.duplicated(keep='first')]
    return df


def process_data(df, today, drr_data=None, proj_date=None):
    df = df.copy()
    df = df.dropna(how='all')
    df = standardize_columns(df)

    if 'Order Name' not in df.columns:
        st.error("Could not find 'Campaign name' column.")
        return pd.DataFrame()

    df = df.dropna(subset=['Order Name'])
    df = df[df['Order Name'].str.strip() != '']

    df['Start Date'] = pd.to_datetime(df['Start Date'], errors='coerce')
    df['End Date'] = pd.to_datetime(df['End Date'], errors='coerce')
    today = pd.Timestamp(today)

    for col in ['Budget', 'Total Spend', 'Impressions', 'Clicks', 'CTR', 'ROAS', 'DPVR', 'Purchases', 'eCPM', 'NTB']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    if 'NTB' not in df.columns:
        df['NTB'] = 0

    df['Budget'] = df.apply(
        lambda row: extract_budget_from_name(row['Order Name']) if row.get('Budget', 0) == 0 else row['Budget'],
        axis=1
    )

    df['Total Days'] = (df['End Date'] - df['Start Date']).dt.days + 1
    df['Elapsed Days'] = ((today - df['Start Date']).dt.days + 1).clip(lower=0)
    df['Elapsed Days'] = df[['Elapsed Days', 'Total Days']].min(axis=1)
    df['Remaining Days'] = (df['Total Days'] - df['Elapsed Days']).clip(lower=0)

    df['Daily Budget'] = np.where(df['Total Days'] > 0, df['Budget'] / df['Total Days'], 0)
    df['Ideal Spend'] = df['Daily Budget'] * df['Elapsed Days']
    df['Remaining Budget'] = (df['Budget'] - df['Total Spend']).clip(lower=0)

    df['DR %'] = np.where(df['Budget'] > 0, round((df['Total Spend'] / df['Budget']) * 100, 1), 0)
    df['Expected DR %'] = np.where(df['Total Days'] > 0, round((df['Elapsed Days'] / df['Total Days']) * 100, 1), 0)
    df['Pacing %'] = np.where(df['Ideal Spend'] > 0, round((df['Total Spend'] / df['Ideal Spend']) * 100, 1), 0)

    # Expected DRR = Remaining Budget / Remaining Days
    df['Expected DRR'] = np.where(df['Remaining Days'] > 0, df['Remaining Budget'] / df['Remaining Days'], 0)

    # Current DRR from 3-day file
    df['Current DRR'] = 0.0
    if drr_data is not None:
        drr_df = drr_data.copy()
        drr_df = standardize_columns(drr_df)
        if 'Order Name' in drr_df.columns and 'Total Spend' in drr_df.columns:
            drr_df['Total Spend'] = pd.to_numeric(drr_df['Total Spend'], errors='coerce').fillna(0)
            drr_lookup = drr_df.groupby('Order Name')['Total Spend'].sum().reset_index()
            drr_lookup.columns = ['Order Name', '3D Spend']
            drr_lookup['Current DRR'] = drr_lookup['3D Spend'] / 3
            df = df.merge(drr_lookup[['Order Name', 'Current DRR']], on='Order Name', how='left', suffixes=('_old', ''))
            if 'Current DRR_old' in df.columns:
                df['Current DRR'] = df['Current DRR'].fillna(df['Current DRR_old'])
                df.drop('Current DRR_old', axis=1, inplace=True)
            df['Current DRR'] = df['Current DRR'].fillna(0)
    else:
        df['Current DRR'] = np.where(df['Elapsed Days'] > 0, df['Total Spend'] / df['Elapsed Days'], 0)

    # Projected Spend
    df['Projected Spend'] = df['Total Spend']
    df['Projected DR %'] = df['DR %']
    if proj_date is not None:
        proj_ts = pd.Timestamp(proj_date)
        if proj_ts > today:
            days_to_project = (proj_ts - today).days
            df['Projected Spend'] = df['Total Spend'] + (df['Current DRR'] * days_to_project)
            df['Projected Spend'] = df[['Projected Spend', 'Budget']].min(axis=1)
            df['Projected DR %'] = np.where(df['Budget'] > 0, round((df['Projected Spend'] / df['Budget']) * 100, 1), 0)

    # Status
    def assign_status(row):
        if row.get('Order Status', '') == 'Ended':
            return 'Ended'
        if row.get('Order Status', '') == 'Inactive':
            return 'Inactive'
        if row.get('Order Status', '') == 'Line items not running':
            return 'Not Spending'
        if row['Budget'] == 0:
            return 'No Budget'
        if row['Total Spend'] == 0 and row['Elapsed Days'] > 3:
            return 'Not Spending'
        if row['Pacing %'] < under_threshold:
            return 'Under-delivering'
        elif row['Pacing %'] > over_threshold:
            return 'Over-delivering'
        else:
            return 'On Track'

    df['Status'] = df.apply(assign_status, axis=1)
    df['Account Short'] = df['Account'].str.replace('IN - GCS - CEPC - ', '', regex=False).str.strip()

    return df


# ═══════════════════════════════════════════════════════════════
# BADGE FUNCTIONS
# ═══════════════════════════════════════════════════════════════
STATUS_ICONS = {
    'On Track': '🟢', 'Under-delivering': '🟡', 'Over-delivering': '🔵',
    'Not Spending': '🔴', 'No Budget': '⚪', 'Inactive': '⚪', 'Ended': '⏹️'
}

def badge_ctr(val):
    try:
        v = float(val)
        if v > 0.006: return f'🟢 {v:.4f}'
        elif v >= 0.004: return f'🟡 {v:.4f}'
        else: return f'🔴 {v:.4f}'
    except: return str(val)

def badge_dpvr(dpvr, ctr):
    try:
        d, c = float(dpvr), float(ctr)
        if d > c: return f'🟢 {d:.4f}'
        else: return f'🔴 {d:.4f}'
    except: return str(dpvr)

def badge_ntb(val):
    try:
        v = float(val)
        if v > 0.6: return f'🟢 {v:.1%}'
        elif v >= 0.4: return f'🟡 {v:.1%}'
        else: return f'🔴 {v:.1%}'
    except: return str(val)

def badge_roas(val):
    try:
        v = float(val)
        if v > 2: return f'🟢 {v:.2f}'
        elif v >= 1: return f'🟡 {v:.2f}'
        else: return f'🔴 {v:.2f}'
    except: return str(val)


# ═══════════════════════════════════════════════════════════════
# MAIN DASHBOARD
# ═══════════════════════════════════════════════════════════════

if uploaded_file is not None:
    raw_df = parse_file(uploaded_file)

    drr_raw = None
    if uploaded_3day is not None:
        drr_raw = parse_file(uploaded_3day)

    df = process_data(raw_df, TODAY, drr_data=drr_raw, proj_date=projection_date)

    if len(df) == 0:
        st.error("No data processed. Check file format.")
        st.stop()

    if show_only_delivering:
        active_df = df[df['Order Status'] == 'Delivering'].copy()
    else:
        active_df = df[~df['Status'].isin(['Ended', 'Inactive'])].copy()

    # Counts
    delivering_count = len(df[df['Order Status'] == 'Delivering'])
    inactive_count = len(df[df['Order Status'] == 'Inactive'])
    ended_count = len(df[df['Order Status'] == 'Ended'])
    line_not_running = len(df[df['Order Status'] == 'Line items not running'])
    inactive_combined = inactive_count + line_not_running

    status_counts = active_df['Status'].value_counts()
    total_budget = active_df[active_df['Budget'] > 0]['Budget'].sum()
    total_spend = active_df['Total Spend'].sum()
    total_ideal = active_df[active_df['Budget'] > 0]['Ideal Spend'].sum()
    current_dr = (total_spend / total_ideal * 100) if total_ideal > 0 else 0

    at_risk = active_df[(active_df['Pacing %'] < 80) & (active_df['Budget'] > 0)]
    budget_at_risk = at_risk['Remaining Budget'].sum()

    total_accounts = df['Account Short'].nunique()
    active_accounts = active_df['Account Short'].nunique()
    ended_accounts = df[df['Order Status'] == 'Ended']['Account Short'].nunique()

    acct_df = active_df[active_df['Budget'] > 0].copy()
    if len(acct_df) > 0:
        acct_agg = acct_df.groupby('Account Short').agg({'Budget': 'sum', 'Total Spend': 'sum', 'Ideal Spend': 'sum'}).reset_index()
        acct_agg['Pacing %'] = np.where(acct_agg['Ideal Spend'] > 0, (acct_agg['Total Spend'] / acct_agg['Ideal Spend']) * 100, 0)
        acct_under = len(acct_agg[acct_agg['Pacing %'] < under_threshold])
        acct_over = len(acct_agg[acct_agg['Pacing %'] > over_threshold])
        acct_on_track = len(acct_agg) - acct_under - acct_over
    else:
        acct_under = acct_over = acct_on_track = 0

    # Projection
    proj_ts = pd.Timestamp(projection_date)
    today_ts = pd.Timestamp(TODAY)
    show_projection = proj_ts > today_ts
    proj_total_spend = active_df['Projected Spend'].sum() if show_projection else 0

    # ═══════════════════════════════════════════════════════════
    # HEADER
    # ═══════════════════════════════════════════════════════════
    title_text = "📊 DSP Delivery Tracker"
    if report_name:
        title_text += f" — {report_name}"
    st.title(title_text)
    st.caption(f"📅 {TODAY.strftime('%d %B %Y')} | Total Orders: {len(df)}")

    if uploaded_3day is not None:
        st.success("✅ 3-Day DRR file loaded — Current DRR from actual last 3 days")
    else:
        st.info("ℹ️ Upload 'Last 3 Days Data' for accurate Current DRR. Using estimated DRR.")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ACCOUNT LEVEL SUMMARY
    # ═══════════════════════════════════════════════════════════
    st.subheader("🏢 Account Level Summary")
    a1, a2, a3, a4, a5, a6, a7, a8 = st.columns(8)
    a1.metric("Total Accounts", total_accounts)
    a2.metric("Active Accounts", active_accounts)
    a3.metric("⏹️ Ended", ended_accounts)
    a4.metric("🟡 Under-delivery", acct_under)
    a5.metric("🔵 Over-delivery", acct_over)
    a6.metric("🟢 On Track", acct_on_track)
    a7.metric("💰 Total Budget", f"₹{total_budget/100000:.1f}L")
    a8.metric("📊 Current DR%", f"{current_dr:.1f}%")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ORDER LEVEL SUMMARY
    # ═══════════════════════════════════════════════════════════
    st.subheader("📋 Order Level Summary")
    o1, o2, o3, o4, o5, o6, o7, o8 = st.columns(8)
    o1.metric("Total Orders", len(df))
    o2.metric("🟢 Active", delivering_count)
    o3.metric("⏹️ Ended", ended_count)
    o4.metric("⚪ Inactive/Not Running", inactive_combined)
    o5.metric("🟢 On Track", status_counts.get('On Track', 0))
    o6.metric("🟡 Under", status_counts.get('Under-delivering', 0))
    o7.metric("🔵 Over", status_counts.get('Over-delivering', 0))
    o8.metric("⚠️ Budget at Risk", f"₹{budget_at_risk/100000:.1f}L")

    # Projection row
    if show_projection:
        st.markdown("---")
        st.subheader(f"🔮 Projection (by {projection_date.strftime('%d %b %Y')})")
        pr1, pr2, pr3, pr4 = st.columns(4)
        pr1.metric("📅 Days to Projection", f"{(proj_ts - today_ts).days} days")
        pr2.metric("💸 Projected Spend", f"₹{proj_total_spend/100000:.1f}L")
        pr3.metric("📊 Projected DR%", f"{(proj_total_spend/total_budget*100):.1f}%" if total_budget > 0 else "N/A")
        pr4.metric("📉 Projected Gap", f"₹{(total_budget - proj_total_spend)/100000:.1f}L remaining")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ACCOUNT-LEVEL OVERVIEW
    # ═══════════════════════════════════════════════════════════
    st.header("🏢 Account-Level Overview")

    if len(acct_df) > 0:
        account_summary = acct_df.groupby('Account Short').agg({
            'Budget': 'sum', 'Total Spend': 'sum', 'Ideal Spend': 'sum',
            'Elapsed Days': 'mean', 'Total Days': 'mean',
            'Current DRR': 'sum', 'Expected DRR': 'sum', 'Projected Spend': 'sum',
            'CTR': 'mean', 'DPVR': 'mean', 'ROAS': 'mean',
            'Order Name': 'count'
        }).reset_index()

        account_summary.columns = ['Account', 'Budget', 'Spends', 'Ideal Spend',
                                    'Avg Elapsed', 'Avg Total Days',
                                    'Current DRR', 'Expected DRR', 'Projected Spend',
                                    'CTR', 'DPVR', 'ROAS', 'Orders']

        account_summary['DR %'] = round((account_summary['Spends'] / account_summary['Budget']) * 100, 1)
        account_summary['Expected DR %'] = round((account_summary['Avg Elapsed'] / account_summary['Avg Total Days']) * 100, 1)
        account_summary['Pacing %'] = np.where(
            account_summary['Ideal Spend'] > 0,
            round((account_summary['Spends'] / account_summary['Ideal Spend']) * 100, 1), 0)

        if show_projection:
            account_summary['Proj DR %'] = round((account_summary['Projected Spend'] / account_summary['Budget']) * 100, 1)

        def acct_status(row):
            if row['Pacing %'] < under_threshold: return 'Under-delivering'
            elif row['Pacing %'] > over_threshold: return 'Over-delivering'
            else: return 'On Track'

        account_summary['Status'] = account_summary.apply(acct_status, axis=1)
        account_summary = account_summary.sort_values('Pacing %', ascending=True)

        st.caption(f"{len(account_summary)} Accounts")

        disp_cols = ['Account', 'Budget', 'Spends', 'DR %', 'Expected DR %', 'Pacing %', 'Current DRR', 'Expected DRR']
        if show_projection:
            disp_cols.append('Proj DR %')
        disp_cols += ['CTR', 'DPVR', 'ROAS', 'Orders', 'Status']

        acct_display = account_summary[disp_cols].copy()
        acct_display['Status'] = acct_display['Status'].map(lambda x: f"{STATUS_ICONS.get(x, '')} {x}")

        fmt_dict = {
            'Budget': '₹{:,.0f}', 'Spends': '₹{:,.0f}',
            'DR %': '{:.1f}%', 'Expected DR %': '{:.1f}%', 'Pacing %': '{:.1f}%',
            'Current DRR': '₹{:,.0f}', 'Expected DRR': '₹{:,.0f}',
            'CTR': '{:.4f}', 'DPVR': '{:.4f}', 'ROAS': '{:.2f}'
        }
        if show_projection:
            fmt_dict['Proj DR %'] = '{:.1f}%'

        st.dataframe(acct_display.style.format(fmt_dict), use_container_width=True,
                     height=min(600, max(250, len(account_summary) * 38)))

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ORDER-LEVEL DELIVERY TRACKER
    # ═══════════════════════════════════════════════════════════
    st.header("📋 Order-Level Delivery Tracker")

    fcol1, fcol2, fcol3 = st.columns([2, 2, 1])
    with fcol1:
        acct_filter = st.multiselect("Filter by Account", options=sorted(active_df['Account Short'].unique()), default=[])
    with fcol2:
        status_filter = st.multiselect("Filter by Status", options=active_df['Status'].unique().tolist(), default=active_df['Status'].unique().tolist())
    with fcol3:
        pacing_range = st.slider("Pacing %", 0, 200, (0, 200))

    filtered_df = active_df.copy()
    if acct_filter:
        filtered_df = filtered_df[filtered_df['Account Short'].isin(acct_filter)]
    filtered_df = filtered_df[
        (filtered_df['Status'].isin(status_filter)) &
        (filtered_df['Pacing %'].between(pacing_range[0], pacing_range[1]))
    ]

    order_data = {
        'Account': filtered_df['Account Short'].values,
        'Order Name': filtered_df['Order Name'].values,
        'Budget': filtered_df['Budget'].values,
        'Spends': filtered_df['Total Spend'].values,
        'DR %': filtered_df['DR %'].values,
        'Expected DR %': filtered_df['Expected DR %'].values,
        'Pacing %': filtered_df['Pacing %'].values,
        'Current DRR': filtered_df['Current DRR'].values,
        'Expected DRR': filtered_df['Expected DRR'].values,
    }
    if show_projection:
        order_data['Projected Spend'] = filtered_df['Projected Spend'].values
        order_data['Proj DR %'] = filtered_df['Projected DR %'].values

    order_data['CTR'] = filtered_df['CTR'].values
    order_data['DPVR'] = filtered_df['DPVR'].values
    order_data['ROAS'] = filtered_df['ROAS'].values
    order_data['Status'] = [f"{STATUS_ICONS.get(s, '')} {s}" for s in filtered_df['Status'].values]

    order_display = pd.DataFrame(order_data).sort_values('Pacing %', ascending=True)

    order_fmt = {
        'Budget': '₹{:,.0f}', 'Spends': '₹{:,.0f}',
        'DR %': '{:.1f}%', 'Expected DR %': '{:.1f}%', 'Pacing %': '{:.1f}%',
        'Current DRR': '₹{:,.0f}', 'Expected DRR': '₹{:,.0f}',
        'CTR': '{:.4f}', 'DPVR': '{:.4f}', 'ROAS': '{:.2f}'
    }
    if show_projection:
        order_fmt['Projected Spend'] = '₹{:,.0f}'
        order_fmt['Proj DR %'] = '{:.1f}%'

    st.dataframe(order_display.style.format(order_fmt), use_container_width=True, height=600)

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # PERFORMANCE METRICS
    # ═══════════════════════════════════════════════════════════
    st.header("📈 Performance Metrics")
    st.caption("🟢 Good | 🟡 Average | 🔴 Poor")

    perf_view = st.radio("View by:", ["Account Level", "Order Level"], horizontal=True)

    if perf_view == "Account Level":
        perf_source = active_df[active_df['Budget'] > 0]
        if len(perf_source) > 0:
            perf_agg = perf_source.groupby('Account Short').agg({
                'CTR': 'mean', 'DPVR': 'mean', 'NTB': 'mean',
                'ROAS': 'mean', 'Total Spend': 'sum', 'Order Name': 'count'
            }).reset_index()
            perf_agg.columns = ['Account', 'CTR', 'DPVR', 'NTB', 'ROAS', 'Spend', 'Orders']
            perf_agg = perf_agg.sort_values('Spend', ascending=False)

            perf_display = pd.DataFrame({
                'Account': perf_agg['Account'].values,
                'CTR': [badge_ctr(v) for v in perf_agg['CTR'].values],
                'DPVR': [badge_dpvr(d, c) for d, c in zip(perf_agg['DPVR'].values, perf_agg['CTR'].values)],
                'NTB': [badge_ntb(v) for v in perf_agg['NTB'].values],
                'ROAS': [badge_roas(v) for v in perf_agg['ROAS'].values],
                'Spend': [f"₹{v:,.0f}" for v in perf_agg['Spend'].values],
                'Orders': perf_agg['Orders'].values
            })
            st.dataframe(perf_display, use_container_width=True, height=min(600, max(250, len(perf_display) * 38)))
    else:
        perf_acct = st.selectbox("Select Account", options=["All"] + sorted(active_df['Account Short'].unique().tolist()))
        perf_orders = active_df[active_df['Budget'] > 0].copy()
        if perf_acct != "All":
            perf_orders = perf_orders[perf_orders['Account Short'] == perf_acct]

        if len(perf_orders) > 0:
            perf_ord_display = pd.DataFrame({
                'Account': perf_orders['Account Short'].values,
                'Order Name': perf_orders['Order Name'].str[:55].values,
                'CTR': [badge_ctr(v) for v in perf_orders['CTR'].values],
                'DPVR': [badge_dpvr(d, c) for d, c in zip(perf_orders['DPVR'].values, perf_orders['CTR'].values)],
                'NTB': [badge_ntb(v) for v in perf_orders['NTB'].values],
                'ROAS': [badge_roas(v) for v in perf_orders['ROAS'].values],
                'Spend': [f"₹{v:,.0f}" for v in perf_orders['Total Spend'].values]
            })
            st.dataframe(perf_ord_display, use_container_width=True, height=min(600, max(250, len(perf_ord_display) * 38)))

    st.markdown("---")
    l1, l2, l3, l4 = st.columns(4)
    l1.markdown("**CTR**\n- 🟢 > 0.6%\n- 🟡 0.4-0.6%\n- 🔴 < 0.4%")
    l2.markdown("**DPVR**\n- 🟢 > CTR\n- 🔴 < CTR")
