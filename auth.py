import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd

# --- CONEXÃO COM O GOOGLE SHEETS ---
def get_auth_connection():
    """Conecta ao Google Sheets para buscar usuários."""
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        
        # Pega as credenciais dos secrets
        if "google_credentials" in st.secrets:
            creds_dict = dict(st.secrets["google_credentials"])
        else:
            # Fallback caso use o formato antigo
            return None

        # Correção obrigatória de padding para Windows
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        
        # 🚨 ALTERAÇÃO AQUI: Tenta abrir pelo NOME "BaseFAQ" (Igual ao app.py)
        # Isso evita o erro de 'spreadsheet_url' faltando
        try:
            sh = client.open("BaseFAQ")
        except:
            # Se não achar pelo nome, tenta pelo URL se ele existir
            if "spreadsheet_url" in st.secrets:
                sh = client.open_by_url(st.secrets["spreadsheet_url"])
            else:
                st.error("Não foi possível encontrar a planilha 'BaseFAQ'. Verifique o nome.")
                return None

        # Tenta abrir a aba 'Usuarios'
        return sh.worksheet("Usuarios") 
        
    except Exception as e:
        # Se der erro (ex: aba não existe), retorna None e o sistema avisa
        # st.error(f"Erro ao conectar no banco de usuários: {e}") # Comentado para não poluir a tela se for erro temporário
        return None

# --- FUNÇÕES DE AUTENTICAÇÃO ---

def get_all_users():
    """Baixa todos os usuários da planilha e retorna como um Dicionário."""
    worksheet = get_auth_connection()
    if not worksheet: return {}
    
    try:
        # Pega todos os registros
        records = worksheet.get_all_records()
        
        # Converte para o formato que o sistema espera
        users_db = {}
        for row in records:
            # Converte string 'TRUE'/'FALSE' do Excel para booleano Python
            p_acesso = str(row.get('PrimeiroAcesso', 'FALSE')).upper() == 'TRUE'
            
            # Garante que as chaves existem
            usuario = str(row.get('Usuario', '')).strip()
            if usuario:
                users_db[usuario] = {
                    'password': str(row.get('Senha', '')),
                    'name': row.get('Nome', 'Sem Nome'),
                    'role': row.get('Funcao', 'user'),
                    'primeiro_acesso': p_acesso,
                    'agente': row.get('Nome', 'Sem Nome')
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
        # Converte ambos para string para garantir
        if str(users_db[username]['password']).strip() == str(password).strip():
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
            
        # 2. Atualiza a Coluna B (Senha) -> Assumindo que Senha é a coluna 2
        # Melhor: Achar a coluna 'Senha' dinamicamente
        header = worksheet.row_values(1)
        col_senha = header.index('Senha') + 1
        col_acesso = header.index('PrimeiroAcesso') + 1
        
        worksheet.update_cell(cell.row, col_senha, new_password)
        worksheet.update_cell(cell.row, col_acesso, "FALSE")
        
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
        # Transforma o dicionário em lista para o DataFrame
        users_list = []
        for u, data in users.items():
            users_list.append({
                'Usuário': u,
                'Nome': data['name'],
                'Função': data['role'],
                'Primeiro Acesso': 'Sim' if data['primeiro_acesso'] else 'Não'
            })
        
        st.dataframe(pd.DataFrame(users_list), use_container_width=True)
    else:
        st.info("Nenhum usuário encontrado ou erro na conexão.")
    
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
                    if ws:
                        # Verifica se usuário já existe
                        existing = ws.find(new_user)
                        if existing:
                            st.error("Usuário já existe!")
                        else:
                            # Adiciona linha: Usuario, Senha, Nome, Funcao, PrimeiroAcesso
                            # A ordem aqui DEVE bater com as colunas da planilha (A, B, C, D, E)
                            ws.append_row([new_user, new_pass, new_name, new_role, "TRUE"])
                            st.success(f"Usuário {new_user} criado com sucesso!")
                            st.rerun()
                    else:
                        st.error("Erro de conexão.")
                except Exception as e:
                    st.error(f"Erro ao criar: {e}")
            else:
                st.warning("Preencha todos os campos.")
