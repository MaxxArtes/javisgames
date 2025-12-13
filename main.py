import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel
from supabase import create_client, Client
import requests 

# 1. Carrega as variáveis de ambiente
load_dotenv()

app = FastAPI()

# 2. Configura o CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Configura o Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    raise ValueError("Verifique o arquivo .env, as chaves não foram encontradas.")

supabase: Client = create_client(url, key)

# --- CREDENCIAIS Z-API ---
ZAPI_INSTANCE_ID = "3EB841CFDDB82238F05676920E0B7E08"
ZAPI_TOKEN = "9C37DABF607A4D31B7D53FA6"
ZAPI_BASE_URL = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

# --- ADICIONE ESTE MODELO NO INÍCIO JUNTO COM OS OUTROS ---
class PerfilUpdateData(BaseModel):
    nome: str | None = None
    telefone: str | None = None
    email_contato: str | None = None
    email_login: str | None = None
    nova_senha: str | None = None

# --- MODELOS DE DADOS ---
class LoginData(BaseModel):
    email: str
    password: str

class EmailData(BaseModel):
    email: str

class NovoAlunoData(BaseModel):
    nome: str
    email: str
    cpf: str
    senha: str
    turma_codigo: str 

class ReposicaoData(BaseModel):
    id_aluno: int
    data_hora: str 
    motivo: str

class InscricaoAulaData(BaseModel):
    nome: str
    email: str
    telefone: str
    nascimento: str
    cidade: str
    aceitou_termos: bool

class MensagemChat(BaseModel):
    telefone: str 
    texto: str    

class ChatMensagemData(BaseModel):
    mensagem: str

class ChatAdminReply(BaseModel):
    id_aluno: int
    mensagem: str

class StatusUpdateData(BaseModel):
    status: str

MAPA_CURSOS = {
    "GAME PRO": "game-pro",
    "DESIGNER START": "designer-start",
    "GAME DEV": "game-dev",
    "STREAMING": "streaming"
}

# --- FUNÇÃO AUXILIAR Z-API ---
def enviar_mensagem_zapi(telefone_destino: str, mensagem_texto: str):
    headers = {"Content-Type": "application/json"}
    payload = {"phone": telefone_destino, "message": mensagem_texto}
    try:
        response = requests.post(ZAPI_BASE_URL, json=payload, headers=headers)
        return response.status_code == 200
    except Exception as e:
        print(f"Erro Z-API: {e}")
        return False

# --- ROTAS ---

@app.get("/admin/meus-dados")
def get_dados_funcionario(authorization: str = Header(None)):
    # ... (código de verificação do token igual) ...
    try:
        # ... (busca usuario) ...
        
        # MUDANÇA AQUI: Adicione 'telefone, email' e 'id_colaborador' no select
        response = supabase.table("tb_colaboradores")\
            .select("id_colaborador, nome_completo, telefone, email, id_cargo, tb_cargos!fk_cargos(nome_cargo, nivel_acesso)")\
            .eq("user_id", user_id)\
            .eq("ativo", True)\
            .execute()
            
        # ... (verificação se existe) ...
        
        funcionario = response.data[0]
        
        return {
            "id_colaborador": funcionario['id_colaborador'], # NOVO
            "nome": funcionario['nome_completo'],
            "telefone": funcionario['telefone'], # NOVO
            "email_contato": funcionario['email'], # NOVO
            "cargo": funcionario['tb_cargos']['nome_cargo'],
            "nivel": funcionario['tb_cargos']['nivel_acesso']
        }
    except Exception as e:
        print(f"Erro ao buscar dados do funcionário: {e}")
        raise HTTPException(status_code=403, detail="Acesso negado ou erro interno")

