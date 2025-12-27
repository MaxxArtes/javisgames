import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel
from supabase import create_client, Client
import requests 
from datetime import datetime, timedelta
import shutil
import logging

# Configuração básica do Logger
logging.basicConfig(
    level=logging.INFO, # Registra INFO, WARNING e ERROR
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("app.log"), # Salva em arquivo
        logging.StreamHandler()         # Mostra no terminal
    ]
)
logger = logging.getLogger(__name__)

# Dicionário para traduzir dia da semana em número (0 = Segunda, 6 = Domingo)
DIAS_MAPA = {
    "Segunda": 0, "Segunda-feira": 0, "Terça": 1, "Terça-feira": 1,
    "Quarta": 2, "Quarta-feira": 2, "Quinta": 3, "Quinta-feira": 3,
    "Sexta": 4, "Sexta-feira": 4, "Sábado": 5, "Sabado": 5, "Domingo": 6
}

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


# --- MODELOS DE DADOS ---

class FuncionarioEdicaoData(BaseModel):
    nome: str | None = None
    telefone: str | None = None
    id_cargo: int | None = None
    ativo: bool | None = None

class PerfilUpdateData(BaseModel):
    nome: str | None = None
    telefone: str | None = None
    email_contato: str | None = None
    email_login: str | None = None
    nova_senha: str | None = None

class ReposicaoUpdate(BaseModel):
    presenca: bool | None = None # True=Veio, False=Faltou, None=Pendente
    observacoes: str | None = None
    
class TurmaData(BaseModel):
    codigo: str
    id_professor: int | None = None
    curso: str
    dia_semana: str
    horario: str
    sala: str
    status: str
    tipo: str = "PARTICULAR" # NOVO CAMPO: Padrão é Particular
    data_inicio: str | None = None
    qtd_aulas: int | None = 0
    data_termino_real: str | None = None
    
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
    celular: str 
    telefone: str | None = None
    data_nascimento: str | None = None

class ReposicaoData(BaseModel):
    id_aluno: int
    data_hora: str 
    turma_codigo: str
    id_professor: int
    conteudo_aula: str
    motivo: str | None = None
    observacoes: str | None = None

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

class NovoFuncionarioData(BaseModel):
    nome: str
    email: str
    senha: str
    telefone: str
    id_cargo: int

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

# --- AUXILIARES LÓGICA ---

def calcular_previsao(data_inicio_str: str, qtd: int):
    if not data_inicio_str or not qtd: return None
    try:
        dt_inicio = datetime.strptime(data_inicio_str, "%Y-%m-%d")
        dias_totais = (qtd - 1) * 7 
        dt_fim = dt_inicio + timedelta(days=dias_totais)
        return dt_fim.strftime("%Y-%m-%d")
    except: return None

# --- CONTEXTO DO USUÁRIO (MULTI-CIDADE) ---
def get_contexto_usuario(token: str):
    try:
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        
        resp = supabase.table("tb_colaboradores")\
            .select("id_colaborador, id_unidade, id_cargo, tb_cargos!fk_cargos(nivel_acesso)")\
            .eq("user_id", user_id)\
            .single()\
            .execute()
            
        dados = resp.data
        return {
            "user_id": user_id,
            "id_colaborador": dados['id_colaborador'],
            "id_unidade": dados['id_unidade'],
            "nivel": dados['tb_cargos']['nivel_acesso']
        }
    except Exception as e:
        print(f"Erro contexto usuario: {e}")
        raise HTTPException(status_code=401, detail="Usuário não identificado.")

# --- ROTAS ---

# 1. GESTÃO DE EQUIPE (RH)

