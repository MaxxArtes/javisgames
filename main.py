import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel
from supabase import create_client, Client
import requests # Essencial para conectar na Z-API

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

# --- CREDENCIAIS Z-API (JÁ CONFIGURADAS) ---
ZAPI_INSTANCE_ID = "3EB841CFDDB82238F05676920E0B7E08"
ZAPI_TOKEN = "9C37DABF607A4D31B7D53FA6"
ZAPI_BASE_URL = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

# --- MODELOS DE DADOS ---
# MODELOS PARA O CHAT
class ChatMensagemData(BaseModel):
    mensagem: str

class ChatAdminReply(BaseModel):
    id_aluno: int
    mensagem: str
    
class LoginData(BaseModel):
    email: str
    password: str

class EmailData(BaseModel):
    email: str

MAPA_CURSOS = {
    "GAME PRO": "game-pro",
    "DESIGNER START": "designer-start",
    "GAME DEV": "game-dev",
    "STREAMING": "streaming"
}

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

# Modelo para inscrição da aula (Site -> Whatsapp)
class InscricaoAulaData(BaseModel):
    nome: str
    email: str
    telefone: str
    nascimento: str
    cidade: str
    aceitou_termos: bool

# Modelo para chat (App -> Whatsapp do Aluno)
class MensagemChat(BaseModel):
    telefone: str # Número do aluno (destino)
    texto: str    # O que o funcionário digitou

# --- FUNÇÃO AUXILIAR DE ENVIO (Z-API) ---
def enviar_mensagem_zapi(telefone_destino: str, mensagem_texto: str):
    """
    Função centralizada para enviar mensagens via Z-API.
    """
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "phone": telefone_destino, 
        "message": mensagem_texto
    }

    try:
        response = requests.post(ZAPI_BASE_URL, json=payload, headers=headers)
        
        if response.status_code == 200:
            print(f"✅ Z-API Sucesso para {telefone_destino}")
            return True
        else:
            print(f"❌ Z-API Erro ({response.status_code}): {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Erro de conexão Z-API: {e}")
        return False

# --- ROTAS DO SISTEMA ---

