import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import os

# --- CONEXÃO COM O GOOGLE SHEETS ---
def get_auth_connection():
    """Conecta ao Google Sheets para buscar usuários."""
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        
        if "google_credentials" in st.secrets:
            creds_dict = dict(st.secrets["google_credentials"])
        else:
            return None

        # Correção obrigatória de padding para Windows
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Tenta abrir pelo NOME "BaseFAQ" ou URL
        try:
            sh = client.open("BaseFAQ")
        except:
            if "spreadsheet_url" in st.secrets:
                sh = client.open_by_url(st.secrets["spreadsheet_url"])
            else:
                return None

        return sh.worksheet("Usuarios") 
        
    except Exception as e:
        return None

# --- LEITURA LOCAL (CSVs) ---
def get_csv_agents():
    """Varre a pasta data/ para encontrar nomes de agentes nos arquivos CSV."""
    agents = set()
    DATA_FOLDER = 'data'
    
    if not os.path.exists(DATA_FOLDER):
        return agents

    for filename in os.listdir(DATA_FOLDER):
        if filename.endswith(".csv"):
            try:
                path = os.path.join(DATA_FOLDER, filename)
                # Leitura robusta
                df = pd.read_csv(path, sep=';', encoding='latin1', engine='python')
                if df.shape[1] < 2:
                    df = pd.read_csv(path, sep=',', encoding='utf-8', engine='python')
                
                df.columns = df.columns.str.strip().str.upper().str.replace('[^A-Z0-9_]+', '', regex=True)
                
                if 'NOM_AGENTE' in df.columns: target = 'NOM_AGENTE'
                elif 'NOMAGENTE' in df.columns: target = 'NOMAGENTE'
                else: continue
                
                unique_names = df[target].dropna().unique()
                for name in unique_names:
                    if str(name).strip():
                        agents.add(str(name).strip())
            except:
                continue
    return agents

# --- FUNÇÕES DE USUÁRIOS ---

def get_all_users():
    """Retorna dicionário unificado: Nuvem (Prioridade) + Local (Implícito)."""
    users_db = {}
    
    # 1. Carrega da Nuvem
    worksheet = get_auth_connection()
    cloud_usernames = set() # Para rastrear quem já está na nuvem
    
    if worksheet:
        try:
            records = worksheet.get_all_records()
            for row in records:
                usuario = str(row.get('Usuario', '')).strip()
                if usuario:
                    p_acesso = str(row.get('PrimeiroAcesso', 'FALSE')).upper() == 'TRUE'
                    users_db[usuario] = {
                        'password': str(row.get('Senha', '')),
                        'name': row.get('Nome', 'Sem Nome'),
                        'role': row.get('Funcao', 'user'),
                        'primeiro_acesso': p_acesso,
                        'agente': row.get('Nome', 'Sem Nome'),
                        'source': 'cloud'
                    }
                    cloud_usernames.add(usuario)
        except: pass

    # 2. Carrega Local (Apenas os que NÃO estão na nuvem)
    csv_agents = get_csv_agents()
    for agent in csv_agents:
        if agent not in cloud_usernames:
            users_db[agent] = {
                'password': '12345',
                'name': agent,
                'role': 'user',
                'primeiro_acesso': True,
                'agente': agent,
                'source': 'local' # Indica que veio do CSV
            }
            
    return users_db

def check_password(username, password):
    users_db = get_all_users()
    if username in users_db:
        if str(users_db[username]['password']).strip() == str(password).strip():
            return True
    return False

def get_user_info(username):
    users_db = get_all_users()
    return users_db.get(username, {})

