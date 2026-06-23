import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np

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
    div[data-testid="stMetricValue"] { font-size: 28px; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("📊 DSP Delivery Tracker")
    st.caption("CEPC Team Dashboard")
    st.markdown("---")

    # File Upload
    st.subheader("📁 Upload Entity Order Summary")
    uploaded_file = st.file_uploader(
        "Upload Order-Level Export (CSV/Excel)",
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
    show_ended_june = st.checkbox("Include orders ending in June 2026", value=True)


# ═══════════════════════════════════════════════════════════════
# DATA PROCESSING
# ═══════════════════════════════════════════════════════════════

def process_entity_order_summary(df, today):
    """Process the Entity Order Summary file"""
    df = df.copy()

    # Standardize column names (handle variations)
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
        elif cl == 'total cost':
            col_map[col] = 'Total Spend'
        elif cl == 'impressions':
            col_map[col] = 'Impressions'
        elif cl == 'click-throughs' or cl == 'clickthroughs':
            col_map[col] = 'Clicks'
        elif cl == 'ctr':
            col_map[col] = 'CTR'
        elif 'total roas' == cl or cl == 'total roas':
            col_map[col] = 'ROAS'
        elif 'total dpvr' in cl:
            col_map[col] = 'DPVR'
        elif 'total purchases' in cl:
            col_map[col] = 'Purchases'
        elif 'ecpm' in cl:
            col_map[col] = 'eCPM'
        elif 'branded' in cl:
            col_map[col] = 'Branded Searches'
        elif 'new-to-brand' in cl or 'ntb' in cl:
            col_map[col] = 'NTB Rate'

    df = df.rename(columns=col_map)

    # Clean data
    df = df.dropna(subset=['Order Name'])
    df = df[df['Order Name'].str.strip() != '']

    # Parse dates
    df['Start Date'] = pd.to_datetime(df['Start Date'], errors='coerce')
    df['End Date'] = pd.to_datetime(df['End Date'], errors='coerce')
    today = pd.Timestamp(today)

    # Convert numeric columns
    for col in ['Budget', 'Total Spend', 'Impressions', 'Clicks', 'CTR', 'ROAS', 'DPVR', 'Purchases', 'eCPM']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # ═══ PACING CALCULATIONS ═══
    df['Total Days'] = (df['End Date'] - df['Start Date']).dt.days + 1
    df['Elapsed Days'] = ((today - df['Start Date']).dt.days + 1).clip(lower=0)
    df['Elapsed Days'] = df[['Elapsed Days', 'Total Days']].min(axis=1)
    df['Remaining Days'] = (df['Total Days'] - df['Elapsed Days']).clip(lower=0)

    df['Daily Budget'] = np.where(df['Total Days'] > 0, df['Budget'] / df['Total Days'], 0)
    df['Ideal Spend'] = df['Daily Budget'] * df['Elapsed Days']
    df['Remaining Budget'] = (df['Budget'] - df['Total Spend']).clip(lower=0)

    # Delivery Rate
    df['DR %'] = np.where(df['Budget'] > 0, (df['Total Spend'] / df['Budget']) * 100, 0)

    # Pacing % (actual vs expected)
    df['Pacing %'] = np.where(
        df['Ideal Spend'] > 0,
        (df['Total Spend'] / df['Ideal Spend']) * 100,
        0
    )

    # Required DRR to finish on time
    df['Required DRR'] = np.where(
        df['Remaining Days'] > 0,
        df['Remaining Budget'] / df['Remaining Days'],
        0
    )

    # Current DRR (based on elapsed performance)
    df['Current DRR'] = np.where(
        df['Elapsed Days'] > 0,
        df['Total Spend'] / df['Elapsed Days'],
        0
    )

    # ═══ STATUS FLAGS ═══
    def assign_status(row):
        if row.get('Order Status', '') == 'Ended':
            return '⏹️ Ended'
        if row.get('Order Status', '') == 'Inactive':
            return '⚪ Inactive'
        if row.get('Order Status', '') == 'Line items not running':
            return '🔴 Not Spending'
        if row['Budget'] == 0 or pd.isna(row['Budget']):
            return '⚪ No Budget'
        if row['Total Spend'] == 0 and row['Elapsed Days'] > 3:
            return '🔴 Not Spending'
        if row['Pacing %'] < under_threshold:
            return '🟡 Under-delivering'
        elif row['Pacing %'] > over_threshold:
            return '🔵 Over-delivering'
        else:
            return '🟢 On Track'

    df['Status'] = df.apply(assign_status, axis=1)

    return df


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

    # ═══ FILTER: Only Delivering / June End Date ═══
    if show_only_delivering:
        active_df = df[df['Order Status'] == 'Delivering'].copy()
    else:
        active_df = df[df['Order Status'] != 'Ended'].copy()

    if show_ended_june:
        june_ended = df[
            (df['Order Status'] == 'Ended') & 
            (df['End Date'].dt.month == 6) & 
            (df['End Date'].dt.year == 2026)
        ]
        # Don't add to active_df, show separately

    ended_df = df[df['Order Status'] == 'Ended']

    # ═══════════════════════════════════════════════════════════
    # HEADER METRICS
    # ═══════════════════════════════════════════════════════════
    st.title("📊 CEPC DSP Delivery Tracker")
    st.caption(f"Report Date: {report_date.strftime('%d %B %Y')} | "
               f"Total Orders: {len(df)} | Active: {len(active_df)} | Ended: {len(ended_df)}")
    st.markdown("---")

    # Status counts for active orders
    status_counts = active_df['Status'].value_counts()

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("📦 Active Orders", len(active_df))
    with col2:
        st.metric("🟢 On Track", status_counts.get('🟢 On Track', 0))
    with col3:
        st.metric("🟡 Under", status_counts.get('🟡 Under-delivering', 0))
    with col4:
        st.metric("🔵 Over", status_counts.get('🔵 Over-delivering', 0))
    with col5:
        st.metric("🔴 Not Spending", status_counts.get('🔴 Not Spending', 0))
    with col6:
        total_budget = active_df['Budget'].sum()
        total_spend = active_df['Total Spend'].sum()
        st.metric("💰 Overall DR%", f"{(total_spend/total_budget*100):.1f}%" if total_budget > 0 else "N/A")

    # Budget summary
    st.markdown("---")
    bud_col1, bud_col2, bud_col3 = st.columns(3)
    with bud_col1:
        st.metric("💰 Total Active Budget", f"₹{total_budget:,.0f}")
    with bud_col2:
        st.metric("💸 Total Spend", f"₹{total_spend:,.0f}")
    with bud_col3:
        st.metric("📊 Remaining", f"₹{total_budget - total_spend:,.0f}")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ACCOUNT-LEVEL VIEW
    # ═══════════════════════════════════════════════════════════
    st.header("🏢 Account-Level Overview")

    account_summary = active_df.groupby('Account').agg({
        'Budget': 'sum',
        'Total Spend': 'sum',
        'Ideal Spend': 'sum',
        'Impressions': 'sum',
        'Clicks': 'sum',
        'Purchases': 'sum',
        'Order Name': 'count'
    }).reset_index()

    account_summary.columns = ['Account', 'Budget', 'Spend', 'Ideal Spend', 
                                'Impressions', 'Clicks', 'Purchases', 'Orders']

    account_summary['Pacing %'] = np.where(
        account_summary['Ideal Spend'] > 0,
        round((account_summary['Spend'] / account_summary['Ideal Spend']) * 100, 1),
        0
    )
    account_summary['DR %'] = round((account_summary['Spend'] / account_summary['Budget']) * 100, 1)
    account_summary['ROAS'] = np.where(
        account_summary['Spend'] > 0,
        round(account_summary['Purchases'] * 100 / account_summary['Spend'], 2),  # Simplified
        0
    )

    def acct_status(row):
        if row['Pacing %'] < under_threshold:
            return '🟡 Under'
        elif row['Pacing %'] > over_threshold:
            return '🔵 Over'
        else:
            return '🟢 On Track'

    account_summary['Status'] = account_summary.apply(acct_status, axis=1)
    account_summary = account_summary.sort_values('Pacing %', ascending=True)

    # Clean account names for display
    account_summary['Account Short'] = account_summary['Account'].str.replace('IN - GCS - CEPC - ', '', regex=False)

    # Chart
    fig_accounts = px.bar(
        account_summary,
        x='Pacing %',
        y='Account Short',
        orientation='h',
        color='Status',
        color_discrete_map={
            '🟢 On Track': '#4caf50',
            '🟡 Under': '#ff9800',
            '🔵 Over': '#2196f3'
        },
        title="Account Pacing (% of Expected Delivery)",
        hover_data=['Budget', 'Spend', 'Orders']
    )
    fig_accounts.add_vline(x=under_threshold, line_dash="dash", line_color="orange", annotation_text=f"{under_threshold}%")
    fig_accounts.add_vline(x=over_threshold, line_dash="dash", line_color="blue", annotation_text=f"{over_threshold}%")
    fig_accounts.update_layout(height=max(400, len(account_summary) * 40), yaxis_title="")
    st.plotly_chart(fig_accounts, use_container_width=True)

    # Account table
    with st.expander("📋 Account Details Table", expanded=False):
        display_acct = account_summary[['Account Short', 'Budget', 'Spend', 'Pacing %', 'DR %', 'Orders', 'Impressions', 'Clicks', 'Status']].copy()
        st.dataframe(
            display_acct.style.format({
                'Budget': '₹{:,.0f}',
                'Spend': '₹{:,.0f}',
                'Pacing %': '{:.1f}%',
                'DR %': '{:.1f}%',
                'Impressions': '{:,.0f}',
                'Clicks': '{:,.0f}'
            }),
            use_container_width=True,
            height=400
        )

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ORDER-LEVEL DETAIL
    # ═══════════════════════════════════════════════════════════
    st.header("📋 Order-Level Delivery Tracker")

    # Filters
    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        acct_filter = st.multiselect(
            "Filter by Account",
            options=sorted(active_df['Account'].str.replace('IN - GCS - CEPC - ', '').unique()),
            default=[]
        )
    with fcol2:
        status_filter = st.multiselect(
            "Filter by Status",
            options=active_df['Status'].unique().tolist(),
            default=active_df['Status'].unique().tolist()
        )
    with fcol3:
        pacing_range = st.slider("Pacing % Range", 0, 200, (0, 200))

    # Apply filters
    filtered_df = active_df.copy()
    if acct_filter:
        filtered_df = filtered_df[filtered_df['Account'].str.replace('IN - GCS - CEPC - ', '').isin(acct_filter)]
    filtered_df = filtered_df[
        (filtered_df['Status'].isin(status_filter)) &
        (filtered_df['Pacing %'].between(pacing_range[0], pacing_range[1]))
    ]

    # Display columns
    display_cols = ['Order Name', 'Account', 'Start Date', 'End Date', 'Budget',
                    'Total Spend', 'Pacing %', 'DR %', 'Current DRR', 'Required DRR',
                    'CTR', 'DPVR', 'ROAS', 'Status']

    available_cols = [c for c in display_cols if c in filtered_df.columns]

    st.dataframe(
        filtered_df[available_cols].sort_values('Pacing %', ascending=True)
        .style.format({
            'Budget': '₹{:,.0f}',
            'Total Spend': '₹{:,.0f}',
            'Pacing %': '{:.1f}%',
            'DR %': '{:.1f}%',
            'Current DRR': '₹{:,.0f}',
            'Required DRR': '₹{:,.0f}',
            'CTR': '{:.4f}',
            'DPVR': '{:.4f}',
            'ROAS': '{:.2f}'
        }),
        use_container_width=True,
        height=500
    )

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # VISUAL ANALYTICS
    # ═══════════════════════════════════════════════════════════
    st.header("📈 Analytics")

    tab1, tab2, tab3, tab4 = st.tabs(["🎯 Pacing Distribution", "💰 Budget vs Spend", "📊 DRR Gap", "🏆 Performance"])

    with tab1:
        fig = px.histogram(
            active_df[active_df['Pacing %'] > 0], 
            x='Pacing %', nbins=25,
            color='Status',
            color_discrete_map={
                '🟢 On Track': '#4caf50',
                '🟡 Under-delivering': '#ff9800',
                '🔵 Over-delivering': '#2196f3',
                '🔴 Not Spending': '#f44336'
            },
            title="Pacing Distribution (Active Orders)"
        )
        fig.add_vline(x=under_threshold, line_dash="dash", line_color="orange")
        fig.add_vline(x=over_threshold, line_dash="dash", line_color="blue")
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        fig2 = px.scatter(
            active_df[active_df['Budget'] > 0],
            x='Budget', y='Total Spend',
            color='Status',
            hover_name='Order Name',
            size='Impressions',
            color_discrete_map={
                '🟢 On Track': '#4caf50',
                '🟡 Under-delivering': '#ff9800',
                '🔵 Over-delivering': '#2196f3',
                '🔴 Not Spending': '#f44336'
            },
            title="Budget vs Spend (size = impressions)"
        )
        max_val = max(active_df['Budget'].max(), active_df['Total Spend'].max()) * 1.1
        fig2.add_trace(go.Scatter(x=[0, max_val], y=[0, max_val], mode='lines', 
                                   line=dict(dash='dash', color='gray'), name='Ideal'))
        st.plotly_chart(fig2, use_container_width=True)

    with tab3:
        drr_df = active_df[(active_df['Remaining Days'] > 0) & (active_df['Budget'] > 0)].copy()
        drr_df['DRR Gap'] = drr_df['Current DRR'] - drr_df['Required DRR']
        drr_df = drr_df.nsmallest(15, 'DRR Gap')
        drr_df['Order Short'] = drr_df['Order Name'].str[:50]

        fig3 = px.bar(
            drr_df, x='DRR Gap', y='Order Short', orientation='h',
            color=np.where(drr_df['DRR Gap'] < 0, 'Needs Boost', 'On Pace'),
            color_discrete_map={'Needs Boost': '#f44336', 'On Pace': '#4caf50'},
            title="Top 15 Orders Needing DRR Increase"
        )
        fig3.update_layout(height=500, yaxis_title="")
        st.plotly_chart(fig3, use_container_width=True)

    with tab4:
        perf_df = active_df[active_df['Budget'] > 0][['Account', 'CTR', 'DPVR', 'ROAS']].copy()
        perf_df['Account Short'] = perf_df['Account'].str.replace('IN - GCS - CEPC - ', '')
        perf_agg = perf_df.groupby('Account Short').mean(numeric_only=True).reset_index()

        fig4 = px.bar(
            perf_agg.melt(id_vars='Account Short', value_vars=['CTR', 'DPVR']),
            x='Account Short', y='value', color='variable',
            barmode='group', title="CTR & DPVR by Account"
        )
        fig4.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig4, use_container_width=True)

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ALERTS
    # ═══════════════════════════════════════════════════════════
    st.header("🚨 Alerts & Action Items")

    al_col1, al_col2 = st.columns(2)

    with al_col1:
        st.subheader("🔴 Not Spending / Zero Delivery")
        not_spending = active_df[active_df['Status'] == '🔴 Not Spending']
        if len(not_spending) > 0:
            for _, row in not_spending.iterrows():
                st.error(f"**{row['Order Name'][:60]}**\n\n"
                        f"Budget: ₹{row['Budget']:,.0f} | Spend: ₹{row['Total Spend']:,.0f}")
        else:
            st.success("✅ All orders are spending!")

    with al_col2:
        st.subheader("🟡 Severely Under (<80%)")
        severe = active_df[(active_df['Pacing %'] < 80) & (active_df['Pacing %'] > 0)]
        if len(severe) > 0:
            for _, row in severe.head(10).iterrows():
                st.warning(f"**{row['Order Name'][:60]}**\n\n"
                          f"Pacing: {row['Pacing %']:.1f}% | "
                          f"Gap: ₹{row['Ideal Spend'] - row['Total Spend']:,.0f}")
        else:
            st.success("✅ No severely under-delivering orders!")

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # DOWNLOAD
    # ═══════════════════════════════════════════════════════════
    st.header("📥 Download Processed Data")

    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "⬇️ Order-Level Tracker (CSV)",
            active_df.to_csv(index=False),
            f"order_tracker_{report_date.strftime('%Y%m%d')}.csv",
            "text/csv"
        )
    with dl2:
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
    st.markdown("### Welcome! Upload your Entity Order Summary to get started.")
    st.markdown("---")

    st.markdown("""
    ## 📁 How to Use

    **Step 1:** Download Entity Order Summary from DSP Console

    **Step 2:** Upload the CSV/Excel file using the sidebar ←

    **Step 3:** View delivery tracker with pacing & alerts!

    ---

    ## 📋 Expected File: Entity Order Summary

    Download from DSP Console → Reports → Entity Order Summary

    Required columns:
    | Column | Description |
    |--------|-------------|
    | Order status | Delivering / Ended / Inactive |
    | Campaign name | Order name |
    | Advertiser account name | Account name |
    | Campaign start date | Start date |
    | Campaign end date | End date |
    | Campaign budget amount | Budget |
    | Total cost | Spend to date |
    | Impressions | Total impressions |
    | Ctr | Click-through rate |
    | Total dpvr | Detail page view rate |
    | Total roas | Return on ad spend |

    ---

    ## 🚦 Status Definitions

    | Status | Condition |
    |--------|-----------|
    | 🟢 On Track | 98% ≤ Pacing ≤ 105% |
    | 🟡 Under-delivering | Pacing < 98% |
    | 🔵 Over-delivering | Pacing > 105% |
    | 🔴 Not Spending | Zero spend or "Line items not running" |
    | ⏹️ Ended | Order completed |
    """)

    st.info("👈 Upload your Entity Order Summary in the sidebar to begin!")
