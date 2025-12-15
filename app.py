import streamlit as st
import pandas as pd
import plotly.express as px
import os 
import pandas.api.types
import json
import gspread
from google.oauth2.service_account import Credentials
from auth import (
    check_password,
    get_user_info,
    change_password_db,
    user_manager_interface
)
from datetime import datetime

# --- Configuração Inicial ---
st.set_page_config(
    page_title="Dashboard de Desempenho de Agentes",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Mapeamento de meses
MESES_ORDER = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", 
               "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
MESES = {month: f"{month}.csv" for month in MESES_ORDER}


# Inicialização de variáveis de estado
if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = None
if 'role' not in st.session_state:
    st.session_state['role'] = None
if 'primeiro_acesso' not in st.session_state:
    st.session_state['primeiro_acesso'] = False
    
# --- Funções Auxiliares ---

def format_time(minutes):
    """Converte minutos decimais para o formato MM:SS."""
    if pd.isna(minutes) or minutes is None or minutes == 0:
        return '00:00'
    try:
        total_seconds = round(minutes * 60)
        mins = total_seconds // 60
        secs = total_seconds % 60
        return f'{int(mins):02d}:{int(secs):02d}'
    except:
        return 'N/A'

def apply_formatting(df):
    """Aplica formatação condicional."""
    df_copy = df.copy()
    time_cols = [col for col in ['TMA', 'TME', 'TMIA', 'TMIC'] if col in df_copy.columns]
    for col in time_cols:
        if pd.api.types.is_numeric_dtype(df_copy[col]):
             df_copy[col] = df_copy[col].apply(format_time)
    
    if 'FCR' in df_copy.columns and pd.api.types.is_numeric_dtype(df_copy['FCR']):
        df_copy['FCR'] = (df_copy['FCR'] * 100).map('{:.2f}%'.format)

    if 'Satisfacao' in df_copy.columns and pd.api.types.is_numeric_dtype(df_copy['Satisfacao']):
        df_copy['Satisfacao'] = (df_copy['Satisfacao'] / 5.0 * 100).map('{:.2f}%'.format)
        
    return df_copy

# --- Funções de Carregamento de Dados (COM LIMPEZA DE NOMES) ---
@st.cache_data(show_spinner="Carregando dados...")
def load_and_preprocess_data(file_name):
    DATA_FOLDER = 'data' 
    file_path = os.path.join(DATA_FOLDER, file_name)
    
    if not os.path.exists(file_path):
        if os.path.exists(DATA_FOLDER):
            for f in os.listdir(DATA_FOLDER):
                if f.lower() == file_name.lower():
                    file_path = os.path.join(DATA_FOLDER, f)
                    break
    
    if not os.path.exists(file_path):
        return pd.DataFrame()

    try:
        df = pd.read_csv(file_path, sep=';', encoding='latin1', engine='python')
        if df.shape[1] < 2:
             df = pd.read_csv(file_path, sep=',', encoding='utf-8', engine='python')
    except Exception as e:
        st.error(f"Erro ao ler {file_name}: {e}")
        return pd.DataFrame()

    cols = df.columns.str.strip().str.upper()
    df.columns = cols.str.replace('[^A-Z0-9_]+', '', regex=True) 
    
    rename_mapping = {
        'NOM_AGENTE': 'Agente', 'NOMAGENTE': 'Agente',
        'QTDATENDIMENTO': 'QTD Atendimento', 
        'SATISFACAO': 'Satisfacao', 
        'QTDSATISFACAO': 'QTD Avaliacoes',
        'TMA': 'TMA', 'FCR': 'FCR', 'NPS': 'NPS',
        'TMIA': 'TMIA', 'TME': 'TME', 'TMIC': 'TMIC'
    }
    df = df.rename(columns=rename_mapping)

    # 🚨 LIMPEZA CRÍTICA DE NOMES 🚨
    # Isso remove espaços extras e garante que o login bata com o CSV
    if 'Agente' in df.columns:
        df['Agente'] = df['Agente'].astype(str).str.strip()

    def time_to_minutes(time_str):
        if pd.isna(time_str) or str(time_str).strip() == '': return 0.0
        try:
            parts = str(time_str).split(':')
            if len(parts) == 3: h, m, s = map(float, parts); return (h*60)+m+(s/60)
            elif len(parts) == 2: m, s = map(float, parts); return m+(s/60)
            else: return 0.0
        except: return 0.0

    for col in ['TMA', 'TME', 'TMIA', 'TMIC']:
        if col in df.columns:
             if df[col].dtype == object:
                df[col] = df[col].apply(time_to_minutes)

    for col in ['FCR', 'Satisfacao', 'NPS']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('%', '', regex=False).str.replace(',', '.', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    if 'FCR' in df.columns: 
        if df['FCR'].mean() > 1: df['FCR'] = df['FCR'] / 100
    if 'Satisfacao' in df.columns: 
        if df['Satisfacao'].max() > 5: df['Satisfacao'] = df['Satisfacao'] / 100 * 5 
    
    return df

@st.cache_data(show_spinner="Carregando histórico...")
def load_all_history_data():
    DATA_FOLDER = 'data' 
    df_list = []
    if not os.path.exists(DATA_FOLDER): return pd.DataFrame()
    for filename in os.listdir(DATA_FOLDER):
        if filename.endswith(".csv"):
            try:
                path = os.path.join(DATA_FOLDER, filename)
                df_temp = pd.read_csv(path, sep=';', encoding='latin1', engine='python')
                if df_temp.shape[1] < 2: 
                    df_temp = pd.read_csv(path, sep=',', encoding='utf-8', engine='python')

                month_name = filename.replace('.csv', '').capitalize()
                if month_name.lower() not in MESES: continue 
                
                df_temp.columns = df_temp.columns.str.strip().str.upper().str.replace('[^A-Z0-9_]+', '', regex=True) 
                df_temp = df_temp.rename(columns={'NOM_AGENTE': 'Agente', 'NOMAGENTE': 'Agente', 'QTDATENDIMENTO': 'QTD Atendimento', 'SATISFACAO': 'Satisfacao', 'QTDSATISFACAO': 'QTD Avaliacoes'})
                
                # 🚨 LIMPEZA DE NOMES NO HISTÓRICO 🚨
                if 'Agente' in df_temp.columns:
                    df_temp['Agente'] = df_temp['Agente'].astype(str).str.strip()

                df_temp['Mês'] = month_name
                df_temp['MonthSort'] = MESES_ORDER.index(month_name.lower())
                
                if not df_temp.empty and 'Agente' in df_temp.columns: df_list.append(df_temp)
            except: continue
    if not df_list: return pd.DataFrame()
    df = pd.concat(df_list, ignore_index=True)
    
    def time_to_minutes(time_str):
        if pd.isna(time_str): return 0.0
        try: parts = str(time_str).split(':'); return float(parts[0])*60 + float(parts[1]) if len(parts)==2 else 0.0
        except: return 0.0
    
    for col in ['TMA', 'TME', 'TMIA', 'TMIC']:
        if col in df.columns and df[col].dtype == object: 
            df[col] = df[col].apply(time_to_minutes)
    
    for col in ['FCR', 'Satisfacao']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace('%','').str.replace(',','.'), errors='coerce')
            
    if 'FCR' in df.columns: 
        if df['FCR'].mean() > 1: df['FCR'] = df['FCR'] / 100
    if 'Satisfacao' in df.columns: 
        if df['Satisfacao'].max() > 5: df['Satisfacao'] = df['Satisfacao'] / 100 * 5 
        
    return df

@st.cache_data(show_spinner="Carregando detalhes diários...")
def load_daily_data(selected_month_name, agente_name=None):
    month_folder = selected_month_name.lower()
    DATA_FOLDER = os.path.join('data', month_folder)
    df_list = []
    if not os.path.exists(DATA_FOLDER): return pd.DataFrame()
    for filename in os.listdir(DATA_FOLDER):
        if filename.endswith(".csv"):
            try:
                path = os.path.join(DATA_FOLDER, filename)
                df_temp = pd.read_csv(path, sep=';', encoding='latin1', engine='python')
                if df_temp.shape[1] < 2: 
                    df_temp = pd.read_csv(path, sep=',', encoding='utf-8', engine='python')

                df_temp.columns = df_temp.columns.str.strip().str.upper().str.replace('[^A-Z0-9_]+', '', regex=True) 
                df_temp = df_temp.rename(columns={'NOM_AGENTE': 'Agente', 'NOMAGENTE': 'Agente', 'QTDATENDIMENTO': 'QTD Atendimento', 'SATISFACAO': 'Satisfacao', 'QTDSATISFACAO': 'QTD Avaliacoes'})
                
                # 🚨 LIMPEZA DE NOMES NO DIÁRIO 🚨
                if 'Agente' in df_temp.columns:
                    df_temp['Agente'] = df_temp['Agente'].astype(str).str.strip()

                df_temp['Dia'] = filename.replace('.csv', '').replace('.', '/')
                df_temp['DaySort'] = int(filename.split('.')[0])
                
                month_idx = MESES_ORDER.index(month_folder) + 1
                year = datetime.now().year
                df_temp['Data'] = pd.to_datetime({'year': [year]*len(df_temp), 'month': [month_idx]*len(df_temp), 'day': df_temp['DaySort']}, errors='coerce')

                if agente_name and 'Agente' in df_temp.columns: df_temp = df_temp[df_temp['Agente'] == agente_name]
                if not df_temp.empty: df_list.append(df_temp)
            except: continue
    if not df_list: return pd.DataFrame()
    df = pd.concat(df_list, ignore_index=True)
    
    for col in ['FCR', 'Satisfacao']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace('%','').str.replace(',','.'), errors='coerce')
    if 'FCR' in df.columns: 
        if df['FCR'].mean() > 1: df['FCR'] = df['FCR'] / 100
    if 'Satisfacao' in df.columns: 
        if df['Satisfacao'].max() > 5: df['Satisfacao'] = df['Satisfacao'] / 100 * 5 
    return df

