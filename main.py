import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel
from supabase import create_client, Client
import requests 
from datetime import datetime, timedelta
import shutil

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

class PerfilUpdateData(BaseModel):
    nome: str | None = None
    telefone: str | None = None
    email_contato: str | None = None
    email_login: str | None = None
    nova_senha: str | None = None

class ReposicaoUpdate(BaseModel):
    presenca: bool | None = None
    observacoes: str | None = None
    
class TurmaData(BaseModel):
    codigo: str
    id_professor: int | None = None
    curso: str
    dia_semana: str
    horario: str
    sala: str
    status: str
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

# --- NOVA FUNÇÃO: CONTEXTO DO USUÁRIO (MULTI-CIDADE) ---
def get_contexto_usuario(token: str):
    """
    Retorna o ID do usuário, ID da Unidade e Nível de Acesso.
    Essencial para filtrar dados por cidade.
    """
    try:
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        
        # Busca dados extras incluindo a Unidade
        resp = supabase.table("tb_colaboradores")\
            .select("id_colaborador, id_unidade, id_cargo, tb_cargos!fk_cargos(nivel_acesso)")\
            .eq("user_id", user_id)\
            .single()\
            .execute()
            
        dados = resp.data
        return {
            "user_id": user_id,
            "id_colaborador": dados['id_colaborador'],
            "id_unidade": dados['id_unidade'], # A CIDADE DO USUÁRIO
            "nivel": dados['tb_cargos']['nivel_acesso']
        }
    except Exception as e:
        print(f"Erro contexto usuario: {e}")
        raise HTTPException(status_code=401, detail="Usuário não identificado ou sem unidade configurada.")

# --- ROTAS ---

@app.get("/admin/gerenciar-turmas")
def admin_listar_turmas_completo(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token) # Pega cidade do usuário

    try:
        # Query base
        query = supabase.table("tb_turmas")\
            .select("*, tb_colaboradores(nome_completo)")\
            .order("codigo_turma")
        
        # FILTRO DE CIDADE: Se não for Diretor (Nível 9 ou 10), vê só a sua cidade
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
            "data_inicio": dados.data_inicio,
            "qtd_aulas": dados.qtd_aulas,
            "previsao_termino": previsao,
            "data_termino_real": dados.data_termino_real,
            "id_unidade": ctx['id_unidade'] # SALVA NA CIDADE DO USUÁRIO
        }).execute()
        return {"message": "Turma criada!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/admin/editar-turma/{codigo_original}")
