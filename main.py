import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # <--- Necessário para o navegador deixar conectar
from pydantic import BaseModel
from supabase import create_client, Client

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
