import json
import streamlit as st
import pandas as pd
# A linha 'import pandas.api.types' não é necessária aqui.

# Nome do arquivo JSON de usuários
USER_FILE = 'users.json'
DEFAULT_PASSWORD = '12345'

def load_users():
    """Carrega os dados dos usuários do arquivo JSON, forçando a codificação UTF-8."""
    try:
        # Tenta carregar o arquivo existente
        with open(USER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        # Se não existir, retorna um admin inicial e cria o arquivo
        return create_initial_admin_data() 
    except json.JSONDecodeError:
        st.error(f"Erro ao ler o arquivo {USER_FILE}. Verifique a formatação JSON.")
        return {}

def create_initial_admin_data():
    """Cria a estrutura de dados para o admin inicial."""
    admin_data = {
        "admin": {
            "password": DEFAULT_PASSWORD,
            "role": "admin",
            "primeiro_acesso": True,
            "agente": "Admin Master" # Nome de agente de exemplo para o admin
        }
    }
    # Salva o arquivo assim que ele é criado
    save_users(admin_data)
    return admin_data


def save_users(users):
    """Salva os dados dos usuários no arquivo JSON, forçando a codificação UTF-8."""
    try:
        # Usando encoding='utf-8' e ensure_ascii=False para preservar acentos
        with open(USER_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=4, ensure_ascii=False)
    except Exception as e:
        st.error(f"Erro ao salvar o arquivo {USER_FILE}: {e}")

def check_password(username, password):
    """Verifica se a senha do usuário está correta."""
    users = load_users()
    if username in users and users[username]['password'] == password:
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

# 🚨 --- NOVA FUNÇÃO (Deletar Usuário) --- 🚨
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


# 🚨 --- FUNÇÃO ATUALIZADA --- 🚨
def user_manager_interface(df):
    """Interface do Streamlit para o gerenciamento de usuários (apenas Admin)."""
    st.subheader("⚙️ Gerenciamento de Usuários") 

    users = load_users()
    
    # 1. Adicionar Agentes do CSV
    st.markdown("##### ➕ Adicionar Novos Agentes do CSV")
    
    agentes_com_login = {info.get('agente') for info in users.values() if info.get('role') == 'user'}
    
    # Garante que a coluna 'Agente' exista e seja tratada como string
    if 'Agente' in df.columns:
        # Converte tudo para string e remove NaNs/Nones
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
            st.rerun() # Atualiza a interface
        else:
            st.success("Todos os agentes no CSV já possuem login de usuário.")
    else:
        st.warning("Coluna 'Agente' não encontrada no CSV para sincronização automática.")
        
    st.markdown("---")

    # 2.  --- SEÇÃO: CRIAÇÃO MANUAL --- 
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
                st.rerun() # Recarrega para atualizar la tabela
            else:
                st.error(message)

    st.markdown("---")


    # 3. Tabela de Usuários e Permissões
    st.markdown("##### 📝 Usuários Atuais")
    
    user_list = []
    # Recarrega os usuários após possível adição
    users = load_users() 
    for login, info in users.items():
        user_list.append({
            "Login": login,
            "Nome do Agente": info.get('agente', 'N/A'),
            "Função": info.get('role', 'user').capitalize(),
            "Primeiro Acesso": "Sim" if info.get('primeiro_acesso', False) else "Não"
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
                users[user_to_reset]['primeiro_acesso'] = True # Força a mudança
                save_users(users)
                st.success(f"Senha do usuário **{user_to_reset}** redefinida com sucesso. O usuário será forçado a alterar esta senha no próximo login.")
                st.rerun()
            else:
                st.error("Erro ao redefinir a senha.")
        else:
            st.warning("Preencha o campo da nova senha.")

    st.markdown("---")

    # 5. 🚨 --- NOVA SEÇÃO: DELETAR USUÁRIO --- 🚨
    st.markdown("##### ❌ Deletar Usuário")
    st.warning("Atenção: Esta ação é permanente e não pode ser desfeita.")

    # Lista de usuários que podem ser deletados (todos, exceto o admin logado)
    current_admin = st.session_state.get('username')
    users_to_delete = [login for login in users.keys() if login != current_admin]
    
    if not users_to_delete:
        st.info("Nenhum outro usuário disponível para deletar.")
    else:
        user_to_delete = st.selectbox("Selecione o Usuário para Deletar:", users_to_delete, key="select_delete")
        
        # Expander para confirmação de segurança
        with st.expander(f"Confirmar exclusão de '{user_to_delete}'"):
            st.write(f"Você tem certeza que deseja deletar permanentemente o usuário **{user_to_delete}**?")
            
            # Botão de confirmação dentro do expander
            if st.button("Sim, deletar este usuário", type="primary"):
                success, message = delete_user_db(user_to_delete, current_admin)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)
