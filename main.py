import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel
from supabase import create_client, Client
import requests  # <--- Biblioteca necessária para o CallMeBot

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

# --- MODELOS DE DADOS EXISTENTES ---
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

# --- MODELO PARA INSCRIÇÃO DA AULA (WHATSAPP) ---
class InscricaoAulaData(BaseModel):
    nome: str
    email: str
    telefone: str
    nascimento: str
    cidade: str
    aceitou_termos: bool

# --- ROTAS ADMINISTRATIVAS & ALUNO ---

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

# --- INTEGRAÇÃO WHATSAPP (CALLMEBOT) ---

def enviar_whatsapp_api(dados: InscricaoAulaData):
    # DADOS REAIS QUE VOCÊ FORNECEU
    phone_number = "556581350686"
    apikey = "4578856"
    
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
    
    # URL da API Gratuita
    url = f"https://api.callmebot.com/whatsapp.php"
    
    try:
        print(f"--- Enviando notificação para {phone_number} ---")
        # Envia a requisição para o bot
        requests.get(url, params={"phone": phone_number, "text": mensagem, "apikey": apikey})
        return True
            
    except Exception as e:
        print(f"Erro de conexão no envio: {e}")
        # Retorna False mas não trava o sistema
        return False

@app.post("/inscrever-aula")
def inscrever_aula(dados: InscricaoAulaData):
    try:
        # 1. Dispara o WhatsApp
        enviar_whatsapp_api(dados)
        
        # 2. Retorna sucesso para o site
        return {"message": "Inscrição recebida com sucesso!"}
            
    except Exception as e:
        print(f"Erro crítico: {e}")
        # Retorna erro 500 se algo muito grave acontecer
        raise HTTPException(status_code=500, detail="Erro interno")

# Modelo de dados que o App vai mandar
class MensagemChat(BaseModel):
    telefone: str # Número do aluno (destino)
    texto: str    # O que o funcionário digitou

@app.post("/chat/enviar")
def enviar_mensagem_chat(dados: MensagemChat):
    print(f"--- APP: Enviando msg para {dados.telefone} ---")
    
    # AQUI CONFIGURAMOS O ENVIO
    # Como o CallMeBot Grátis só manda para o SEU número cadastrado,
    # vamos usar o seu número como destino para testar a integração.
    
    meu_numero_admin = "5565992532020" # Seu número que tem a API Key
    minha_apikey = "4578856"
    
    # Montamos um aviso para você saber que funcionou
    texto_formatado = (
        f"📱 *Simulação de Envio para Aluno*\n"
        f"Para: {dados.telefone}\n"
        f"Msg: {dados.texto}"
    )
    
    url = "https://api.callmebot.com/whatsapp.php"
    
    try:
        # Envia a requisição
        requests.get(url, params={
            "phone": meu_numero_admin, 
            "text": texto_formatado, 
            "apikey": minha_apikey
        })
        return {"message": "Enviado com sucesso (Modo Teste)"}
    except Exception as e:
        print(f"Erro chat: {e}")
        raise HTTPException(status_code=500, detail="Erro no envio")

