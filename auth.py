import streamlit as st
import pandas as pd
import plotly.express as px
import os 
import pandas.api.types
from auth import (
    check_password,
    get_user_info,
    change_password_db,
    user_manager_interface
)
import datetime # Importa datetime para o calendário

# --- Configuração Inicial ---
st.set_page_config(
    page_title="Dashboard de Desempenho de Agentes",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Mapeamento de meses (para facilitar a identificação dos arquivos e ordenação)
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
    
# --- Funções Auxiliares de Formatação ---

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
    """Aplica formatação condicional (Tempo, Percentual) ao DataFrame."""
    df_copy = df.copy()
    
    # Colunas de Tempo
    time_cols = [col for col in ['TMA', 'TME', 'TMIA', 'TMIC'] if col in df_copy.columns]
    for col in time_cols:
         # Verifica se a coluna é numérica antes de aplicar format_time
        if pd.api.types.is_numeric_dtype(df_copy[col]):
             df_copy[col] = df_copy[col].apply(format_time)

    # Colunas de Porcentagem (FCR e Satisfacao)
    
    if 'FCR' in df_copy.columns and pd.api.types.is_numeric_dtype(df_copy['FCR']):
        df_copy['FCR'] = (df_copy['FCR'] * 100).map('{:.2f}%'.format)

    if 'Satisfacao' in df_copy.columns and pd.api.types.is_numeric_dtype(df_copy['Satisfacao']):
        # Converte a métrica de 0-5 para 0-100%
        df_copy['Satisfacao'] = (df_copy['Satisfacao'] / 5.0 * 100).map('{:.2f}%'.format)
        
    return df_copy


# --- Funções de Carregamento e Tratamento de Dados ---
# Função principal: Carrega UM mês (usada para o painel principal)
@st.cache_data(show_spinner="Carregando dados do mês selecionado...")
def load_and_preprocess_data(file_name):
    """Carrega o CSV específico do mês na pasta 'data/'."""
    
    DATA_FOLDER = 'data' 
    file_path = os.path.join(DATA_FOLDER, file_name)
    
    if not os.path.exists(file_path):
        st.warning(f"Arquivo de dados '{file_name}' não encontrado na pasta '{DATA_FOLDER}/'.")
        return pd.DataFrame()
        
    try:
        df = pd.read_csv(file_path, encoding='utf-8', engine='python')
    except Exception as e:
        st.error(f"Erro ao ler o arquivo {file_name}: {e}")
        return pd.DataFrame()

    # LIMPEZA E RENOMEAÇÃO DE COLUNAS
    cols = df.columns.str.strip().str.upper()
    df.columns = cols.str.replace('[^A-Z0-9_]+', '', regex=True) 

    rename_mapping = {
        'NOM_AGENTE': 'Agente',
        'QTDATENDIMENTO': 'QTD Atendimento', # Corrigido (sem S)
        'SATISFACAO': 'Satisfacao',
        'QTDSATISFACAO': 'QTD Avaliacoes',
    }
    df = df.rename(columns=rename_mapping)

    EXPECTED_COLS = {
        'QTD Atendimento', 'TMA', 'TME', 'TMIA', 'TMIC', 
        'FCR', 'Satisfacao', 'NPS', 'QTD Avaliacoes', 'Agente'
    }
    
    missing_cols = EXPECTED_COLS - set(df.columns)
    if missing_cols:
         st.warning(f"As seguintes colunas esperadas não foram encontradas após a limpeza: {missing_cols}")

    # Conversão de colunas de tempo
    def time_to_minutes(time_str):
        if pd.isna(time_str) or time_str == '': return 0.0
        try:
            parts = str(time_str).split(':')
            if len(parts) == 3: # Formato HH:MM:SS
                hours, minutes, seconds = map(float, parts)
                return (hours * 60) + minutes + seconds / 60
            elif len(parts) == 2: # Formato MM:SS
                minutes, seconds = map(float, parts)
                return minutes + seconds / 60
            else:
                return 0.0
        except:
            return 0.0

    time_cols = ['TMA', 'TME', 'TMIA', 'TMIC']
    for col in time_cols:
        if col in df.columns:
             if not df[col].isnull().all():
                  df[col] = df[col].apply(time_to_minutes)


    # Conversão de FCR, Satisfacao e NPS (Garantindo que são numéricos)
    for col in ['FCR', 'Satisfacao', 'NPS']:
        if col in df.columns:
            current_col_name = col
            df[current_col_name] = df[current_col_name].astype(str).str.replace('%', '', regex=False).str.replace(',', '.', regex=False)
            df[current_col_name] = pd.to_numeric(df[current_col_name], errors='coerce')
    
    # Normaliza FCR (0-1) e Satisfação (0-5)
    if 'FCR' in df.columns and pd.api.types.is_numeric_dtype(df['FCR']):
        df['FCR'] = df['FCR'] / 100
    
    if 'Satisfacao' in df.columns and pd.api.types.is_numeric_dtype(df['Satisfacao']):
        df['Satisfacao'] = df['Satisfacao'] / 100 * 5 
    
    return df

# --- Função 2: Carrega TODOS os dados (para Histórico e Admin) ---
@st.cache_data(show_spinner="Carregando histórico completo...")
def load_all_history_data():
    """Carrega TODOS os CSVs de TODOS os meses disponíveis na pasta 'data/' para o histórico."""
    DATA_FOLDER = 'data' 
    df_list = []
    
    if not os.path.exists(DATA_FOLDER):
        return pd.DataFrame()
        
    # 1. Leitura e Combinação dos Arquivos
    for filename in os.listdir(DATA_FOLDER):
        if filename.endswith(".csv"):
            path = os.path.join(DATA_FOLDER, filename)
            try:
                df_temp = pd.read_csv(path, encoding='utf-8', engine='python')
                
                # Adiciona coluna de mês e ordenação
                month_name = filename.replace('.csv', '').capitalize()
                month_name_lower = month_name.lower()
                if month_name_lower not in MESES: continue 
                
                # TRATAMENTO DE COLUNAS (ANTES de adicionar Mês/MonthSort)
                df_temp.columns = df_temp.columns.str.strip().str.upper().str.replace('[^A-Z0-9_]+', '', regex=True) 
                rename_mapping_temp = {
                    'NOM_AGENTE': 'Agente', 'QTDATENDIMENTO': 'QTD Atendimento', # Corrigido (sem S)
                    'SATISFACAO': 'Satisfacao', 'QTDSATISFACAO': 'QTD Avaliacoes',
                }
                df_temp = df_temp.rename(columns=rename_mapping_temp)
                
                # Adiciona Mês e MonthSort DEPOIS da limpeza
                df_temp['Mês'] = month_name
                df_temp['MonthSort'] = MESES_ORDER.index(month_name_lower)

                if df_temp.empty or 'Agente' not in df_temp.columns: continue
                
                df_list.append(df_temp)
            except Exception as e:
                continue

    if not df_list: return pd.DataFrame()
    df = pd.concat(df_list, ignore_index=True)

    # --- Tratamento Final (Geral para Histórico) ---
    time_cols = ['TMA', 'TME', 'TMIA', 'TMIC']
    def time_to_minutes(time_str):
        if pd.isna(time_str) or time_str == '': return 0.0
        try: parts = str(time_str).split(':')
        except: return 0.0
        try:
            if len(parts) == 3: h, m, s = map(float, parts); return (h * 60) + m + s / 60
            elif len(parts) == 2: m, s = map(float, parts); return m + s / 60
            else: return 0.0
        except: return 0.0
    for col in time_cols:
        if col in df.columns and not df[col].isnull().all(): 
             df[col] = df[col].apply(time_to_minutes)
    for col in ['FCR', 'Satisfacao', 'NPS']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('%', '', regex=False).str.replace(',', '.', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'FCR' in df.columns and pd.api.types.is_numeric_dtype(df['FCR']): df['FCR'] = df['FCR'] / 100
    if 'Satisfacao' in df.columns and pd.api.types.is_numeric_dtype(df['Satisfacao']): df['Satisfacao'] = df['Satisfacao'] / 100 * 5 
    
    return df

# --- Função 3: Carrega os dados DIÁRIOS de uma subpasta ---
@st.cache_data(show_spinner="Carregando detalhes diários...")
def load_daily_data(selected_month_name, agente_name=None):
    """Carrega todos os CSVs da subpasta 'data/[mês]' e filtra pelo agente (se fornecido)."""
    
    month_folder_lower = selected_month_name.lower()
    DATA_FOLDER = os.path.join('data', month_folder_lower) # Caminho: data/outubro
    
    df_list = []
    
    if not os.path.exists(DATA_FOLDER) or not os.path.isdir(DATA_FOLDER):
        return pd.DataFrame()
        
    for filename in os.listdir(DATA_FOLDER):
        if filename.endswith(".csv"):
            path = os.path.join(DATA_FOLDER, filename)
            try:
                df_temp = pd.read_csv(path, encoding='utf-8', engine='python')
                
                # Limpa colunas ANTES de adicionar Dia/DaySort
                df_temp.columns = df_temp.columns.str.strip().str.upper().str.replace('[^A-Z0-9_]+', '', regex=True) 
                rename_mapping_temp = {
                    'NOM_AGENTE': 'Agente', 'QTDATENDIMENTO': 'QTD Atendimento', # Corrigido (sem S)
                    'SATISFACAO': 'Satisfacao', 'QTDSATISFACAO': 'QTD Avaliacoes',
                }
                df_temp = df_temp.rename(columns=rename_mapping_temp)

                # Adiciona coluna de Dia (01.10.csv -> 01/10)
                day_month_str = filename.replace('.csv', '').replace('.', '/')
                df_temp['Dia'] = day_month_str 
                # Adiciona ordenação (01.10.csv -> 1)
                df_temp['DaySort'] = int(filename.split('.')[0])
                
                # Adiciona a coluna de Data real (para o filtro de calendário)
                month_num_index = MESES_ORDER.index(month_folder_lower)
                month_num = month_num_index + 1
                year = datetime.date.today().year # Usa o ano atual
                
                # Cria um DataFrame de datas para garantir que a conversão funcione
                date_components = pd.DataFrame({
                    'year': [year] * len(df_temp),
                    'month': [month_num] * len(df_temp),
                    'day': df_temp['DaySort']
                })
                df_temp['Data'] = pd.to_datetime(date_components, errors='coerce')
                
                # Filtra pelo agente (se fornecido)
                if agente_name and 'Agente' in df_temp.columns:
                    df_temp = df_temp[df_temp['Agente'] == agente_name]
                
                if df_temp.empty: 
                    continue
                
                df_list.append(df_temp)
            except Exception as e:
                st.warning(f"Erro ao processar o arquivo diário {filename}: {e}")
                continue

    if not df_list: return pd.DataFrame()
    df = pd.concat(df_list, ignore_index=True)

    # Tratamento de tipos (copiado de load_all_history_data)
    time_cols = ['TMA', 'TME', 'TMIA', 'TMIC']
    def time_to_minutes(time_str):
        if pd.isna(time_str) or time_str == '': return 0.0
        try: parts = str(time_str).split(':')
        except: return 0.0
        try:
            if len(parts) == 3: h, m, s = map(float, parts); return (h * 60) + m + s / 60
            elif len(parts) == 2: m, s = map(float, parts); return m + s / 60
            else: return 0.0
        except: return 0.0
    for col in time_cols:
        if col in df.columns and not df[col].isnull().all(): 
             df[col] = df[col].apply(time_to_minutes)
    for col in ['FCR', 'Satisfacao', 'NPS']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('%', '', regex=False).str.replace(',', '.', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'FCR' in df.columns and pd.api.types.is_numeric_dtype(df['FCR']): df['FCR'] = df['FCR'] / 100
    if 'Satisfacao' in df.columns and pd.api.types.is_numeric_dtype(df['Satisfacao']): df['Satisfacao'] = df['Satisfacao'] / 100 * 5 
    
    return df

# --- Função 4: Carrega dados do Ranking Semanal ---
@st.cache_data(show_spinner="Carregando dados do ranking semanal...")
def load_ranking_data(filename): # Recebe o nome do arquivo
    """Carrega um arquivo CSV de ranking da pasta 'data/semana/'."""
    
    RANKING_FILE_PATH = os.path.join('data', 'semana', filename)
    
    if not os.path.exists(RANKING_FILE_PATH):
        # Retorna um DF vazio, o erro será tratado na função de exibição
        return pd.DataFrame()
        
    try:
        df = pd.read_csv(RANKING_FILE_PATH, encoding='utf-8', engine='python')
    except Exception as e:
        st.error(f"Erro ao ler o arquivo de ranking {RANKING_FILE_PATH}: {e}")
        return pd.DataFrame()

    # LIMPEZA E RENOMEAÇÃO DE COLUNAS
    cols = df.columns.str.strip().str.upper()
    df.columns = cols.str.replace('[^A-Z0-9_]+', '', regex=True) 

    rename_mapping = {
        'NOM_AGENTE': 'Agente',
        'QTDATENDIMENTO': 'QTD Atendimento', # Corrigido (sem S)
        'SATISFACAO': 'Satisfacao',
        'QTDSATISFACAO': 'QTD Avaliacoes',
    }
    df = df.rename(columns=rename_mapping)

    if 'Agente' not in df.columns:
        st.error(f"Arquivo de ranking {filename} não contém a coluna 'Agente'.")
        return pd.DataFrame()

    # Conversão de colunas de tempo
    def time_to_minutes(time_str):
        if pd.isna(time_str) or time_str == '': return 0.0
        try:
            parts = str(time_str).split(':')
            if len(parts) == 3: hours, minutes, seconds = map(float, parts); return (hours * 60) + minutes + seconds / 60
            elif len(parts) == 2: minutes, seconds = map(float, parts); return minutes + seconds / 60
            else: return 0.0
        except: return 0.0

    time_cols = ['TMA', 'TME', 'TMIA', 'TMIC']
    for col in time_cols:
        if col in df.columns and not df[col].isnull().all():
             df[col] = df[col].apply(time_to_minutes)

    # Conversão de FCR, Satisfacao e NPS (Garantindo que são numéricos)
    for col in ['FCR', 'Satisfacao', 'NPS']:
        if col in df.columns:
            current_col_name = col
            df[current_col_name] = df[current_col_name].astype(str).str.replace('%', '', regex=False).str.replace(',', '.', regex=False)
            df[current_col_name] = pd.to_numeric(df[current_col_name], errors='coerce')
    
    # Normaliza FCR (0-1) e Satisfação (0-5)
    if 'FCR' in df.columns and pd.api.types.is_numeric_dtype(df['FCR']):
        df['FCR'] = df['FCR'] / 100
    
    if 'Satisfacao' in df.columns and pd.api.types.is_numeric_dtype(df['Satisfacao']):
        df['Satisfacao'] = df['Satisfacao'] / 100 * 5 
    
    return df

# --- Função 5: Carrega os dados de AVALIAÇÃO Diária ---
@st.cache_data(show_spinner="Carregando avaliações diárias...")
def load_evaluation_data(selected_month_name, agente_name):
    """Carrega todos os CSVs da subpasta 'data/[mês]/notas/' e filtra pelo agente."""
    
    month_folder_lower = selected_month_name.lower()
    EVAL_FOLDER = os.path.join('data', month_folder_lower, 'notas') # Caminho: data/outubro/notas
    
    df_list = []
    
    if not os.path.exists(EVAL_FOLDER) or not os.path.isdir(EVAL_FOLDER):
        return pd.DataFrame()
        
    for filename in os.listdir(EVAL_FOLDER):
        if filename.endswith(".csv"):
            path = os.path.join(EVAL_FOLDER, filename)
            try:
                df_temp = pd.read_csv(path, encoding='utf-8', engine='python')
                
                # Limpa colunas ANTES
                df_temp.columns = df_temp.columns.str.strip().str.upper().str.replace('[^A-Z0-9_]+', '', regex=True) 

                # Renomeia (Baseado no seu input: nom_agente, num_protocolo, nom_valor)
                rename_mapping_temp = {
                    'NOM_AGENTE': 'Agente', 
                    'NUM_PROTOCOLO': 'Protocolo',
                    'NOM_VALOR': 'Nota', # 'nom_valor' vira 'NOMVALOR' -> 'Nota'
                    'DIA': 'Dia (CSV)' # Coluna 'Dia' original do CSV
                }
                df_temp = df_temp.rename(columns=rename_mapping_temp)

                # Adiciona Dia e DaySort (do nome do arquivo)
                day_month_str = filename.replace('.csv', '').replace('.', '/')
                df_temp['Dia'] = day_month_str 
                df_temp['DaySort'] = int(filename.split('.')[0])

                # Filtra pelo agente
                if 'Agente' in df_temp.columns:
                    df_temp = df_temp[df_temp['Agente'] == agente_name]
                else:
                    continue # Pula se não tiver coluna Agente

                if df_temp.empty: 
                    continue
                    
                df_list.append(df_temp)
            except Exception as e:
                st.warning(f"Erro ao ler arquivo de avaliação {filename}: {e}")
                continue

    if not df_list: return pd.DataFrame()
    df = pd.concat(df_list, ignore_index=True)
    return df

# --- Funções de Dashboard KPI e Histórico ---

def display_kpi(df_filtered):
    """Exibe os cards de KPIs agregados."""
    kpi_cols = {
        'QTD Atendimento': 'sum', 'TMA': 'mean', 'TME': 'mean', 'TMIA': 'mean',
        'FCR': 'mean', 'Satisfacao': 'mean', 'NPS': 'mean', 'QTD Avaliacoes': 'sum'
    }
    valid_kpi_cols = {col: agg for col, agg in kpi_cols.items() if col in df_filtered.columns}
    if not valid_kpi_cols: return
    kpi_data = df_filtered.agg(valid_kpi_cols).reset_index().T
    kpi_data.columns = kpi_data.iloc[0]
    kpi_data = kpi_data[1:]
    display_kpi_metrics(kpi_data)

def display_kpi_metrics(kpi_data):
    """Função auxiliar para formatar e exibir as métricas de KPI."""
    cols = st.columns(8)
    def display_metric(col, label, unit="", fmt="{:.2f}"):
        if label in kpi_data.columns and not kpi_data.empty and not pd.isna(kpi_data[label].iloc[0]):
            val = kpi_data[label].iloc[0]
            if label in ['TMA', 'TME', 'TMIA']: formatted_val = format_time(val); unit = ""
            elif label in ['FCR']: formatted_val = f"{val:.2%}"; unit = ""
            elif label in ['Satisfacao']: formatted_val = f"{(val / 5.0):.2%}"; unit = "" 
            elif label in ['QTD Atendimento', 'QTD Avaliacoes']: formatted_val = f"{val:.0f}"; unit = ""
            else: formatted_val = fmt.format(val)
            col.metric(label, f"{formatted_val} {unit}")
        else: col.metric(label, "N/A")
    display_metric(cols[0], "QTD Atendimento")
    display_metric(cols[1], "TMA", unit="")
    display_metric(cols[2], "TME", unit="")
    display_metric(cols[3], "TMIA", unit="")
    display_metric(cols[4], "FCR", unit="") 
    display_metric(cols[5], "Satisfacao", unit="") 
    display_metric(cols[6], "NPS", unit="")
    display_metric(cols[7], "QTD Avaliacoes")
    st.markdown("---")


def display_monthly_history(agente_name=None): # Nome do agente é opcional
    """Carrega todos os dados, filtra pelo agente (se houver) e exibe o histórico."""
    
    if agente_name:
        st.header("📈 Histórico Mês a Mês (Meu)")
    else:
        st.header("📈 Histórico Mês a Mês (Geral)")

    # Carrega todos os dados históricos DENTRO desta função
    df_full_history = load_all_history_data()

    if df_full_history.empty:
        st.info("Não há dados históricos disponíveis.")
        return

    # 1. Filtra pelo agente (se fornecido)
    if agente_name:
        df_agent_history = df_full_history[df_full_history['Agente'] == agente_name].copy() if 'Agente' in df_full_history.columns else pd.DataFrame()
    else:
        df_agent_history = df_full_history.copy() # Admin vê tudo
    
    if df_agent_history.empty:
         st.info("Não há histórico de dados para a seleção atual.")
         return

    # Garante que as colunas Mês e MonthSort existem APÓS o filtro
    if 'Mês' not in df_agent_history.columns or 'MonthSort' not in df_agent_history.columns:
        st.info("Colunas 'Mês' ou 'MonthSort' não encontradas nos dados históricos do agente.")
        return

    # Define as agregações
    agg_dict = {
        'QTD Atendimento': 'sum', 'TMA': 'mean', 'TME': 'mean', 'TMIA': 'mean',
        'FCR': 'mean', 'Satisfacao': 'mean', 'NPS': 'mean', 'QTD Avaliacoes': 'sum',
        'MonthSort': 'first' # Coluna auxiliar para manter a ordem
    }

    # Filtra as colunas válidas e agrupa
    valid_agg_cols = {col: agg for col, agg in agg_dict.items() if col in df_agent_history.columns}
    
    if not valid_agg_cols:
        st.info("Não há métricas suficientes para exibir o histórico mensal.")
        return

    # Agrupa por Mês e MonthSort
    df_monthly = df_agent_history.groupby(['MonthSort', 'Mês'], as_index=False).agg(valid_agg_cols)
    
    # Ordena usando a coluna MonthSort
    df_monthly = df_monthly.sort_values(by='MonthSort')
    
    # --- Gráficos de Tendência Mensal ---
    st.subheader("Gráficos de Tendência Mensal")
    
    col1, col2 = st.columns(2)
    
    # Gráfico de Satisfação Mensal (usa dados numéricos de df_monthly)
    if 'Satisfacao' in df_monthly.columns:
        with col1:
            fig_sat = px.line(
                df_monthly, 
                x='Mês', 
                y='Satisfacao', 
                title='Satisfação Mês a Mês (0-5)',
                markers=True,
                # Garante que a ordem do eixo X siga a ordenação dos dados (MonthSort)
                category_orders={"Mês": df_monthly['Mês']} 
            )
            fig_sat.update_yaxes(range=[0, 5])
            st.plotly_chart(fig_sat, use_container_width=True)

    # Gráfico de FCR Mensal (usa dados numéricos de df_monthly)
    if 'FCR' in df_monthly.columns:
         with col2:
            fig_fcr = px.line(
                df_monthly, 
                x='Mês', 
                y='FCR', 
                title='FCR Mês a Mês (0-1)',
                markers=True,
                category_orders={"Mês": df_monthly['Mês']}
            )
            fig_fcr.update_yaxes(range=[0, 1], tickformat=".0%")
            st.plotly_chart(fig_fcr, use_container_width=True)
    
    st.markdown("---")

    # Tabela de Histórico
    st.subheader("Tabela de Histórico Mês a Mês")

    # Descarta a coluna de ordenação
    df_monthly_display = df_monthly.drop(columns=['MonthSort'])

    # Aplica formatação de exibição
    df_display = apply_formatting(df_monthly_display)

    # Reordena e exibe as colunas
    cols = ['Mês'] + [col for col in df_display.columns if col != 'Mês']
    df_display = df_display[cols]
    
    st.dataframe(df_display, use_container_width=True)
    st.markdown("---")

# --- FUNÇÃO DE DETALHE DIÁRIO (com Gráficos) ---
def display_daily_detail(selected_month, agente_name=None): # Agente opcional
    st.header(f"📅 Detalhe Dia a Dia ({selected_month.capitalize()})")
    
    # Carrega dados diários (filtrados por agente se agente_name for fornecido)
    df_daily = load_daily_data(selected_month_name=selected_month, agente_name=agente_name)
    
    if df_daily.empty:
        if agente_name:
            st.info(f"Nenhum dado diário encontrado para {agente_name} na subpasta 'data/{selected_month.lower()}/'.")
        else:
            st.info(f"Nenhum dado diário encontrado na subpasta 'data/{selected_month.lower()}/'.")
        return

    # Define as agregações
    agg_dict = {
        'QTD Atendimento': 'sum', 'TMA': 'mean', 'TME': 'mean', 'TMIA': 'mean',
        'FCR': 'mean', 'Satisfacao': 'mean', 'NPS': 'mean', 'QTD Avaliacoes': 'sum',
        'DaySort': 'first', 'Data': 'first' # Mantém a coluna Data
    }
    # Se for admin (agente_name=None), precisamos agrupar por Dia E Agente
    group_by_cols = ['DaySort', 'Dia']
    if agente_name is None: 
        group_by_cols.append('Agente')
        agg_dict['Agente'] = 'first' # Mantém o nome do agente

    valid_agg_cols = {col: agg for col, agg in agg_dict.items() if col in df_daily.columns}
    
    if not valid_agg_cols or 'DaySort' not in df_daily.columns:
        st.info("Não há métricas ou colunas de dia suficientes para exibir o detalhe diário.")
        return

    # Agrupa por Dia (e Agente, se admin)
    df_daily_agg = df_daily.groupby(group_by_cols, as_index=False).agg(valid_agg_cols)
    
    # Ordena usando a coluna DaySort
    df_daily_agg = df_daily_agg.sort_values(by='DaySort')

    # --- Gráficos de Tendência Diária ---
    st.subheader("Gráficos de Tendência Diária")
    
    col1, col2 = st.columns(2)
    
    plot_color = 'Agente' if agente_name is None else None # Colore por agente se for admin
    
    # Gráfico de Satisfação
    if 'Satisfacao' in df_daily_agg.columns:
        with col1:
            fig_sat = px.line(
                df_daily_agg, x='Dia', y='Satisfacao', title='Satisfação Diária (0-5)',
                markers=True, color=plot_color
            )
            fig_sat.update_yaxes(range=[0, 5])
            st.plotly_chart(fig_sat, use_container_width=True)

    # Gráfico de FCR
    if 'FCR' in df_daily_agg.columns:
         with col2:
            fig_fcr = px.line(
                df_daily_agg, x='Dia', y='FCR', title='FCR Diário (0-1)',
                markers=True, color=plot_color
            )
            fig_fcr.update_yaxes(range=[0, 1], tickformat=".0%")
            st.plotly_chart(fig_fcr, use_container_width=True)
    
    st.markdown("---")

    # Tabela de Detalhe Diário
    st.subheader("Tabela de Detalhe Diário")
    
    # Descarta a coluna de ordenação
    df_daily_agg = df_daily_agg.drop(columns=['DaySort', 'Data']) # Remove Data também

    # Aplica formatação de exibição
    df_display = apply_formatting(df_daily_agg)

    # Reordena e exibe as colunas
    cols = ['Dia'] + [col for col in df_display.columns if col != 'Dia']
    df_display = df_display[cols]
    
    st.dataframe(df_display, use_container_width=True)
    st.markdown("---")

# 🚨 --- INÍCIO DA ADIÇÃO (Função Tabela 4) --- 🚨
def display_evaluation_details(selected_month, agente_name):
    """Carrega e exibe a tabela de avaliações diárias (Tabela 4)."""
    st.header("⭐ Minhas Avaliações (Detalhe Diário)")
    
    df_evals = load_evaluation_data(selected_month_name=selected_month, agente_name=agente_name)
    
    if df_evals.empty:
        st.info(f"Nenhuma avaliação encontrada para {agente_name} na subpasta 'data/{selected_month.lower()}/notas/'.")
        return

    # Garante que 'DaySort' existe para ordenação
    if 'DaySort' not in df_evals.columns:
        st.error("Erro: A coluna 'DaySort' não foi criada ao carregar as avaliações.")
        return
        
    df_evals = df_evals.sort_values(by='DaySort')
    
    # Define as colunas que queremos mostrar, com base no seu pedido
    # (Dia, Protocolo, Nota)
    cols_to_show = ['Dia', 'Protocolo', 'Nota']
    
    # Adiciona 'Comentário' se ela existir no CSV
    if 'Comentário' in df_evals.columns:
        cols_to_show.append('Comentário')
        
    # Filtra o DataFrame final para ter certeza que todas as colunas existem
    final_cols = [col for col in cols_to_show if col in df_evals.columns]
    
    df_display = df_evals[final_cols]
    
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    st.markdown("---")
# 🚨 --- FIM DA ADIÇÃO --- 🚨


# --- FUNÇÕES DE PAINEL ---

def display_user_dashboard(df_agent_current_month): # Recebe dados do mês selecionado
    """Dashboard para o usuário comum: Mês selecionado E Histórico (lido separadamente)."""
    agente_name = st.session_state['agente_name']
    selected_month = st.session_state['selected_month_name']
    
    st.title(f"👤 Dashboard de Desempenho - {agente_name}")
    
    # --- Painel do Mês Selecionado (Tabela 1) ---
    st.header(f"📊 {selected_month.capitalize()} - Resultado do Mês")
    
    if df_agent_current_month.empty:
        st.warning(f"Não há dados para o agente {agente_name} no mês de {selected_month}.")
    else:
        # KPIs Agregados do Mês
        display_kpi(df_agent_current_month)

        # Tabela Detalhada do Mês
        st.subheader("📋 Tabela de Detalhe Mensal")
        df_display = apply_formatting(df_agent_current_month)
        # Adiciona a coluna 'Mês' no início
        df_display.insert(0, 'Mês', selected_month.capitalize()) 
        # Mantém apenas as colunas relevantes
        relevant_cols = [
            'Mês', 'Agente', 'QTD Atendimento', 'TMA', 'TME', 'TMIA', 
            'FCR', 'Satisfacao', 'NPS', 'QTD Avaliacoes'
        ]
        final_cols = [col for col in relevant_cols if col in df_display.columns]
        st.dataframe(df_display[final_cols], use_container_width=True)

    # --- Painel de Histórico (Tabela 2) ---
    display_monthly_history(agente_name=agente_name) 

    # --- Painel de Detalhe Diário (Tabela 3) ---
    display_daily_detail(selected_month, agente_name=agente_name)
    
    # 🚨 --- INÍCIO DA ADIÇÃO (Tabela 4) --- 🚨
    display_evaluation_details(selected_month, agente_name)
    # 🚨 --- FIM DA ADIÇÃO --- 🚨


def display_admin_dashboard(df_monthly_aggregate): # df (passado do main) é o MENSAL
    """Dashboard para o administrador."""
    st.title(f"🧑‍💼 Dashboard Global - {st.session_state['selected_month_name']}")

    selected_month = st.session_state['selected_month_name']

    # 1. Carrega os dados DIÁRIOS para este mês (para todos os agentes)
    df_daily_full = load_daily_data(selected_month_name=selected_month, agente_name=None)
    
    is_date_available = not df_daily_full.empty and 'Data' in df_daily_full.columns

    # --- Filtros do Admin na Sidebar ---
    st.sidebar.subheader(f"Filtros (Admin - {selected_month})")
    
    # 2. Filtro de Agente
    agent_list = ["Todos os Agentes"]
    source_df_for_agents = df_daily_full if is_date_available else df_monthly_aggregate
    
    if 'Agente' in source_df_for_agents.columns:
        # CORREÇÃO: Converte para string ANTES de ordenar
        unique_agents = source_df_for_agents['Agente'].dropna().unique()
        valid_agents = [str(agent) for agent in unique_agents if str(agent).strip() != '']
        agent_list.extend(sorted(list(set(valid_agents))))

    selected_agent = st.sidebar.selectbox(
        "Filtrar por Agente:", 
        agent_list,
        key="admin_agent_filter"
    )
    
    # 3. Filtro de Calendário (Dias)
    if is_date_available:
        valid_dates = df_daily_full['Data'].dropna()
        if not valid_dates.empty:
            min_date = valid_dates.min().date()
            max_date = valid_dates.max().date()
            
            selected_date_range = st.sidebar.date_input(
                "Selecione o Período (Calendário):",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                format="DD/MM/YYYY"
            )
            
            if isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
                start_date, end_date = selected_date_range
            else:
                 start_date, end_date = min_date, max_date 

            if not start_date or not end_date:
                st.warning("Selecione um período válido.")
                df_filtered_daily = pd.DataFrame() 
            else:
                # Filtra o DataFrame diário pelos dias selecionados
                df_filtered_daily = df_daily_full[
                    (df_daily_full['Data'].dt.date >= start_date) & 
                    (df_daily_full['Data'].dt.date <= end_date)
                ].copy()
        
        else: # Datas inválidas
            st.sidebar.info(f"Nenhum dado diário com data válida encontrado.")
            df_filtered_daily = pd.DataFrame() 
            is_date_available = False
        
    else:
        st.sidebar.info(f"Nenhum dado diário encontrado na subpasta 'data/{selected_month.lower()}/'. Exibindo o consolidado mensal.")
        df_filtered_daily = pd.DataFrame() 
        is_date_available = False
        
    
    # 4. Decide qual DataFrame usar com base nos filtros
    if is_date_available:
        df_filtered = df_filtered_daily.copy() # Usa dados diários filtrados
    else:
        df_filtered = df_monthly_aggregate.copy() # Usa dados mensais

    # Aplica o filtro de Agente (se não for "Todos")
    if selected_agent != "Todos os Agentes":
        df_filtered = df_filtered[df_filtered['Agente'] == selected_agent].copy()

    if df_filtered.empty:
        st.warning("Nenhum dado encontrado para a seleção atual.")
        return

    # --- Lógica de Exibição (Admin vs Agente) ---
    if selected_agent != "Todos os Agentes":
        # 1. Se um agente foi selecionado, o Admin vê o PAINEL DO USUÁRIO
        
        st.header(f"Visão do Agente: {selected_agent}")
        
        # Tabela 1: Detalhe Mensal (do CSV principal)
        df_agent_current_month = df_monthly_aggregate[df_monthly_aggregate['Agente'] == selected_agent].copy() if 'Agente' in df_monthly_aggregate.columns else pd.DataFrame()
        
        st.header(f"📊 {selected_month.capitalize()} - Resultado do Mês (Agente: {selected_agent})")
        if df_agent_current_month.empty:
            st.warning(f"Não há dados consolidados para o agente {selected_agent} no mês de {selected_month}.")
        else:
            display_kpi(df_agent_current_month)
            st.subheader("📋 Tabela de Detalhe Mensal")
            df_display = apply_formatting(df_agent_current_month)
            df_display.insert(0, 'Mês', selected_month.capitalize()) 
            relevant_cols = ['Mês', 'Agente', 'QTD Atendimento', 'TMA', 'TME', 'TMIA', 'FCR', 'Satisfacao', 'NPS', 'QTD Avaliacoes']
            final_cols = [col for col in relevant_cols if col in df_display.columns]
            st.dataframe(df_display[final_cols], use_container_width=True)

        # Tabela 2: Histórico Mês a Mês
        display_monthly_history(agente_name=selected_agent) 

        # Tabela 3: Detalhe Dia a Dia (baseado no df_filtered que já foi filtrado por dia E agente)
        display_daily_detail(selected_month, agente_name=selected_agent)
        
        # Tabela 4: Avaliações (do agente selecionado)
        display_evaluation_details(selected_month, agente_name=selected_agent)
        
    else:
        # 2. Se "Todos os Agentes", mostra o painel de Admin (Ranking, etc.)
        
        # Criação das abas
        tab1, tab2, tab3 = st.tabs(["Visão Geral (Período Selecionado)", "Histórico Geral (Todos os Meses)", "Detalhe Diário (Período Selecionado)"])

        with tab1:
            st.subheader("📈 Métricas Agregadas (Período Selecionado)")
            display_kpi(df_filtered) # Usa o DF filtrado (diário ou mensal)
            
            # Rankings (Sempre visíveis, não filtrados pelo calendário)
            st.subheader("🏆 Ranking Top 3")
            st.info("Os rankings abaixo são baseados nos arquivos consolidados (semanais e mensal) e **não** são afetados pelo filtro de calendário.")
            
            col_rank1, col_rank2, col_rank3 = st.columns(3)
            
            # --- RANKING 1: SEMANAL ATUAL ---
            with col_rank1:
                st.markdown("##### 🥇 Semana Atual")
                df_ranking_atual = load_ranking_data("ranking_semanal_atual.csv")
                
                if df_ranking_atual.empty:
                    st.warning("Arquivo 'ranking_semanal_atual.csv' não encontrado.")
                elif 'Agente' not in df_ranking_atual.columns:
                     st.error("Ranking Atual: Coluna 'Agente' não encontrada.")
                else:
                    agg_cols = [col for col in ['QTD Atendimento', 'Satisfacao', 'FCR', 'TMIA'] if col in df_ranking_atual.columns]
                    agg_dict = {col: ('sum' if col.startswith('QTD') else 'mean') for col in agg_cols}
                    df_compare_atual = df_ranking_atual.groupby('Agente').agg(agg_dict).reset_index()

                    # FCR
                    if 'FCR' in df_compare_atual.columns and 'QTD Atendimento' in df_compare_atual.columns:
                        df_fcr_filtered = df_compare_atual[(df_compare_atual['FCR'] > 0.0) & (df_compare_atual['FCR'] < 1.0)]
                        top_fcr = df_fcr_filtered.sort_values(by=['FCR', 'QTD Atendimento'], ascending=[False, False]).head(3) 
                        top_fcr = top_fcr[['Agente', 'FCR']] 
                        top_fcr['FCR'] = (top_fcr['FCR'] * 100).map('{:.2f}%'.format) 
                        st.dataframe(top_fcr, use_container_width=True, hide_index=True)
                    else: st.info("Métrica 'FCR' não disponível.")
                    # Satisfacao
                    if 'Satisfacao' in df_compare_atual.columns and 'QTD Atendimento' in df_compare_atual.columns:
                        df_satisfacao_filtered = df_compare_atual[(df_compare_atual['Satisfacao'] > 0.0) & (df_compare_atual['Satisfacao'] < 5.0)]
                        top_satisfacao = df_satisfacao_filtered.sort_values(by=['Satisfacao', 'QTD Atendimento'], ascending=[False, False]).head(3)
                        top_satisfacao = top_satisfacao[['Agente', 'Satisfacao']]
                        top_satisfacao['Satisfacao'] = (top_satisfacao['Satisfacao'] / 5.0 * 100).map('{:.2f}%'.format)
                        st.dataframe(top_satisfacao, use_container_width=True, hide_index=True)
                    else: st.info("Métrica 'Satisfacao' não disponível.")
                    # TMIA
                    if 'TMIA' in df_compare_atual.columns and 'QTD Atendimento' in df_compare_atual.columns:
                        df_tmia_filtered = df_compare_atual[(df_compare_atual['TMIA'] > 0.0)]
                        top_tmia = df_tmia_filtered.sort_values(by=['TMIA', 'QTD Atendimento'], ascending=[True, False]).head(3)
                        top_tmia = top_tmia[['Agente', 'TMIA']]
                        top_tmia['TMIA'] = top_tmia['TMIA'].apply(format_time)
                        st.dataframe(top_tmia, use_container_width=True, hide_index=True)
                    else: st.info("Métrica 'TMIA' não disponível.")

            # --- RANKING 2: SEMANAL ANTERIOR ---
            with col_rank2:
                st.markdown("##### 🥈 Semana Anterior")
                df_ranking_anterior = load_ranking_data("ranking_semanal_anterior.csv")
                
                if df_ranking_anterior.empty:
                    st.warning("Arquivo 'ranking_semanal_anterior.csv' não encontrado.")
                elif 'Agente' not in df_ranking_anterior.columns:
                     st.error("Ranking Anterior: Coluna 'Agente' não encontrada.")
                else:
                    agg_cols_ant = [col for col in ['QTD Atendimento', 'Satisfacao', 'FCR', 'TMIA'] if col in df_ranking_anterior.columns]
                    agg_dict_ant = {col: ('sum' if col.startswith('QTD') else 'mean') for col in agg_cols_ant}
                    df_compare_anterior = df_ranking_anterior.groupby('Agente').agg(agg_dict_ant).reset_index()

                    # FCR
                    if 'FCR' in df_compare_anterior.columns and 'QTD Atendimento' in df_compare_anterior.columns:
                        df_fcr_filtered_ant = df_compare_anterior[(df_compare_anterior['FCR'] > 0.0) & (df_compare_anterior['FCR'] < 1.0)]
                        top_fcr_ant = df_fcr_filtered_ant.sort_values(by=['FCR', 'QTD Atendimento'], ascending=[False, False]).head(3) 
                        top_fcr_ant = top_fcr_ant[['Agente', 'FCR']] 
                        top_fcr_ant['FCR'] = (top_fcr_ant['FCR'] * 100).map('{:.2f}%'.format) 
                        st.dataframe(top_fcr_ant, use_container_width=True, hide_index=True)
                    # Satisfacao
                    if 'Satisfacao' in df_compare_anterior.columns and 'QTD Atendimento' in df_compare_anterior.columns:
                        df_satisfacao_filtered_ant = df_compare_anterior[(df_compare_anterior['Satisfacao'] > 0.0) & (df_compare_anterior['Satisfacao'] < 5.0)]
                        top_satisfacao_ant = df_satisfacao_filtered_ant.sort_values(by=['Satisfacao', 'QTD Atendimento'], ascending=[False, False]).head(3)
                        top_satisfacao_ant = top_satisfacao_ant[['Agente', 'Satisfacao']]
                        top_satisfacao_ant['Satisfacao'] = (top_satisfacao_ant['Satisfacao'] / 5.0 * 100).map('{:.2f}%'.format)
                        st.dataframe(top_satisfacao_ant, use_container_width=True, hide_index=True)
                    # TMIA
                    if 'TMIA' in df_compare_anterior.columns and 'QTD Atendimento' in df_compare_anterior.columns:
                        df_tmia_filtered_ant = df_compare_anterior[(df_compare_anterior['TMIA'] > 0.0)]
                        top_tmia_ant = df_tmia_filtered_ant.sort_values(by=['TMIA', 'QTD Atendimento'], ascending=[True, False]).head(3)
                        top_tmia_ant = top_tmia_ant[['Agente', 'TMIA']]
                        top_tmia_ant['TMIA'] = top_tmia_ant['TMIA'].apply(format_time)
                        st.dataframe(top_tmia_ant, use_container_width=True, hide_index=True)

            # --- RANKING 3: MÊS ATUAL (CONSOLIDADO) ---
            with col_rank3:
                st.markdown(f"##### 🥉 Consolidado do Mês ({selected_month})")
                
                # Usa o df_monthly_aggregate (o CSV do mês inteiro)
                if df_monthly_aggregate.empty:
                    st.warning("Arquivo consolidado do mês não encontrado.")
                elif 'Agente' not in df_monthly_aggregate.columns:
                     st.error("Ranking Mensal: Coluna 'Agente' não encontrada.")
                else:
                    # Não precisa agregar, pois df_monthly_aggregate já é agregado
                    df_compare_monthly = df_monthly_aggregate.copy() 

                    # FCR
                    if 'FCR' in df_compare_monthly.columns and 'QTD Atendimento' in df_compare_monthly.columns:
                        df_fcr_filtered_cal = df_compare_monthly[(df_compare_monthly['FCR'] > 0.0) & (df_compare_monthly['FCR'] < 1.0)]
                        top_fcr_cal = df_fcr_filtered_cal.sort_values(by=['FCR', 'QTD Atendimento'], ascending=[False, False]).head(3) 
                        top_fcr_cal = top_fcr_cal[['Agente', 'FCR']] 
                        top_fcr_cal['FCR'] = (top_fcr_cal['FCR'] * 100).map('{:.2f}%'.format) 
                        st.dataframe(top_fcr_cal, use_container_width=True, hide_index=True)
                    else: st.info("Métrica 'FCR' não disponível.")
                    # Satisfacao
                    if 'Satisfacao' in df_compare_monthly.columns and 'QTD Atendimento' in df_compare_monthly.columns:
                        df_satisfacao_filtered_cal = df_compare_monthly[(df_compare_monthly['Satisfacao'] > 0.0) & (df_compare_monthly['Satisfacao'] < 5.0)]
                        top_satisfacao_cal = df_satisfacao_filtered_cal.sort_values(by=['Satisfacao', 'QTD Atendimento'], ascending=[False, False]).head(3)
                        top_satisfacao_cal = top_satisfacao_cal[['Agente', 'Satisfacao']]
                        top_satisfacao_cal['Satisfacao'] = (top_satisfacao_cal['Satisfacao'] / 5.0 * 100).map('{:.2f}%'.format)
                        st.dataframe(top_satisfacao_cal, use_container_width=True, hide_index=True)
                    else: st.info("Métrica 'Satisfacao' não disponível.")
                    # TMIA
                    if 'TMIA' in df_compare_monthly.columns and 'QTD Atendimento' in df_compare_monthly.columns:
                        df_tmia_filtered_cal = df_compare_monthly[(df_compare_monthly['TMIA'] > 0.0)]
                        top_tmia_cal = df_tmia_filtered_cal.sort_values(by=['TMIA', 'QTD Atendimento'], ascending=[True, False]).head(3)
                        top_tmia_cal = top_tmia_cal[['Agente', 'TMIA']]
                        top_tmia_cal['TMIA'] = top_tmia_cal['TMIA'].apply(format_time)
                        st.dataframe(top_tmia_cal, use_container_width=True, hide_index=True)
                    else: st.info("Métrica 'TMIA' não disponível.")

            st.markdown("---")
            
            # Gráficos de Comparação (Baseados no FILTRO DE CALENDÁRIO)
            st.subheader("⚖️ Comparação de Agentes (Período Selecionado)")
            
            agg_cols = [col for col in ['QTD Atendimento', 'Satisfacao', 'NPS', 'FCR', 'TMA', 'TME', 'TMIA'] if col in df_filtered.columns]

            if 'Agente' in df_filtered.columns and agg_cols:
                agg_dict_cal = {col: ('sum' if col.startswith('QTD') else 'mean') 
                                for col in agg_cols if col in df_filtered.columns}
                
                if agg_dict_cal:
                    df_compare_calendario = df_filtered.groupby('Agente').agg(agg_dict_cal).reset_index()

                    if 'Satisfacao' in df_compare_calendario.columns:
                        fig_sat_agent = px.bar(df_compare_calendario.sort_values(by='Satisfacao', ascending=False), x='Agente', y='Satisfacao', title='Média de Satisfação por Agente', color='Satisfacao', color_continuous_scale=px.colors.sequential.Plotly3)
                        st.plotly_chart(fig_sat_agent, use_container_width=True)
                    if 'TMA' in df_compare_calendario.columns:
                        fig_tma_agent = px.bar(df_compare_calendario.sort_values(by='TMA', ascending=False), x='Agente', y='TMA', title='TMA (Tempo Médio de Atendimento) por Agente (em minutos)', color='TMA', color_continuous_scale=px.colors.sequential.Reds)
                        st.plotly_chart(fig_tma_agent, use_container_width=True)
                    
                    # Tabela Consolidada de Agentes (Período Selecionado)
                    st.markdown("---")
                    st.subheader("📋 Tabela Consolidada de Agentes (Período Selecionado)")
                    
                    df_compare_sorted = df_compare_calendario.sort_values(by=['Satisfacao', 'QTD Atendimento'], ascending=[False, False])
                    df_display_admin_agg = apply_formatting(df_compare_sorted)
                    st.dataframe(df_display_admin_agg, use_container_width=True, hide_index=True)
                
                else: 
                    st.warning("Não há colunas de métricas suficientes no período selecionado para comparar agentes.")
            else: 
                st.warning("Não há dados de 'Agente' no período selecionado.")

        with tab2:
            # Chama a função de histórico SEM nome de agente (visão admin/geral)
            display_monthly_history(agente_name=None)
            
        with tab3:
            # Chama a função de detalhe diário (que já usa df_filtered)
            st.header(f"📅 Detalhe Dia a Dia ({selected_month.capitalize()})")
            
            if not is_date_available:
                st.info("Detalhe diário não disponível (nenhuma subpasta encontrada).")
                # Se não houver dados diários, exibe o consolidado mensal
                df_display = apply_formatting(df_filtered)
                st.dataframe(df_display, use_container_width=True)
            else:
                # Agrupamento para métricas diárias (Médias por Data e Agente)
                agg_dict_full = {
                    'QTD Atendimento': 'sum', 'TMA': 'mean', 'TME': 'mean', 'TMIA': 'mean',
                    'FCR': 'mean', 'Satisfacao': 'mean', 'NPS': 'mean', 'QTD Avaliacoes': 'sum',
                    'DaySort': 'first', 'Agente': 'first', 'Data': 'first'
                }
                
                agg_cols_full = [col for col in agg_dict_full.keys() if col in df_filtered.columns]
                
                df_daily_agg = df_filtered.groupby(['DaySort', 'Dia', 'Agente'], as_index=False).agg({
                    col: agg_dict_full[col] for col in agg_cols_full
                }).sort_values(by='DaySort')

                st.subheader("Gráficos de Tendência Diária (Todos Agentes)")
                col1, col2 = st.columns(2)
                if 'Satisfacao' in df_daily_agg.columns:
                    with col1:
                        fig_sat = px.line(df_daily_agg, x='Dia', y='Satisfacao', title='Satisfação Diária (0-5)', markers=True, color='Agente')
                        fig_sat.update_yaxes(range=[0, 5])
                        st.plotly_chart(fig_sat, use_container_width=True)
                if 'FCR' in df_daily_agg.columns:
                     with col2:
                        fig_fcr = px.line(df_daily_agg, x='Dia', y='FCR', title='FCR Diário (0-1)', markers=True, color='Agente')
                        fig_fcr.update_yaxes(range=[0, 1], tickformat=".0%")
                        st.plotly_chart(fig_fcr, use_container_width=True)
                
                st.markdown("---")
                st.subheader("Tabela de Detalhe Diário (Todos Agentes)")
                df_daily_agg = df_daily_agg.drop(columns=['DaySort', 'Data']) 
                df_display = apply_formatting(df_daily_agg)
                cols = ['Dia'] + [col for col in df_display.columns if col != 'Dia']
                st.dataframe(df_display[cols], use_container_width=True)


# --- Funções de Autenticação na UI (Inalterada) ---
def login_form():
    """Exibe o formulário de login no sidebar."""
    st.sidebar.title("🔒 Login")
    with st.sidebar.form("login_form"):
        username = st.text_input("Usuário", key="login_user")
        password = st.text_input("Senha", type="password", key="login_pass")
        submitted = st.form_submit_button("Entrar")
        if submitted:
            if check_password(username, password):
                user_info = get_user_info(username)
                st.session_state['authenticated'] = True
                st.session_state['username'] = username
                st.session_state['role'] = user_info.get('role', 'user')
                st.session_state['primeiro_acesso'] = user_info.get('primeiro_acesso', True)
                st.session_state['agente_name'] = user_info.get('agente', 'Usuário Desconhecido')
                st.sidebar.success(f"Bem-vindo, {username}!")
                st.rerun() 
            else: st.sidebar.error("Usuário ou senha incorretos.")
def change_password_form():
    """Exibe o formulário de alteração de senha no sidebar."""
    st.sidebar.title("🔑 Alterar Senha")
    is_first_access = st.session_state.get('primeiro_acesso', False)
    if is_first_access: st.sidebar.warning("É seu primeiro acesso! Você deve alterar a senha.")
    with st.sidebar.form("change_pass_form"):
        new_password = st.text_input("Nova Senha", type="password", key="new_pass")
        confirm_password = st.text_input("Confirmar Nova Senha", type="password", key="confirm_pass")
        submitted = st.form_submit_button("Atualizar Senha")
        if submitted:
            if not new_password or not confirm_password: st.sidebar.error("Preencha ambos os campos.")
            elif new_password != confirm_password: st.sidebar.error("As senhas não coincidem.")
            else:
                if change_password_db(st.session_state['username'], new_password):
                    st.session_state['primeiro_acesso'] = False 
                    st.sidebar.success("Senha alterada com sucesso!")
                    if is_first_access: st.info("Senha alterada. Clique em 'Prosseguir para Dashboard' na barra lateral.")
                    st.rerun() 
                else: st.sidebar.error("Erro interno ao salvar a senha.")
def logout_button():
    """Botão de Logout."""
    if st.sidebar.button("Sair (Logout)"):
        st.session_state['authenticated'] = False
        st.session_state['username'] = None
        st.session_state['role'] = None
        st.session_state['primeiro_acesso'] = False
        st.rerun() 

# --- Lógica Principal da Aplicação ---
def main():
    
    # --- Configuração do Filtro Mensal na Sidebar ---
    st.sidebar.markdown("---")
    DATA_FOLDER = 'data'
    
    # 1. Busca pelos arquivos CSV disponíveis na pasta 'data'
    available_files = []
    if os.path.exists(DATA_FOLDER):
        for filename in os.listdir(DATA_FOLDER):
            if filename.endswith(".csv"):
                month_name = filename.replace('.csv', '').capitalize()
                if month_name.lower() in MESES: # Garante que só meses válidos entrem na lista
                    available_files.append(month_name)
        # Ordena os meses disponíveis
        available_files.sort(key=lambda x: list(MESES.keys()).index(x.lower()) if x.lower() in MESES else 99)
    
    # 2. Inicialização e Seleção do Mês
    if 'selected_month_name' not in st.session_state:
        # Define o último mês disponível como padrão, ou o primeiro se não houver último
        st.session_state['selected_month_name'] = available_files[-1] if available_files else list(MESES.keys())[0].capitalize()

    selected_month_name = st.session_state['selected_month_name']
    file_to_load = None
    
    if available_files:
        selected_month_key = st.sidebar.selectbox(
            "Selecione o Mês:", 
            available_files,
            index=available_files.index(selected_month_name) if selected_month_name in available_files else 0
        )
        st.session_state['selected_month_name'] = selected_month_key
        file_to_load = MESES.get(selected_month_key.lower())
    else:
        st.sidebar.warning(f"Crie a pasta '{DATA_FOLDER}/' e adicione os arquivos mensais (ex: janeiro.csv).")
    
    # 3. Carrega o DataFrame (apenas o mês selecionado para a visão principal)
    df = pd.DataFrame()
    if file_to_load:
        df = load_and_preprocess_data(file_to_load)
    
    
    if st.session_state['authenticated']:
        change_password_form()
        logout_button()
        
        # 🚨 --- ADIÇÃO DA ASSINATURA --- 🚨
        st.sidebar.markdown("---")
        st.sidebar.caption("Desenvolvido por Vinicios Oliveira")
        # 🚨 --- FIM DA ADIÇÃO --- 🚨

        if st.session_state.get('primeiro_acesso'):
            st.title("Bem-vindo(a)! 🔑")
            st.warning("É o seu primeiro acesso. Você deve alterar a senha no menu lateral para continuar.")
            if st.sidebar.button("Prosseguir para Dashboard"):
                st.session_state['primeiro_acesso'] = False 
                st.rerun() 
            return 
            
        # Verifica se há dados carregados para o mês selecionado
        if df.empty and not os.path.exists('data'): 
             st.warning(f"Não há dados disponíveis para o mês de **{st.session_state.get('selected_month_name', 'N/A')}**. Verifique o console para erros ou a estrutura de pastas.")
             # Permite continuar para mostrar o histórico se houver
        
        agente_name = st.session_state.get('agente_name')
        df_agent_filtered = df[df['Agente'] == agente_name].copy() if agente_name and 'Agente' in df.columns and not df.empty else pd.DataFrame()

        if st.session_state['role'] == 'admin':
            
            admin_selection = st.sidebar.radio(
                "Painel do Administrador", 
                ["Dashboard Global", "Gerenciar Usuários"]
            )
            
            if admin_selection == "Dashboard Global":
                display_admin_dashboard(df) # Passa o DF MENSAL
            elif admin_selection == "Gerenciar Usuários":
                # Gerenciador de usuários precisa de todos os dados históricos para funcionar
                df_full_history = load_all_history_data() 
                if 'Agente' in df_full_history.columns:
                    user_manager_interface(df_full_history) # Passa o DF completo
                else:
                    st.error("A coluna 'Agente' não foi encontrada. Não é possível gerenciar usuários a partir do CSV.")
                
        else: # Usuário Comum
            # Verifica se há algum dado histórico para o agente antes de dar o aviso final
            df_full_history_check = load_all_history_data()
            df_agent_hist_check = df_full_history_check[df_full_history_check['Agente'] == agente_name].copy() if 'Agente' in df_full_history_check.columns else pd.DataFrame()

            if not df_agent_filtered.empty or not df_agent_hist_check.empty :
                 display_user_dashboard(df_agent_filtered) # Passa apenas os dados do mês selecionado
            else:
                 st.warning(f"Não foram encontrados dados de desempenho para o agente: **{agente_name}** em nenhum mês.")


    else:
        st.title("Dashboard de Desempenho de Agentes")
        st.info("Entre com suas credenciais na barra lateral para acessar o sistema.")
        st.markdown("---")
        st.write("Atenção: O administrador inicial tem login: `admin` e senha: `12345`.")
        login_form()
        
        # 🚨 --- ADIÇÃO DA ASSINATURA --- 🚨
        st.sidebar.markdown("---")
        st.sidebar.caption("Desenvolvido por Vinicios Oliveira")
        # 🚨 --- FIM DA ADIÇÃO --- 🚨

if __name__ == '__main__':
    main()
