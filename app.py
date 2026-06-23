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

st.markdown("""
<style>
    .stMetric > div { background-color: #f8f9fa; border-radius: 8px; padding: 10px; }
    div[data-testid="stMetricValue"] { font-size: 26px; }
    .block-container { padding-top: 1rem; }
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
    """Extract budget from order name when budget field is 0.
    Examples: '50K' -> 50000, '1L' -> 100000, '2.1L' -> 210000, '10.4L' -> 1040000
    """
    if pd.isna(order_name):
        return 0

    name = str(order_name)

    # Look for patterns like "50K", "1.5L", "10.4L", "2L" etc.
    # Try L (Lakhs) first - pattern: number followed by L
    l_matches = re.findall(r'(\d+\.?\d*)\s*[Ll]', name)
    if l_matches:
        # Take the last match (usually budget is at the end)
        return float(l_matches[-1]) * 100000

    # Try K (Thousands) - pattern: number followed by K
    k_matches = re.findall(r'(\d+\.?\d*)\s*[Kk]', name)
    if k_matches:
        return float(k_matches[-1]) * 1000

    return 0


def process_entity_order_summary(df, today):
    df = df.copy()

    # Remove completely empty rows
    df = df.dropna(how='all')

    # Standardize column names
    col_map = {}
    for col in df.columns:
        cl = col.lower().strip()
        if 'order status' in cl:
            col_map[col] = 'Order Status'
        elif 'campaign name' in cl:
            col_map[col] = 'Order Name'
        elif 'advertiser' in cl and 'account' in cl:
            col_map[col] = 'Account'
        elif 'start' in cl and 'date' in cl:
            col_map[col] = 'Start Date'
        elif 'end' in cl and 'date' in cl:
            col_map[col] = 'End Date'
        elif 'budget' in cl:
            col_map[col] = 'Budget'
        elif 'total cost' in cl:
            col_map[col] = 'Total Spend'
        elif cl == 'impressions':
            col_map[col] = 'Impressions'
        elif 'click' in cl:
            col_map[col] = 'Clicks'
        elif cl == 'ctr':
            col_map[col] = 'CTR'
        elif cl == 'total roas' or cl == 'total roas clicks':
            if 'ROAS' not in col_map.values():
                col_map[col] = 'ROAS'
        elif 'total dpvr' in cl:
            col_map[col] = 'DPVR'
        elif 'total purchases' in cl:
            col_map[col] = 'Purchases'
        elif 'ecpm' in cl:
            col_map[col] = 'eCPM'

    df = df.rename(columns=col_map)

    # Remove duplicate columns
    df = df.loc[:, ~df.columns.duplicated(keep='first')]

    # Clean data
    if 'Order Name' not in df.columns:
        st.error("Could not find 'Campaign name' column in your file. Please check the format.")
        return pd.DataFrame()

    df = df.dropna(subset=['Order Name'])
    df = df[df['Order Name'].str.strip() != '']

    # Parse dates
    df['Start Date'] = pd.to_datetime(df['Start Date'], errors='coerce')
    df['End Date'] = pd.to_datetime(df['End Date'], errors='coerce')
    today = pd.Timestamp(today)

    # Convert numeric columns
    numeric_cols = ['Budget', 'Total Spend', 'Impressions', 'Clicks', 'CTR', 'ROAS', 'DPVR', 'Purchases', 'eCPM']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # ═══ BUDGET EXTRACTION FROM ORDER NAME ═══
    # If budget is 0, try to extract from order name
    df['Budget'] = df.apply(
        lambda row: extract_budget_from_name(row['Order Name']) if row['Budget'] == 0 else row['Budget'],
        axis=1
    )

    # ═══ PACING CALCULATIONS ═══
    df['Total Days'] = (df['End Date'] - df['Start Date']).dt.days + 1
    df['Elapsed Days'] = ((today - df['Start Date']).dt.days + 1).clip(lower=0)
    df['Elapsed Days'] = df[['Elapsed Days', 'Total Days']].min(axis=1)
    df['Remaining Days'] = (df['Total Days'] - df['Elapsed Days']).clip(lower=0)

    df['Daily Budget'] = np.where(df['Total Days'] > 0, df['Budget'] / df['Total Days'], 0)
    df['Ideal Spend'] = df['Daily Budget'] * df['Elapsed Days']
    df['Remaining Budget'] = (df['Budget'] - df['Total Spend']).clip(lower=0)

    # Delivery Rate % (spend / budget)
    df['DR %'] = np.where(df['Budget'] > 0, round((df['Total Spend'] / df['Budget']) * 100, 1), 0)

    # Days Delivery Rate (what % should have been delivered by now based on elapsed days)
    df['Expected DR %'] = np.where(
        df['Total Days'] > 0,
        round((df['Elapsed Days'] / df['Total Days']) * 100, 1),
        0
    )

    # Pacing % (actual vs expected)
    df['Pacing %'] = np.where(
        df['Ideal Spend'] > 0,
        round((df['Total Spend'] / df['Ideal Spend']) * 100, 1),
        0
    )

    # DRR
    df['Required DRR'] = np.where(
        df['Remaining Days'] > 0,
        df['Remaining Budget'] / df['Remaining Days'],
        0
    )
    df['Current DRR'] = np.where(
        df['Elapsed Days'] > 0,
        df['Total Spend'] / df['Elapsed Days'],
        0
    )

    # ═══ STATUS FLAGS ═══
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

    # Clean account name for display
    df['Account Short'] = df['Account'].str.replace('IN - GCS - CEPC - ', '', regex=False).str.strip()

    return df


# ═══════════════════════════════════════════════════════════════
# COLOR MAP
# ═══════════════════════════════════════════════════════════════
STATUS_COLORS = {
    'On Track': '#4caf50',
    'Under-delivering': '#ff9800',
    'Over-delivering': '#2196f3',
    'Not Spending': '#f44336',
    'No Budget': '#9e9e9e',
    'Inactive': '#9e9e9e',
    'Ended': '#607d8b'
}

STATUS_ICONS = {
    'On Track': '🟢',
    'Under-delivering': '🟡',
    'Over-delivering': '🔵',
    'Not Spending': '🔴',
    'No Budget': '⚪',
    'Inactive': '⚪',
    'Ended': '⏹️'
}


# ═══════════════════════════════════════════════════════════════
# MAIN DASHBOARD
# ═══════════════════════════════════════════════════════════════

if uploaded_file is not None:
    # Load file
    if uploaded_file.name.endswith('.csv'):
        raw_df = pd.read_csv(uploaded_file)
    else:
        raw_df = pd.read_excel(uploaded_file)

    # Process
    df = process_entity_order_summary(raw_df, report_date)

    if len(df) == 0:
        st.error("No data could be processed. Please check your file format.")
        st.stop()

    # Filter active orders
    if show_only_delivering:
        active_df = df[df['Order Status'] == 'Delivering'].copy()
    else:
        active_df = df[~df['Status'].isin(['Ended', 'Inactive'])].copy()

    ended_df = df[df['Status'] == 'Ended']

    # ═══════════════════════════════════════════════════════════
    # HEADER
    # ═══════════════════════════════════════════════════════════
    st.title("📊 CEPC DSP Delivery Tracker")
    st.caption(f"📅 {report_date.strftime('%d %B %Y')} | Total: {len(df)} | Active: {len(active_df)} | Ended: {len(ended_df)}")
    st.markdown("---")

    # Metrics row
    status_counts = active_df['Status'].value_counts()
    total_budget = active_df[active_df['Budget'] > 0]['Budget'].sum()
    total_spend = active_df['Total Spend'].sum()

    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("📦 Active", len(active_df))
    c2.metric("🟢 On Track", status_counts.get('On Track', 0))
    c3.metric("🟡 Under", status_counts.get('Under-delivering', 0))
    c4.metric("🔵 Over", status_counts.get('Over-delivering', 0))
    c5.metric("🔴 Not Spending", status_counts.get('Not Spending', 0))
    c6.metric("💰 Budget", f"₹{total_budget/100000:.1f}L")
    c7.metric("💸 Spend", f"₹{total_spend/100000:.1f}L")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ACCOUNT-LEVEL VIEW (TABLE FIRST, CHART SMALLER)
    # ═══════════════════════════════════════════════════════════
    st.header("🏢 Account-Level Overview")

    acct_df = active_df[active_df['Budget'] > 0].copy()

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
                                    'Avg Elapsed Days', 'Avg Total Days',
                                    'CTR', 'DPVR', 'ROAS', 'Orders']

        # Days Delivery Rate = Actual DR% vs Expected DR% based on elapsed days
        account_summary['DR %'] = round((account_summary['Spends'] / account_summary['Budget']) * 100, 1)
        account_summary['Expected DR %'] = round((account_summary['Avg Elapsed Days'] / account_summary['Avg Total Days']) * 100, 1)
        account_summary['Pacing %'] = np.where(
            account_summary['Ideal Spend'] > 0,
            round((account_summary['Spends'] / account_summary['Ideal Spend']) * 100, 1),
            0
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

        # ═══ ACCOUNT TABLE (PROMINENT) ═══
        st.subheader(f"📋 {len(account_summary)} Accounts")

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
            }).background_gradient(subset=['Pacing %'], cmap='RdYlGn', vmin=50, vmax=120),
            use_container_width=True,
            height=min(600, max(200, len(account_summary) * 38))
        )

        # ═══ SMALL CHART (Collapsed by default) ═══
        with st.expander("📊 Account Pacing Chart", expanded=False):
            fig_accounts = px.bar(
                account_summary,
                x='Pacing %',
                y='Account',
                orientation='h',
                color='Status',
                color_discrete_map=STATUS_COLORS,
                hover_data=['Budget', 'Spends', 'Orders']
            )
            fig_accounts.add_vline(x=under_threshold, line_dash="dash", line_color="orange")
            fig_accounts.add_vline(x=over_threshold, line_dash="dash", line_color="blue")
            fig_accounts.update_layout(height=max(300, len(account_summary) * 28), yaxis_title="", showlegend=False)
            st.plotly_chart(fig_accounts, use_container_width=True)

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ORDER-LEVEL DETAIL
    # ═══════════════════════════════════════════════════════════
    st.header("📋 Order-Level Delivery Tracker")

    # Filters in a compact row
    fcol1, fcol2, fcol3 = st.columns([2, 2, 1])
    with fcol1:
        all_accounts = sorted(active_df['Account Short'].unique())
        acct_filter = st.multiselect("Filter by Account", options=all_accounts, default=[])
    with fcol2:
        all_statuses = active_df['Status'].unique().tolist()
        status_filter = st.multiselect("Filter by Status", options=all_statuses, default=all_statuses)
    with fcol3:
        pacing_range = st.slider("Pacing %", 0, 200, (0, 200))

    # Apply filters
    filtered_df = active_df.copy()
    if acct_filter:
        filtered_df = filtered_df[filtered_df['Account Short'].isin(acct_filter)]
    filtered_df = filtered_df[
        (filtered_df['Status'].isin(status_filter)) &
        (filtered_df['Pacing %'].between(pacing_range[0], pacing_range[1]))
    ]

    # Prepare display
    order_display = filtered_df[['Account Short', 'Order Name', 'Budget', 'Total Spend',
                                  'DR %', 'Expected DR %', 'Pacing %',
                                  'CTR', 'DPVR', 'ROAS', 'Status']].copy()
    order_display = order_display.sort_values('Pacing %', ascending=True)
    order_display['Status'] = order_display['Status'].map(lambda x: f"{STATUS_ICONS.get(x, '')} {x}")

    # Rename for cleaner headers
    order_display.columns = ['Account', 'Order Name', 'Budget', 'Spends',
                              'DR %', 'Expected DR %', 'Pacing %',
                              'CTR', 'DPVR', 'ROAS', 'Status']

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
        }).background_gradient(subset=['Pacing %'], cmap='RdYlGn', vmin=50, vmax=120),
        use_container_width=True,
        height=600
    )

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ANALYTICS (COMPACT)
    # ═══════════════════════════════════════════════════════════
    st.header("📈 Analytics")

    chart_data = active_df[(active_df['Budget'] > 0) & (active_df['Pacing %'] > 0)].copy()
    # Ensure no duplicate columns for plotly
    chart_data = chart_data.loc[:, ~chart_data.columns.duplicated(keep='first')]

    tab1, tab2, tab3, tab4 = st.tabs(["🎯 Pacing Distribution", "💰 Budget vs Spend", "📊 DRR Gap", "🏆 Performance"])

    with tab1:
        if len(chart_data) > 0:
            fig = px.histogram(
                chart_data[['Pacing %', 'Status']],
                x='Pacing %',
                nbins=20,
                color='Status',
                color_discrete_map=STATUS_COLORS,
                title="Pacing Distribution"
            )
            fig.add_vline(x=under_threshold, line_dash="dash", line_color="orange")
            fig.add_vline(x=over_threshold, line_dash="dash", line_color="blue")
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data to display.")

    with tab2:
        if len(chart_data) > 0:
            scatter_df = chart_data[['Budget', 'Total Spend', 'Status', 'Order Name']].copy()
            fig2 = px.scatter(
                scatter_df,
                x='Budget',
                y='Total Spend',
                color='Status',
                hover_name='Order Name',
                color_discrete_map=STATUS_COLORS,
                title="Budget vs Spend"
            )
            max_val = scatter_df[['Budget', 'Total Spend']].max().max() * 1.1
            fig2.add_trace(go.Scatter(
                x=[0, max_val], y=[0, max_val],
                mode='lines', line=dict(dash='dash', color='gray'),
                name='Ideal', showlegend=True
            ))
            fig2.update_layout(height=400)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No data to display.")

    with tab3:
        drr_data = active_df[(active_df['Remaining Days'] > 0) & (active_df['Budget'] > 0)].copy()
        if len(drr_data) > 0:
            drr_data = drr_data.loc[:, ~drr_data.columns.duplicated(keep='first')]
            drr_data['DRR Gap'] = drr_data['Current DRR'] - drr_data['Required DRR']
            drr_data = drr_data.nsmallest(15, 'DRR Gap')
            drr_data['Order Short'] = drr_data['Order Name'].str[:45]
            drr_data['Gap Type'] = np.where(drr_data['DRR Gap'] < 0, 'Needs Boost', 'On Pace')

            fig3 = px.bar(
                drr_data[['Order Short', 'DRR Gap', 'Gap Type']],
                x='DRR Gap', y='Order Short', orientation='h',
                color='Gap Type',
                color_discrete_map={'Needs Boost': '#f44336', 'On Pace': '#4caf50'},
                title="Top 15 Orders Needing DRR Increase"
            )
            fig3.update_layout(height=450, yaxis_title="")
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No data to display.")

    with tab4:
        perf_data = active_df[active_df['Budget'] > 0].copy()
        if len(perf_data) > 0:
            perf_data = perf_data.loc[:, ~perf_data.columns.duplicated(keep='first')]
            perf_agg = perf_data.groupby('Account Short')[['CTR', 'DPVR']].mean().reset_index()

            fig4 = px.bar(
                perf_agg.melt(id_vars='Account Short', value_vars=['CTR', 'DPVR']),
                x='Account Short', y='value', color='variable',
                barmode='group', title="Avg CTR & DPVR by Account"
            )
            fig4.update_layout(xaxis_tickangle=-45, height=400)
            st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("No data to display.")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ALERTS
    # ═══════════════════════════════════════════════════════════
    st.header("🚨 Alerts")

    al1, al2 = st.columns(2)

    with al1:
        st.subheader("🔴 Not Spending")
        not_spending = active_df[active_df['Status'] == 'Not Spending']
        if len(not_spending) > 0:
            for _, row in not_spending.head(10).iterrows():
                st.error(f"**{row['Account Short']}** — {row['Order Name'][:50]}\n\n"
                         f"Budget: ₹{row['Budget']:,.0f} | Spend: ₹{row['Total Spend']:,.0f}")
        else:
            st.success("✅ All orders spending!")

    with al2:
        st.subheader("🟡 Severely Under (<80%)")
        severe = active_df[(active_df['Pacing %'] < 80) & (active_df['Pacing %'] > 0) & (active_df['Budget'] > 0)]
        if len(severe) > 0:
            for _, row in severe.head(10).iterrows():
                st.warning(f"**{row['Account Short']}** — {row['Order Name'][:50]}\n\n"
                           f"Pacing: {row['Pacing %']:.1f}%")
        else:
            st.success("✅ No severely under-delivering!")

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
    # ═══════════════════════════════════════════════════════════
    # LANDING PAGE
    # ═══════════════════════════════════════════════════════════
    st.title("📊 CEPC DSP Delivery Tracker")
    st.markdown("### Upload your Entity Order Summary to get started")
    st.markdown("---")

    st.markdown("""
    ## 📁 How to Use

    1. Download **Entity Order Summary** from DSP Console
    2. Upload CSV/Excel in the sidebar ←
    3. View delivery tracker with pacing & alerts

    ---

    ## 🚦 Status Definitions

    | Status | Condition |
    |--------|-----------|
    | 🟢 On Track | 98% ≤ Pacing ≤ 105% |
    | 🟡 Under-delivering | Pacing < 98% |
    | 🔵 Over-delivering | Pacing > 105% |
    | 🔴 Not Spending | Zero spend or line items not running |

    ---

    ## 💡 Key Metrics

    | Metric | Meaning |
    |--------|---------|
    | **DR %** | Actual Delivery Rate = Spend / Budget |
    | **Expected DR %** | What DR% should be based on elapsed days |
    | **Pacing %** | DR% / Expected DR% — above 100 = ahead of schedule |

    ---

    ## 📋 Budget Extraction

    If budget is missing in the file, the tool extracts it from the order name:
    - `"...50K"` → ₹50,000
    - `"...1L"` → ₹1,00,000
    - `"...2.1L"` → ₹2,10,000
    """)

    st.info("👈 Upload your file in the sidebar to begin!")
