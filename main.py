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
    # Novos campos
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
    celular: str  # Obrigatório para contato
    telefone: str | None = None # Opcional
    data_nascimento: str | None = None # Vem do HTML como YYYY-MM-DD

class ReposicaoData(BaseModel):
    id_aluno: int
    data_hora: str 
    turma_codigo: str
    id_professor: int
    conteudo_aula: str
    motivo: str | None = None # Agora é opcional
    observacoes: str | None = None # Agora é opcional

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

# Função auxiliar para calcular data final (1 aula por semana)
def calcular_previsao(data_inicio_str: str, qtd: int):
    if not data_inicio_str or not qtd:
        return None
    try:
        dt_inicio = datetime.strptime(data_inicio_str, "%Y-%m-%d")
        # Subtrai 1 porque a primeira aula conta como a semana 0
        dias_totais = (qtd - 1) * 7 
        dt_fim = dt_inicio + timedelta(days=dias_totais)
        return dt_fim.strftime("%Y-%m-%d")
    except:
        return None

# --- ROTAS DE TURMAS ---

@app.get("/admin/gerenciar-turmas")
def admin_listar_turmas_completo(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        # Busca turmas e o nome do professor associado
        # Usamos !inner ou left join implicito
        response = supabase.table("tb_turmas")\
            .select("*, tb_colaboradores(nome_completo)")\
            .order("codigo_turma")\
            .execute()
        return response.data
    except Exception as e:
        print(f"Erro listar turmas: {e}")
        return []

@app.post("/admin/salvar-turma")
def admin_salvar_turma(dados: TurmaData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        # Calcula previsão automática
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
            "previsao_termino": previsao, # Salva o cálculo
            "data_termino_real": dados.data_termino_real
        }).execute()
        return {"message": "Turma criada!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/admin/editar-turma/{codigo_original}")
def admin_editar_turma(codigo_original: str, dados: TurmaData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        # Recalcula previsão ao editar
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
            "previsao_termino": previsao, # Atualiza o cálculo
            "data_termino_real": dados.data_termino_real
        }).eq("codigo_turma", codigo_original).execute()
        return {"message": "Turma atualizada!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/admin/meus-dados")
