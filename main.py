import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # <--- Necessário para o navegador deixar conectar
from pydantic import BaseModel
from supabase import create_client, Client
from fastapi import Header

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

@app.get("/meus-cursos-permitidos")
def get_cursos_permitidos(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token não fornecido")

    try:
        # 1. Pegar o usuário logado usando o token que veio do Front
        token = authorization.split(" ")[1] # Remove o "Bearer "
        user_response = supabase.auth.get_user(token)
        user_id = user_response.user.id

        # 2. Descobrir o ID do Aluno na tabela tb_alunos
        aluno_data = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
        
        if not aluno_data.data:
            return {"cursos": []} # Usuário não é aluno ainda
            
        id_aluno = aluno_data.data[0]['id_aluno']

        # 3. Buscar as matrículas e descobrir os nomes dos cursos
        # Consultamos tb_matriculas e pedimos os dados da tb_turmas relacionada
        response = supabase.table("tb_matriculas")\
            .select("tb_turmas(nome_curso)")\
            .eq("id_aluno", id_aluno)\
            .execute()

        # 4. Processar a lista para devolver os IDs do HTML
        cursos_liberados = []
        for item in response.data:
            # O Supabase retorna algo como {'tb_turmas': {'nome_curso': 'Game Pro'}}
            if item.get('tb_turmas'):
                nome_db = item['tb_turmas']['nome_curso']
                # Transforma 'Game Pro' em 'game-pro' usando nosso mapa
                if nome_db in MAPA_CURSOS:
                    cursos_liberados.append(MAPA_CURSOS[nome_db])

        return {"cursos": cursos_liberados}

    except Exception as e:
        print(f"Erro ao buscar cursos: {e}")
        return {"cursos": []} # Em caso de erro, não libera nada por segurança

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

