import streamlit as st
import pandas as pd
from datetime import datetime
import numpy as np
import re

st.set_page_config(page_title="DSP Delivery Tracker", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>.stDeployButton{display:none!important}.stMetric>div{background-color:#f8f9fa;border-radius:8px;padding:10px}div[data-testid="stMetricValue"]{font-size:22px}</style>""", unsafe_allow_html=True)
TODAY = datetime.today()
CURRENT_MONTH = TODAY.month
CURRENT_YEAR = TODAY.year

with st.sidebar:
    st.title("📊 DSP Delivery Tracker")
    st.markdown("---")
    st.subheader("📝 Report Name")
    report_name = st.text_input("Name this report", value="", placeholder="e.g. June Week 3 Report")
    st.markdown("---")
    st.subheader("📁 Upload Files")
    uploaded_file = st.file_uploader("1️⃣ Overall Data (Full YTD-MTD)", type=['csv','xlsx','xls'])
    uploaded_3day = st.file_uploader("2️⃣ Last 3 Days Data (for DRR)", type=['csv','xlsx','xls'])
    st.markdown("---")
    st.subheader("📅 Projection")
    projection_date = st.date_input("Projection Date", datetime(2026,6,30))
    st.markdown("---")
    st.subheader("⚙️ Pacing Thresholds")
    under_threshold = st.slider("Under-delivering below (%)", 80, 100, 98)
    over_threshold = st.slider("Over-delivering above (%)", 100, 120, 105)
    st.markdown("---")
    st.subheader("🔍 Filters")
    show_only_delivering = st.checkbox("Show only 'Delivering' orders", value=True)

def extract_budget_from_name(order_name):
    if pd.isna(order_name): return 0
    all_matches = []
    for match in re.finditer(r'(\d+\.?\d*)\s*([KkLl])', str(order_name)):
        value = float(match.group(1))
        unit = match.group(2).upper()
        if unit == 'L': all_matches.append((match.start(), value*100000))
        elif unit == 'K': all_matches.append((match.start(), value*1000))
    if all_matches:
        all_matches.sort(key=lambda x: x[0])
        return all_matches[-1][1]
    return 0

def parse_file(f):
    if f.name.endswith('.csv'): return pd.read_csv(f)
    return pd.read_excel(f)

def standardize_columns(df):
    col_map = {}
    used = set()
    for col in df.columns:
        cl = col.lower().strip()
        m = None
        if 'order status' in cl: m = 'Order Status'
        elif 'campaign name' in cl: m = 'Order Name'
        elif 'advertiser' in cl and 'account' in cl: m = 'Account'
        elif 'start' in cl and 'date' in cl: m = 'Start Date'
        elif 'end' in cl and 'date' in cl: m = 'End Date'
        elif 'budget' in cl: m = 'Budget'
        elif 'total cost' in cl: m = 'Total Spend'
        elif cl == 'impressions': m = 'Impressions'
        elif 'click' in cl: m = 'Clicks'
        elif cl == 'ctr': m = 'CTR'
        elif 'total roas' in cl and 'click' not in cl: m = 'ROAS'
        elif 'total dpvr' in cl: m = 'DPVR'
        elif 'total purchases' in cl: m = 'Purchases'
        elif 'ecpm' in cl: m = 'eCPM'
        elif 'new-to-brand' in cl or 'ntb' in cl: m = 'NTB'
        if m and m not in used: col_map[col] = m; used.add(m)
    df = df.rename(columns=col_map)
    return df.loc[:, ~df.columns.duplicated(keep='first')]

def process_data(df, today, drr_data=None, proj_date=None):
    df = df.copy().dropna(how='all')
    df = standardize_columns(df)
    if 'Order Name' not in df.columns:
        st.error("Could not find 'Campaign name' column.")
        return pd.DataFrame()
    df = df.dropna(subset=['Order Name'])
    df = df[df['Order Name'].str.strip() != '']
    df['Start Date'] = pd.to_datetime(df['Start Date'], errors='coerce')
    df['End Date'] = pd.to_datetime(df['End Date'], errors='coerce')
    today = pd.Timestamp(today)
    for col in ['Budget','Total Spend','Impressions','Clicks','CTR','ROAS','DPVR','Purchases','eCPM','NTB']:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    if 'NTB' not in df.columns: df['NTB'] = 0
    df['Budget'] = df.apply(lambda r: extract_budget_from_name(r['Order Name']) if r.get('Budget',0)==0 else r['Budget'], axis=1)
    df['Total Days'] = (df['End Date']-df['Start Date']).dt.days + 1
    df['Elapsed Days'] = ((today-df['Start Date']).dt.days+1).clip(lower=0)
    df['Elapsed Days'] = df[['Elapsed Days','Total Days']].min(axis=1)
    df['Remaining Days'] = (df['Total Days']-df['Elapsed Days']).clip(lower=0)
    df['Daily Budget'] = np.where(df['Total Days']>0, df['Budget']/df['Total Days'], 0)
    df['Ideal Spend'] = df['Daily Budget']*df['Elapsed Days']
    df['Remaining Budget'] = (df['Budget']-df['Total Spend']).clip(lower=0)
    df['DR %'] = np.where(df['Ideal Spend']>0, round((df['Total Spend']/df['Ideal Spend'])*100,1), 0)
    df['Expected DRR'] = np.where(df['Remaining Days']>0, df['Remaining Budget']/df['Remaining Days'], 0)
    df['Current DRR'] = 0.0
    if drr_data is not None:
        drr_df = standardize_columns(drr_data.copy())
        if 'Order Name' in drr_df.columns and 'Total Spend' in drr_df.columns:
            drr_df['Total Spend'] = pd.to_numeric(drr_df['Total Spend'], errors='coerce').fillna(0)
            drr_lookup = drr_df.groupby('Order Name')['Total Spend'].sum().reset_index()
            drr_lookup.columns = ['Order Name','3D Spend']
            drr_lookup['Current DRR'] = drr_lookup['3D Spend']/3
            df = df.merge(drr_lookup[['Order Name','Current DRR']], on='Order Name', how='left', suffixes=('_old',''))
            if 'Current DRR_old' in df.columns:
                df['Current DRR'] = df['Current DRR'].fillna(df['Current DRR_old'])
                df.drop('Current DRR_old', axis=1, inplace=True)
            df['Current DRR'] = df['Current DRR'].fillna(0)
    else:
        df['Current DRR'] = np.where(df['Elapsed Days']>0, df['Total Spend']/df['Elapsed Days'], 0)
    effective_drr = np.where(df['Current DRR']>0, df['Current DRR'], df['Daily Budget'])
    df['Projected at End'] = df['Total Spend'] + (effective_drr * df['Remaining Days'])
    df['Projected at End'] = df[['Projected at End','Budget']].min(axis=1)
    df['Proj End %'] = np.where(df['Budget']>0, round((df['Projected at End']/df['Budget'])*100,1), 0)
    df['Projected Spend'] = df['Total Spend']
    if proj_date is not None:
        proj_ts = pd.Timestamp(proj_date)
        if proj_ts > today:
            days_proj = (proj_ts - today).days
            df['Projected Spend'] = df['Total Spend'] + (effective_drr * days_proj)
            df['Projected Spend'] = df[['Projected Spend','Budget']].min(axis=1)
    def assign_status(row):
        if row.get('Order Status','') == 'Ended': return 'Ended'
        if row.get('Order Status','') == 'Inactive': return 'Inactive'
        if row.get('Order Status','') == 'Line items not running': return 'Not Spending'
        if row['Budget'] == 0: return 'No Budget'
        if row['Total Spend'] == 0 and row['Elapsed Days'] > 3: return 'Not Spending'
        if row['Proj End %'] >= under_threshold and row['Proj End %'] <= over_threshold: return 'On Track'
        elif row['Proj End %'] > over_threshold: return 'Over-delivering'
        else: return 'Under-delivering'
    df['Status'] = df.apply(assign_status, axis=1)
    df['Account Short'] = df['Account'].str.replace('IN - GCS - CEPC - ', '', regex=False).str.strip()
    df['CTR %'] = df['CTR']*100
    df['DPVR %'] = df['DPVR']*100
    return df

STATUS_ICONS = {'On Track':'🟢','Under-delivering':'🟡','Over-delivering':'🔵','Not Spending':'🔴','No Budget':'⚪','Inactive':'⚪','Ended':'⏹️'}
def badge_ctr(v):
    try:
        v=float(v)
        if v>0.60:return f'🟢 {v:.2f}%'
        elif v>=0.40:return f'🟡 {v:.2f}%'
        else:return f'🔴 {v:.2f}%'
    except:return str(v)
def badge_dpvr(d,c):
    try:
        d,c=float(d),float(c)
        if d>c:return f'🟢 {d:.2f}%'
        else:return f'🔴 {d:.2f}%'
    except:return str(d)
def badge_ntb(v):
    try:
        v=float(v)
        if v>0.6:return f'🟢 {v:.1%}'
        elif v>=0.4:return f'🟡 {v:.1%}'
        else:return f'🔴 {v:.1%}'
    except:return str(v)
def badge_roas(v):
    try:
        v=float(v)
        if v>2:return f'🟢 {v:.2f}'
        elif v>=1:return f'🟡 {v:.2f}'
        else:return f'🔴 {v:.2f}'
    except:return str(v)

if uploaded_file is not None:
    raw_df = parse_file(uploaded_file)
    drr_raw = parse_file(uploaded_3day) if uploaded_3day else None
    df = process_data(raw_df, TODAY, drr_data=drr_raw, proj_date=projection_date)
    if len(df)==0: st.error("No data."); st.stop()

    if show_only_delivering: active_df = df[df['Order Status']=='Delivering'].copy()
    else: active_df = df[~df['Status'].isin(['Ended','Inactive'])].copy()

    # ALL orders for current month (for account overview)
    all_current_month = df[
        ((df['Start Date'].dt.month <= CURRENT_MONTH) & (df['Start Date'].dt.year <= CURRENT_YEAR)) &
        ((df['End Date'].dt.month >= CURRENT_MONTH) & (df['End Date'].dt.year >= CURRENT_YEAR)) |
        (df['Start Date'].dt.month == CURRENT_MONTH) & (df['Start Date'].dt.year == CURRENT_YEAR) |
        (df['End Date'].dt.month == CURRENT_MONTH) & (df['End Date'].dt.year == CURRENT_YEAR)
    ].copy()
    # Simpler: any order that was active at any point in current month
    all_current_month = df[
        (df['Start Date'] <= pd.Timestamp(CURRENT_YEAR, CURRENT_MONTH, 28)) &
        (df['End Date'] >= pd.Timestamp(CURRENT_YEAR, CURRENT_MONTH, 1))
    ].copy()

    active_for_dates = df[df['Order Status'].isin(['Delivering','Inactive','Line items not running'])]
    flight_start = active_for_dates['Start Date'].min()
    flight_end = active_for_dates['End Date'].max()
    delivering_count = len(df[df['Order Status']=='Delivering'])
    inactive_count = len(df[df['Order Status']=='Inactive'])
    ended_count = len(df[df['Order Status']=='Ended'])
    line_not_running = len(df[df['Order Status']=='Line items not running'])
    inactive_combined = inactive_count + line_not_running
    total_accounts = df['Account Short'].nunique()
    active_accounts = active_df['Account Short'].nunique()
    ended_accounts = df[df['Order Status']=='Ended']['Account Short'].nunique()
    proj_ts = pd.Timestamp(projection_date)
    today_ts = pd.Timestamp(TODAY)
    show_projection = proj_ts > today_ts

    title = "📊 DSP Delivery Tracker"
    if report_name: title += f" — {report_name}"
    st.title(title)
    st.caption(f"📅 {TODAY.strftime('%d %B %Y')} | Flight: {flight_start.strftime('%d %b %Y') if pd.notna(flight_start) else 'N/A'} → {flight_end.strftime('%d %b %Y') if pd.notna(flight_end) else 'N/A'} | Orders: {len(df)}")
    if uploaded_3day: st.success("✅ 3-Day DRR file loaded")
    else: st.info("ℹ️ Upload 'Last 3 Days Data' for accurate Current DRR")
    st.markdown("---")

    # ACCOUNT SUMMARY
    st.subheader("🏢 Account Level Summary")
    acct_sum_filter = st.multiselect("Select Accounts (leave empty for all)", options=sorted(active_df['Account Short'].unique()), default=[], key="acct_sum")
    sum_df = active_df.copy()
    if acct_sum_filter: sum_df = sum_df[sum_df['Account Short'].isin(acct_sum_filter)]
    sum_budget = sum_df[sum_df['Budget']>0]['Budget'].sum()
    sum_ideal = sum_df[sum_df['Budget']>0]['Ideal Spend'].sum()
    sum_spend = sum_df['Total Spend'].sum()
    sum_dr = (sum_spend/sum_ideal*100) if sum_ideal>0 else 0
    sum_acct = sum_df[sum_df['Budget']>0].groupby('Account Short').agg({'Budget':'sum','Projected at End':'sum'}).reset_index()
    sum_acct['Proj %'] = np.where(sum_acct['Budget']>0,(sum_acct['Projected at End']/sum_acct['Budget'])*100,0)
    s_under = len(sum_acct[sum_acct['Proj %']<under_threshold])
    s_over = len(sum_acct[sum_acct['Proj %']>over_threshold])
    s_on_track = len(sum_acct) - s_under - s_over
    a1,a2,a3,a4,a5,a6,a7,a8 = st.columns(8)
    a1.metric("Total Accounts", total_accounts)
    a2.metric("Active Accounts", len(sum_acct))
    a3.metric("⏹️ Ended", ended_accounts)
    a4.metric("🟡 Under-delivery", s_under)
    a5.metric("🔵 Over-delivery", s_over)
    a6.metric("🟢 On Track", s_on_track)
    a7.metric("💰 Budget", f"₹{sum_budget/100000:.1f}L")
    a8.metric("📊 DR%", f"{sum_dr:.1f}%")
    st.markdown("---")

    # ORDER SUMMARY
    st.subheader("📋 Order Level Summary")
    status_counts = active_df['Status'].value_counts()
    total_budget = active_df[active_df['Budget']>0]['Budget'].sum()
    at_risk = active_df[(active_df['Proj End %']<80)&(active_df['Budget']>0)]
    budget_at_risk = at_risk['Remaining Budget'].sum()
    o1,o2,o3,o4,o5,o6,o7,o8 = st.columns(8)
    o1.metric("Total Orders", len(df))
    o2.metric("🟢 Active", delivering_count)
    o3.metric("⏹️ Ended", ended_count)
    o4.metric("⚪ Inactive/Not Running", inactive_combined)
    o5.metric("🟢 On Track", status_counts.get('On Track',0))
    o6.metric("🟡 Under", status_counts.get('Under-delivering',0))
    o7.metric("🔵 Over", status_counts.get('Over-delivering',0))
    o8.metric("⚠️ Budget at Risk", f"₹{budget_at_risk/100000:.1f}L")
    if show_projection:
        st.markdown("---")
        proj_total = active_df['Projected Spend'].sum()
        st.subheader(f"🔮 Projection (by {projection_date.strftime('%d %b %Y')})")
        pr1,pr2,pr3 = st.columns(3)
        pr1.metric("📅 Days to Projection", f"{(proj_ts-today_ts).days} days")
        pr2.metric("💸 Projected Total Spend", f"₹{proj_total/100000:.1f}L")
        pr3.metric("📉 Projected Remaining", f"₹{(total_budget-proj_total)/100000:.1f}L")
    st.markdown("---")

    # ACCOUNT OVERVIEW TABLE — ALL ORDERS FOR CURRENT MONTH
    st.header("🏢 Account-Level Overview")
    st.caption(f"📅 Showing all orders active in {TODAY.strftime('%B %Y')} (all statuses)")

    acct_overview_df = all_current_month.copy()
    if len(acct_overview_df) > 0:
        acct_table_filter = st.multiselect("Filter by Account", options=sorted(acct_overview_df['Account Short'].unique()), default=[], key="acct_tbl")
        if acct_table_filter: acct_overview_df = acct_overview_df[acct_overview_df['Account Short'].isin(acct_table_filter)]

        account_summary = acct_overview_df.groupby('Account Short').agg({
            'Budget':'sum','Total Spend':'sum','Ideal Spend':'sum',
            'Current DRR':'sum','Expected DRR':'sum',
            'Projected Spend':'sum','Projected at End':'sum',
            'Start Date':'min','End Date':'max',
            'CTR %':'mean','DPVR %':'mean','ROAS':'mean',
            'Order Name':'count','Order Status': lambda x: ', '.join(x.unique())
        }).reset_index()
        account_summary.columns = ['Account','Budget','Spends','Ideal Spend','Current DRR','Expected DRR','Projected Spend','Projected at End','Start Date','End Date','CTR %','DPVR %','ROAS','Orders','Statuses']
        account_summary['DR %'] = np.where(account_summary['Ideal Spend']>0, round((account_summary['Spends']/account_summary['Ideal Spend'])*100,1),0)
        account_summary['Proj End %'] = np.where(account_summary['Budget']>0, round((account_summary['Projected at End']/account_summary['Budget'])*100,1),0)
        def a_status(r):
            if r['Proj End %']>=under_threshold and r['Proj End %']<=over_threshold: return 'On Track'
            elif r['Proj End %']>over_threshold: return 'Over-delivering'
            else: return 'Under-delivering'
        account_summary['Status'] = account_summary.apply(a_status, axis=1)
        account_summary = account_summary.sort_values('DR %', ascending=True)
        account_summary['Start Date'] = account_summary['Start Date'].dt.strftime('%d %b %Y')
        account_summary['End Date'] = account_summary['End Date'].dt.strftime('%d %b %Y')

        st.caption(f"{len(account_summary)} Accounts | All orders (Delivering + Ended + Inactive)")
        disp = ['Account','Start Date','End Date','Budget','Spends','DR %','Current DRR','Expected DRR']
        if show_projection: disp.append('Projected Spend')
        disp += ['CTR %','DPVR %','ROAS','Orders','Status']
        ad = account_summary[disp].copy()
        ad['Status'] = ad['Status'].map(lambda x: f"{STATUS_ICONS.get(x,'')} {x}")
        fmt = {'Budget':'₹{:,.0f}','Spends':'₹{:,.0f}','DR %':'{:.1f}%','Current DRR':'₹{:,.0f}','Expected DRR':'₹{:,.0f}','CTR %':'{:.2f}%','DPVR %':'{:.2f}%','ROAS':'{:.2f}'}
        if show_projection: fmt['Projected Spend'] = '₹{:,.0f}'
        st.dataframe(ad.style.format(fmt), use_container_width=True, height=min(650,max(250,len(account_summary)*38)))
    st.markdown("---")

    # ORDER TABLE (still uses active_df based on filter)
    st.header("📋 Order-Level Delivery Tracker")
    fc1,fc2,fc3 = st.columns([2,2,1])
    with fc1: ord_acct = st.multiselect("Filter by Account", options=sorted(active_df['Account Short'].unique()), default=[], key="ord_a")
    with fc2: ord_status = st.multiselect("Filter by Status", options=active_df['Status'].unique().tolist(), default=active_df['Status'].unique().tolist())
    with fc3: pr = st.slider("DR %", 0, 200, (0,200))
    fdf = active_df.copy()
    if ord_acct: fdf = fdf[fdf['Account Short'].isin(ord_acct)]
    fdf = fdf[(fdf['Status'].isin(ord_status))&(fdf['DR %'].between(pr[0],pr[1]))]
    od = {'Account':fdf['Account Short'].values,'Order Name':fdf['Order Name'].values,'Start Date':fdf['Start Date'].dt.strftime('%d %b %Y').values,'End Date':fdf['End Date'].dt.strftime('%d %b %Y').values,'Budget':fdf['Budget'].values,'Spends':fdf['Total Spend'].values,'DR %':fdf['DR %'].values,'Current DRR':fdf['Current DRR'].values,'Expected DRR':fdf['Expected DRR'].values}
    if show_projection: od['Projected Spend'] = fdf['Projected Spend'].values
    od['CTR %'] = fdf['CTR %'].values; od['DPVR %'] = fdf['DPVR %'].values; od['ROAS'] = fdf['ROAS'].values
    od['Status'] = [f"{STATUS_ICONS.get(s,'')} {s}" for s in fdf['Status'].values]
    odf = pd.DataFrame(od).sort_values('DR %', ascending=True)
    of = {'Budget':'₹{:,.0f}','Spends':'₹{:,.0f}','DR %':'{:.1f}%','Current DRR':'₹{:,.0f}','Expected DRR':'₹{:,.0f}','CTR %':'{:.2f}%','DPVR %':'{:.2f}%','ROAS':'{:.2f}'}
    if show_projection: of['Projected Spend'] = '₹{:,.0f}'
    st.dataframe(odf.style.format(of), use_container_width=True, height=600)
    st.markdown("---")

    # PERFORMANCE
    st.header("📈 Performance Metrics")
    st.caption("🟢 Good | 🟡 Average | 🔴 Poor")
    pv = st.radio("View by:", ["Account Level","Order Level"], horizontal=True)
    if pv == "Account Level":
        ps = active_df[active_df['Budget']>0]
        if len(ps)>0:
            pa = ps.groupby('Account Short').agg({'CTR %':'mean','DPVR %':'mean','NTB':'mean','ROAS':'mean','Total Spend':'sum','Order Name':'count'}).reset_index()
            pa.columns = ['Account','CTR %','DPVR %','NTB','ROAS','Spend','Orders']
            pa = pa.sort_values('Spend', ascending=False)
            st.dataframe(pd.DataFrame({'Account':pa['Account'].values,'CTR':[badge_ctr(v) for v in pa['CTR %'].values],'DPVR':[badge_dpvr(d,c) for d,c in zip(pa['DPVR %'].values,pa['CTR %'].values)],'NTB':[badge_ntb(v) for v in pa['NTB'].values],'ROAS':[badge_roas(v) for v in pa['ROAS'].values],'Spend':[f"₹{v:,.0f}" for v in pa['Spend'].values],'Orders':pa['Orders'].values}), use_container_width=True, height=min(600,max(250,len(pa)*38)))
    else:
        pa2 = st.selectbox("Select Account", options=["All"]+sorted(active_df['Account Short'].unique().tolist()))
        po = active_df[active_df['Budget']>0].copy()
        if pa2 != "All": po = po[po['Account Short']==pa2]
        if len(po)>0:
            st.dataframe(pd.DataFrame({'Account':po['Account Short'].values,'Order Name':po['Order Name'].str[:55].values,'CTR':[badge_ctr(v) for v in po['CTR %'].values],'DPVR':[badge_dpvr(d,c) for d,c in zip(po['DPVR %'].values,po['CTR %'].values)],'NTB':[badge_ntb(v) for v in po['NTB'].values],'ROAS':[badge_roas(v) for v in po['ROAS'].values],'Spend':[f"₹{v:,.0f}" for v in po['Total Spend'].values]}), use_container_width=True, height=min(600,max(250,len(po)*38)))
    st.markdown("---")
    l1,l2,l3,l4 = st.columns(4)
    l1.markdown("**CTR**\n- 🟢 > 0.60%\n- 🟡 0.40-0.60%\n- 🔴 < 0.40%")
    l2.markdown("**DPVR**\n- 🟢 > CTR\n- 🔴 < CTR")
    l3.markdown("**NTB**\n- 🟢 > 60%\n- 🟡 40-60%\n- 🔴 < 40%")
    l4.markdown("**ROAS**\n- 🟢 > 2\n- 🟡 1-2\n- 🔴 < 1")
    st.markdown("---")
    st.header("📥 Download")
    dl1,dl2 = st.columns(2)
    with dl1: st.download_button("⬇️ Order Tracker",active_df.to_csv(index=False),f"order_tracker_{TODAY.strftime('%Y%m%d')}.csv","text/csv")
    with dl2:
        if len(acct_overview_df)>0: st.download_button("⬇️ Account Summary",account_summary.to_csv(index=False),f"account_summary_{TODAY.strftime('%Y%m%d')}.csv","text/csv")
else:
    st.title("📊 DSP Delivery Tracker")
    st.markdown("### Upload your Entity Order Summary to get started")
    st.markdown("---")
    st.markdown("""
## 📁 How to Use
**File 1 (Required):** Entity Order Summary — Full YTD-MTD data

**File 2 (Optional):** Last 3 Days data — for accurate Current DRR

---
## 📊 Key Metrics
| Metric | Formula |
|--------|---------|
| **DR %** | Actual Spend / Ideal Spend × 100 |
| **Current DRR** | Last 3 days spend ÷ 3 |
| **Expected DRR** | Remaining Budget ÷ Remaining Days |
| **Projected Spend** | Current Spend + (DRR × Days) |

---
## 🚦 Status (Based on Projected End Spend)
| Status | Condition |
|--------|-----------|
| 🟢 On Track | Projected end spend = 98-105% of budget |
| 🟡 Under-delivering | Projected end spend < 98% of budget |
| 🔵 Over-delivering | Projected end spend > 105% of budget |
| 🔴 Not Spending | Zero spend after 3+ days |

---
## 🏢 Account Overview
Shows **all orders for the current month** regardless of status (Delivering + Ended + Inactive). This gives you the complete picture of account-level spend.
    """)
    st.info("👈 Upload your file in the **sidebar** to begin!")