def get_dados_funcionario(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token ausente")
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        
        # --- BUSCA COM CAMPOS EXTRAS ---
        response = supabase.table("tb_colaboradores")\
            .select("id_colaborador, nome_completo, telefone, email, id_cargo, tb_cargos!fk_cargos(nome_cargo, nivel_acesso)")\
            .eq("user_id", user_id)\
            .eq("ativo", True)\
            .execute()
            
        if not response.data:
            raise HTTPException(status_code=403, detail="Usuário não é um colaborador ativo.")
        
        funcionario = response.data[0]
        
        return {
            "id_colaborador": funcionario['id_colaborador'], # IMPORTANTE
            "nome": funcionario['nome_completo'],
            "telefone": funcionario['telefone'], # IMPORTANTE
            "email_contato": funcionario['email'], # IMPORTANTE
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
        # 1. Identificar quem está cadastrando (o Vendedor)
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id_logado = user.user.id
        
        resp_colab = supabase.table("tb_colaboradores").select("id_colaborador").eq("user_id", user_id_logado).execute()
        id_vendedor_atual = resp_colab.data[0]['id_colaborador'] if resp_colab.data else None

        # 2. Criar usuário no Auth do Supabase (Login)
        user_auth = supabase.auth.admin.create_user({
            "email": dados.email,
            "password": dados.senha,
            "email_confirm": True 
        })
        new_user_id = user_auth.user.id

        # 3. Formatar data de nascimento para 8 caracteres (YYYYMMDD) se houver
        nasc_formatado = None
        if dados.data_nascimento:
            nasc_formatado = dados.data_nascimento.replace("-", "")[:8]

        # 4. Inserir na tabela de Alunos (Dados Completos)
        aluno_resp = supabase.table("tb_alunos").insert({
            "nome_completo": dados.nome,
            "cpf": dados.cpf,
            "email": dados.email, # Se tiver coluna email na tb_alunos, senão remova essa linha
            "celular": dados.celular,
            "telefone": dados.telefone,
            "data_nascimento": nasc_formatado,
            "user_id": new_user_id
        }).execute()
        
        if not aluno_resp.data:
            raise Exception("Erro ao inserir dados do aluno")

        novo_id_aluno = aluno_resp.data[0]['id_aluno']

        # 5. Inserir na tabela de Matrículas (Com Vendedor)
        supabase.table("tb_matriculas").insert({
            "id_aluno": novo_id_aluno,
            "codigo_turma": dados.turma_codigo,
            "id_vendedor": id_vendedor_atual, # Grava quem vendeu
            "status_financeiro": "Ok"
        }).execute()

        return {"message": "Aluno cadastrado com sucesso!"}

    except Exception as e:
        print(f"Erro cadastro: {e}")
        # Se der erro, tenta limpar o usuário criado no Auth para não ficar "morto"
        # (Opcional, mas boa prática)
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/admin/listar-alunos")
def admin_listar_alunos():
    try:
        response = supabase.table("tb_alunos").select("*, tb_matriculas(codigo_turma, status_financeiro)").execute()
        return response.data
    except: return []

@app.post("/admin/agendar-reposicao")
def admin_reposicao(dados: ReposicaoData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        # --- 1. PREPARAR DADOS DA REPOSIÇÃO ---
        # Converte string para objeto de data/hora
        # Formato esperado do HTML: "2024-02-20T14:30"
        dt_repo_inicio = datetime.strptime(dados.data_hora, "%Y-%m-%dT%H:%M")
        # Reposição dura 1 Hora
        dt_repo_fim = dt_repo_inicio + timedelta(hours=1) 

        # --- 2. VERIFICAR CONFLITOS COM TURMAS DO PROFESSOR ---
        # Busca todas as turmas ATIVAS deste professor
        resp_turmas = supabase.table("tb_turmas")\
            .select("*")\
            .eq("id_professor", dados.id_professor)\
            .in_("status", ["Em Andamento", "Planejada"])\
            .execute()

        for turma in resp_turmas.data:
            # Pula se faltar dados essenciais
            if not turma['data_inicio'] or not turma['qtd_aulas'] or not turma['horario']:
                continue

            # 2.1 - Calcular data da primeira aula (ajustando dia da semana)
            dt_inicio_turma = datetime.strptime(turma['data_inicio'], "%Y-%m-%d")
            dia_alvo = DIAS_MAPA.get(turma['dia_semana'].split("-")[0].strip(), 0)
            dias_diff = (dia_alvo - dt_inicio_turma.weekday() + 7) % 7
            dt_aula_atual = dt_inicio_turma + timedelta(days=dias_diff)

            # 2.2 - Pegar hora da aula (Ex: "14:00")
            hora_str = turma['horario'].split("-")[0].strip() # Pega só o inicio
            hora_h, hora_m = map(int, hora_str.split(":"))

            # 2.3 - Varrer todas as aulas dessa turma
            for _ in range(turma['qtd_aulas']):
                # Monta o DateTime exato desta aula
                inicio_aula = dt_aula_atual.replace(hour=hora_h, minute=hora_m)
                # Aula de Curso dura 2h 30min
                fim_aula = inicio_aula + timedelta(hours=2, minutes=30)

                # 2.4 - A LÓGICA DE COLISÃO
                # (InicioRepo < FimAula) E (FimRepo > InicioAula)
                if (dt_repo_inicio < fim_aula) and (dt_repo_fim > inicio_aula):
                    # CONFLITO DETECTADO!
                    msg_erro = f"Conflito! O Prof. já tem aula da turma {turma['codigo_turma']} neste horário ({inicio_aula.strftime('%d/%m %H:%M')} às {fim_aula.strftime('%H:%M')})."
                    raise HTTPException(status_code=409, detail=msg_erro)

                # Avança para a próxima semana
                dt_aula_atual += timedelta(days=7)

        # --- 3. SE NÃO HOUVE CONFLITO, SALVA ---
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

    except HTTPException as he:
        raise he # Repassa o erro de conflito para o front
    except Exception as e:
        print(f"Erro reposição: {e}")
        raise HTTPException(status_code=400, detail="Erro interno ao agendar.")
        
@app.get("/admin/agenda-geral")
def admin_agenda(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        eventos = []

        # --- 1. BUSCAR REPOSIÇÕES ---
        # Query segura que traz os dados mesmo se professor/aluno forem nulos
        resp_repo = supabase.table("tb_reposicoes")\
            .select("id, data_reposicao, motivo, observacoes, presenca, conteudo_aula, codigo_turma, arquivo_assinatura, tb_alunos(nome_completo), tb_colaboradores(nome_completo)")\
            .execute()
        
        for rep in resp_repo.data:
            # Tratamento de segurança para nomes (Evita erro se for None/Null)
            nome_aluno = "Aluno (Removido)"
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
                # DADOS EXTRAS PARA O MODAL COMPLETO:
                "nome_aluno": nome_aluno,
                "nome_prof": nome_prof,
                "conteudo": rep['conteudo_aula'],
                "turma": rep['codigo_turma'],
                "presenca": rep['presenca'],
                "observacoes": rep['observacoes'],
                "arquivo": rep['arquivo_assinatura'] # Link do arquivo se existir
            })

        # --- 2. BUSCAR TURMAS (Aulas Recorrentes) ---
        try:
            resp_turmas = supabase.table("tb_turmas")\
                .select("codigo_turma, nome_curso, dia_semana, horario, data_inicio, qtd_aulas, tb_colaboradores(nome_completo)")\
                .in_("status", ["Em Andamento", "Planejada"])\
                .execute()

            for turma in resp_turmas.data:
                # Se faltar dados vitais para o calendário, pula essa turma
                if not turma['data_inicio'] or not turma['qtd_aulas'] or not turma['horario']: 
                    continue
                
                try:
                    dt_inicio = datetime.strptime(turma['data_inicio'], "%Y-%m-%d")
                    
                    # Identifica o dia da semana (Segunda=0, ... Domingo=6)
                    dia_str = turma['dia_semana'].split("-")[0].strip()
                    dia_alvo = DIAS_MAPA.get(dia_str, 0) 
                    
                    # Ajusta a data de início para cair no dia da semana correto
                    dias_diff = (dia_alvo - dt_inicio.weekday() + 7) % 7
                    dt_atual = dt_inicio + timedelta(days=dias_diff)
                    
                    hora_ini = turma['horario'].split("-")[0].strip()
                    
                    nome_prof_t = "Sem Prof"
                    if turma.get('tb_colaboradores') and turma['tb_colaboradores'].get('nome_completo'):
                        nome_prof_t = turma['tb_colaboradores']['nome_completo']

                    # Gera as N aulas
                    for i in range(turma['qtd_aulas']):
                        # Formata para ISO (YYYY-MM-DDTHH:MM:SS)
                        start_iso = f"{dt_atual.strftime('%Y-%m-%d')}T{hora_ini}:00"
                        
                        eventos.append({
                            "id": f"aula-{turma['codigo_turma']}-{i}", # ID virtual
                            "title": f"📚 {turma['codigo_turma']} - {turma['nome_curso']} ({nome_prof_t})",
                            "start": start_iso,
                            "color": "#0088cc", # Azul
                            "tipo": "aula"
                        })
                        # Avança 1 semana
                        dt_atual += timedelta(days=7)
                except Exception as e_loop:
                    print(f"Erro ao processar turma {turma.get('codigo_turma')}: {e_loop}")
                    continue

        except Exception as e_turma:
            print(f"Erro geral ao buscar turmas: {e_turma}")
            # Não para o código, apenas loga e segue entregando as reposições

        return eventos

    except Exception as e:
        print(f"Erro CRÍTICO na agenda: {e}")
        # Retorna lista vazia para não quebrar o site
        return []
        
# ---ATUALIZAR REPOSIÇÃO ---
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
    presenca: str = Form(...),      # Recebe como string "true"/"false"
    observacoes: str = Form(None),
    arquivo: UploadFile = File(None), # Arquivo é opcional
    authorization: str = Header(None)
):
    if not authorization: raise HTTPException(status_code=401)
    
    try:
        # Converter presença para Booleano ou None
        presenca_bool = None
        if presenca == "true": presenca_bool = True
        elif presenca == "false": presenca_bool = False

        updates = {
            "presenca": presenca_bool,
            "observacoes": observacoes
        }

        # --- LÓGICA DE UPLOAD ---
        if arquivo:
            file_content = arquivo.file.read() # CORREÇÃO: read síncrono
            file_ext = arquivo.filename.split('.')[-1]
            file_path = f"assinatura_{id_repo}.{file_ext}" # Nome único
            
            # Envia para o Supabase Storage
            # bucket 'listas-chamada' deve existir
            supabase.storage.from_("listas-chamada").upload(
                file_path, 
                file_content, 
                file_options={"content-type": arquivo.content_type, "upsert": "true"}
            )
            
            # Pega URL Pública
            public_url = supabase.storage.from_("listas-chamada").get_public_url(file_path)
            updates["arquivo_assinatura"] = public_url

        # Atualiza no Banco
        supabase.table("tb_reposicoes").update(updates).eq("id", id_repo).execute()
        
        return {"message": "Dados e arquivo atualizados!"}

    except Exception as e:
        print(f"Erro upload: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/meus-cursos-permitidos")
def get_cursos_permitidos(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
