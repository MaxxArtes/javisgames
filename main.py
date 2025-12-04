import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # <--- Necessário para o navegador deixar conectar
from pydantic import BaseModel
from supabase import create_client, Client
from fastapi import Header
import uuid

# 1. Carrega as variáveis
load_dotenv()

app = FastAPI()

# 2. Configura o CORS (Permite que seu HTML fale com o Python)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Em produção, troque "*" pelo seu domínio ex: "https://meusite.com"
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

class LoginData(BaseModel):
    email: str
    password: str

# Adicione essa classe para validar o dado que chega
class EmailData(BaseModel):
    email: str

MAPA_CURSOS = {
    "GAME PRO": "game-pro",
    "DESIGNER START": "designer-start",
    "GAME DEV": "game-dev",
    "STREAMING": "streaming"
}

# --- MODELOS NOVOS ---
class NovoAlunoData(BaseModel):
    nome: str
    email: str
    cpf: str
    senha: str
    turma_codigo: str # Ex: 'TURMA-GP-01'

class ReposicaoData(BaseModel):
    id_aluno: int
    data_hora: str # Formato ISO '2025-12-01T14:00:00'
    motivo: str

# --- ROTAS ADMINISTRATIVAS ---

@app.get("/admin/meus-dados")
def get_dados_funcionario(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token ausente")

    try:
        # 1. Pega o ID do usuário logado (do Supabase Auth)
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        # 2. Busca na tabela tb_colaboradores E tb_cargos
        # O select usa a sintaxe de join do Supabase: tb_cargos(nome_cargo, nivel_acesso)
        response = supabase.table("tb_colaboradores")\
            .select("nome_completo, id_cargo, tb_cargos(nome_cargo, nivel_acesso)")\
            .eq("user_id", user_id)\
            .eq("ativo", True)\
            .execute()

        # 3. Se não achar ninguém ou não estiver ativo
        if not response.data:
            raise HTTPException(status_code=403, detail="Usuário não é um colaborador ativo.")

        funcionario = response.data[0]
        
        # Retorna os dados organizados
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
    # 1. Valida se quem está pedindo é um funcionário (Opcional: verificar cargo)
    if not authorization:
        raise HTTPException(status_code=401, detail="Não autorizado")
    
    try:
        # 2. Cria o Usuário de Login no Supabase (Auth)
        # Usamos admin_create_user para não deslogar o professor atual
        user_auth = supabase.auth.admin.create_user({
            "email": dados.email,
            "password": dados.senha,
            "email_confirm": True # Já confirma o email para ele poder logar
        })
        new_user_id = user_auth.user.id

        # 3. Insere na Tabela de Alunos
        aluno_resp = supabase.table("tb_alunos").insert({
            "nome_completo": dados.nome,
            "cpf": dados.cpf,
            "user_id": new_user_id
        }).execute()
        
        novo_id_aluno = aluno_resp.data[0]['id_aluno']

        # 4. Cria a Matrícula
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
        # Busca alunos e suas matrículas
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
        # Aqui vamos simular pegando das Turmas e das Reposições para montar o calendário
        # 1. Pegar Turmas Fixas
        turmas = supabase.table("tb_turmas").select("*").execute()
        
        # 2. Pegar Reposições
        reposicoes = supabase.table("tb_reposicoes")\
            .select("data_reposicao, tb_alunos(nome_completo)")\
            .execute()

        eventos = []

        # Transforma Reposições em Eventos do Calendário
        for rep in reposicoes.data:
            eventos.append({
                "title": f"Reposição: {rep['tb_alunos']['nome_completo']}",
                "start": rep['data_reposicao'],
                "color": "#ff4d4d" # Vermelho
            })

        # Para turmas fixas (simplificado para exemplo)
        # Em um sistema real, você geraria recorrencia. Aqui vamos devolver as reposições.
        return eventos

    except Exception as e:
        return []

@app.get("/meus-cursos-permitidos")
def get_cursos_permitidos(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token ausente")

    try:
        # 1. Pega usuário
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        # 2. Pega ID do Aluno
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
        
        if not aluno_resp.data:
            return {"cursos": []}

        id_aluno = aluno_resp.data[0]['id_aluno']

        # 3. Busca matrículas e INCLUI A DATA (data_matricula)
        response = supabase.table("tb_matriculas")\
            .select("codigo_turma, data_matricula, tb_turmas(nome_curso)")\
            .eq("id_aluno", id_aluno)\
            .execute()

        # 4. Monta a lista com ID e DATA
        liberados = []
        for item in response.data:
            if item.get('tb_turmas'):
                nome_banco = item['tb_turmas']['nome_curso']
                
                if nome_banco in MAPA_CURSOS:
                    liberados.append({
                        "id": MAPA_CURSOS[nome_banco],       # Ex: 'game-pro'
                        "data_inicio": item['data_matricula'] # Ex: '2025-12-04'
                    })
        
        return {"cursos": liberados}

    except Exception as e:
        print(f"Erro Permissões: {e}")
        return {"cursos": []}
        
@app.post("/recuperar-senha")
def recuperar_senha(dados: EmailData):
    try:
        # ATUALIZADO: Agora aponta para o seu domínio real
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
        # Tenta logar
        response = supabase.auth.sign_in_with_password({
            "email": dados.email, 
            "password": dados.password
        })
        # Retorna o token para o frontend
        return {"token": response.session.access_token, "user": { "email": response.user.email }}
    except Exception as e:
        print(f"Erro no login: {e}") # Ajuda a ver o erro no terminal
        raise HTTPException(status_code=400, detail="Email ou senha incorretos")




