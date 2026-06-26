import streamlit as st
import pandas as pd
from datetime import datetime
import numpy as np
import re
from io import BytesIO

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

# ═══════════════════════════════════════════════════════════════
# DASHBOARD EXPORT FUNCTIONS
# ═══════════════════════════════════════════════════════════════
def generate_html_report(title, acct_summary_df, order_df, perf_df, summary_metrics):
    html = f"""
