import json
import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe, get_as_dataframe
from google.oauth2.service_account import Credentials

# --- Configurações ---
# O URL é pego dos "Segredos" do Streamlit, não fica no código.
WORKSHEET_NAME = "Página1" 
DEFAULT_PASSWORD = '12345'

# Define os "escopos" (permissões) que o gspread precisa
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# --- Funções de Conexão (NOVAS, usando gspread) ---

def get_connection():
    """Conecta ao Google Sheets usando os Segredos do Streamlit."""
    try:
        # Pega as credenciais JSON dos "Segredos" do Streamlit
        creds_json = st.secrets["connections"]["gsheets"]["service_account_info"]
        creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
        client = gspread.authorize(creds)
        
        # Pega o URL da planilha dos "Segredos"
        spreadsheet_url = st.secrets["spreadsheet_url"]
        spreadsheet = client.open_by_url(spreadsheet_url)
        
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        return worksheet
    except KeyError:
        st.error("Erro: 'connections.gsheets' ou 'spreadsheet_url' não encontrados nos Segredos (Secrets) do Streamlit. Verifique a Etapa 5.")
        return None
    except Exception as e:
        st.error(f"Não foi possível conectar ao Google Sheets: {e}")
        return None

def load_users_df():
    """Carrega a planilha inteira de usuários como um DataFrame."""
    worksheet = get_connection()
    if worksheet is None:
        return pd.DataFrame(columns=["username", "password", "role", "agente", "primeiro_acesso"])
    try:
        # Usa gspread-dataframe para ler a planilha
        df = get_as_dataframe(worksheet, evaluate_formulas=True)
        # Garante que as colunas esperadas existam
        for col in ["username", "password", "role", "agente", "primeiro_acesso"]:
             if col not in df.columns:
                 df[col] = pd.NA
                 
        # Limpa linhas vazias
        df = df.dropna(subset=['username'])
        # Garante que 'primeiro_acesso' seja lido como Booleano
        df['primeiro_acesso'] = df['primeiro_acesso'].map({'TRUE': True, 'FALSE': False, True: True, False: False}).fillna(True)
        # Garante que a senha seja string
        df['password'] = df['password'].astype(str)
        return df
    except Exception as e:
        st.error(f"Não foi possível ler os dados do Google Sheets: {e}")
        return pd.DataFrame(columns=["username", "password", "role", "agente", "primeiro_acesso"])

def save_users_df(df):
    """Salva (sobrescreve) o DataFrame inteiro de volta no Google Sheets."""
    worksheet = get_connection()
    if worksheet is None:
        return
    try:
        # Garante que 'primeiro_acesso' seja salvo como string 'TRUE'/'FALSE'
        df['primeiro_acesso'] = df['primeiro_acesso'].map({True: 'TRUE', False: 'FALSE'})
        worksheet.clear() # Limpa a planilha
        set_with_dataframe(worksheet, df) # Escreve o DataFrame de volta
    except Exception as e:
        st.error(f"Falha ao salvar usuários no Google Sheets: {e}")

def load_users():
    """Converte o DataFrame de usuários para o formato de dicionário que o app espera."""
    df_users = load_users_df()
    if df_users.empty:
        st.error("O banco de dados de usuários (Google Sheet) está vazio ou não foi encontrado.")
        return {}
    
    # Converte o DataFrame para o dicionário: {username: {password: '123', ...}}
    users_dict = df_users.set_index('username').to_dict('index')
    return users_dict

def save_users(users_dict):
    """Converte o dicionário de usuários de volta para DataFrame e salva."""
    df = pd.DataFrame.from_dict(users_dict, orient='index')
    df = df.reset_index().rename(columns={'index': 'username'})
    save_users_df(df)

# --- Funções de Lógica de Autenticação (Modificadas para usar load/save) ---

def check_password(username, password):
    """Verifica se a senha do usuário está correta."""
    users = load_users()
    if username in users and users[username]['password'] == str(password): # Garante comparação de string
        return True
    return False

def get_user_info(username):
    """Retorna o dicionário de informações do usuário."""
    users = load_users()
    return users.get(username, {})

def change_password_db(username, new_password):
    """Altera a senha do usuário e marca o primeiro acesso como falso."""
    users = load_users()
    if username in users:
        users[username]['password'] = new_password
        users[username]['primeiro_acesso'] = False
        save_users(users)
        return True
    return False

def add_user_from_csv(login, nome_agente):
    """Adiciona um novo usuário (agente) com senha padrão, se não existir."""
    users = load_users()
    if login not in users:
        new_user = {
            "password": DEFAULT_PASSWORD,
            "role": "user",
            "primeiro_acesso": True,
            "agente": nome_agente
        }
        users[login] = new_user
        save_users(users)
        return True
    return False

def add_manual_user(login, nome_agente, role):
    """Adiciona um novo usuário manualmente (admin, user) com senha padrão."""
    users = load_users()
    if not login or not nome_agente:
        return False, "Login e Nome do Agente são obrigatórios."
    if login in users:
        return False, f"O login '{login}' já existe."
    
    new_user = {
        "password": DEFAULT_PASSWORD,
        "role": role,
        "primeiro_acesso": True,
        "agente": nome_agente
    }
    users[login] = new_user
    save_users(users)
    return True, f"Usuário '{login}' criado com sucesso."

