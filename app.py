import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np
import re

# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="CEPC DSP Delivery Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# FIXED CSS - only hide edit button, NOT sidebar
st.markdown("""
<style>
    .stMetric > div { background-color: #f8f9fa; border-radius: 8px; padding: 10px; }
    div[data-testid="stMetricValue"] { font-size: 24px; }
    .block-container { padding-top: 1rem; }
    [data-testid="stToolbar"] { display: none !important; }
    .stDeployButton { display: none !important; }
    footer { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("📊 DSP Delivery Tracker")
    st.caption("CEPC Team Dashboard")
    st.markdown("---")

    st.subheader("📁 Upload Entity Order Summary")
    uploaded_file = st.file_uploader(
        "Upload Order Level Export (CSV/Excel)",
        type=['csv', 'xlsx', 'xls'],
        help="Upload your Entity Order Summary from DSP Console"
    )

    st.markdown("---")
    st.subheader("📅 Settings")
    report_date = st.date_input("Report Date", datetime(2026, 6, 23))

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


def process_entity_order_summary(df, today):
    df = df.copy()
    df = df.dropna(how='all')

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

    if 'Order Name' not in df.columns:
        st.error("Could not find 'Campaign name' column. Please check file format.")
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

    df['Required DRR'] = np.where(df['Remaining Days'] > 0, df['Remaining Budget'] / df['Remaining Days'], 0)
    df['Current DRR'] = np.where(df['Elapsed Days'] > 0, df['Total Spend'] / df['Elapsed Days'], 0)

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
# PERFORMANCE COLOR CODING (using HTML for reliability)
# ═══════════════════════════════════════════════════════════════
STATUS_ICONS = {
    'On Track': '🟢',
    'Under-delivering': '🟡',
    'Over-delivering': '🔵',
    'Not Spending': '🔴',
    'No Budget': '⚪',
    'Inactive': '⚪',
    'Ended': '⏹️'
}


def get_ctr_badge(val):
    try:
        v = float(val)
        if v > 0.006:
            return f'🟢 {v:.4f}'
        elif v >= 0.004:
            return f'🟡 {v:.4f}'
        else:
            return f'🔴 {v:.4f}'
    except:
        return str(val)


def get_dpvr_badge(dpvr_val, ctr_val):
    try:
        d = float(dpvr_val)
        c = float(ctr_val)
        if d > c:
            return f'🟢 {d:.4f}'
        else:
            return f'🔴 {d:.4f}'
    except:
        return str(dpvr_val)


def get_ntb_badge(val):
    try:
        v = float(val)
        if v > 0.6:
            return f'🟢 {v:.1%}'
        elif v >= 0.4:
            return f'🟡 {v:.1%}'
        else:
            return f'🔴 {v:.1%}'
    except:
        return str(val)


def get_roas_badge(val):
    try:
        v = float(val)
        if v > 2:
            return f'🟢 {v:.2f}'
        elif v >= 1:
            return f'🟡 {v:.2f}'
        else:
            return f'🔴 {v:.2f}'
    except:
        return str(val)


# ═══════════════════════════════════════════════════════════════
# MAIN DASHBOARD
# ═══════════════════════════════════════════════════════════════

if uploaded_file is not None:
    if uploaded_file.name.endswith('.csv'):
        raw_df = pd.read_csv(uploaded_file)
    else:
        raw_df = pd.read_excel(uploaded_file)

    df = process_entity_order_summary(raw_df, report_date)

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
    on_track_count = status_counts.get('On Track', 0)
    under_count = status_counts.get('Under-delivering', 0)
    over_count = status_counts.get('Over-delivering', 0)
    not_spending_count = status_counts.get('Not Spending', 0)

    total_budget = active_df[active_df['Budget'] > 0]['Budget'].sum()
    total_spend = active_df['Total Spend'].sum()
    total_ideal = active_df[active_df['Budget'] > 0]['Ideal Spend'].sum()
    current_dr = (total_spend / total_ideal * 100) if total_ideal > 0 else 0

    at_risk = active_df[(active_df['Pacing %'] < 80) & (active_df['Budget'] > 0)]
    budget_at_risk = at_risk['Remaining Budget'].sum()

    total_accounts = df['Account Short'].nunique()
    active_accounts = active_df['Account Short'].nunique()
    acct_df = active_df[active_df['Budget'] > 0].copy()

    if len(acct_df) > 0:
        acct_agg = acct_df.groupby('Account Short').agg({'Budget': 'sum', 'Total Spend': 'sum', 'Ideal Spend': 'sum'}).reset_index()
        acct_agg['Pacing %'] = np.where(acct_agg['Ideal Spend'] > 0, (acct_agg['Total Spend'] / acct_agg['Ideal Spend']) * 100, 0)
        acct_under = len(acct_agg[acct_agg['Pacing %'] < under_threshold])
        acct_over = len(acct_agg[acct_agg['Pacing %'] > over_threshold])
        acct_on_track = len(acct_agg[(acct_agg['Pacing %'] >= under_threshold) & (acct_agg['Pacing %'] <= over_threshold)])
    else:
        acct_under = acct_over = acct_on_track = 0

    # ═══════════════════════════════════════════════════════════
    # HEADER
    # ═══════════════════════════════════════════════════════════
    st.title("📊 CEPC DSP Delivery Tracker")
    st.caption(f"📅 {report_date.strftime('%d %B %Y')} | Total Orders: {len(df)}")
    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ACCOUNT LEVEL SUMMARY
    # ═══════════════════════════════════════════════════════════
    st.subheader("🏢 Account Level Summary")
    a1, a2, a3, a4, a5, a6, a7 = st.columns(7)
    a1.metric("Total Accounts", total_accounts)
    a2.metric("Active Accounts", active_accounts)
    a3.metric("🟡 Under-delivery", acct_under)
    a4.metric("🔵 Over-delivery", acct_over)
    a5.metric("🟢 On Track", acct_on_track)
    a6.metric("💰 Total Budget", f"₹{total_budget/100000:.1f}L")
    a7.metric("📊 Current DR%", f"{current_dr:.1f}%")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ORDER LEVEL SUMMARY
    # ═══════════════════════════════════════════════════════════
    st.subheader("📋 Order Level Summary")
    o1, o2, o3, o4, o5, o6, o7 = st.columns(7)
    o1.metric("Total Orders", len(df))
    o2.metric("🟢 Active Orders", delivering_count)
    o3.metric("⚪ Inactive/Not Running", inactive_combined)
    o4.metric("🟢 On Track", on_track_count)
    o5.metric("🟡 Under-delivering", under_count)
    o6.metric("🔵 Over-delivering", over_count)
    o7.metric("⚠️ Budget at Risk", f"₹{budget_at_risk/100000:.1f}L")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ACCOUNT-LEVEL OVERVIEW (TABLE ONLY)
    # ═══════════════════════════════════════════════════════════
    st.header("🏢 Account-Level Overview")

    if len(acct_df) > 0:
        account_summary = acct_df.groupby('Account Short').agg({
            'Budget': 'sum',
            'Total Spend': 'sum',
            'Ideal Spend': 'sum',
            'Elapsed Days': 'mean',
            'Total Days': 'mean',
            'CTR': 'mean',
            'DPVR': 'mean',
            'ROAS': 'mean',
            'Order Name': 'count'
        }).reset_index()

        account_summary.columns = ['Account', 'Budget', 'Spends', 'Ideal Spend',
                                    'Avg Elapsed', 'Avg Total Days',
                                    'CTR', 'DPVR', 'ROAS', 'Orders']

        account_summary['DR %'] = round((account_summary['Spends'] / account_summary['Budget']) * 100, 1)
        account_summary['Expected DR %'] = round((account_summary['Avg Elapsed'] / account_summary['Avg Total Days']) * 100, 1)
        account_summary['Pacing %'] = np.where(
            account_summary['Ideal Spend'] > 0,
            round((account_summary['Spends'] / account_summary['Ideal Spend']) * 100, 1), 0
        )

        def acct_status(row):
            if row['Pacing %'] < under_threshold:
                return 'Under-delivering'
            elif row['Pacing %'] > over_threshold:
                return 'Over-delivering'
            else:
                return 'On Track'

        account_summary['Status'] = account_summary.apply(acct_status, axis=1)
        account_summary = account_summary.sort_values('Pacing %', ascending=True)

        st.caption(f"{len(account_summary)} Accounts")

        acct_display = account_summary[['Account', 'Budget', 'Spends', 'DR %', 'Expected DR %', 'Pacing %', 'CTR', 'DPVR', 'ROAS', 'Orders', 'Status']].copy()
        acct_display['Status'] = acct_display['Status'].map(lambda x: f"{STATUS_ICONS.get(x, '')} {x}")

        st.dataframe(
            acct_display.style.format({
                'Budget': '₹{:,.0f}',
                'Spends': '₹{:,.0f}',
                'DR %': '{:.1f}%',
                'Expected DR %': '{:.1f}%',
                'Pacing %': '{:.1f}%',
                'CTR': '{:.4f}',
                'DPVR': '{:.4f}',
                'ROAS': '{:.2f}'
            }),
            use_container_width=True,
            height=min(600, max(250, len(account_summary) * 38))
        )

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ORDER-LEVEL DELIVERY TRACKER
    # ═══════════════════════════════════════════════════════════
    st.header("📋 Order-Level Delivery Tracker")

    fcol1, fcol2, fcol3 = st.columns([2, 2, 1])
    with fcol1:
        all_accounts = sorted(active_df['Account Short'].unique())
        acct_filter = st.multiselect("Filter by Account", options=all_accounts, default=[])
    with fcol2:
        all_statuses = active_df['Status'].unique().tolist()
        status_filter = st.multiselect("Filter by Status", options=all_statuses, default=all_statuses)
    with fcol3:
        pacing_range = st.slider("Pacing %", 0, 200, (0, 200))

    filtered_df = active_df.copy()
    if acct_filter:
        filtered_df = filtered_df[filtered_df['Account Short'].isin(acct_filter)]
    filtered_df = filtered_df[
        (filtered_df['Status'].isin(status_filter)) &
        (filtered_df['Pacing %'].between(pacing_range[0], pacing_range[1]))
    ]

    order_display = pd.DataFrame({
        'Account': filtered_df['Account Short'].values,
        'Order Name': filtered_df['Order Name'].values,
        'Budget': filtered_df['Budget'].values,
        'Spends': filtered_df['Total Spend'].values,
        'DR %': filtered_df['DR %'].values,
        'Expected DR %': filtered_df['Expected DR %'].values,
        'Pacing %': filtered_df['Pacing %'].values,
        'CTR': filtered_df['CTR'].values,
        'DPVR': filtered_df['DPVR'].values,
        'ROAS': filtered_df['ROAS'].values,
        'Status': [f"{STATUS_ICONS.get(s, '')} {s}" for s in filtered_df['Status'].values]
    })
    order_display = order_display.sort_values('Pacing %', ascending=True)

    st.dataframe(
        order_display.style.format({
            'Budget': '₹{:,.0f}',
            'Spends': '₹{:,.0f}',
            'DR %': '{:.1f}%',
            'Expected DR %': '{:.1f}%',
            'Pacing %': '{:.1f}%',
            'CTR': '{:.4f}',
            'DPVR': '{:.4f}',
            'ROAS': '{:.2f}'
        }),
        use_container_width=True,
        height=600
    )

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # PERFORMANCE METRICS (EMOJI BADGES - NO applymap needed)
    # ═══════════════════════════════════════════════════════════
    st.header("📈 Performance Metrics")
    st.caption("🟢 Good | 🟡 Average | 🔴 Poor")

    perf_view = st.radio("View by:", ["Account Level", "Order Level"], horizontal=True)

    if perf_view == "Account Level":
        perf_source = active_df[active_df['Budget'] > 0].copy()
        if len(perf_source) > 0:
            perf_agg = perf_source.groupby('Account Short').agg({
                'CTR': 'mean',
                'DPVR': 'mean',
                'NTB': 'mean',
                'ROAS': 'mean',
                'Total Spend': 'sum',
                'Order Name': 'count'
            }).reset_index()
            perf_agg.columns = ['Account', 'CTR', 'DPVR', 'NTB', 'ROAS', 'Spend', 'Orders']
            perf_agg = perf_agg.sort_values('Spend', ascending=False).reset_index(drop=True)

            # Create color-coded display using emoji badges
            perf_display = pd.DataFrame({
                'Account': perf_agg['Account'],
                'CTR': [get_ctr_badge(v) for v in perf_agg['CTR']],
                'DPVR': [get_dpvr_badge(d, c) for d, c in zip(perf_agg['DPVR'], perf_agg['CTR'])],
                'NTB': [get_ntb_badge(v) for v in perf_agg['NTB']],
                'ROAS': [get_roas_badge(v) for v in perf_agg['ROAS']],
                'Spend': [f"₹{v:,.0f}" for v in perf_agg['Spend']],
                'Orders': perf_agg['Orders']
            })

            st.dataframe(perf_display, use_container_width=True, height=min(600, max(250, len(perf_display) * 38)))

    else:
        perf_acct_filter = st.selectbox("Select Account", options=["All"] + sorted(active_df['Account Short'].unique().tolist()))

        perf_orders = active_df[active_df['Budget'] > 0].copy()
        if perf_acct_filter != "All":
            perf_orders = perf_orders[perf_orders['Account Short'] == perf_acct_filter]

        if len(perf_orders) > 0:
            perf_order_display = pd.DataFrame({
                'Account': perf_orders['Account Short'].values,
                'Order Name': perf_orders['Order Name'].str[:55].values,
                'CTR': [get_ctr_badge(v) for v in perf_orders['CTR'].values],
                'DPVR': [get_dpvr_badge(d, c) for d, c in zip(perf_orders['DPVR'].values, perf_orders['CTR'].values)],
                'NTB': [get_ntb_badge(v) for v in perf_orders['NTB'].values],
                'ROAS': [get_roas_badge(v) for v in perf_orders['ROAS'].values],
                'Spend': [f"₹{v:,.0f}" for v in perf_orders['Total Spend'].values]
            })

            st.dataframe(perf_order_display, use_container_width=True, height=min(600, max(250, len(perf_order_display) * 38)))

    # Legend
    st.markdown("---")
    leg1, leg2, leg3, leg4 = st.columns(4)
    with leg1:
        st.markdown("**CTR**\n- 🟢 > 0.6%\n- 🟡 0.4-0.6%\n- 🔴 < 0.4%")
    with leg2:
        st.markdown("**DPVR**\n- 🟢 > CTR\n- 🔴 < CTR")
    with leg3:
        st.markdown("**NTB**\n- 🟢 > 60%\n- 🟡 40-60%\n- 🔴 < 40%")
    with leg4:
        st.markdown("**ROAS**\n- 🟢 > 2\n- 🟡 1-2\n- 🔴 < 1")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # DOWNLOAD
    # ═══════════════════════════════════════════════════════════
    st.header("📥 Download")
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "⬇️ Order Tracker (CSV)",
            active_df.to_csv(index=False),
            f"order_tracker_{report_date.strftime('%Y%m%d')}.csv",
            "text/csv"
        )
    with dl2:
        if len(acct_df) > 0:
            st.download_button(
                "⬇️ Account Summary (CSV)",
                account_summary.to_csv(index=False),
                f"account_summary_{report_date.strftime('%Y%m%d')}.csv",
                "text/csv"
            )

else:
    st.title("📊 CEPC DSP Delivery Tracker")
    st.markdown("### Upload your Entity Order Summary to get started")
    st.markdown("---")
    st.markdown("""
    ## 📁 How to Use
    1. Download **Entity Order Summary** from DSP Console
    2. Upload CSV/Excel in the sidebar ←
    3. View delivery tracker with pacing & performance metrics

    ---
    ## 🚦 Status Definitions
    | Status | Condition |
    |--------|-----------|
    | 🟢 On Track | 98% ≤ Pacing ≤ 105% |
    | 🟡 Under-delivering | Pacing < 98% |
    | 🔵 Over-delivering | Pacing > 105% |
    | 🔴 Not Spending | Zero spend or line items not running |

    ---
    ## 📈 Performance Thresholds
    | Metric | 🟢 Good | 🟡 Average | 🔴 Poor |
    |--------|---------|-----------|---------|
    | CTR | > 0.6% | 0.4-0.6% | < 0.4% |
    | DPVR | > CTR | - | < CTR |
    | NTB | > 60% | 40-60% | < 40% |
    | ROAS | > 2 | 1-2 | < 1 |
    """)
    st.info("👈 Upload your file in the sidebar to begin!")