@st.cache_data(show_spinner="Carregando avaliações...")
def load_evaluation_data(selected_month_name, agente_name):
    EVAL_FOLDER = os.path.join('data', selected_month_name.lower(), 'notas')
    df_list = []
    if not os.path.exists(EVAL_FOLDER): return pd.DataFrame()
    for filename in os.listdir(EVAL_FOLDER):
        if filename.endswith(".csv"):
            try:
                path = os.path.join(EVAL_FOLDER, filename)
                df_temp = pd.read_csv(path, sep=';', encoding='latin1', engine='python')
                if df_temp.shape[1] < 2: df_temp = pd.read_csv(path, sep=',', encoding='utf-8', engine='python')

                df_temp.columns = df_temp.columns.str.strip().str.upper().str.replace('[^A-Z0-9_]+', '', regex=True)
                df_temp = df_temp.rename(columns={'NOM_AGENTE': 'Agente', 'NUM_PROTOCOLO': 'Protocolo', 'NOM_VALOR': 'Nota'})
                
                # 🚨 LIMPEZA DE NOMES NAS AVALIAÇÕES 🚨
                if 'Agente' in df_temp.columns:
                    df_temp['Agente'] = df_temp['Agente'].astype(str).str.strip()

                df_temp['Dia'] = filename.replace('.csv', '').replace('.', '/')
                df_temp['DaySort'] = int(filename.split('.')[0])
                if 'Agente' in df_temp.columns: df_temp = df_temp[df_temp['Agente'] == agente_name]
                if not df_temp.empty: df_list.append(df_temp)
            except: continue
    return pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()

