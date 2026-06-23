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

# Custom CSS for better visuals
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 12px;
        color: white;
        text-align: center;
        margin: 5px;
    }
    .status-on-track { color: #00c853; font-weight: bold; }
    .status-under { color: #ff9800; font-weight: bold; }
    .status-over { color: #2196f3; font-weight: bold; }
    .status-not-spending { color: #f44336; font-weight: bold; }
    .stMetric > div { background-color: #f8f9fa; border-radius: 8px; padding: 10px; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SIDEBAR - FILE UPLOAD & FILTERS
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/a/a9/Amazon_logo.svg", width=150)
    st.title("📊 DSP Delivery Tracker")
    st.markdown("---")

    # File Upload
    st.subheader("📁 Upload Raw Data")
    uploaded_file = st.file_uploader(
        "Upload Order-Level Export (CSV/Excel)",
        type=['csv', 'xlsx', 'xls'],
        help="Upload your DSP raw order data with: Campaign Name, Start Date, End Date, Budget, Total Cost, 7-Day metrics"
    )

    # Active Accounts Upload (optional)
    st.markdown("---")
    st.subheader("👥 Account Mapping (Optional)")
    accounts_file = st.file_uploader(
        "Upload Active Accounts List",
        type=['csv', 'xlsx', 'xls'],
        key="accounts",
        help="Upload your active accounts list for mapping"
    )

    # Date override
    st.markdown("---")
    st.subheader("📅 Settings")
    report_date = st.date_input("Report Date (Today)", datetime(2026, 6, 22))

    # Pacing thresholds
    st.subheader("⚙️ Pacing Thresholds")
    under_threshold = st.slider("Under-delivering below (%)", 80, 100, 98)
    over_threshold = st.slider("Over-delivering above (%)", 100, 120, 105)
    not_spending_days = st.slider("Not spending threshold (₹)", 0, 5000, 500)


# ═══════════════════════════════════════════════════════════════
# DATA PROCESSING FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def extract_account_name(order_name):
    """Extract advertiser account from order name using pattern matching"""
    if pd.isna(order_name):
        return "Unknown"

    # Pattern: "IN - GCS - CEPC - [ACCOUNT NAME]_..." or "IN - GCS - CEPC - [ACCOUNT NAME] -..."
    parts = str(order_name).split(" - ")
    if len(parts) >= 4:
        # Get the 4th part and clean it
        account_part = parts[3].strip()
        # Remove everything after underscore, dash-with-spaces, or specific keywords
        for delimiter in ['_', ' - DSP', ' -  ', '  ']:
            if delimiter in account_part:
                account_part = account_part.split(delimiter)[0].strip()
                break
        return f"IN - GCS - CEPC - {account_part}"
    return order_name


def calculate_pacing(df, today):
    """Calculate all pacing metrics"""
    df = df.copy()

    # Parse dates
    df['Start Date'] = pd.to_datetime(df['Start Date'], errors='coerce')
    df['End Date'] = pd.to_datetime(df['End Date'], errors='coerce')
    today = pd.Timestamp(today)

    # Core calculations
    df['Total Days'] = (df['End Date'] - df['Start Date']).dt.days + 1
    df['Elapsed Days'] = ((today - df['Start Date']).dt.days + 1).clip(lower=0)
    df['Elapsed Days'] = df[['Elapsed Days', 'Total Days']].min(axis=1)

    df['Daily Budget'] = df['Budget'] / df['Total Days']
    df['Ideal Spend'] = df['Daily Budget'] * df['Elapsed Days']
    df['Remaining Budget'] = df['Budget'] - df['Total Spend']
    df['Remaining Days'] = df['Total Days'] - df['Elapsed Days']

    # Pacing percentage
    df['Pacing %'] = np.where(
        df['Ideal Spend'] > 0,
        (df['Total Spend'] / df['Ideal Spend']) * 100,
        0
    )

    # Ideal DRR vs Current DRR
    df['Ideal DRR'] = np.where(
        df['Remaining Days'] > 0,
        df['Remaining Budget'] / df['Remaining Days'],
        0
    )
    df['Current DRR'] = df['7D Spend'] / 7

    # Status assignment
    def assign_status(row):
        if row['Elapsed Days'] >= row['Total Days']:
            return '⏹️ Ended'
        if row['7D Spend'] < not_spending_days and row['Elapsed Days'] > 7:
            return '🔴 Not Spending'
        if row['Pacing %'] < under_threshold:
            return '🟡 Under-delivering'
        elif row['Pacing %'] > over_threshold:
            return '🔵 Over-delivering'
        else:
            return '🟢 On Track'

    df['Status'] = df.apply(assign_status, axis=1)

    # Account mapping
    df['Account'] = df['Order Name'].apply(extract_account_name)

    return df


def parse_uploaded_file(uploaded_file):
    """Parse the uploaded raw file into standardized format"""
    if uploaded_file.name.endswith('.csv'):
        raw_df = pd.read_csv(uploaded_file)
    else:
        raw_df = pd.read_excel(uploaded_file)

    # Auto-detect column mapping (flexible for different export formats)
    col_mapping = {}

    for col in raw_df.columns:
        col_lower = col.lower().strip()
        if 'campaign name' in col_lower or 'order name' in col_lower:
            col_mapping['Order Name'] = col
        elif 'start' in col_lower and 'date' in col_lower:
            col_mapping['Start Date'] = col
        elif 'end' in col_lower and 'date' in col_lower:
            col_mapping['End Date'] = col
        elif 'budget' in col_lower:
            col_mapping['Budget'] = col

    # Handle the split columns (Till Yesterday vs 7 Days)
    # Look for Total Cost columns
    cost_cols = [c for c in raw_df.columns if 'cost' in c.lower() or 'spend' in c.lower()]

    # If standard format with positional columns (like your raw file)
    if len(raw_df.columns) >= 12:
        # Your format: Campaign Name, Start, End, Budget, [Till Yesterday: Cost, CTR, DPVR, ROAS], [7 Days: Cost, CTR, DPVR, ROAS]
        df = pd.DataFrame({
            'Order Name': raw_df.iloc[:, 0],
            'Start Date': raw_df.iloc[:, 1],
            'End Date': raw_df.iloc[:, 2],
            'Budget': pd.to_numeric(raw_df.iloc[:, 3], errors='coerce'),
            'Total Spend': pd.to_numeric(raw_df.iloc[:, 4], errors='coerce'),
            'CTR': pd.to_numeric(raw_df.iloc[:, 5], errors='coerce'),
            'DPVR': pd.to_numeric(raw_df.iloc[:, 6], errors='coerce'),
            'ROAS': pd.to_numeric(raw_df.iloc[:, 7], errors='coerce'),
            '7D Spend': pd.to_numeric(raw_df.iloc[:, 8], errors='coerce'),
            '7D CTR': pd.to_numeric(raw_df.iloc[:, 9], errors='coerce'),
            '7D DPVR': pd.to_numeric(raw_df.iloc[:, 10], errors='coerce'),
            '7D ROAS': pd.to_numeric(raw_df.iloc[:, 11], errors='coerce'),
        })
    else:
        # Try column name mapping
        df = raw_df.rename(columns=col_mapping)

    # Clean: remove rows where Order Name is null
    df = df.dropna(subset=['Order Name'])
    df = df[df['Order Name'].str.strip() != '']

    # Fill NaN spend with 0
    df['Total Spend'] = df['Total Spend'].fillna(0)
    df['7D Spend'] = df['7D Spend'].fillna(0)
    df['Budget'] = df['Budget'].fillna(0)

    return df


# ═══════════════════════════════════════════════════════════════
# MAIN DASHBOARD
# ═══════════════════════════════════════════════════════════════

if uploaded_file is not None:
    # Parse and process
    raw_df = parse_uploaded_file(uploaded_file)
    df = calculate_pacing(raw_df, report_date)

    # Filter out ended campaigns for active view
    active_df = df[df['Status'] != '⏹️ Ended']
    ended_df = df[df['Status'] == '⏹️ Ended']

    # ═══════════════════════════════════════════════════════════
    # TOP METRICS ROW
    # ═══════════════════════════════════════════════════════════
    st.title("📊 CEPC DSP Delivery Tracker")
    st.caption(f"Report Date: {report_date.strftime('%d %B %Y')} | Orders: {len(df)} | Active: {len(active_df)}")
    st.markdown("---")

    # Status counts
    status_counts = active_df['Status'].value_counts()

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("📦 Total Orders", len(df))
    with col2:
        on_track = status_counts.get('🟢 On Track', 0)
        st.metric("🟢 On Track", on_track)
    with col3:
        under = status_counts.get('🟡 Under-delivering', 0)
        st.metric("🟡 Under-delivering", under)
    with col4:
        over = status_counts.get('🔵 Over-delivering', 0)
        st.metric("🔵 Over-delivering", over)
    with col5:
        not_spending = status_counts.get('🔴 Not Spending', 0)
        st.metric("🔴 Not Spending", not_spending)

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ACCOUNT-LEVEL SUMMARY
    # ═══════════════════════════════════════════════════════════
    st.header("🏢 Account-Level Overview")

    # Aggregate to account level
    account_summary = active_df.groupby('Account').agg({
        'Budget': 'sum',
        'Total Spend': 'sum',
        'Ideal Spend': 'sum',
        '7D Spend': 'sum',
        'Order Name': 'count',
        'Current DRR': 'sum'
    }).reset_index()

    account_summary.columns = ['Account', 'Total Budget', 'Total Spend', 
                                'Ideal Spend', '7D Spend', 'Order Count', 'Current DRR']
    account_summary['Pacing %'] = round(
        (account_summary['Total Spend'] / account_summary['Ideal Spend']) * 100, 1
    )
    account_summary['DR %'] = round(
        (account_summary['Total Spend'] / account_summary['Total Budget']) * 100, 1
    )

    def account_status(row):
        if row['7D Spend'] < not_spending_days * row['Order Count']:
            return '🔴 Not Spending'
        elif row['Pacing %'] < under_threshold:
            return '🟡 Under'
        elif row['Pacing %'] > over_threshold:
            return '🔵 Over'
        else:
            return '🟢 On Track'

    account_summary['Status'] = account_summary.apply(account_status, axis=1)
    account_summary = account_summary.sort_values('Pacing %', ascending=True)

    # Account pacing chart
    fig_accounts = px.bar(
        account_summary,
        x='Pacing %',
        y='Account',
        orientation='h',
        color='Status',
        color_discrete_map={
            '🟢 On Track': '#4caf50',
            '🟡 Under': '#ff9800',
            '🔵 Over': '#2196f3',
            '🔴 Not Spending': '#f44336'
        },
        title="Account Pacing Overview",
        hover_data=['Total Budget', 'Total Spend', 'Order Count']
    )
    fig_accounts.add_vline(x=98, line_dash="dash", line_color="green", 
                           annotation_text="98%")
    fig_accounts.add_vline(x=105, line_dash="dash", line_color="blue", 
                           annotation_text="105%")
    fig_accounts.update_layout(height=max(400, len(account_summary) * 35))
    st.plotly_chart(fig_accounts, use_container_width=True)

    # Account table
    with st.expander("📋 Account Details Table", expanded=True):
        st.dataframe(
            account_summary[['Account', 'Total Budget', 'Total Spend', 'Pacing %', 
                           'DR %', '7D Spend', 'Order Count', 'Status']]
            .style.format({
                'Total Budget': '₹{:,.0f}',
                'Total Spend': '₹{:,.0f}',
                'Pacing %': '{:.1f}%',
                'DR %': '{:.1f}%',
                '7D Spend': '₹{:,.0f}'
            }),
            use_container_width=True,
            height=400
        )

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ORDER-LEVEL DETAIL (Filterable)
    # ═══════════════════════════════════════════════════════════
    st.header("📋 Order-Level Delivery Tracker")

    # Filters
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:
        status_filter = st.multiselect(
            "Filter by Status",
            options=active_df['Status'].unique().tolist(),
            default=active_df['Status'].unique().tolist()
        )
    with filter_col2:
        account_filter = st.multiselect(
            "Filter by Account",
            options=sorted(active_df['Account'].unique().tolist()),
            default=sorted(active_df['Account'].unique().tolist())
        )
    with filter_col3:
        pacing_range = st.slider("Pacing % Range", 0, 200, (0, 200))

    # Apply filters
    filtered_df = active_df[
        (active_df['Status'].isin(status_filter)) &
        (active_df['Account'].isin(account_filter)) &
        (active_df['Pacing %'].between(pacing_range[0], pacing_range[1]))
    ]

    # Order table
    display_cols = ['Order Name', 'Account', 'Start Date', 'End Date', 'Budget',
                    'Total Spend', 'Ideal Spend', 'Pacing %', '7D Spend', 
                    'Current DRR', 'Ideal DRR', 'Status']

    st.dataframe(
        filtered_df[display_cols].sort_values('Pacing %', ascending=True)
        .style.format({
            'Budget': '₹{:,.0f}',
            'Total Spend': '₹{:,.0f}',
            'Ideal Spend': '₹{:,.0f}',
            'Pacing %': '{:.1f}%',
            '7D Spend': '₹{:,.0f}',
            'Current DRR': '₹{:,.0f}',
            'Ideal DRR': '₹{:,.0f}'
        }),
        use_container_width=True,
        height=500
    )

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # VISUAL ANALYTICS
    # ═══════════════════════════════════════════════════════════
    st.header("📈 Visual Analytics")

    viz_tab1, viz_tab2, viz_tab3, viz_tab4 = st.tabs([
        "🎯 Pacing Distribution", "💰 Budget vs Spend", 
        "📉 DRR Analysis", "🔥 Heatmap"
    ])

    with viz_tab1:
        # Pacing distribution histogram
        fig_dist = px.histogram(
            active_df, x='Pacing %', nbins=20,
            color='Status',
            color_discrete_map={
                '🟢 On Track': '#4caf50',
                '🟡 Under-delivering': '#ff9800',
                '🔵 Over-delivering': '#2196f3',
                '🔴 Not Spending': '#f44336'
            },
            title="Pacing Distribution Across All Active Orders"
        )
        fig_dist.add_vline(x=98, line_dash="dash", line_color="green")
        fig_dist.add_vline(x=105, line_dash="dash", line_color="blue")
        st.plotly_chart(fig_dist, use_container_width=True)

    with viz_tab2:
        # Budget vs Spend scatter
        fig_scatter = px.scatter(
            active_df,
            x='Budget',
            y='Total Spend',
            size='7D Spend',
            color='Status',
            hover_name='Order Name',
            color_discrete_map={
                '🟢 On Track': '#4caf50',
                '🟡 Under-delivering': '#ff9800',
                '🔵 Over-delivering': '#2196f3',
                '🔴 Not Spending': '#f44336'
            },
            title="Budget vs Actual Spend (bubble size = 7D spend velocity)"
        )
        # Add ideal line
        max_val = max(active_df['Budget'].max(), active_df['Total Spend'].max())
        fig_scatter.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode='lines', line=dict(dash='dash', color='gray'),
            name='Ideal (1:1)'
        ))
        st.plotly_chart(fig_scatter, use_container_width=True)

    with viz_tab3:
        # Current DRR vs Ideal DRR
        drr_df = active_df[active_df['Remaining Days'] > 0].copy()
        drr_df['DRR Gap'] = drr_df['Current DRR'] - drr_df['Ideal DRR']
        drr_df = drr_df.sort_values('DRR Gap', ascending=True).head(20)

        fig_drr = px.bar(
            drr_df,
            x='DRR Gap',
            y='Order Name',
            orientation='h',
            color=np.where(drr_df['DRR Gap'] < 0, 'Needs Increase', 'Ahead'),
            color_discrete_map={'Needs Increase': '#f44336', 'Ahead': '#4caf50'},
            title="Top 20 Orders: Current DRR vs Required DRR (Gap)"
        )
        fig_drr.update_layout(height=600)
        st.plotly_chart(fig_drr, use_container_width=True)

    with viz_tab4:
        # Account x Metric heatmap
        heatmap_data = account_summary[['Account', 'Pacing %', 'DR %']].set_index('Account')
        fig_heat = px.imshow(
            heatmap_data.T,
            color_continuous_scale='RdYlGn',
            title="Account Health Heatmap",
            labels=dict(color="Percentage")
        )
        fig_heat.update_layout(height=300)
        st.plotly_chart(fig_heat, use_container_width=True)

    st.markdown("---")

    # ═══════════════════════════════════════════════════════════
    # ALERTS & ACTION ITEMS
    # ═══════════════════════════════════════════════════════════
    st.header("🚨 Alerts & Action Items")

    alert_col1, alert_col2 = st.columns(2)

    with alert_col1:
        st.subheader("🔴 Not Spending (Immediate Action)")
        not_spending_df = active_df[active_df['Status'] == '🔴 Not Spending']
        if len(not_spending_df) > 0:
            for _, row in not_spending_df.iterrows():
                st.error(f"**{row['Order Name'][:50]}...**\n\n"
                        f"Budget: ₹{row['Budget']:,.0f} | "
                        f"7D Spend: ₹{row['7D Spend']:,.0f}")
        else:
            st.success("✅ No orders with zero spend!")

    with alert_col2:
        st.subheader("🟡 Severely Under-delivering (<80%)")
        severe_under = active_df[active_df['Pacing %'] < 80]
        if len(severe_under) > 0:
            for _, row in severe_under.iterrows():
                st.warning(f"**{row['Order Name'][:50]}...**\n\n"
                          f"Pacing: {row['Pacing %']:.1f}% | "
                          f"Gap: ₹{row['Ideal Spend'] - row['Total Spend']:,.0f}")
        else:
            st.success("✅ No severely under-delivering orders!")

    # ═══════════════════════════════════════════════════════════
    # DOWNLOAD PROCESSED DATA
    # ═══════════════════════════════════════════════════════════
    st.markdown("---")
    st.header("📥 Download Processed Tracker")

    dl_col1, dl_col2 = st.columns(2)

    with dl_col1:
        csv_orders = df.to_csv(index=False)
        st.download_button(
            "⬇️ Download Order-Level Tracker (CSV)",
            csv_orders,
            f"delivery_tracker_orders_{report_date.strftime('%Y%m%d')}.csv",
            "text/csv"
        )

    with dl_col2:
        csv_accounts = account_summary.to_csv(index=False)
        st.download_button(
            "⬇️ Download Account-Level Summary (CSV)",
            csv_accounts,
            f"delivery_tracker_accounts_{report_date.strftime('%Y%m%d')}.csv",
            "text/csv"
        )

else:
    # ═══════════════════════════════════════════════════════════
    # LANDING PAGE (No file uploaded yet)
    # ═══════════════════════════════════════════════════════════
    st.title("📊 CEPC DSP Delivery Tracker")
    st.markdown("### Welcome! Upload your raw order data to get started.")

    st.markdown("---")

    st.markdown("""
    ## 📁 How to Use

    **Step 1:** Export your DSP order-level data (CSV or Excel)

    **Step 2:** Upload it using the sidebar file uploader ←

    **Step 3:** View your delivery tracker with pacing status!

    ---

    ## 📋 Expected File Format

    Your raw file should have these columns (in order):

    | Column | Description | Example |
    |--------|-------------|---------|
    | Campaign Name | Order name from DSP | IN - GCS - CEPC - Sekyo_1L_P+... |
    | Campaign Start Date | Order start | 2026-06-03 |
    | Campaign End Date | Order end | 2026-07-03 |
    | Campaign Budget | Total order budget | 100000 |
    | Total Cost (Cumulative) | Spend till yesterday | 54530 |
    | CTR | Click-through rate | 0.0068 |
    | Total DPVR | Detail page view rate | 0.012 |
    | Total ROAS | Return on ad spend | 6.73 |
    | Total Cost (7 Days) | Last 7 days spend | 91042 |
    | CTR (7 Days) | 7-day CTR | 0.012 |
    | DPVR (7 Days) | 7-day DPVR | 0.016 |
    | ROAS (7 Days) | 7-day ROAS | 0.11 |

    ---

    ## 🚦 Status Definitions

    | Status | Condition |
    |--------|-----------|
    | 🟢 On Track | 98% ≤ Pacing ≤ 105% |
    | 🟡 Under-delivering | Pacing < 98% |
    | 🔵 Over-delivering | Pacing > 105% |
    | 🔴 Not Spending | < ₹500 spend in last 7 days |
    | ⏹️ Ended | Past end date |
    """)

    st.info("👈 Upload your file in the sidebar to begin!")