def delete_user_db(username_to_delete, current_admin_username):
    """Deleta um usuário do arquivo JSON."""
    if username_to_delete == current_admin_username:
        return False, "Você não pode deletar a si mesmo."
        
    users = load_users()
    if username_to_delete in users:
        del users[username_to_delete]
        save_users(users)
        return True, f"Usuário '{username_to_delete}' deletado com sucesso."
    else:
        return False, f"Usuário '{username_to_delete}' não encontrado."

# --- Interface do Admin (Inalterada, mas agora usa as novas funções) ---

def user_manager_interface(df):
    """Interface do Streamlit para o gerenciamento de usuários (apenas Admin)."""
    st.subheader("⚙️ Gerenciamento de Usuários") 

    users = load_users()
    
    # 1. Adicionar Agentes do CSV
    st.markdown("##### ➕ Adicionar Novos Agentes do CSV")
    
    agentes_com_login = {info.get('agente') for info in users.values() if info.get('role') == 'user'}
    
    if 'Agente' in df.columns:
        df['Agente'] = df['Agente'].fillna('').astype(str).str.strip()
        agentes_no_csv = set(df[df['Agente'] != '']['Agente'].unique())
        agentes_a_adicionar = agentes_no_csv - agentes_com_login

        if agentes_a_adicionar:
            st.info(f"Encontrados **{len(agentes_a_adicionar)}** novos agentes no CSV que não possuem login.")
            for agente in sorted(list(agentes_a_adicionar)):
                login_sugerido = agente.lower().replace(" ", ".").replace("-", "")
                counter = 1
                original_login = login_sugerido
                while login_sugerido in users:
                    login_sugerido = f"{original_login}{counter}"
                    counter += 1
                add_user_from_csv(login_sugerido, agente)
            st.success("Novos usuários adicionados com sucesso! Senha padrão: **12345**.")
            st.rerun() 
        else:
            st.success("Todos os agentes no CSV já possuem login de usuário.")
    else:
        st.warning("Coluna 'Agente' não encontrada no CSV para sincronização automática.")
        
    st.markdown("---")

    # 2. SEÇÃO: CRIAÇÃO MANUAL
    st.markdown("##### ➕ Criar Novo Usuário Manualmente")
    with st.form("manual_add_form", clear_on_submit=True):
        st.write("Crie um novo login para um agente ou um novo administrador. A senha padrão será **12345**.")
        col1, col2 = st.columns(2)
        with col1:
            new_login = st.text_input("Novo Login (ex: joao.silva)")
            new_agente_name = st.text_input("Nome do Agente (Nome de exibição)")
        with col2:
            new_role = st.selectbox("Função", ["user", "admin"], help="User: vê apenas seus dados. Admin: vê tudo.")
        
        submitted = st.form_submit_button("Criar Usuário")
        
        if submitted:
            success, message = add_manual_user(new_login, new_agente_name, new_role)
            if success:
                st.success(message)
                st.rerun() 
            else:
                st.error(message)

    st.markdown("---")

    # 3. Tabela de Usuários e Permissões
    st.markdown("##### 📝 Usuários Atuais")
    
    user_list = []
    users = load_users() 
    for login, info in users.items():
        user_list.append({
            "Login": login,
            "Nome do Agente": info.get('agente', 'N/A'),
            "Função": info.get('role', 'user').capitalize(),
            "Primeiro Acesso": "Sim" if info.get('primeiro_acesso', True) else "Não" # Padrão True
        })

    df_users = pd.DataFrame(user_list)
    st.dataframe(df_users, use_container_width=True)
    
    st.markdown("---")

    # 4. Alteração de Senha de Outros Usuários
    st.markdown("##### 🔑 Redefinir Senha de Usuário")
    
    users_to_reset = [login for login in users.keys() if login != st.session_state.get('username')]
    
    col1, col2 = st.columns(2)
    with col1:
        if users_to_reset:
            user_to_reset = st.selectbox("Selecione o Usuário (para Redefinir Senha):", users_to_reset, key="select_reset")
        else:
            user_to_reset = None
            st.info("Nenhum outro usuário disponível para redefinição.")
    with col2:
        new_pass_reset = st.text_input("Nova Senha:", type="password", key="reset_pass")

    if st.button("Redefinir Senha do Usuário") and user_to_reset:
        if new_pass_reset:
            if change_password_db(user_to_reset, new_pass_reset):
                users = load_users() 
                users[user_to_reset]['primeiro_acesso'] = True 
                save_users(users)
                st.success(f"Senha do usuário **{user_to_reset}** redefinida com sucesso.")
                st.rerun()
            else:
                st.error("Erro ao redefinir a senha.")
        else:
            st.warning("Preencha o campo da nova senha.")

    st.markdown("---")

    # 5. SEÇÃO: DELETAR USUÁRIO
    st.markdown("##### ❌ Deletar Usuário")
    st.warning("Atenção: Esta ação é permanente e não pode ser desfeita.")

    current_admin = st.session_state.get('username')
    users_to_delete = [login for login in users.keys() if login != current_admin]
    
    if not users_to_delete:
        st.info("Nenhum outro usuário disponível para deletar.")
    else:
        user_to_delete = st.selectbox("Selecione o Usuário para Deletar:", users_to_delete, key="select_delete")
        
        with st.expander(f"Confirmar exclusão de '{user_to_delete}'"):
            st.write(f"Você tem certeza que deseja deletar permanentemente o usuário **{user_to_delete}**?")
            
            if st.button("Sim, deletar este usuário", type="primary"):
                success, message = delete_user_db(user_to_delete, current_admin)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)