@st.cache_data(show_spinner="Carregando Ranking Semanal...")
def load_ranking_data(filename):
    path = os.path.join('data', 'semana', filename)
    if not os.path.exists(path): return pd.DataFrame()
    try:
        df = pd.read_csv(path, sep=';', encoding='latin1', engine='python')
        if df.shape[1] < 2: df = pd.read_csv(path, sep=',', encoding='utf-8', engine='python')
        
        df.columns = df.columns.str.strip().str.upper().str.replace('[^A-Z0-9_]+', '', regex=True)
        df = df.rename(columns={'NOM_AGENTE': 'Agente', 'QTDATENDIMENTO': 'QTD Atendimento', 'SATISFACAO': 'Satisfacao'})
        
        # 🚨 LIMPEZA DE NOMES NO RANKING 🚨
        if 'Agente' in df.columns:
            df['Agente'] = df['Agente'].astype(str).str.strip()

        for col in ['FCR', 'Satisfacao']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace('%','').str.replace(',','.'), errors='coerce')
        if 'FCR' in df.columns and df['FCR'].mean() > 1: df['FCR'] = df['FCR'] / 100
        if 'Satisfacao' in df.columns and df['Satisfacao'].max() > 5: df['Satisfacao'] = df['Satisfacao'] / 100 * 5 
        
        def time_to_minutes(time_str):
            if pd.isna(time_str): return 0.0
            try: parts = str(time_str).split(':'); return float(parts[0])*60 + float(parts[1]) if len(parts)==2 else 0.0
            except: return 0.0
        for col in ['TMA', 'TMIA']:
            if col in df.columns: df[col] = df[col].apply(time_to_minutes)
            
        return df
    except: return pd.DataFrame()