@app.get("/admin/listar-cargos")
def admin_listar_cargos(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        return supabase.table("tb_cargos").select("*").order("nivel_acesso").execute().data
    except: return []

@app.get("/admin/listar-equipe")
def admin_listar_equipe(filtro_unidade: int | None = None, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)

    # Apenas Nível 8+ (Gerente) pode ver a lista
    if ctx['nivel'] < 8:
        raise HTTPException(status_code=403, detail="Acesso restrito à Gerência.")

    try:
        query = supabase.table("tb_colaboradores")\
            .select("*, tb_cargos!fk_cargos(nome_cargo, nivel_acesso)")\
            .order("nome_completo")
        
        # LÓGICA DO FILTRO:
        if ctx['nivel'] < 9: 
            # Se for Gerente (8) ou menor, FORÇA a ver só a própria unidade
            query = query.eq("id_unidade", ctx['id_unidade'])
        else:
            # Se for Diretor (9 ou 10) e escolheu uma cidade, filtra por ela
            if filtro_unidade:
                query = query.eq("id_unidade", filtro_unidade)
            
        return query.execute().data
    except Exception as e:
        print(f"Erro listar equipe: {e}")
        return []
        
@app.post("/admin/cadastrar-funcionario")
def admin_cadastrar_funcionario(dados: NovoFuncionarioData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)

    # Apenas Nível 8+ pode cadastrar
    if ctx['nivel'] < 8:
        raise HTTPException(status_code=403, detail="Acesso restrito à Gerência.")

    try:
        user_auth = supabase.auth.admin.create_user({
            "email": dados.email,
            "password": dados.senha,
            "email_confirm": True 
        })
        new_user_id = user_auth.user.id

        supabase.table("tb_colaboradores").insert({
            "nome_completo": dados.nome.upper(),
            "email": dados.email,
            "telefone": dados.telefone,
            "id_cargo": dados.id_cargo,
            "user_id": new_user_id,
            "id_unidade": ctx['id_unidade'],
            "ativo": True
        }).execute()

        return {"message": "Funcionário cadastrado com sucesso!"}
    except Exception as e:
        print(f"Erro cadastro func: {e}")
        raise HTTPException(status_code=400, detail="Erro ao criar funcionário.")

# --- Rota de Edição ---
@app.put("/admin/editar-funcionario/{id_colaborador}")
def admin_editar_funcionario(id_colaborador: int, dados: FuncionarioEdicaoData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)

    # Apenas Gerentes (8+) podem editar
    if ctx['nivel'] < 8:
        raise HTTPException(status_code=403, detail="Acesso restrito à Gerência.")

    try:
        updates = {}
        if dados.nome: updates["nome_completo"] = dados.nome.upper()
        if dados.telefone: updates["telefone"] = dados.telefone
        if dados.id_cargo: updates["id_cargo"] = dados.id_cargo
        if dados.ativo is not None: updates["ativo"] = dados.ativo

        if updates:
            supabase.table("tb_colaboradores").update(updates).eq("id_colaborador", id_colaborador).execute()

        return {"message": "Funcionário atualizado com sucesso!"}
    except Exception as e:
        print(f"Erro update func: {e}")
        raise HTTPException(status_code=400, detail="Erro ao atualizar funcionário.")

# 2. GESTÃO DE TURMAS
@app.get("/admin/gerenciar-turmas")
def admin_listar_turmas_completo(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)

    try:
        query = supabase.table("tb_turmas").select("*, tb_colaboradores(nome_completo)").order("codigo_turma")
        if ctx['nivel'] < 9:
            query = query.eq("id_unidade", ctx['id_unidade'])
        return query.execute().data
    except Exception as e:
        print(f"Erro listar turmas: {e}")
        return []

@app.post("/admin/salvar-turma")
def admin_salvar_turma(dados: TurmaData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)

    try:
        previsao = calcular_previsao(dados.data_inicio, dados.qtd_aulas)
        supabase.table("tb_turmas").insert({
            "codigo_turma": dados.codigo.upper(),
            "id_professor": dados.id_professor,
            "nome_curso": dados.curso,
            "dia_semana": dados.dia_semana,
            "horario": dados.horario,
            "sala": dados.sala,
            "status": dados.status,
            "tipo_turma": dados.tipo, # Salva se é PROJETO ou PARTICULAR
            "data_inicio": dados.data_inicio,
            "qtd_aulas": dados.qtd_aulas,
            "previsao_termino": previsao,
            "data_termino_real": dados.data_termino_real,
            "id_unidade": ctx['id_unidade']
        }).execute()
        return {"message": "Turma criada!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/admin/editar-turma/{codigo_original}")
def admin_editar_turma(codigo_original: str, dados: TurmaData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        previsao = calcular_previsao(dados.data_inicio, dados.qtd_aulas)
        supabase.table("tb_turmas").update({
            "id_professor": dados.id_professor,
            "nome_curso": dados.curso,
            "dia_semana": dados.dia_semana,
            "horario": dados.horario,
            "sala": dados.sala,
            "status": dados.status,
            "tipo_turma": dados.tipo, # Atualiza o tipo
            "data_inicio": dados.data_inicio,
            "qtd_aulas": dados.qtd_aulas,
            "previsao_termino": previsao,
            "data_termino_real": dados.data_termino_real
        }).eq("codigo_turma", codigo_original).execute()
        return {"message": "Turma atualizada!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# 3. DADOS DO FUNCIONÁRIO
@app.get("/admin/meus-dados")
def get_dados_funcionario(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        
        response = supabase.table("tb_colaboradores")\
            .select("id_colaborador, nome_completo, telefone, email, id_cargo, id_unidade, tb_cargos!fk_cargos(nome_cargo, nivel_acesso)")\
            .eq("user_id", user_id)\
            .eq("ativo", True)\
            .execute()
            
        if not response.data: raise HTTPException(status_code=403)
        funcionario = response.data[0]
        
        return {
            "id_colaborador": funcionario['id_colaborador'],
            "nome": funcionario['nome_completo'],
            "telefone": funcionario['telefone'],
            "email_contato": funcionario['email'],
            "cargo": funcionario['tb_cargos']['nome_cargo'],
            "nivel": funcionario['tb_cargos']['nivel_acesso'],
            "unidade": funcionario['id_unidade']
        }
    except Exception as e:
        raise HTTPException(status_code=403, detail="Erro interno")

# 4. CADASTRO DE ALUNO
@app.post("/admin/cadastrar-aluno")
def admin_cadastrar_aluno(dados: NovoAlunoData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    
    try:
        user_auth = supabase.auth.admin.create_user({ "email": dados.email, "password": dados.senha, "email_confirm": True })
        new_user_id = user_auth.user.id

        nasc_formatado = None
        if dados.data_nascimento: nasc_formatado = dados.data_nascimento.replace("-", "")[:8]

        aluno_resp = supabase.table("tb_alunos").insert({
            "nome_completo": dados.nome,
            "cpf": dados.cpf,
            "email": dados.email,
            "celular": dados.celular,
            "telefone": dados.telefone,
            "data_nascimento": nasc_formatado,
            "user_id": new_user_id,
            "id_unidade": ctx['id_unidade']
        }).execute()
        
        if not aluno_resp.data: raise Exception("Erro aluno")
        novo_id_aluno = aluno_resp.data[0]['id_aluno']

        supabase.table("tb_matriculas").insert({
            "id_aluno": novo_id_aluno,
            "codigo_turma": dados.turma_codigo,
            "id_vendedor": ctx['id_colaborador'],
            "status_financeiro": "Ok"
        }).execute()

        return {"message": "Sucesso!"}
    except Exception as e:
        print(f"Erro cadastro: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/admin/listar-alunos")
def admin_listar_alunos(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        # Agora buscamos também o 'tipo_turma' dentro de tb_turmas, através da matrícula
        query = supabase.table("tb_alunos").select("*, tb_matriculas(codigo_turma, status_financeiro, tb_turmas(tipo_turma))")
        if ctx['nivel'] < 9: query = query.eq("id_unidade", ctx['id_unidade'])
        return query.execute().data
    except Exception as e: 
        print(f"Erro listar alunos: {e}")
        return []

# 5. REPOSIÇÕES E AGENDA
@app.post("/admin/agendar-reposicao")
def admin_reposicao(dados: ReposicaoData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        dt_repo_inicio = datetime.strptime(dados.data_hora, "%Y-%m-%dT%H:%M")
        dt_repo_fim = dt_repo_inicio + timedelta(hours=1) 

        resp_turmas = supabase.table("tb_turmas").select("*").eq("id_professor", dados.id_professor).in_("status", ["Em Andamento", "Planejada"]).execute()

        for turma in resp_turmas.data:
            if not turma['data_inicio'] or not turma['qtd_aulas'] or not turma['horario']: continue
            dt_inicio_turma = datetime.strptime(turma['data_inicio'], "%Y-%m-%d")
            dia_alvo = DIAS_MAPA.get(turma['dia_semana'].split("-")[0].strip(), 0)
            dias_diff = (dia_alvo - dt_inicio_turma.weekday() + 7) % 7
            dt_aula_atual = dt_inicio_turma + timedelta(days=dias_diff)
            hora_h, hora_m = map(int, turma['horario'].split("-")[0].strip().split(":"))

            for _ in range(turma['qtd_aulas']):
                inicio_aula = dt_aula_atual.replace(hour=hora_h, minute=hora_m)
                fim_aula = inicio_aula + timedelta(hours=2, minutes=30)
                if (dt_repo_inicio < fim_aula) and (dt_repo_fim > inicio_aula):
                    raise HTTPException(status_code=409, detail=f"Conflito de horário com turma {turma['codigo_turma']}.")
                dt_aula_atual += timedelta(days=7)

        supabase.table("tb_reposicoes").insert({
            "id_aluno": dados.id_aluno,
            "data_reposicao": dados.data_hora,
            "codigo_turma": dados.turma_codigo,
            "id_professor": dados.id_professor,
            "conteudo_aula": dados.conteudo_aula,
            "motivo": dados.motivo,
            "observacoes": dados.observacoes,
            "criado_por": user_id,
            "status": "Agendada",
            "presenca": None 
        }).execute()
        
        return {"message": "Agendada com sucesso!"}
    except HTTPException as he: raise he
    except Exception as e: raise HTTPException(status_code=400, detail="Erro interno.")
        
@app.get("/admin/agenda-geral")
def admin_agenda(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        eventos = []
        # REPOSIÇÕES (Filtrar se não for diretor)
        if ctx['nivel'] < 9:
            alunos = supabase.table("tb_alunos").select("id_aluno").eq("id_unidade", ctx['id_unidade']).execute()
            ids = [a['id_aluno'] for a in alunos.data]
            resp_repo = supabase.table("tb_reposicoes").select("*, tb_alunos(nome_completo), tb_colaboradores(nome_completo)").in_("id_aluno", ids).execute()
        else:
            resp_repo = supabase.table("tb_reposicoes").select("*, tb_alunos(nome_completo), tb_colaboradores(nome_completo)").execute()
        
        for rep in resp_repo.data:
            nome_aluno = "Aluno?"
            if rep.get('tb_alunos'): nome_aluno = rep['tb_alunos'].get('nome_completo', 'Aluno?')
            nome_prof = "?"
            if rep.get('tb_colaboradores'): nome_prof = rep['tb_colaboradores'].get('nome_completo', '?')
            
            eventos.append({
                "id": rep['id'],
                "title": f"🔄 Reposição: {nome_aluno}",
                "start": rep['data_reposicao'],
                "color": "#ff4d4d",
                "tipo": "reposicao",
                "nome_aluno": nome_aluno,
                "nome_prof": nome_prof,
                "conteudo": rep['conteudo_aula'],
                "turma": rep['codigo_turma'],
                "presenca": rep['presenca'],
                "observacoes": rep['observacoes'],
                "arquivo": rep['arquivo_assinatura']
            })

        # TURMAS (Aulas Recorrentes)
        query_t = supabase.table("tb_turmas").select("*, tb_colaboradores(nome_completo)").in_("status", ["Em Andamento", "Planejada"])
        if ctx['nivel'] < 9: query_t = query_t.eq("id_unidade", ctx['id_unidade'])
        resp_turmas = query_t.execute()

        for turma in resp_turmas.data:
            if not turma['data_inicio'] or not turma['qtd_aulas'] or not turma['horario']: continue
            try:
                dt_inicio = datetime.strptime(turma['data_inicio'], "%Y-%m-%d")
                dia_alvo = DIAS_MAPA.get(turma['dia_semana'].split("-")[0].strip(), 0) 
                dias_diff = (dia_alvo - dt_inicio.weekday() + 7) % 7
                dt_atual = dt_inicio + timedelta(days=dias_diff)
                hora_ini = turma['horario'].split("-")[0].strip()
                nome_prof_t = turma['tb_colaboradores']['nome_completo'] if turma.get('tb_colaboradores') else "Sem Prof"

                for i in range(turma['qtd_aulas']):
                    eventos.append({
                        "id": f"aula-{turma['codigo_turma']}-{i}",
                        "title": f"📚 {turma['codigo_turma']} - {turma['nome_curso']} ({nome_prof_t})",
                        "start": f"{dt_atual.strftime('%Y-%m-%d')}T{hora_ini}:00",
                        "color": "#0088cc",
                        "tipo": "aula"
                    })
                    dt_atual += timedelta(days=7)
            except: continue

        return eventos
    except: return []

@app.put("/admin/reposicao-completa/{id_repo}")
def atualizar_reposicao_completa(id_repo: str, presenca: str = Form(...), observacoes: str = Form(None), arquivo: UploadFile = File(None), authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        presenca_bool = None
        if presenca == "true": presenca_bool = True
        elif presenca == "false": presenca_bool = False
        updates = { "presenca": presenca_bool, "observacoes": observacoes }

        if arquivo:
            file_content = arquivo.file.read()
            file_ext = arquivo.filename.split('.')[-1]
            file_path = f"assinatura_{id_repo}.{file_ext}" 
            supabase.storage.from_("listas-chamada").upload(file_path, file_content, file_options={"content-type": arquivo.content_type, "upsert": "true"})
            updates["arquivo_assinatura"] = supabase.storage.from_("listas-chamada").get_public_url(file_path)

        supabase.table("tb_reposicoes").update(updates).eq("id", id_repo).execute()
        return {"message": "Atualizado!"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.patch("/admin/reposicao/{id_repo}")
def atualizar_reposicao(id_repo: str, dados: ReposicaoUpdate, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        supabase.table("tb_reposicoes").update({"presenca": dados.presenca, "observacoes": dados.observacoes}).eq("id", id_repo).execute()
        return {"message": "OK"}
    except: raise HTTPException(status_code=400)

# 6. CRM / LEADS
@app.get("/admin/leads-crm")
def get_leads_crm(filtro_unidade: int | None = None, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    
    try:
        # Tenta buscar os leads. 
        # IMPORTANTE: Certifique-se que a tabela 'inscricoes' tem a coluna 'id_unidade' no Supabase.
        # Se não tiver, crie a coluna ou remova os filtros de .eq("id_unidade") abaixo.
        query = supabase.table("inscricoes").select("*").order("created_at", desc=True)
        
        # Filtros de Unidade
        if ctx['nivel'] < 9:
            # Se for Vendedor, tenta filtrar. Se a coluna nao existir, isso pode dar erro.
            # Se der erro, remova essa linha temporariamente até criar a coluna no banco.
            query = query.eq("id_unidade", ctx['id_unidade'])
        elif filtro_unidade:
            query = query.eq("id_unidade", filtro_unidade)

        leads = query.execute().data
        
        # Busca CPFs de alunos para comparar
        alunos = supabase.table("tb_alunos").select("cpf").execute().data
        cpfs = set(''.join(filter(str.isdigit, a['cpf'])) for a in alunos if a.get('cpf'))
        
        res = []
        for l in leads:
            cpf_l = ''.join(filter(str.isdigit, l.get('cpf','') or ''))
            res.append({
                "id": l['id'], 
                "nome": l['nome'], 
                "cpf": l.get('cpf','-'), 
                "whatsapp": l['whatsapp'],
                "workshop": l['workshop'], 
                "data_agendada": l['data_agendada'], 
                "status": l.get('status','Pendente'),
                "vendedor": l.get('vendedor','-'), 
                "ja_e_aluno": (cpf_l in cpfs and cpf_l != ''),
                "id_unidade": l.get('id_unidade') 
            })
        return res
    except Exception as e:
        print(f"Erro CRM: {e}") 
        # Retorna lista vazia em vez de erro 500 para não travar a tela
        return []

@app.patch("/admin/leads-crm/{id_inscricao}")
def atualizar_status_lead(id_inscricao: int, dados: StatusUpdateData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    if ctx['nivel'] not in [3, 4, 8, 9, 10]: raise HTTPException(status_code=403)
    try:
        resp = supabase.table("tb_colaboradores").select("nome_completo").eq("user_id", ctx['user_id']).execute()
        nome = resp.data[0]['nome_completo']
        supabase.table("inscricoes").update({ "status": dados.status, "vendedor": nome }).eq("id", id_inscricao).execute()
        return {"message": "OK"}
    except: raise HTTPException(status_code=500)

@app.patch("/admin/meus-dados")
def atualizar_meu_perfil(dados: PerfilUpdateData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user_id = supabase.auth.get_user(token).user.id
        updates = {}
        if dados.nome: updates["nome_completo"] = dados.nome.upper()
        if dados.telefone: updates["telefone"] = dados.telefone
        if dados.email_contato: updates["email"] = dados.email_contato
        if updates: supabase.table("tb_colaboradores").update(updates).eq("user_id", user_id).execute()
        
        auth_up = {}
        if dados.email_login: auth_up["email"] = dados.email_login
        if dados.nova_senha: auth_up["password"] = dados.nova_senha
        if auth_up: supabase.auth.update_user(auth_up)
        return {"message": "Perfil atualizado!"}
    except: raise HTTPException(status_code=500)

@app.get("/admin/listar-turmas")
def admin_listar_turmas(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        query = supabase.table("tb_turmas").select("*")
        if ctx['nivel'] < 9: query = query.eq("id_unidade", ctx['id_unidade'])
        return query.execute().data
    except: return []

@app.get("/admin/listar-professores")
def admin_listar_professores(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        query = supabase.table("tb_colaboradores").select("id_colaborador, nome_completo").eq("id_cargo", 6)
        if ctx['nivel'] < 9: query = query.eq("id_unidade", ctx['id_unidade'])
        return query.execute().data
    except: return []

# --- 7. CHAT & Z-API (RESTAURADOS) ---

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
    if not authorization: raise HTTPException(status_code=401, detail="Token ausente")
    try:
        token = authorization.split(" ")[1]
        ctx = get_contexto_usuario(token) # Pega contexto para filtrar por cidade

        lista_alunos_permitidos = []
        filtrar_por_aluno = False

        # Se for Professor (Nível 5) -> Vê só seus alunos (lógica original)
        # Se for Coord/Vendedor (Nível < 9) -> Vê alunos da sua UNIDADE
        
        if ctx['nivel'] == 5: # Professor
            turmas_resp = supabase.table("tb_turmas").select("codigo_turma").eq("id_professor", ctx['id_colaborador']).execute()
            codigos_turmas = [t['codigo_turma'] for t in turmas_resp.data]
            if not codigos_turmas: return []
            matriculas_resp = supabase.table("tb_matriculas").select("id_aluno").in_("codigo_turma", codigos_turmas).execute()
            lista_alunos_permitidos = [m['id_aluno'] for m in matriculas_resp.data]
            filtrar_por_aluno = True
            
        elif ctx['nivel'] < 9: # Coord/Vendedor da unidade
            alunos_unidade = supabase.table("tb_alunos").select("id_aluno").eq("id_unidade", ctx['id_unidade']).execute()
            lista_alunos_permitidos = [a['id_aluno'] for a in alunos_unidade.data]
            filtrar_por_aluno = True

        query = supabase.table("tb_chat").select("id_aluno, mensagem, created_at, tb_alunos(nome_completo)").order("created_at", desc=True).limit(300)
        
        if filtrar_por_aluno:
            if not lista_alunos_permitidos: return []
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

@app.post("/login")
def realizar_login(dados: LoginData):
    try:
        response = supabase.auth.sign_in_with_password({"email": dados.email, "password": dados.password})
        return {"token": response.session.access_token, "user": { "email": response.user.email }}
    except: raise HTTPException(status_code=400, detail="Email ou senha incorretos")

@app.post("/recuperar-senha")
def recuperar_senha(dados: EmailData):
    try:
        site_url = "https://www.javisgameacademy.com.br/RedefinirSenha.html" 
        supabase.auth.reset_password_email(dados.email, options={"redirect_to": site_url})
        return {"message": "Email enviado"}
    except: raise HTTPException(status_code=400, detail="Erro ao enviar email.")

# --- CONTEÚDO DAS AULAS ---
@app.get("/conteudo-aula")
def get_conteudo_aula(titulo: str):
    """
    Busca o script, código e desafio da aula pelo título exato.
    Ex: titulo="Aula 01: O Primeiro Contato"
    """
    try:
        # Busca na tabela 'conteudos_aulas' onde 'titulo_aula' é igual ao parametro
        # .maybe_single() retorna None se não achar, em vez de erro
        response = supabase.table("conteudos_aulas").select("*").eq("titulo_aula", titulo).maybe_single().execute()
        
        if response.data:
            return response.data
        else:
            # Retorna um conteúdo padrão se não achar no banco
            return {
                "titulo_aula": titulo,
                "script": "Conteúdo ainda não disponível no sistema.",
                "codigo_exemplo": "# Aguardando atualização do professor...",
                "desafio": "Tente explorar o Pygame por conta própria!"
            }
    except Exception as e:
        print(f"Erro ao buscar conteúdo da aula: {e}")
        raise HTTPException(status_code=500, detail="Erro interno ao buscar aula")

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

@app.get("/admin/dashboard-stats")
def get_dashboard_stats(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    
    try:
        # 1. CRM / LEADS
        q_leads = supabase.table("inscricoes").select("status", count="exact")
        if ctx['nivel'] < 9: q_leads = q_leads.eq("id_unidade", ctx['id_unidade'])
        leads_data = q_leads.execute().data
        
        pendentes = sum(1 for l in leads_data if l.get('status') == 'Pendente')
        atendimento = sum(1 for l in leads_data if l.get('status') == 'Em Atendimento')
        matriculados = sum(1 for l in leads_data if l.get('status') == 'Matriculado')
        perdidos = sum(1 for l in leads_data if l.get('status') == 'Perdido')
        total_leads = len(leads_data)
        taxa_conversao = (matriculados / total_leads * 100) if total_leads > 0 else 0

        # 2. ALUNOS E TURMAS
        q_alunos = supabase.table("tb_alunos").select("id_aluno", count="exact")
        if ctx['nivel'] < 9: q_alunos = q_alunos.eq("id_unidade", ctx['id_unidade'])
        total_alunos = q_alunos.execute().count

        q_turmas = supabase.table("tb_turmas").select("status, nome_curso")
        if ctx['nivel'] < 9: q_turmas = q_turmas.eq("id_unidade", ctx['id_unidade'])
        turmas_data = q_turmas.execute().data
        
        # CORREÇÃO: Turmas Ativas agora são "Em Andamento" (Vagas) + "Fechada" (Lotada/Sem Vagas)
        turmas_ativas = sum(1 for t in turmas_data if t['status'] in ['Em Andamento', 'Fechada'])
        
        # Agrupar cursos para o gráfico
        cursos_map = {}
        for t in turmas_data:
            nome = t.get('nome_curso', 'Outros')
            cursos_map[nome] = cursos_map.get(nome, 0) + 1

        # 3. REPOSIÇÕES PENDENTES
        repo_count = supabase.table("tb_reposicoes").select("id", count="exact").eq("status", "Agendada").execute().count

        return {
            "leads": { "pendentes": pendentes, "atendimento": atendimento, "matriculados": matriculados, "perdidos": perdidos, "total": total_leads, "conversao": round(taxa_conversao, 1) },
            "escola": { "total_alunos": total_alunos, "turmas_ativas": turmas_ativas },
            "reposicoes": repo_count,
            "grafico_cursos": cursos_map
        }
    except Exception as e:
        print(f"Erro dashboard: {e}")
        return {}



class MensagemDiretaData(BaseModel):
    id_colaborador: int | None = None # Se for None, é suporte geral
    mensagem: str

@app.get("/aluno/meus-contatos")
def get_contatos_aluno(authorization: str = Header(None)):
    """
    Retorna:
    1. Coordenador Pedagógico da unidade (ID Cargo 4).
    2. Professores das turmas ATIVAS do aluno.
    """
    if not authorization: raise HTTPException(status_code=401)
    try:
        # 1. Identificar o Aluno
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        
        # Busca ID do Aluno e Unidade
        aluno_resp = supabase.table("tb_alunos").select("id_aluno, id_unidade").eq("user_id", user.user.id).execute()
        
        if not aluno_resp.data: 
            return []
        
        aluno = aluno_resp.data[0]
        id_aluno = aluno['id_aluno']
        id_unidade = aluno['id_unidade']

        contatos = []

        # --- PARTE A: COORDENADOR PEDAGÓGICO (ID 4) ---
        try:
            # Busca apenas quem tem id_cargo = 4 (Coord. Pedagógico) na unidade do aluno
            coords = supabase.table("tb_colaboradores")\
                .select("id_colaborador, nome_completo, id_cargo")\
                .eq("id_unidade", id_unidade)\
                .eq("ativo", True)\
                .eq("id_cargo", 4)\
                .execute()

            for c in coords.data:
                contatos.append({
                    "id": c['id_colaborador'],
                    "nome": c['nome_completo'],
                    "cargo": "Coord. Pedagógico",
                    "tipo": "Coordenacao"
                })
        except Exception:
            pass 

        # --- PARTE B: PROFESSORES (Das Turmas) ---
        try:
            # 1. Matrículas do aluno
            matriculas = supabase.table("tb_matriculas").select("codigo_turma").eq("id_aluno", id_aluno).execute()
            codigos_turmas = [m['codigo_turma'] for m in matriculas.data]

            if codigos_turmas:
                # 2. Turmas para pegar os IDs dos professores
                turmas = supabase.table("tb_turmas")\
                    .select("codigo_turma, nome_curso, id_professor")\
                    .in_("codigo_turma", codigos_turmas)\
                    .execute()
                
                prof_curso_map = {}
                ids_professores = []
                
                for t in turmas.data:
                    pid = t.get('id_professor')
                    if pid:
                        prof_curso_map[str(pid)] = t['nome_curso']
                        ids_professores.append(pid)

                # 3. Dados dos Professores
                if ids_professores:
                    profs = supabase.table("tb_colaboradores")\
                        .select("id_colaborador, nome_completo")\
                        .in_("id_colaborador", ids_professores)\
                        .execute()
                        
                    for p in profs.data:
                        pid = p['id_colaborador']
                        nome_curso = prof_curso_map.get(str(pid)) or "Professor"

                        contatos.append({
                            "id": pid,
                            "nome": p['nome_completo'],
                            "cargo": f"Prof. {nome_curso}",
                            "tipo": "Professor",
                            "codigo_turma_grupo": t['codigo_turma']
                        })
        except Exception:
            pass 

        return contatos

    except Exception:
        return []

@app.get("/chat/mensagens-com/{id_colaborador}")
def get_mensagens_privadas(id_colaborador: str, authorization: str = Header(None)):
    """ Busca mensagens trocadas especificamente com aquele colaborador """
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user_id = supabase.auth.get_user(token).user.id
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).single().execute()
        id_aluno = aluno_resp.data['id_aluno']
        
        # Conversão de "null" string para None real se for chat geral
        target = int(id_colaborador) if id_colaborador != "geral" else None
        
        query = supabase.table("tb_chat").select("*").eq("id_aluno", id_aluno)
        
        if target:
            query = query.eq("id_colaborador", target)
        else:
            query = query.is_("id_colaborador", "null") # Chat Geral
            
        return query.order("created_at").execute().data
    except Exception as e:
        return []

@app.post("/chat/enviar-direto")
def enviar_msg_direta(dados: MensagemDiretaData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user_id = supabase.auth.get_user(token).user.id
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).single().execute()
        
        payload = {
            "id_aluno": aluno_resp.data['id_aluno'],
            "mensagem": dados.mensagem,
            "enviado_por_admin": False,
            "lida": False
        }
        
        # Se tiver id_colaborador, salva. Se não, fica NULL (Suporte Geral)
        if dados.id_colaborador:
            payload["id_colaborador"] = dados.id_colaborador

        supabase.table("tb_chat").insert(payload).execute()
        return {"message": "Enviado"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- MODELO NOVO PARA O GRUPO ---
class MensagemGrupoData(BaseModel):
    codigo_turma: str
    mensagem: str

# --- ROTAS DO GRUPO DA TURMA ---

@app.get("/chat/turma/{codigo_turma}")
def get_chat_turma(codigo_turma: str, authorization: str = Header(None)):
    """ Lê as mensagens do grupo da turma """
    if not authorization: raise HTTPException(status_code=401)
    try:
        # Pega as últimas 50 mensagens
        msgs = supabase.table("tb_chat_turma")\
            .select("*")\
            .eq("codigo_turma", codigo_turma)\
            .order("created_at", desc=False)\
            .limit(50)\
            .execute()
        return msgs.data
    except Exception as e:
        print(f"Erro chat turma: {e}")
        return []

@app.post("/chat/turma/enviar")
def enviar_chat_turma(dados: MensagemGrupoData, authorization: str = Header(None)):
    """ Envia mensagem para o grupo (Versão Corrigida: Sem maybe_single) """
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        
        # 1. Descobrir QUEM está enviando (Aluno ou Staff?)
        nome_exibicao = "Usuário"
        cargo_exibicao = "Desconhecido"
        
        # Tenta achar como Colaborador (Busca segura)
        colab_resp = supabase.table("tb_colaboradores").select("nome_completo, id_cargo").eq("user_id", user_id).execute()
        
        if colab_resp.data and len(colab_resp.data) > 0:
            c = colab_resp.data[0]
            nome_exibicao = c['nome_completo'].split()[0] # Primeiro nome
            if c['id_cargo'] == 6: cargo_exibicao = "Professor"
            elif c['id_cargo'] == 4: cargo_exibicao = "Coordenação"
            else: cargo_exibicao = "Staff"
        else:
            # Se não achou colaborador, busca como Aluno (Busca segura)
            aluno_resp = supabase.table("tb_alunos").select("nome_completo").eq("user_id", user_id).execute()
            
            if aluno_resp.data and len(aluno_resp.data) > 0:
                nome_exibicao = aluno_resp.data[0]['nome_completo'].split()[0]
                cargo_exibicao = "Aluno"
            else:
                print(f"ERRO: Usuário {user_id} não encontrado nem como aluno nem colaborador.")
        
        # 2. Salvar Mensagem
        supabase.table("tb_chat_turma").insert({
            "codigo_turma": dados.codigo_turma,
            "mensagem": dados.mensagem,
            "id_usuario_envio": user_id,
            "nome_exibicao": nome_exibicao,
            "cargo_exibicao": cargo_exibicao
        }).execute()
        
        return {"message": "Enviado"}
    except Exception as e:
        print(f"Erro envio grupo: {e}") # Log para debug
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/chat/historico-unificado")
def get_historico_unificado(authorization: str = Header(None)):
    """
    Retorna uma lista unificada de conversas recentes (Alunos e Grupos),
    ordenada pela mensagem mais recente.
    """
    if not authorization: raise HTTPException(status_code=401)
    try:
        # 1. Buscar últimas mensagens privadas (tb_chat)
        # Limitamos a 200 para pegar histórico recente sem pesar o banco
        chats_privados = supabase.table("tb_chat")\
            .select("*, tb_alunos(nome_completo)")\
            .order("created_at", desc=True)\
            .limit(200)\
            .execute()
            
        # 2. Buscar últimas mensagens de grupo (tb_chat_turma)
        chats_grupos = supabase.table("tb_chat_turma")\
            .select("*")\
            .order("created_at", desc=True)\
            .limit(200)\
            .execute()
            
        historico = []
        ids_processados = set() # Para evitar duplicatas (mostrar só a última do aluno)
        grupos_processados = set() # Para evitar duplicatas (mostrar só a última do grupo)

        # Processar Privados
        for c in chats_privados.data:
            id_aluno = c['id_aluno']
            if id_aluno not in ids_processados:
                nome = "Aluno Desconhecido"
                if c.get('tb_alunos'):
                    nome = c['tb_alunos']['nome_completo']
                
                historico.append({
                    "tipo": "privado",
                    "id": id_aluno,
                    "nome": nome,
                    "ultima_msg": c['mensagem'],
                    "timestamp": c['created_at'],
                    "lida": c['lida']
                })
                ids_processados.add(id_aluno)

        # Processar Grupos
        for g in chats_grupos.data:
            cod_turma = g['codigo_turma']
            if cod_turma not in grupos_processados:
                historico.append({
                    "tipo": "grupo",
                    "id": cod_turma, # O ID do grupo é o código da turma
                    "nome": f"Grupo {cod_turma}",
                    "ultima_msg": f"{g['nome_exibicao']}: {g['mensagem']}",
                    "timestamp": g['created_at'],
                    "lida": True # Grupos não têm status de lido individual
                })
                grupos_processados.add(cod_turma)

        # 3. Ordenar tudo por data (mais recente primeiro)
        historico.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return historico

    except Exception as e:
        print(f"Erro historico unificado: {e}")
        return []
# --- ADICIONAR NO FINAL DO ARQUIVO main.py ---

@app.get("/conteudo-didatico/cursos")
def get_cursos_didaticos(authorization: str = Header(None)):
    """
    Retorna a estrutura completa de cursos, módulos e aulas.
    """
    if not authorization: raise HTTPException(status_code=401)
    
    try:
        # A sintaxe do select aninhado no Supabase Python segue o padrão PostgREST
        response = supabase.table("cursos")\
            .select("id, titulo, icone, ordem, modulos(id, titulo, ordem, aulas(id, titulo, caminho_arquivo, ordem))")\
            .eq("ativo", True)\
            .order("ordem")\
            .execute()

        cursos = response.data
        
        # Ordenação manual no Python para garantir (Módulos e Aulas)
        # O Supabase às vezes não garante a ordem de itens aninhados na resposta JSON
        for curso in cursos:
            # Ordenar módulos
            if 'modulos' in curso and curso['modulos']:
                curso['modulos'].sort(key=lambda x: x['ordem'])
                
                # Ordenar aulas dentro de cada módulo
                for modulo in curso['modulos']:
                    if 'aulas' in modulo and modulo['aulas']:
                        modulo['aulas'].sort(key=lambda x: x['ordem'])
        
        return cursos

    except Exception as e:
        print(f"Erro ao buscar cursos didáticos: {e}")
        # Retorna lista vazia em caso de erro para não quebrar o front
        return []


# --- MODELO PARA SALVAR CONTEÚDO ---
class AulaConteudoData(BaseModel):
    conteudo: str

# --- ROTA: PEGAR CONTEÚDO DA AULA ---
@app.get("/admin/aula/{id_aula}/conteudo")
def get_aula_conteudo(id_aula: int, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        # Busca o conteúdo no banco
        response = supabase.table("aulas").select("conteudo, caminho_arquivo").eq("id", id_aula).single().execute()
        data = response.data
        
        # Se tiver conteúdo editado no banco, retorna ele.
        if data.get('conteudo'):
            return {"html": data['conteudo'], "tipo": "banco"}
        
        # Se não tiver, retorna aviso ou tenta ler o arquivo estático (opcional, mas complexo via API)
        return {"html": "", "tipo": "vazio"} 
    except Exception as e:
        print(f"Erro buscar conteudo: {e}")
        raise HTTPException(status_code=500, detail="Erro ao carregar aula")

# --- ROTA: SALVAR CONTEÚDO ---
@app.put("/admin/aula/{id_aula}/salvar")
def salvar_aula_conteudo(id_aula: int, dados: AulaConteudoData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    
    # Verifica permissão (apenas Prof, Coord ou Admin)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    if ctx['nivel'] < 5: # Assumindo que 5 é professor
        raise HTTPException(status_code=403, detail="Sem permissão para editar aulas.")

    try:
        supabase.table("aulas").update({"conteudo": dados.conteudo}).eq("id", id_aula).execute()
        return {"message": "Aula salva com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


