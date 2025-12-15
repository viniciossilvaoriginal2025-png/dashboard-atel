import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

# --- CONEXÃO COM O GOOGLE SHEETS (Mesma lógica do app.py) ---
def get_auth_connection():
    """Conecta ao Google Sheets para buscar usuários."""
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        
        # Pega as credenciais dos secrets
        if "google_credentials" in st.secrets:
            creds_dict = dict(st.secrets["google_credentials"])
        else:
            return None

        # Correção de padding para Windows
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Abre a planilha pelo Link
        sh = client.open_by_url(st.secrets["spreadsheet_url"])
        return sh.worksheet("Usuarios") # Abre a aba 'Usuarios'
        
    except Exception as e:
        st.error(f"Erro ao conectar no banco de usuários: {e}")
        return None

# --- FUNÇÕES DE AUTENTICAÇÃO ---

def get_all_users():
    """Baixa todos os usuários da planilha e retorna como um Dicionário."""
    worksheet = get_auth_connection()
    if not worksheet: return {}
    
    try:
        # Pega todos os registros
        records = worksheet.get_all_records()
        
        # Converte para o formato que o sistema espera:
        # {'admin': {'password': '...', 'name': '...', 'role': '...', 'primeiro_acesso': True}}
        users_db = {}
        for row in records:
            # Converte string 'TRUE'/'FALSE' do Excel para booleano Python
            p_acesso = str(row['PrimeiroAcesso']).upper() == 'TRUE'
            
            users_db[str(row['Usuario'])] = {
                'password': str(row['Senha']),
                'name': row['Nome'],
                'role': row['Funcao'],
                'primeiro_acesso': p_acesso,
                'agente': row['Nome'] # Alias para manter compatibilidade
            }
        return users_db
    except Exception as e:
        st.error(f"Erro ao ler usuários: {e}")
        return {}

def check_password(username, password):
    """Verifica se o usuário e senha batem com a planilha."""
    users_db = get_all_users() # Busca dados frescos da planilha
    
    if username in users_db:
        # Compara a senha digitada com a senha da planilha
        if str(users_db[username]['password']) == str(password):
            return True
    return False

def get_user_info(username):
    """Retorna os dados do usuário."""
    users_db = get_all_users()
    return users_db.get(username, {})

def change_password_db(username, new_password):
    """Atualiza a senha DIRETAMENTE na planilha."""
    worksheet = get_auth_connection()
    if not worksheet: return False
    
    try:
        # 1. Encontra a linha do usuário
        cell = worksheet.find(username)
        if not cell:
            return False
            
        # 2. Atualiza a Coluna B (Senha) -> cell.row, col 2
        worksheet.update_cell(cell.row, 2, new_password)
        
        # 3. Atualiza a Coluna E (PrimeiroAcesso) -> cell.row, col 5
        # Define como FALSE pois ele já trocou a senha
        worksheet.update_cell(cell.row, 5, "FALSE")
        
        return True
    except Exception as e:
        st.error(f"Erro ao salvar senha na nuvem: {e}")
        return False

# --- INTERFACE DE GERENCIAMENTO (PARA O ADMIN) ---
def user_manager_interface(df_history):
    """Interface para o Admin adicionar/remover usuários na planilha."""
    st.header("👥 Gerenciar Usuários (Nuvem)")
    
    # Lista usuários atuais
    users = get_all_users()
    
    # Converte para DataFrame para exibir bonitinho
    if users:
        df_users = pd.DataFrame.from_dict(users, orient='index')
        st.dataframe(df_users[['name', 'role', 'primeiro_acesso']], use_container_width=True)
    
    st.markdown("---")
    
    # Formulário de Novo Usuário
    with st.form("add_user_form"):
        st.subheader("Adicionar Novo Usuário")
        c1, c2 = st.columns(2)
        new_user = c1.text_input("Usuário (Login)")
        new_pass = c2.text_input("Senha Inicial")
        new_name = c1.text_input("Nome do Agente (Igual ao CSV)")
        new_role = c2.selectbox("Função", ["user", "admin"])
        
        if st.form_submit_button("Salvar Usuário"):
            if new_user and new_pass and new_name:
                try:
                    ws = get_auth_connection()
                    # Adiciona linha: Usuario, Senha, Nome, Funcao, PrimeiroAcesso
                    ws.append_row([new_user, new_pass, new_name, new_role, "TRUE"])
                    st.success(f"Usuário {new_user} criado com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao criar: {e}")
            else:
                st.warning("Preencha todos os campos.")
