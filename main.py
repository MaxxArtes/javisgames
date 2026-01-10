import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware 
from supabase import create_client, Client
import requests 
import logging

# Importar modelos e rotas
from app.modelos import (
    LoginData,
    EmailData,
    InscricaoAulaData,
    MensagemChat,
    ChatMensagemData
)
from app.rotas_admin import router as admin_router

# Configuração básica do Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 1. Carrega as variáveis de ambiente
load_dotenv()

app = FastAPI()

# 2. Configura o CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.javisgameacademy.com.br",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080"
        "http://localhost:5500"
    ], 
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
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")

if not ZAPI_INSTANCE_ID or not ZAPI_TOKEN:
    raise ValueError("Verifique as variáveis ZAPI_INSTANCE_ID e ZAPI_TOKEN no ambiente.")

ZAPI_BASE_URL = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

MAPA_CURSOS = {
    "GAME PRO": "game-pro",
    "DESIGNER START": "designer-start",
    "GAME DEV": "game-dev",
    "STREAMING": "streaming"
}

# Incluir rotas administrativas
app.include_router(admin_router)


# --- FUNÇÕES AUXILIARES ---

def enviar_mensagem_zapi(telefone_destino: str, mensagem_texto: str):
    headers = {"Content-Type": "application/json"}
    payload = {"phone": telefone_destino, "message": mensagem_texto}
    try:
        response = requests.post(ZAPI_BASE_URL, json=payload, headers=headers)
        return response.status_code == 200
    except Exception as e:
        print(f"Erro Z-API: {e}")
        return False


# --- ROTAS PÚBLICAS ---

@app.get("/chat/historico")
def get_historico_aluno(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
        if not aluno_resp.data:
            return []
        id_aluno = aluno_resp.data[0]['id_aluno']
        msgs = supabase.table("tb_chat").select("*").eq("id_aluno", id_aluno).order("created_at").execute()
        return msgs.data
    except Exception as e:
        print(e)
        return []


@app.post("/chat/enviar-aluno")
def enviar_msg_aluno(dados: ChatMensagemData, authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
        if not aluno_resp.data:
            raise HTTPException(status_code=404)
        id_aluno = aluno_resp.data[0]['id_aluno']
        supabase.table("tb_chat").insert({
            "id_aluno": id_aluno,
            "mensagem": dados.mensagem,
            "enviado_por_admin": False
        }).execute()
        return {"message": "Enviado"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/enviar")
def enviar_mensagem_chat(dados: MensagemChat):
    if enviar_mensagem_zapi(dados.telefone, dados.texto):
        return {"message": "Enviado"}
    raise HTTPException(status_code=500)


@app.post("/login")
def realizar_login(dados: LoginData):
    try:
        response = supabase.auth.sign_in_with_password({"email": dados.email, "password": dados.password})
        return {"token": response.session.access_token, "user": {"email": response.user.email}}
    except:
        raise HTTPException(status_code=400, detail="Email ou senha incorretos")


@app.post("/recuperar-senha")
def recuperar_senha(dados: EmailData):
    try:
        supabase.auth.reset_password_email(dados.email)
        return {"message": "Email enviado"}
    except:
        raise HTTPException(status_code=400)


@app.post("/cadastrar")
def realizar_cadastro(dados: InscricaoAulaData):
    try:
        supabase.table("tb_inscricoes").insert({
            "nome": dados.nome,
            "email": dados.email,
            "telefone": dados.telefone,
            "nascimento": dados.nascimento,
            "cidade": dados.cidade,
            "aceitou_termos": dados.aceitou_termos,
            "status": "PENDENTE"
        }).execute()
        return {"message": "Inscrição realizada"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