def admin_editar_turma(codigo_original: str, dados: TurmaData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    # Na edição, não mudamos a unidade (a turma continua onde nasceu)
    try:
        previsao = calcular_previsao(dados.data_inicio, dados.qtd_aulas)

        supabase.table("tb_turmas").update({
            "id_professor": dados.id_professor,
            "nome_curso": dados.curso,
            "dia_semana": dados.dia_semana,
            "horario": dados.horario,
            "sala": dados.sala,
            "status": dados.status,
            "data_inicio": dados.data_inicio,
            "qtd_aulas": dados.qtd_aulas,
            "previsao_termino": previsao,
            "data_termino_real": dados.data_termino_real
        }).eq("codigo_turma", codigo_original).execute()
        return {"message": "Turma atualizada!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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
            
        if not response.data:
            raise HTTPException(status_code=403, detail="Colaborador inativo.")
        
        funcionario = response.data[0]
        
        return {
            "id_colaborador": funcionario['id_colaborador'],
            "nome": funcionario['nome_completo'],
            "telefone": funcionario['telefone'],
            "email_contato": funcionario['email'],
            "cargo": funcionario['tb_cargos']['nome_cargo'],
            "nivel": funcionario['tb_cargos']['nivel_acesso'],
            "unidade": funcionario['id_unidade'] # Retorna a unidade também
        }
    except Exception as e:
        print(f"Erro dados func: {e}")
        raise HTTPException(status_code=403, detail="Erro interno")

@app.post("/admin/cadastrar-aluno")
def admin_cadastrar_aluno(dados: NovoAlunoData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token) # Pega contexto (unidade e id_colaborador)
    
    try:
        # 1. Criar Auth
        user_auth = supabase.auth.admin.create_user({
            "email": dados.email,
            "password": dados.senha,
            "email_confirm": True 
        })
        new_user_id = user_auth.user.id

        nasc_formatado = None
        if dados.data_nascimento:
            nasc_formatado = dados.data_nascimento.replace("-", "")[:8]

        # 2. Inserir Aluno (COM UNIDADE)
        aluno_resp = supabase.table("tb_alunos").insert({
            "nome_completo": dados.nome,
            "cpf": dados.cpf,
            "email": dados.email,
            "celular": dados.celular,
            "telefone": dados.telefone,
            "data_nascimento": nasc_formatado,
            "user_id": new_user_id,
            "id_unidade": ctx['id_unidade'] # O aluno pertence à cidade de quem cadastrou
        }).execute()
        
        if not aluno_resp.data: raise Exception("Erro ao inserir aluno")
        novo_id_aluno = aluno_resp.data[0]['id_aluno']

        # 3. Matrícula
        supabase.table("tb_matriculas").insert({
            "id_aluno": novo_id_aluno,
            "codigo_turma": dados.turma_codigo,
            "id_vendedor": ctx['id_colaborador'],
            "status_financeiro": "Ok"
        }).execute()

        return {"message": "Aluno cadastrado com sucesso!"}

    except Exception as e:
        print(f"Erro cadastro: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/admin/listar-alunos")
def admin_listar_alunos(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)

    try:
        query = supabase.table("tb_alunos").select("*, tb_matriculas(codigo_turma, status_financeiro)")
        
        # Filtro de Cidade
        if ctx['nivel'] < 9:
            query = query.eq("id_unidade", ctx['id_unidade'])

        return query.execute().data
    except: return []

@app.post("/admin/agendar-reposicao")
def admin_reposicao(dados: ReposicaoData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    # Reposição não tem id_unidade direto, ela herda da Turma ou Aluno
    # Mas a verificação de conflito deve ser global ou por prof (que já filtra implicitamente)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        dt_repo_inicio = datetime.strptime(dados.data_hora, "%Y-%m-%dT%H:%M")
        dt_repo_fim = dt_repo_inicio + timedelta(hours=1) 

        # --- VERIFICAR CONFLITOS ---
        resp_turmas = supabase.table("tb_turmas")\
            .select("*")\
            .eq("id_professor", dados.id_professor)\
            .in_("status", ["Em Andamento", "Planejada"])\
            .execute()

        for turma in resp_turmas.data:
            if not turma['data_inicio'] or not turma['qtd_aulas'] or not turma['horario']: continue

            dt_inicio_turma = datetime.strptime(turma['data_inicio'], "%Y-%m-%d")
            dia_alvo = DIAS_MAPA.get(turma['dia_semana'].split("-")[0].strip(), 0)
            dias_diff = (dia_alvo - dt_inicio_turma.weekday() + 7) % 7
            dt_aula_atual = dt_inicio_turma + timedelta(days=dias_diff)

            hora_str = turma['horario'].split("-")[0].strip()
            hora_h, hora_m = map(int, hora_str.split(":"))

            for _ in range(turma['qtd_aulas']):
                inicio_aula = dt_aula_atual.replace(hour=hora_h, minute=hora_m)
                fim_aula = inicio_aula + timedelta(hours=2, minutes=30)

                if (dt_repo_inicio < fim_aula) and (dt_repo_fim > inicio_aula):
                    msg_erro = f"Conflito! O Prof. já tem aula da turma {turma['codigo_turma']} neste horário."
                    raise HTTPException(status_code=409, detail=msg_erro)

                dt_aula_atual += timedelta(days=7)

        # Salvar Reposição
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
        
        return {"message": "Reposição agendada com sucesso!"}

    except HTTPException as he: raise he
    except Exception as e:
        print(f"Erro reposição: {e}")
        raise HTTPException(status_code=400, detail="Erro interno ao agendar.")
        
@app.get("/admin/agenda-geral")
def admin_agenda(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token) # Para saber a cidade

    try:
        eventos = []

        # --- 1. BUSCAR REPOSIÇÕES (Filtrado por cidade via Aluno ou Turma) ---
        # Como tb_reposicoes nao tem id_unidade, filtramos depois ou fazemos join complexo.
        # Solução simples: Buscamos e filtramos no Python se necessario, 
        # mas idealmente tb_reposicoes deveria ter id_unidade ou filtrar pelos alunos da unidade.
        
        # Vamos buscar os IDs de alunos desta unidade primeiro
        if ctx['nivel'] < 9:
            alunos_unidade = supabase.table("tb_alunos").select("id_aluno").eq("id_unidade", ctx['id_unidade']).execute()
            ids_permitidos = [a['id_aluno'] for a in alunos_unidade.data]
            
            resp_repo = supabase.table("tb_reposicoes")\
                .select("*, tb_alunos(nome_completo), tb_colaboradores(nome_completo)")\
                .in_("id_aluno", ids_permitidos)\
                .execute()
        else:
            resp_repo = supabase.table("tb_reposicoes")\
                .select("*, tb_alunos(nome_completo), tb_colaboradores(nome_completo)")\
                .execute()
        
        for rep in resp_repo.data:
            nome_aluno = "Aluno?"
            if rep.get('tb_alunos') and rep['tb_alunos'].get('nome_completo'):
                nome_aluno = rep['tb_alunos']['nome_completo']
            elif rep.get('id_aluno'):
                nome_aluno = f"Aluno #{rep['id_aluno']}"

            nome_prof = "?"
            if rep.get('tb_colaboradores') and rep['tb_colaboradores'].get('nome_completo'):
                nome_prof = rep['tb_colaboradores']['nome_completo']
            
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

        # --- 2. BUSCAR TURMAS (Aulas Recorrentes) ---
        query_turmas = supabase.table("tb_turmas")\
            .select("*, tb_colaboradores(nome_completo)")\
            .in_("status", ["Em Andamento", "Planejada"])
            
        if ctx['nivel'] < 9:
            query_turmas = query_turmas.eq("id_unidade", ctx['id_unidade'])
            
        resp_turmas = query_turmas.execute()

        for turma in resp_turmas.data:
            if not turma['data_inicio'] or not turma['qtd_aulas'] or not turma['horario']: continue
            
            try:
                dt_inicio = datetime.strptime(turma['data_inicio'], "%Y-%m-%d")
                dia_str = turma['dia_semana'].split("-")[0].strip()
                dia_alvo = DIAS_MAPA.get(dia_str, 0) 
                dias_diff = (dia_alvo - dt_inicio.weekday() + 7) % 7
                dt_atual = dt_inicio + timedelta(days=dias_diff)
                hora_ini = turma['horario'].split("-")[0].strip()
                
                nome_prof_t = "Sem Prof"
                if turma.get('tb_colaboradores'): nome_prof_t = turma['tb_colaboradores']['nome_completo']

                for i in range(turma['qtd_aulas']):
                    start_iso = f"{dt_atual.strftime('%Y-%m-%d')}T{hora_ini}:00"
                    eventos.append({
                        "id": f"aula-{turma['codigo_turma']}-{i}",
                        "title": f"📚 {turma['codigo_turma']} - {turma['nome_curso']} ({nome_prof_t})",
                        "start": start_iso,
                        "color": "#0088cc",
                        "tipo": "aula"
                    })
                    dt_atual += timedelta(days=7)
            except: continue

        return eventos

    except Exception as e:
        print(f"Erro agenda: {e}")
        return []
        
@app.patch("/admin/reposicao/{id_repo}")
def atualizar_reposicao(id_repo: str, dados: ReposicaoUpdate, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        supabase.table("tb_reposicoes").update({
            "presenca": dados.presenca,
            "observacoes": dados.observacoes
        }).eq("id", id_repo).execute()
        return {"message": "Atualizado!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/admin/reposicao-completa/{id_repo}")
def atualizar_reposicao_completa(
    id_repo: str,
    presenca: str = Form(...),
    observacoes: str = Form(None),
    arquivo: UploadFile = File(None),
    authorization: str = Header(None)
):
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
            
            supabase.storage.from_("listas-chamada").upload(
                file_path, file_content, file_options={"content-type": arquivo.content_type, "upsert": "true"}
            )
            public_url = supabase.storage.from_("listas-chamada").get_public_url(file_path)
            updates["arquivo_assinatura"] = public_url

        supabase.table("tb_reposicoes").update(updates).eq("id", id_repo).execute()
        return {"message": "Atualizado!"}
    except Exception as e:
        print(f"Erro upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- NOVAS ROTAS CRM (Com Filtro de Cidade) ---

@app.get("/admin/leads-crm")
def get_leads_crm(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token) # Pega cidade
    
    try:
        # Filtra leads pela cidade do vendedor logado
        query = supabase.table("inscricoes").select("*").order("created_at", desc=True)
        if ctx['nivel'] < 9:
            query = query.eq("id_unidade", ctx['id_unidade'])
            
        leads = query.execute().data

        # Comparação com CPFs também deve ser filtrada? Não necessariamente, mas ajuda performance
        resp_alunos = supabase.table("tb_alunos").select("cpf").execute()
        cpfs_alunos = set()
        for a in resp_alunos.data:
            if a.get('cpf'):
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
        raise HTTPException(status_code=500, detail="Erro CRM")

@app.patch("/admin/leads-crm/{id_inscricao}")
def atualizar_status_lead(id_inscricao: int, dados: StatusUpdateData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    
    try:
        token = authorization.split(" ")[1]
        ctx = get_contexto_usuario(token) # Pega os dados de quem está logado
        
        # --- REGRA DE PERMISSÃO ---
        # Apenas Vendedor (3), Coordenador (4) ou Gerente/Admin (8, 9, 10) podem editar
        # Professores (5) e Atendentes (2) só olham.
        permissoes_edicao = [3, 4, 8, 9, 10]
        
        if ctx['nivel'] not in permissoes_edicao:
            raise HTTPException(status_code=403, detail="Você não tem permissão para editar leads.")

        # Busca o nome para registrar quem alterou
        resp_colab = supabase.table("tb_colaboradores").select("nome_completo").eq("user_id", ctx['user_id']).execute()
        nome_vendedor = resp_colab.data[0]['nome_completo']

        # Atualiza
        supabase.table("inscricoes").update({
            "status": dados.status,
            "vendedor": nome_vendedor
        }).eq("id", id_inscricao).execute()
        
        return {"message": "Status atualizado"}
        
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Erro update lead: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")

@app.patch("/admin/meus-dados")
def atualizar_meu_perfil(dados: PerfilUpdateData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        updates_tabela = {}
        if dados.nome: updates_tabela["nome_completo"] = dados.nome.upper()
        if dados.telefone: updates_tabela["telefone"] = dados.telefone
        if dados.email_contato: updates_tabela["email"] = dados.email_contato
            
        if updates_tabela:
            supabase.table("tb_colaboradores").update(updates_tabela).eq("user_id", user_id).execute()

        updates_auth = {}
        if dados.email_login: updates_auth["email"] = dados.email_login
        if dados.nova_senha and len(dados.nova_senha) >= 6: updates_auth["password"] = dados.nova_senha
            
        if updates_auth: supabase.auth.update_user(updates_auth)

        return {"message": "Perfil atualizado!"}
    except Exception as e:
        print(f"Erro perfil: {e}")
        raise HTTPException(status_code=500, detail="Erro interno")
        
@app.get("/admin/listar-professores")
def admin_listar_professores(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        # Filtra professores pela unidade do usuário (exceto Diretores)
        query = supabase.table("tb_colaboradores").select("id_colaborador, nome_completo").eq("id_cargo", 6)
        if ctx['nivel'] < 9:
            query = query.eq("id_unidade", ctx['id_unidade'])
            
        return query.execute().data
    except: return []

# Listar Turmas para Selects (Cadastro Aluno) - Com filtro
@app.get("/admin/listar-turmas")
def admin_listar_turmas(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        query = supabase.table("tb_turmas").select("*")
        if ctx['nivel'] < 9:
            query = query.eq("id_unidade", ctx['id_unidade'])
        return query.execute().data
    except: return []

