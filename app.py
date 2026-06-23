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
    if pd.isna(order_name):
        return 0
    name = str(order_name)
    l_matches = re.findall(r'(\d+\.?\d*)\s*[Ll]', name)
    if l_matches:
        return float(l_matches[-1]) * 100000
    k_matches = re.findall(r'(\d+\.?\d*)\s*[Kk]', name)
    if k_matches:
        return float(k_matches[-1]) * 1000
    return 0


def process_entity_order_summary(df, today):
    df = df.copy()
    df = df.dropna(how='all')

    # Standardize column names
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

        if mapped_name and mapped_name not in used_names:
            col_map[col] = mapped_name
            used_names.add(mapped_name)

    df = df.rename(columns=col_map)

    # Drop any remaining duplicate columns
    df = df.loc[:, ~df.columns.duplicated(keep='first')]

    if 'Order Name' not in df.columns:
        st.error("Could not find 'Campaign name' column. Please check file format.")
        return pd.DataFrame()

    df = df.dropna(subset=['Order Name'])
    df = df[df['Order Name'].str.strip() != '']

    # Parse dates
    df['Start Date'] = pd.to_datetime(df['Start Date'], errors='coerce')
    df['End Date'] = pd.to_datetime(df['End Date'], errors='coerce')
    today = pd.Timestamp(today)

    # Numeric columns
    for col in ['Budget', 'Total Spend', 'Impressions', 'Clicks', 'CTR', 'ROAS', 'DPVR', 'Purchases', 'eCPM']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Budget extraction from order name
    df['Budget'] = df.apply(
        lambda row: extract_budget_from_name(row['Order Name']) if row.get('Budget', 0) == 0 else row['Budget'],
        axis=1
    )

    # Pacing calculations
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
    if uploaded_file.name.endswith('.csv'):
        raw_df = pd.read_csv(uploaded_file)
    else:
        raw_df = pd.read_excel(uploaded_file)

    df = process_entity_order_summary(raw_df, report_date)

    if len(df) == 0:
        st.error("No data processed. Check file format.")
        st.stop()

    # Filter
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
    # ACCOUNT-LEVEL VIEW
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
                                    'Avg Elapsed', 'Avg Total Days',
                                    'CTR', 'DPVR', 'ROAS', 'Orders']

        account_summary['DR %'] = round((account_summary['Spends'] / account_summary['Budget']) * 100, 1)
        account_summary['Expected DR %'] = round((account_summary['Avg Elapsed'] / account_summary['Avg Total Days']) * 100, 1)
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

        # ACCOUNT TABLE
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
            }),
            use_container_width=True,
            height=min(600, max(250, len(account_summary) * 38))
        )

        # Chart collapsed
        with st.expander("📊 Account Pacing Chart", expanded=False):
            chart_acct = pd.DataFrame({
                'Account': account_summary['Account'],
                'Pacing %': account_summary['Pacing %'],
                'Status': account_summary['Status']
            })
            fig_accounts = px.bar(
                chart_acct,
                x='Pacing %',
                y='Account',
                orientation='h',
                color='Status',
                color_discrete_map=STATUS_COLORS,
            )
            fig_accounts.add_vline(x=under_threshold, line_dash="dash", line_color="orange")
            fig_accounts.add_vline(x=over_threshold, line_dash="dash", line_color="blue")
            fig_accounts.update_layout(height=max(300, len(account_summary) * 28), yaxis_title="", showlegend=False)
            st.plotly_chart(fig_accounts, use_container_width=True)

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ORDER-LEVEL
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

    # Build clean display dataframe
    order_display = pd.DataFrame({
        'Account': filtered_df['Account Short'],
        'Order Name': filtered_df['Order Name'],
        'Budget': filtered_df['Budget'],
        'Spends': filtered_df['Total Spend'],
        'DR %': filtered_df['DR %'],
        'Expected DR %': filtered_df['Expected DR %'],
        'Pacing %': filtered_df['Pacing %'],
        'CTR': filtered_df['CTR'],
        'DPVR': filtered_df['DPVR'],
        'ROAS': filtered_df['ROAS'],
        'Status': filtered_df['Status'].map(lambda x: f"{STATUS_ICONS.get(x, '')} {x}")
    }).sort_values('Pacing %', ascending=True)

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
    # ANALYTICS (FIXED - using fresh DataFrames for plotly)
    # ═══════════════════════════════════════════════════════════
    st.header("📈 Analytics")

    tab1, tab2, tab3, tab4 = st.tabs(["🎯 Pacing Distribution", "💰 Budget vs Spend", "📊 DRR Gap", "🏆 Performance"])

    with tab1:
        pacing_data = active_df[(active_df['Budget'] > 0) & (active_df['Pacing %'] > 0)]
        if len(pacing_data) > 0:
            # Create a FRESH dataframe with only needed columns
            hist_df = pd.DataFrame({
                'Pacing': pacing_data['Pacing %'].values,
                'Status': pacing_data['Status'].values
            })
            fig = px.histogram(
                hist_df,
                x='Pacing',
                nbins=20,
                color='Status',
                color_discrete_map=STATUS_COLORS,
                title="Pacing Distribution (Active Orders)"
            )
            fig.add_vline(x=under_threshold, line_dash="dash", line_color="orange")
            fig.add_vline(x=over_threshold, line_dash="dash", line_color="blue")
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data to display.")

    with tab2:
        scatter_data = active_df[(active_df['Budget'] > 0)]
        if len(scatter_data) > 0:
            scatter_df = pd.DataFrame({
                'Budget': scatter_data['Budget'].values,
                'Spend': scatter_data['Total Spend'].values,
                'Status': scatter_data['Status'].values,
                'Order': scatter_data['Order Name'].values
            })
            fig2 = px.scatter(
                scatter_df,
                x='Budget',
                y='Spend',
                color='Status',
                hover_name='Order',
                color_discrete_map=STATUS_COLORS,
                title="Budget vs Spend"
            )
            max_val = scatter_df[['Budget', 'Spend']].max().max() * 1.1
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
        drr_source = active_df[(active_df['Remaining Days'] > 0) & (active_df['Budget'] > 0)].copy()
        if len(drr_source) > 0:
            drr_source['DRR Gap'] = drr_source['Current DRR'] - drr_source['Required DRR']
            drr_source = drr_source.nsmallest(15, 'DRR Gap')

            drr_chart = pd.DataFrame({
                'Order': drr_source['Order Name'].str[:45].values,
                'DRR Gap': drr_source['DRR Gap'].values,
                'Type': np.where(drr_source['DRR Gap'].values < 0, 'Needs Boost', 'On Pace')
            })
            fig3 = px.bar(
                drr_chart,
                x='DRR Gap', y='Order', orientation='h',
                color='Type',
                color_discrete_map={'Needs Boost': '#f44336', 'On Pace': '#4caf50'},
                title="Top 15 Orders Needing DRR Increase"
            )
            fig3.update_layout(height=450, yaxis_title="")
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No data to display.")

    with tab4:
        perf_source = active_df[active_df['Budget'] > 0]
        if len(perf_source) > 0:
            perf_agg = perf_source.groupby('Account Short')[['CTR', 'DPVR']].mean().reset_index()
            perf_chart = perf_agg.melt(id_vars='Account Short', value_vars=['CTR', 'DPVR'])

            fig4 = px.bar(
                perf_chart,
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
    ## 💡 Budget Extraction
    If budget is missing, extracted from order name:
    - `"...50K"` → ₹50,000
    - `"...1L"` → ₹1,00,000
    - `"...2.1L"` → ₹2,10,000
    """)
    st.info("👈 Upload your file in the sidebar to begin!")
