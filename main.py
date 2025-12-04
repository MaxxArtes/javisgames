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