# -------------------------------------------------------------
# 🤖 FUNÇÕES DO FAQ (Google Sheets)
# -------------------------------------------------------------

def get_gspread_client():
    """Conecta ao Google Sheets usando as credenciais do secrets.toml"""
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["google_credentials"])
    # Correção obrigatória para Windows
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_data(ttl=300, show_spinner="Carregando FAQ...")
def load_faq_data_secure():
    try:
        client = get_gspread_client()
        try:
            sh = client.open("BaseFAQ")
        except:
            sh = client.open_by_url(st.secrets["spreadsheet_url"])
            
        worksheet = sh.sheet1 
        data = worksheet.get_all_records()
        if not data: return pd.DataFrame()
        return pd.DataFrame(data).astype(str)
    except Exception as e:
        print(f"Erro ao carregar FAQ: {e}") 
        return pd.DataFrame()

def salvar_nova_pergunta(pergunta_texto):
    try:
        client = get_gspread_client()
        try:
            sh = client.open("BaseFAQ")
        except:
            sh = client.open_by_url(st.secrets["spreadsheet_url"])
            
        try:
            worksheet = sh.worksheet("Novas_Perguntas")
        except:
            st.error("Erro: Crie uma aba chamada 'Novas_Perguntas' na sua planilha!")
            return False
            
        quem = st.session_state.get('username', 'Anônimo')
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        worksheet.append_row([agora, pergunta_texto, quem])
        return True
    except Exception as e:
        st.error(f"Erro ao salvar pergunta: {e}")
        return False