@app.post("/admin/cadastrar-aluno")
def admin_cadastrar_aluno(dados: NovoAlunoData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        user_auth = supabase.auth.admin.create_user({
            "email": dados.email,
            "password": dados.senha,
            "email_confirm": True 
        })
        new_user_id = user_auth.user.id
        aluno_resp = supabase.table("tb_alunos").insert({
            "nome_completo": dados.nome,
            "cpf": dados.cpf,
            "user_id": new_user_id
        }).execute()
        novo_id_aluno = aluno_resp.data[0]['id_aluno']
        supabase.table("tb_matriculas").insert({
            "id_aluno": novo_id_aluno,
            "codigo_turma": dados.turma_codigo,
            "status_financeiro": "Pago"
        }).execute()
        return {"message": "Aluno cadastrado com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/admin/listar-alunos")
def admin_listar_alunos():
    try:
        response = supabase.table("tb_alunos").select("*, tb_matriculas(codigo_turma, status_financeiro)").execute()
        return response.data
    except: return []

@app.post("/admin/agendar-reposicao")
def admin_reposicao(dados: ReposicaoData):
    try:
        supabase.table("tb_reposicoes").insert({
            "id_aluno": dados.id_aluno,
            "data_reposicao": dados.data_hora,
            "motivo": dados.motivo
        }).execute()
        return {"message": "Agendada"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/admin/agenda-geral")
def admin_agenda():
    try:
        reposicoes = supabase.table("tb_reposicoes").select("data_reposicao, tb_alunos(nome_completo)").execute()
        eventos = []
        for rep in reposicoes.data:
            eventos.append({
                "title": f"Reposição: {rep['tb_alunos']['nome_completo']}",
                "start": rep['data_reposicao'],
                "color": "#ff4d4d" 
            })
        return eventos
    except: return []

@app.get("/meus-cursos-permitidos")
def get_cursos_permitidos(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
        if not aluno_resp.data: return {"cursos": []}
        id_aluno = aluno_resp.data[0]['id_aluno']
        response = supabase.table("tb_matriculas").select("codigo_turma, data_matricula, tb_turmas(nome_curso)").eq("id_aluno", id_aluno).execute()
        liberados = []
        for item in response.data:
            if item.get('tb_turmas'):
                nome_banco = item['tb_turmas']['nome_curso']
                if nome_banco in MAPA_CURSOS:
                    liberados.append({"id": MAPA_CURSOS[nome_banco], "data_inicio": item['data_matricula']})
        return {"cursos": liberados}
    except: return {"cursos": []}

@app.post("/recuperar-senha")
def recuperar_senha(dados: EmailData):
    try:
        site_url = "https://www.javisgameacademy.com.br/RedefinirSenha.html" 
        supabase.auth.reset_password_email(dados.email, options={"redirect_to": site_url})
        return {"message": "Email enviado"}
    except: raise HTTPException(status_code=400, detail="Erro ao enviar email.")

@app.post("/login")
def realizar_login(dados: LoginData):
    try:
        response = supabase.auth.sign_in_with_password({"email": dados.email, "password": dados.password})
        return {"token": response.session.access_token, "user": { "email": response.user.email }}
    except: raise HTTPException(status_code=400, detail="Email ou senha incorretos")

@app.post("/inscrever-aula")
def inscrever_aula(dados: InscricaoAulaData):
    try:
        numero_admin = "5565981350686"
        mensagem = f"🎮 *NOVA INSCRIÇÃO*\n👤 {dados.nome}\n📧 {dados.email}\n📱 {dados.telefone}"
        enviar_mensagem_zapi(numero_admin, mensagem)
        return {"message": "Sucesso"}
    except: raise HTTPException(status_code=500)

@app.post("/chat/enviar")
def enviar_mensagem_chat(dados: MensagemChat):
    if enviar_mensagem_zapi(dados.telefone, dados.texto):
        return {"message": "Enviado"}
    raise HTTPException(status_code=500)

# --- ROTAS DO NOVO CHAT INTERNO (SUPORTE) ---

@app.get("/chat/historico")
def get_historico_aluno(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
        if not aluno_resp.data: return []
        id_aluno = aluno_resp.data[0]['id_aluno']
        msgs = supabase.table("tb_chat").select("*").eq("id_aluno", id_aluno).order("created_at").execute()
        return msgs.data
    except Exception as e:
        print(e)
        return []

@app.post("/chat/enviar-aluno")
def enviar_msg_aluno(dados: ChatMensagemData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
        if not aluno_resp.data: raise HTTPException(status_code=404)
        id_aluno = aluno_resp.data[0]['id_aluno']
        supabase.table("tb_chat").insert({
            "id_aluno": id_aluno,
            "mensagem": dados.mensagem,
            "enviado_por_admin": False
        }).execute()
        return {"message": "Enviado"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/chat/conversas-ativas")
def admin_listar_conversas_ativas(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token ausente")

    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        # --- CORREÇÃO AQUI TAMBÉM: Usando !fk_cargos para especificar a relação ---
        colab_resp = supabase.table("tb_colaboradores")\
            .select("id_colaborador, id_cargo, tb_cargos!fk_cargos(nivel_acesso)")\
            .eq("user_id", user_id)\
            .execute()

        if not colab_resp.data:
            raise HTTPException(status_code=403, detail="Colaborador não encontrado")

        colaborador = colab_resp.data[0]
        meu_id_colaborador = colaborador['id_colaborador']
        nivel_acesso = colaborador['tb_cargos']['nivel_acesso']

        lista_alunos_permitidos = []
        filtrar_por_aluno = False

        # Se não for admin/gerente (nível < 8), aplica filtro
        if nivel_acesso < 8:
            filtrar_por_aluno = True
            
            turmas_resp = supabase.table("tb_turmas")\
                .select("codigo_turma")\
                .eq("id_professor", meu_id_colaborador)\
                .execute()
            
            codigos_turmas = [t['codigo_turma'] for t in turmas_resp.data]

            if not codigos_turmas:
                return [] # Sem turmas, sem alunos

            matriculas_resp = supabase.table("tb_matriculas")\
                .select("id_aluno")\
                .in_("codigo_turma", codigos_turmas)\
                .execute()
            
            lista_alunos_permitidos = [m['id_aluno'] for m in matriculas_resp.data]
            
            if not lista_alunos_permitidos:
                return [] 

        query = supabase.table("tb_chat").select("id_aluno, mensagem, created_at, tb_alunos(nome_completo)")\
            .order("created_at", desc=True).limit(300)
        
        if filtrar_por_aluno:
            query = query.in_("id_aluno", lista_alunos_permitidos)
            
        msgs = query.execute()
        
        conversas = {}
        for m in msgs.data:
            aid = m['id_aluno']
            if aid not in conversas:
                conversas[aid] = {
                    "id_aluno": aid,
                    "nome": m['tb_alunos']['nome_completo'],
                    "ultima_msg": m['mensagem'],
                    "data": m['created_at']
                }
        
        return list(conversas.values())

    except Exception as e:
        print(f"Erro ao listar conversas: {e}")
        return []

@app.get("/admin/chat/mensagens/{id_aluno}")
def admin_ler_mensagens(id_aluno: int):
    msgs = supabase.table("tb_chat").select("*").eq("id_aluno", id_aluno).order("created_at").execute()
    return msgs.data

@app.post("/admin/chat/responder")
def admin_responder(dados: ChatAdminReply):
    try:
        supabase.table("tb_chat").insert({
            "id_aluno": dados.id_aluno,
            "mensagem": dados.mensagem,
            "enviado_por_admin": True
        }).execute()
        return {"message": "Respondido"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- NOVAS ROTAS CRM ---

@app.get("/admin/leads-crm")
def get_leads_crm(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    
    try:
        # Debug 1: Confirmar token
        print("Iniciando busca CRM...")
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        
        # Debug 2: Ver o que o Supabase retorna
        resp_insc = supabase.table("inscricoes").select("*").order("created_at", desc=True).execute()
        print(f"Inscrições encontradas: {len(resp_insc.data)}") # Vai aparecer no log do Render
        
        leads = resp_insc.data

        # Busca CPFs dos alunos para comparação
        resp_alunos = supabase.table("tb_alunos").select("cpf").execute()
        cpfs_alunos = set()
        for a in resp_alunos.data:
            if a.get('cpf'):
                # Limpa o CPF (remove pontos e traços) para comparação
                cpfs_alunos.add( ''.join(filter(str.isdigit, a['cpf'])) )

        resultado = []
        for lead in leads:
            cpf_lead_limpo = ''.join(filter(str.isdigit, lead.get('cpf', '') or ''))
            is_aluno = cpf_lead_limpo in cpfs_alunos and cpf_lead_limpo != ''
            
            resultado.append({
                "id": lead['id'],
                "nome": lead['nome'],
                "cpf": lead.get('cpf', '---'),
                "whatsapp": lead['whatsapp'],
                "workshop": lead['workshop'],
                "data_agendada": lead['data_agendada'],
                "status": lead.get('status', 'Pendente'),
                "vendedor": lead.get('vendedor', '---'),
                "ja_e_aluno": is_aluno
            })
        return resultado
    except Exception as e:
        print(f"Erro CRM: {e}")
        raise HTTPException(status_code=500, detail="Erro ao processar leads")

@app.patch("/admin/leads-crm/{id_inscricao}")
def atualizar_status_lead(id_inscricao: int, dados: StatusUpdateData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        
        # Identifica o colaborador logado para registrar no lead
        resp_colab = supabase.table("tb_colaboradores").select("nome_completo").eq("user_id", user_id).execute()
        if not resp_colab.data:
            raise HTTPException(status_code=403, detail="Colaborador não encontrado")
            
        nome_vendedor = resp_colab.data[0]['nome_completo']

        supabase.table("inscricoes").update({
            "status": dados.status,
            "vendedor": nome_vendedor
        }).eq("id", id_inscricao).execute()
        
        return {"message": "Status atualizado", "vendedor": nome_vendedor}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@app.patch("/admin/meus-dados")
def atualizar_meu_perfil(dados: PerfilUpdateData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        # 1. Atualizar Tabela Pública (tb_colaboradores)
        updates_tabela = {}
        if dados.nome:
            updates_tabela["nome_completo"] = dados.nome.upper() # Força Maiúsculo
        if dados.telefone:
            updates_tabela["telefone"] = dados.telefone
        if dados.email_contato:
            updates_tabela["email"] = dados.email_contato
            
        if updates_tabela:
            supabase.table("tb_colaboradores").update(updates_tabela).eq("user_id", user_id).execute()

        # 2. Atualizar Autenticação (Login / Senha)
        # Nota: Alterar email de login geralmente envia um email de confirmação pelo Supabase
        updates_auth = {}
        if dados.email_login:
            updates_auth["email"] = dados.email_login
        if dados.nova_senha and len(dados.nova_senha) >= 6:
            updates_auth["password"] = dados.nova_senha
            
        if updates_auth:
            supabase.auth.update_user(updates_auth)

        return {"message": "Perfil atualizado com sucesso!"}

    except Exception as e:
        print(f"Erro ao atualizar perfil: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao atualizar dados.")


