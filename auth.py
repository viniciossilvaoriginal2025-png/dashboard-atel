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
        
        # Pega as credenciais dos secrets
        if "google_credentials" in st.secrets:
            creds_dict = dict(st.secrets["google_credentials"])
        else:
            return None

        # Correção obrigatória de padding para Windows
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Tenta abrir pelo NOME "BaseFAQ" (Igual ao app.py)
        try:
            sh = client.open("BaseFAQ")
        except:
            if "spreadsheet_url" in st.secrets:
                sh = client.open_by_url(st.secrets["spreadsheet_url"])
            else:
                return None

        # Retorna a aba 'Usuarios'
        return sh.worksheet("Usuarios") 
        
    except Exception as e:
        return None

# --- NOVA FUNÇÃO: Ler Agentes dos CSVs Locais ---
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
                # Leitura robusta (igual ao app.py) para garantir que pegue os nomes
                df = pd.read_csv(path, sep=';', encoding='latin1', engine='python')
                if df.shape[1] < 2:
                    df = pd.read_csv(path, sep=',', encoding='utf-8', engine='python')
                
                # Limpa nome da coluna
                df.columns = df.columns.str.strip().str.upper().str.replace('[^A-Z0-9_]+', '', regex=True)
                
                # Procura coluna de Agente
                if 'NOM_AGENTE' in df.columns:
                    target_col = 'NOM_AGENTE'
                elif 'NOMAGENTE' in df.columns:
                    target_col = 'NOMAGENTE'
                else:
                    continue
                
                # Adiciona nomes únicos ao conjunto
                unique_names = df[target_col].dropna().unique()
                for name in unique_names:
                    if str(name).strip():
                        agents.add(str(name).strip())
            except:
                continue
    return agents

# --- FUNÇÕES DE AUTENTICAÇÃO ---

def get_all_users():
    """
    Retorna um dicionário unificado: 
    Usuários da Planilha (Prioridade) + Agentes dos CSVs (Implícitos).
    """
    users_db = {}
    
    # 1. Carrega Usuários da Planilha (Nuvem)
    worksheet = get_auth_connection()
    if worksheet:
        try:
            records = worksheet.get_all_records()
            for row in records:
                p_acesso = str(row.get('PrimeiroAcesso', 'FALSE')).upper() == 'TRUE'
                usuario = str(row.get('Usuario', '')).strip()
                if usuario:
                    users_db[usuario] = {
                        'password': str(row.get('Senha', '')),
                        'name': row.get('Nome', 'Sem Nome'),
                        'role': row.get('Funcao', 'user'),
                        'primeiro_acesso': p_acesso,
                        'agente': row.get('Nome', 'Sem Nome'),
                        'source': 'cloud' # Marca que veio da nuvem
                    }
        except: pass

    # 2. Carrega Agentes dos CSVs (Local)
    # Só adiciona se o agente AINDA NÃO estiver na lista da planilha
    csv_agents = get_csv_agents()
    for agent in csv_agents:
        if agent not in users_db:
            # Cria um usuário "temporário" automático
            users_db[agent] = {
                'password': '12345', # Senha Padrão
                'name': agent,
                'role': 'user',
                'primeiro_acesso': True, # Força troca de senha no primeiro login
                'agente': agent,
                'source': 'local' # Marca que veio do CSV
            }
            
    return users_db

def check_password(username, password):
    """Verifica se o usuário e senha batem."""
    users_db = get_all_users()
    
    if username in users_db:
        # Compara a senha digitada
        stored_pass = str(users_db[username]['password']).strip()
        if stored_pass == str(password).strip():
            return True
    return False

def get_user_info(username):
    """Retorna os dados do usuário."""
    users_db = get_all_users()
    return users_db.get(username, {})

def change_password_db(username, new_password):
    """
    Atualiza a senha.
    - Se o usuário já existe na planilha: Atualiza a célula.
    - Se o usuário veio do CSV (local): Cria uma nova linha na planilha.
    """
    worksheet = get_auth_connection()
    if not worksheet: return False
    
    try:
        # Verifica se o usuário já existe na planilha
        cell = worksheet.find(username)
        
        if cell:
            # --- CENÁRIO 1: Usuário já existe na nuvem -> Atualiza ---
            # Acha colunas dinamicamente
            header = worksheet.row_values(1)
            col_senha = header.index('Senha') + 1
            col_acesso = header.index('PrimeiroAcesso') + 1
            
            worksheet.update_cell(cell.row, col_senha, new_password)
            worksheet.update_cell(cell.row, col_acesso, "FALSE")
        else:
            # --- CENÁRIO 2: Usuário novo (vindo do CSV) -> Cria na nuvem ---
            # Adiciona: Usuario, Senha, Nome, Funcao, PrimeiroAcesso
            # Assume que o username é o próprio nome do agente neste caso
            worksheet.append_row([username, new_password, username, "user", "FALSE"])
        
        return True
    except Exception as e:
        st.error(f"Erro ao salvar senha: {e}")
        return False

# --- INTERFACE DE GERENCIAMENTO (PARA O ADMIN) ---
def user_manager_interface(df_history):
    st.header("👥 Gerenciar Usuários (Nuvem)")
    
    users = get_all_users()
    
    if users:
        users_list = []
        for u, data in users.items():
            source = "☁️ Nuvem" if data.get('source') == 'cloud' else "📂 CSV (Auto)"
            users_list.append({
                'Usuário': u,
                'Nome': data['name'],
                'Função': data['role'],
                'Origem': source
            })
        
        st.dataframe(pd.DataFrame(users_list), use_container_width=True)
    else:
        st.info("Nenhum usuário encontrado.")
    
    st.markdown("---")
    
    with st.form("add_user_form"):
        st.subheader("Adicionar Novo Usuário Manualmente")
        c1, c2 = st.columns(2)
        new_user = c1.text_input("Usuário (Login)")
        new_pass = c2.text_input("Senha Inicial")
        new_name = c1.text_input("Nome do Agente")
        new_role = c2.selectbox("Função", ["user", "admin"])
        
        if st.form_submit_button("Salvar Usuário na Nuvem"):
            if new_user and new_pass and new_name:
                try:
                    ws = get_auth_connection()
                    existing = ws.find(new_user)
                    if existing:
                        st.error("Usuário já existe na planilha!")
                    else:
                        ws.append_row([new_user, new_pass, new_name, new_role, "TRUE"])
                        st.success(f"Usuário {new_user} criado!")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")
            else:
                st.warning("Preencha todos os campos.")