# --- Funções de Display (KPIs e Gráficos) ---
def display_kpi(df):
    kpi_cols = {'QTD Atendimento': 'sum', 'TMA': 'mean', 'FCR': 'mean', 'Satisfacao': 'mean', 'NPS': 'mean', 'QTD Avaliacoes': 'sum'}
    valid = {c: a for c, a in kpi_cols.items() if c in df.columns}
    if not valid: return
    data = df.agg(valid).reset_index().T; data.columns = data.iloc[0]; data = data[1:]
    cols = st.columns(6)
    def show(col, lbl, unit=""):
        if lbl in data.columns and not pd.isna(data[lbl].iloc[0]):
            val = data[lbl].iloc[0]
            if lbl == 'TMA': val_str = format_time(val)
            elif lbl in ['FCR', 'Satisfacao']: val_str = f"{val/5:.2%}" if lbl=='Satisfacao' else f"{val:.2%}"
            else: val_str = f"{val:.0f}"
            col.metric(lbl, val_str)
    show(cols[0], "QTD Atendimento"); show(cols[1], "TMA"); show(cols[2], "FCR"); show(cols[3], "Satisfacao"); show(cols[4], "NPS"); show(cols[5], "QTD Avaliacoes")
    st.markdown("---")

def display_monthly_history(agente_name=None):
    if agente_name: st.header("📈 Histórico (Meu)")
    else: st.header("📈 Histórico (Geral)")
    df = load_all_history_data()
    if df.empty: st.info("Sem histórico."); return
    if agente_name: df = df[df['Agente'] == agente_name]
    if df.empty: st.info("Sem dados."); return
    
    agg = df.groupby(['MonthSort', 'Mês'], as_index=False).agg({'Satisfacao': 'mean', 'FCR': 'mean'})
    agg = agg.sort_values('MonthSort')
    
    c1, c2 = st.columns(2)
    if 'Satisfacao' in agg.columns: c1.plotly_chart(px.line(agg, x='Mês', y='Satisfacao', title='Satisfação', range_y=[0,5], markers=True), use_container_width=True)
    if 'FCR' in agg.columns: c2.plotly_chart(px.line(agg, x='Mês', y='FCR', title='FCR', range_y=[0,1], markers=True), use_container_width=True)
    st.markdown("---")

def display_daily_detail(month, agente_name=None):
    st.header(f"📅 Dia a Dia ({month})")
    df = load_daily_data(month, agente_name)
    if df.empty: st.info("Sem dados diários."); return
    
    grp_cols = ['DaySort', 'Dia']
    if not agente_name: grp_cols.append('Agente')
    
    agg = df.groupby(grp_cols, as_index=False).agg({'Satisfacao': 'mean', 'FCR': 'mean'}).sort_values('DaySort')
    
    c1, c2 = st.columns(2)
    color = 'Agente' if not agente_name else None
    if 'Satisfacao' in agg.columns: c1.plotly_chart(px.line(agg, x='Dia', y='Satisfacao', title='Satisfação Diária', range_y=[0,5], markers=True, color=color), use_container_width=True)
    if 'FCR' in agg.columns: c2.plotly_chart(px.line(agg, x='Dia', y='FCR', title='FCR Diário', range_y=[0,1], markers=True, color=color), use_container_width=True)
    
    st.dataframe(apply_formatting(agg.drop(columns=['DaySort'])), use_container_width=True)
    st.markdown("---")

def display_evaluation_details(month, agente_name):
    st.header("⭐ Avaliações (Detalhe)")
    df = load_evaluation_data(month, agente_name)
    if df.empty: st.info("Nenhuma avaliação."); return
    st.dataframe(df[['Dia', 'Protocolo', 'Nota']].sort_values('Dia'), use_container_width=True, hide_index=True)
    st.markdown("---")

# --- UI DE LOGIN E ADMIN ---
def login_form():
    st.sidebar.title("🔒 Login")
    with st.sidebar.form("login"):
        user = st.text_input("Usuário")
        pwd = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            if check_password(user, pwd):
                u = get_user_info(user)
                st.session_state.update({'authenticated': True, 'username': user, 'role': u.get('role'), 'agente_name': u.get('agente'), 'primeiro_acesso': u.get('primeiro_acesso')})
                st.rerun()
            else: st.sidebar.error("Dados incorretos.")