@app.get("/admin/meus-dados")
def get_dados_funcionario(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token ausente")

    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        response = supabase.table("tb_colaboradores")\
            .select("nome_completo, id_cargo, tb_cargos(nome_cargo, nivel_acesso)")\
            .eq("user_id", user_id)\
            .eq("ativo", True)\
            .execute()

        if not response.data:
            raise HTTPException(status_code=403, detail="Usuário não é um colaborador ativo.")

        funcionario = response.data[0]
        
        return {
            "nome": funcionario['nome_completo'],
            "cargo": funcionario['tb_cargos']['nome_cargo'],
            "nivel": funcionario['tb_cargos']['nivel_acesso']
        }

    except Exception as e:
        print(f"Erro Auth Funcionario: {e}")
        raise HTTPException(status_code=403, detail="Acesso negado")

@app.post("/admin/cadastrar-aluno")
def admin_cadastrar_aluno(dados: NovoAlunoData, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
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
        print(f"Erro Cadastro: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/admin/listar-alunos")
def admin_listar_alunos():
    try:
        response = supabase.table("tb_alunos").select("*, tb_matriculas(codigo_turma, status_financeiro)").execute()
        return response.data
    except Exception as e:
        return []

@app.post("/admin/agendar-reposicao")
def admin_reposicao(dados: ReposicaoData, authorization: str = Header(None)):
    try:
        supabase.table("tb_reposicoes").insert({
            "id_aluno": dados.id_aluno,
            "data_reposicao": dados.data_hora,
            "motivo": dados.motivo
        }).execute()
        return {"message": "Reposição agendada"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/admin/agenda-geral")
def admin_agenda():
    try:
        turmas = supabase.table("tb_turmas").select("*").execute()
        
        reposicoes = supabase.table("tb_reposicoes")\
            .select("data_reposicao, tb_alunos(nome_completo)")\
            .execute()

        eventos = []

        for rep in reposicoes.data:
            eventos.append({
                "title": f"Reposição: {rep['tb_alunos']['nome_completo']}",
                "start": rep['data_reposicao'],
                "color": "#ff4d4d" 
            })

        return eventos

    except Exception as e:
        return []

@app.get("/meus-cursos-permitidos")
def get_cursos_permitidos(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token ausente")

    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
        
        if not aluno_resp.data:
            return {"cursos": []}

        id_aluno = aluno_resp.data[0]['id_aluno']

        response = supabase.table("tb_matriculas")\
            .select("codigo_turma, data_matricula, tb_turmas(nome_curso)")\
            .eq("id_aluno", id_aluno)\
            .execute()

        liberados = []
        for item in response.data:
            if item.get('tb_turmas'):
                nome_banco = item['tb_turmas']['nome_curso']
                
                if nome_banco in MAPA_CURSOS:
                    liberados.append({
                        "id": MAPA_CURSOS[nome_banco],       
                        "data_inicio": item['data_matricula'] 
                    })
        
        return {"cursos": liberados}

    except Exception as e:
        print(f"Erro Permissões: {e}")
        return {"cursos": []}
        
@app.post("/recuperar-senha")
def recuperar_senha(dados: EmailData):
    try:
        site_url = "https://www.javisgameacademy.com.br/RedefinirSenha.html" 
        
        supabase.auth.reset_password_email(dados.email, options={
            "redirect_to": site_url
        })
        
        return {"message": "Email de recuperação enviado com sucesso"}
    except Exception as e:
        print(f"Erro recuperação: {e}")
        raise HTTPException(status_code=400, detail="Erro ao enviar email.")

@app.post("/login")
def realizar_login(dados: LoginData):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": dados.email, 
            "password": dados.password
        })
        return {"token": response.session.access_token, "user": { "email": response.user.email }}
    except Exception as e:
        print(f"Erro no login: {e}") 
        raise HTTPException(status_code=400, detail="Email ou senha incorretos")

# --- INTEGRAÇÃO Z-API (NOTIFICAÇÃO DE AULA) ---

@app.post("/inscrever-aula")
def inscrever_aula(dados: InscricaoAulaData):
    try:
        # SEU NÚMERO PARA RECEBER O AVISO
        numero_admin = "5565981350686"
        
        # Formata a mensagem com emojis
        mensagem = (
            f"🎮 *NOVA INSCRIÇÃO - AULA EXPERIMENTAL*\n\n"
            f"👤 *Nome:* {dados.nome}\n"
            f"📧 *Email:* {dados.email}\n"
            f"📱 *Whatsapp:* {dados.telefone}\n"
            f"🎂 *Nasc:* {dados.nascimento}\n"
            f"🏙 *Cidade:* {dados.cidade}\n"
            f"✅ *Termos:* {'Aceito' if dados.aceitou_termos else 'Não'}"
        )
        
        # Envia via Z-API
        enviar_mensagem_zapi(numero_admin, mensagem)
        
        return {"message": "Inscrição recebida com sucesso!"}
            
    except Exception as e:
        print(f"Erro crítico: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")

# --- INTEGRAÇÃO Z-API (CHAT DO SISTEMA) ---

@app.post("/chat/enviar")
def enviar_mensagem_chat(dados: MensagemChat):
    """
    Envia mensagem para o aluno diretamente pelo WhatsApp da empresa
    """
    print(f"--- APP: Enviando msg para {dados.telefone} ---")
    
    sucesso = enviar_mensagem_zapi(dados.telefone, dados.texto)
    
    if sucesso:
        return {"message": "Enviado com sucesso via Z-API"}
    else:
        raise HTTPException(status_code=500, detail="Erro ao enviar mensagem no WhatsApp")

# --- ROTAS DE SUPORTE (CHAT INTERNO) ---

# 1. Aluno envia mensagem ou busca histórico
@app.get("/chat/historico")
def get_historico_aluno(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    
    # Pega ID do aluno pelo Token
    token = authorization.split(" ")[1]
    user = supabase.auth.get_user(token)
    aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user.user.id).execute()
    
    if not aluno_resp.data: return []
    id_aluno = aluno_resp.data[0]['id_aluno']

    # Busca mensagens
    msgs = supabase.table("tb_chat").select("*").eq("id_aluno", id_aluno).order("created_at").execute()
    return msgs.data

@app.post("/chat/enviar-aluno")
def enviar_msg_aluno(dados: ChatMensagemData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)

    token = authorization.split(" ")[1]
    user = supabase.auth.get_user(token)
    aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user.user.id).execute()
    
    if not aluno_resp.data: raise HTTPException(status_code=404, detail="Aluno não encontrado")
    id_aluno = aluno_resp.data[0]['id_aluno']

    supabase.table("tb_chat").insert({
        "id_aluno": id_aluno,
        "mensagem": dados.mensagem,
        "enviado_por_admin": False
    }).execute()
    
    return {"message": "Enviado"}

# 2. Admin (Funcionário) lista conversas e responde

@app.get("/admin/chat/conversas-ativas")
def admin_listar_conversas_ativas():
    # Retorna lista de alunos que mandaram mensagem recentemente (Distinct)
    # Nota: Em SQL puro seria mais fácil fazer um DISTINCT ON, aqui faremos via lógica simples
    try:
        # Pega todas as mensagens e agrupa no python (para simplificar sem criar views complexas agora)
        msgs = supabase.table("tb_chat").select("id_aluno, mensagem, created_at, tb_alunos(nome_completo)").order("created_at", desc=True).limit(200).execute()
        
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
        print(e)
        return []

@app.get("/admin/chat/mensagens/{id_aluno}")
def admin_ler_mensagens(id_aluno: int):
    msgs = supabase.table("tb_chat").select("*").eq("id_aluno", id_aluno).order("created_at").execute()
    return msgs.data

@app.post("/admin/chat/responder")
def admin_responder(dados: ChatAdminReply):
    supabase.table("tb_chat").insert({
        "id_aluno": dados.id_aluno,
        "mensagem": dados.mensagem,
        "enviado_por_admin": True
    }).execute()
    return {"message": "Respondido"}