def change_password_db(username, new_password):
    worksheet = get_auth_connection()
    if not worksheet: return False
    
    try:
        cell = worksheet.find(username)
        if cell:
            # Atualiza existente
            header = worksheet.row_values(1)
            col_senha = header.index('Senha') + 1
            col_acesso = header.index('PrimeiroAcesso') + 1
            worksheet.update_cell(cell.row, col_senha, new_password)
            worksheet.update_cell(cell.row, col_acesso, "FALSE")
        else:
            # Cria novo (caso raro de migração no momento da troca)
            worksheet.append_row([username, new_password, username, "user", "FALSE"])
        return True
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")
        return False

# 🚨 NOVA FUNÇÃO: SINCRONIZAÇÃO EM MASSA 🚨
def sync_csv_users_to_cloud():
    """Pega usuários que só existem no CSV e salva na Planilha."""
    worksheet = get_auth_connection()
    if not worksheet:
        st.error("Sem conexão com a planilha.")
        return
    
    # 1. Pega usuários atuais da nuvem
    try:
        cloud_records = worksheet.get_all_records()
        cloud_users = {str(row.get('Usuario', '')).strip() for row in cloud_records}
    except:
        cloud_users = set()
    
    # 2. Pega usuários do CSV
    csv_agents = get_csv_agents()
    
    # 3. Identifica os novos
    new_users = []
    for agent in csv_agents:
        if agent not in cloud_users:
            # Formato: [Usuario, Senha, Nome, Funcao, PrimeiroAcesso]
            new_users.append([agent, "12345", agent, "user", "TRUE"])
            
    # 4. Salva em massa (MUITO mais rápido que um por um)
    if new_users:
        try:
            worksheet.append_rows(new_users)
            st.success(f"✅ Sucesso! {len(new_users)} novos agentes foram cadastrados na planilha.")
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao sincronizar: {e}")
    else:
        st.info("Todos os agentes do CSV já estão na nuvem.")

# --- INTERFACE DE GERENCIAMENTO (PARA O ADMIN) ---
def user_manager_interface(df_history):
    st.header("👥 Gerenciar Usuários")
    
    users = get_all_users()
    
    # Conta quantos são locais vs nuvem
    local_count = sum(1 for u in users.values() if u.get('source') == 'local')
    
    # 🚨 BOTÃO MÁGICO DE SINCRONIZAÇÃO 🚨
    if local_count > 0:
        st.info(f"💡 Detectamos **{local_count}** agentes nos arquivos CSV que ainda não estão salvos na planilha.")
        if st.button(f"📥 Importar {local_count} Agentes para a Nuvem Agora"):
            with st.spinner("Sincronizando..."):
                sync_csv_users_to_cloud()
        st.markdown("---")

    # Tabela de Usuários
    if users:
        users_list = []
        for u, data in users.items():
            source_icon = "☁️ Nuvem" if data.get('source') == 'cloud' else "📂 CSV (Temp)"
            users_list.append({
                'Usuário': u,
                'Nome': data['name'],
                'Função': data['role'],
                'Origem': source_icon,
                'Primeiro Acesso': 'Sim' if data['primeiro_acesso'] else 'Não'
            })
        
        st.dataframe(pd.DataFrame(users_list), use_container_width=True)
    else:
        st.info("Nenhum usuário encontrado.")
    
    st.markdown("---")
    
    # Adicionar Manual
    with st.form("add_user_form"):
        st.subheader("Adicionar Usuário Manualmente")
        c1, c2 = st.columns(2)
        new_user = c1.text_input("Usuário (Login)")
        new_pass = c2.text_input("Senha Inicial")
        new_name = c1.text_input("Nome do Agente")
        new_role = c2.selectbox("Função", ["user", "admin"])
        
        if st.form_submit_button("Salvar na Nuvem"):
            if new_user and new_pass and new_name:
                try:
                    ws = get_auth_connection()
                    existing = ws.find(new_user)
                    if existing:
                        st.error("Usuário já existe!")
                    else:
                        ws.append_row([new_user, new_pass, new_name, new_role, "TRUE"])
                        st.success(f"Usuário {new_user} criado!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")
            else:
                st.warning("Preencha todos os campos.")
