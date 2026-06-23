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

# Hide edit/fork buttons and toolbar for viewers
st.markdown("""
<style>
    .stMetric > div { background-color: #f8f9fa; border-radius: 8px; padding: 10px; }
    div[data-testid="stMetricValue"] { font-size: 26px; }
    .block-container { padding-top: 1rem; }
    [data-testid="stToolbar"] { display: none !important; }
    .stDeployButton { display: none !important; }
    #MainMenu { visibility: hidden; }
    header { visibility: hidden; }
    footer { visibility: hidden; }
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
    """Extract budget from the LAST number+unit in order name.
    Takes the last occurrence of K or L in the string.
    Example: '...4.5L_Jun26-Jul26...38K' -> 38000 (last match wins)
    """
    if pd.isna(order_name):
        return 0
    name = str(order_name)

    # Find ALL matches of number followed by K or L with their positions
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
        # Sort by position and take the LAST one
        all_matches.sort(key=lambda x: x[0])
        return all_matches[-1][1]

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
    df = df.loc[:, ~df.columns.duplicated(keep='first')]

    if 'Order Name' not in df.columns:
        st.error("Could not find 'Campaign name' column. Please check file format.")
        return pd.DataFrame()

    df = df.dropna(subset=['Order Name'])
    df = df[df['Order Name'].str.strip() != '']

    df['Start Date'] = pd.to_datetime(df['Start Date'], errors='coerce')
    df['End Date'] = pd.to_datetime(df['End Date'], errors='coerce')
    today = pd.Timestamp(today)

    for col in ['Budget', 'Total Spend', 'Impressions', 'Clicks', 'CTR', 'ROAS', 'DPVR', 'Purchases', 'eCPM']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Budget extraction from LAST number in order name
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

    # Counts for all statuses
    delivering_count = len(df[df['Order Status'] == 'Delivering'])
    inactive_count = len(df[df['Order Status'] == 'Inactive'])
    ended_count = len(df[df['Order Status'] == 'Ended'])
    line_not_running = len(df[df['Order Status'] == 'Line items not running'])

    # ═══════════════════════════════════════════════════════════
    # HEADER
    # ═══════════════════════════════════════════════════════════
    st.title("📊 CEPC DSP Delivery Tracker")
    st.caption(f"📅 {report_date.strftime('%d %B %Y')} | Total Orders: {len(df)}")
    st.markdown("---")

    # ROW 1: Order Status Summary
    st.subheader("📦 Order Status Summary")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("📦 Total Orders", len(df))
    s2.metric("🟢 Delivering", delivering_count)
    s3.metric("⏹️ Ended", ended_count)
    s4.metric("⚪ Inactive", inactive_count)
    s5.metric("🔴 Lines Not Running", line_not_running)

    st.markdown("---")

    # ROW 2: Pacing Status (Active/Delivering only)
    status_counts = active_df['Status'].value_counts()
    total_budget = active_df[active_df['Budget'] > 0]['Budget'].sum()
    total_spend = active_df['Total Spend'].sum()

    st.subheader("🚦 Pacing Status (Delivering Orders)")
    p1, p2, p3, p4, p5, p6, p7 = st.columns(7)
    p1.metric("📋 Active", len(active_df))
    p2.metric("🟢 On Track", status_counts.get('On Track', 0))
    p3.metric("🟡 Under", status_counts.get('Under-delivering', 0))
    p4.metric("🔵 Over", status_counts.get('Over-delivering', 0))
    p5.metric("🔴 Not Spending", status_counts.get('Not Spending', 0))
    p6.metric("💰 Budget", f"₹{total_budget/100000:.1f}L")
    p7.metric("💸 Spend", f"₹{total_spend/100000:.1f}L")

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
                x='Pacing %', y='Account', orientation='h',
                color='Status', color_discrete_map=STATUS_COLORS,
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
    # ANALYTICS (IMPROVED CHARTS)
    # ═══════════════════════════════════════════════════════════
    st.header("📈 Analytics")

    tab1, tab2, tab3, tab4 = st.tabs(["🎯 Pacing Overview", "💰 Budget vs Spend", "📊 DRR Analysis", "🏆 Performance"])

    with tab1:
        pacing_data = active_df[(active_df['Budget'] > 0) & (active_df['Pacing %'] > 0)]
        if len(pacing_data) > 0:
            # Donut chart for status distribution
            col_chart1, col_chart2 = st.columns(2)

            with col_chart1:
                status_dist = pacing_data['Status'].value_counts().reset_index()
                status_dist.columns = ['Status', 'Count']
                fig_donut = px.pie(
                    status_dist,
                    values='Count',
                    names='Status',
                    color='Status',
                    color_discrete_map=STATUS_COLORS,
                    hole=0.5,
                    title="Order Status Distribution"
                )
                fig_donut.update_traces(textposition='inside', textinfo='percent+value')
                fig_donut.update_layout(height=350, showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.2))
                st.plotly_chart(fig_donut, use_container_width=True)

            with col_chart2:
                hist_df = pd.DataFrame({
                    'Pacing': pacing_data['Pacing %'].values,
                    'Status': pacing_data['Status'].values
                })
                fig_hist = px.histogram(
                    hist_df, x='Pacing', nbins=20,
                    color='Status', color_discrete_map=STATUS_COLORS,
                    title="Pacing Distribution"
                )
                fig_hist.add_vline(x=under_threshold, line_dash="dash", line_color="orange", annotation_text=f"{under_threshold}%")
                fig_hist.add_vline(x=over_threshold, line_dash="dash", line_color="blue", annotation_text=f"{over_threshold}%")
                fig_hist.update_layout(height=350, bargap=0.05, showlegend=False)
                st.plotly_chart(fig_hist, use_container_width=True)

            # Account-wise pacing bar (horizontal, sorted)
            acct_pacing = pd.DataFrame({
                'Account': account_summary['Account'].values,
                'Pacing %': account_summary['Pacing %'].values,
                'Status': account_summary['Status'].values,
                'Budget': account_summary['Budget'].values,
                'Spends': account_summary['Spends'].values
            }).sort_values('Pacing %', ascending=True)

            fig_acct_bar = px.bar(
                acct_pacing,
                y='Account', x='Pacing %', orientation='h',
                color='Status', color_discrete_map=STATUS_COLORS,
                title="Account-wise Pacing",
                hover_data=['Budget', 'Spends']
            )
            fig_acct_bar.add_vline(x=under_threshold, line_dash="dash", line_color="orange")
            fig_acct_bar.add_vline(x=over_threshold, line_dash="dash", line_color="blue")
            fig_acct_bar.update_layout(
                height=max(350, len(acct_pacing) * 30),
                yaxis_title="", xaxis_title="Pacing %",
                showlegend=False, margin=dict(l=10)
            )
            st.plotly_chart(fig_acct_bar, use_container_width=True)
        else:
            st.info("No data to display.")

    with tab2:
        scatter_data = active_df[(active_df['Budget'] > 0)]
        if len(scatter_data) > 0:
            scatter_df = pd.DataFrame({
                'Budget': scatter_data['Budget'].values,
                'Spend': scatter_data['Total Spend'].values,
                'Status': scatter_data['Status'].values,
                'Order': scatter_data['Order Name'].str[:50].values,
                'Account': scatter_data['Account Short'].values
            })

            fig2 = px.scatter(
                scatter_df,
                x='Budget', y='Spend',
                color='Status', hover_name='Order',
                color_discrete_map=STATUS_COLORS,
                title="Budget vs Actual Spend (Ideal = on dashed line)",
                size_max=15
            )
            max_val = scatter_df[['Budget', 'Spend']].max().max() * 1.1
            fig2.add_trace(go.Scatter(
                x=[0, max_val], y=[0, max_val],
                mode='lines', line=dict(dash='dash', color='rgba(0,0,0,0.3)', width=2),
                name='Ideal (1:1)', showlegend=True
            ))
            fig2.update_layout(
                height=450,
                xaxis_title="Budget (₹)", yaxis_title="Spend (₹)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig2, use_container_width=True)

            # Budget utilization by account
            util_df = pd.DataFrame({
                'Account': account_summary['Account'].values,
                'Budget': account_summary['Budget'].values,
                'Spends': account_summary['Spends'].values,
                'Remaining': (account_summary['Budget'] - account_summary['Spends']).values
            }).sort_values('Budget', ascending=True)

            fig_util = go.Figure()
            fig_util.add_trace(go.Bar(
                y=util_df['Account'], x=util_df['Spends'],
                name='Spent', orientation='h',
                marker_color='#4caf50'
            ))
            fig_util.add_trace(go.Bar(
                y=util_df['Account'], x=util_df['Remaining'],
                name='Remaining', orientation='h',
                marker_color='#e0e0e0'
            ))
            fig_util.update_layout(
                barmode='stack', title="Budget Utilization by Account",
                height=max(350, len(util_df) * 30),
                xaxis_title="Amount (₹)", yaxis_title="",
                legend=dict(orientation="h", yanchor="bottom", y=1.02)
            )
            st.plotly_chart(fig_util, use_container_width=True)
        else:
            st.info("No data to display.")

    with tab3:
        drr_source = active_df[(active_df['Remaining Days'] > 0) & (active_df['Budget'] > 0)].copy()
        if len(drr_source) > 0:
            drr_source['DRR Gap'] = drr_source['Current DRR'] - drr_source['Required DRR']
            drr_source['DRR Gap %'] = np.where(
                drr_source['Required DRR'] > 0,
                ((drr_source['Current DRR'] - drr_source['Required DRR']) / drr_source['Required DRR']) * 100,
                0
            )

            # Top 15 needing boost
            drr_worst = drr_source.nsmallest(15, 'DRR Gap')

            drr_chart = pd.DataFrame({
                'Order': drr_worst['Order Name'].str[:45].values,
                'DRR Gap (₹)': drr_worst['DRR Gap'].values,
                'Current DRR': drr_worst['Current DRR'].values,
                'Required DRR': drr_worst['Required DRR'].values,
                'Type': np.where(drr_worst['DRR Gap'].values < 0, 'Needs Boost', 'On Pace')
            })

            fig3 = px.bar(
                drr_chart,
                x='DRR Gap (₹)', y='Order', orientation='h',
                color='Type',
                color_discrete_map={'Needs Boost': '#ef5350', 'On Pace': '#66bb6a'},
                title="Top 15 Orders: DRR Gap (Current vs Required Daily Run Rate)",
                hover_data=['Current DRR', 'Required DRR']
            )
            fig3.update_layout(
                height=500, yaxis_title="",
                xaxis_title="DRR Gap (₹) — Negative = Behind Schedule",
                showlegend=False, margin=dict(l=10)
            )
            st.plotly_chart(fig3, use_container_width=True)

            # DRR comparison table
            with st.expander("📋 Full DRR Comparison Table"):
                drr_table = pd.DataFrame({
                    'Account': drr_source['Account Short'].values,
                    'Order': drr_source['Order Name'].str[:50].values,
                    'Current DRR': drr_source['Current DRR'].values,
                    'Required DRR': drr_source['Required DRR'].values,
                    'DRR Gap': drr_source['DRR Gap'].values,
                    'Remaining Days': drr_source['Remaining Days'].values
                }).sort_values('DRR Gap', ascending=True)

                st.dataframe(
                    drr_table.style.format({
                        'Current DRR': '₹{:,.0f}',
                        'Required DRR': '₹{:,.0f}',
                        'DRR Gap': '₹{:,.0f}',
                        'Remaining Days': '{:.0f}'
                    }),
                    use_container_width=True, height=400
                )
        else:
            st.info("No data to display.")

    with tab4:
        perf_source = active_df[active_df['Budget'] > 0]
        if len(perf_source) > 0:
            perf_agg = perf_source.groupby('Account Short').agg({
                'CTR': 'mean',
                'DPVR': 'mean',
                'ROAS': 'mean',
                'Total Spend': 'sum'
            }).reset_index().sort_values('Total Spend', ascending=False)

            # CTR & DPVR grouped bar
            perf_melt = perf_agg.melt(id_vars='Account Short', value_vars=['CTR', 'DPVR'])
            fig4 = px.bar(
                perf_melt,
                x='Account Short', y='value', color='variable',
                barmode='group', title="Average CTR & DPVR by Account",
                color_discrete_map={'CTR': '#1565c0', 'DPVR': '#64b5f6'}
            )
            fig4.update_layout(
                xaxis_tickangle=-45, height=400,
                xaxis_title="", yaxis_title="Rate",
                legend_title="Metric",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig4, use_container_width=True)

            # ROAS bar
            roas_df = perf_agg[perf_agg['ROAS'] > 0].sort_values('ROAS', ascending=True)
            if len(roas_df) > 0:
                fig_roas = px.bar(
                    roas_df,
                    y='Account Short', x='ROAS', orientation='h',
                    title="ROAS by Account",
                    color='ROAS',
                    color_continuous_scale='Greens'
                )
                fig_roas.update_layout(
                    height=max(300, len(roas_df) * 30),
                    yaxis_title="", xaxis_title="ROAS",
                    showlegend=False
                )
                st.plotly_chart(fig_roas, use_container_width=True)
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
    If budget is missing, extracted from the **last number** in order name:
    - `"...4.5L...38K"` → ₹38,000 (takes last number)
    - `"...1L"` → ₹1,00,000
    - `"...2.1L"` → ₹2,10,000
    """)
    st.info("👈 Upload your file in the sidebar to begin!")