def main():
    st.sidebar.markdown("---")
    DATA_FOLDER = 'data'
    files = [f.replace('.csv','').capitalize() for f in os.listdir(DATA_FOLDER) if f.endswith('.csv') and f.lower() in MESES]
    files.sort(key=lambda x: MESES_ORDER.index(x.lower()))
    
    if 'selected_month_name' not in st.session_state:
        st.session_state['selected_month_name'] = files[-1] if files else "Janeiro"
    
    if files:
        sel = st.sidebar.selectbox("Mês:", files, index=files.index(st.session_state['selected_month_name']) if st.session_state['selected_month_name'] in files else 0)
        st.session_state['selected_month_name'] = sel
    
    # Carrega Mês Atual
    df_month = load_and_preprocess_data(MESES.get(st.session_state['selected_month_name'].lower()))

    if st.session_state['authenticated']:
        if st.sidebar.button("Sair"):
            st.session_state.clear(); st.rerun()
        
        st.sidebar.markdown("---")
        st.sidebar.caption("Desenvolvido por Vinicios Oliveira")

        if st.session_state['primeiro_acesso']:
            st.warning("Altere sua senha no menu lateral."); return

        agente = st.session_state['agente_name']
        
        if st.session_state['role'] == 'admin':
            menu = st.sidebar.radio("Menu", ["Dashboard", "Gerenciar Usuários"])
            if menu == "Dashboard":
                st.title(f"Visão Global - {st.session_state['selected_month_name']}")
                
                # Filtros Admin
                agent_list = ["Todos"]
                if not df_month.empty and 'Agente' in df_month.columns:
                    unique_agents = df_month['Agente'].dropna().astype(str).unique()
                    sorted_agents = sorted([ag for ag in unique_agents if ag.strip() != ''])
                    agent_list += sorted_agents
                sel_agent = st.sidebar.selectbox("Agente:", agent_list)
                
                # Filtro Data
                is_date_available = False
                df_daily_full = load_daily_data(st.session_state['selected_month_name'])
                if not df_daily_full.empty and 'Data' in df_daily_full.columns: is_date_available = True
                sel_dates = None
                if is_date_available:
                    try:
                        valid_dates = df_daily_full['Data'].dropna()
                        if not valid_dates.empty:
                            min_d, max_d = valid_dates.min().date(), valid_dates.max().date()
                            sel_dates = st.sidebar.date_input("Período:", [min_d, max_d], min_value=min_d, max_value=max_d)
                    except: pass 

                # Aplica Filtros
                df_view = df_month.copy()
                df_daily_view = df_daily_full.copy()

                if sel_agent != "Todos":
                    if not df_view.empty: df_view = df_view[df_view['Agente'] == sel_agent]
                    if not df_daily_view.empty: df_daily_view = df_daily_view[df_daily_view['Agente'] == sel_agent]
                
                if is_date_available and sel_dates and isinstance(sel_dates, tuple) and len(sel_dates) == 2:
                    df_daily_view = df_daily_view[(df_daily_view['Data'].dt.date >= sel_dates[0]) & (df_daily_view['Data'].dt.date <= sel_dates[1])]

                display_kpi(df_view)
                
                # Rankings
                if sel_agent == "Todos":
                    st.subheader("🏆 Rankings (Semanal)")
                    c1, c2 = st.columns(2)
                    df_rank_atual = load_ranking_data("ranking_semanal_atual.csv")
                    df_rank_ant = load_ranking_data("ranking_semanal_anterior.csv")
                    
                    if not df_rank_atual.empty: 
                        c1.markdown("##### 🥇 Semana Atual"); c1.dataframe(df_rank_atual[['Agente','Satisfacao','FCR']].head(5), hide_index=True)
                    if not df_rank_ant.empty: 
                        c2.markdown("##### 🥈 Semana Anterior"); c2.dataframe(df_rank_ant[['Agente','Satisfacao','FCR']].head(5), hide_index=True)
                    st.markdown("---")

                display_daily_detail(st.session_state['selected_month_name'])
            else:
                hist = load_all_history_data()
                user_manager_interface(hist)
        else:
            st.title(f"Dashboard - {agente}")
            df_agente = df_month[df_month['Agente'] == agente] if not df_month.empty else pd.DataFrame()
            if not df_agente.empty:
                display_kpi(df_agente)
                st.dataframe(apply_formatting(df_agente), use_container_width=True)
            else: st.warning("Sem dados no mês.")
            
            display_monthly_history(agente)
            display_daily_detail(st.session_state['selected_month_name'], agente)
            display_evaluation_details(st.session_state['selected_month_name'], agente)

    else:
        st.title("Dashboard de Desempenho")
        st.info("Faça login para acessar.")
        st.write("Atenção: O administrador inicial tem login: `admin` e senha: `12345`.")
        st.write("Atenção: O Agente inicial tem login: `seu nome` e senha: `12345`.")
        
        # 🚨 --- LINKS ÚTEIS --- 🚨
        st.markdown("---")
        st.subheader("🔗 Links Úteis")
        st.markdown("### 👉 [Abrir Planilha de senhas](https://docs.google.com/spreadsheets/d/1uxeEgHUEeDI6XOOh6UvRQeDjVYXl3ZP8Za3SbI2zVUs/edit?pli=1&gid=1807741321#gid=1807741321)")
        st.markdown("### 👉 [Abrir Planilha de ramais](https://docs.google.com/spreadsheets/d/19_9J68jh0ox4naCgJMKl3flue45DSUFd/edit?pli=1&gid=1360104800#gid=1360104800)")
        st.markdown("### 👉 [Abrir Planilha de escala geral](https://docs.google.com/spreadsheets/d/1eV8xtHURvypPZEOYZHAIfSFPzDHeFFow1pHzHaVZlE4/edit?gid=1626029189#gid=1626029189)")
        st.markdown("### 👉 [Abrir Planilha de escala Call Center](https://docs.google.com/spreadsheets/d/1fqt7MH738ovcd2DeLz8C3FFZq9IuyyHF/edit?gid=2064563243#gid=2064563243)")
        
        # 🚨 --- FAQ e NOVA PERGUNTA --- 🚨
        st.markdown("---")
        st.subheader("❓ Perguntas Frequentes (FAQ)")
        df_faq = load_faq_data_secure()
        
        if not df_faq.empty:
            termo_busca = st.text_input("🔍 Buscar no FAQ", placeholder="Digite sua dúvida...")
            if termo_busca:
                filtro = (
                    df_faq['Pergunta'].str.contains(termo_busca, case=False, na=False) |
                    df_faq['Resposta'].str.contains(termo_busca, case=False, na=False)
                )
                resultados = df_faq[filtro]
            else:
                resultados = df_faq 

            if not resultados.empty:
                for i, r in resultados.iterrows():
                    p = r.get('Pergunta') or r.get('pergunta') or '?'
                    resp = r.get('Resposta') or r.get('resposta') or ''
                    with st.expander(f"**{p}**"): st.write(resp)
            else:
                st.warning("Nenhum resultado encontrado.")
                
            with st.expander("📝 Não encontrou? Envie sua pergunta!"):
                with st.form("form_nova_pergunta"):
                    nova_p = st.text_area("Digite sua dúvida aqui:")
                    enviar = st.form_submit_button("Enviar para o suporte")
                    if enviar and nova_p:
                        if salvar_nova_pergunta(nova_p):
                            st.success("Pergunta enviada com sucesso!")
                        else:
                            st.error("Erro ao enviar. Tente novamente.")
        else:
            st.info("Nenhuma pergunta encontrada na base.")

        login_form()
        st.sidebar.markdown("---")
        st.sidebar.caption("Desenvolvido por Vinicios Oliveira")

if __name__ == '__main__':
    main()
