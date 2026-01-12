"""
Rotas administrativas do sistema
"""
import os
from fastapi import APIRouter, HTTPException, Header, UploadFile, File, Form
from pydantic import BaseModel
from supabase import create_client, Client
from datetime import datetime, timedelta
import requests
import logging
from datetime import datetime

from app.modelos import (
    FuncionarioEdicaoData,
    PerfilUpdateData,
    ReposicaoEdicaoData,
    ReposicaoUpdate,
    TurmaData,
    NovoAlunoData,
    AlunoEdicaoData,
    ReposicaoData,
    ChatAdminReply,
    StatusUpdateData,
    NovoFuncionarioData,
    AulaConteudoData
)

# Logger
logger = logging.getLogger(__name__)

# Router
router = APIRouter(prefix="/admin", tags=["admin"])

# Configuração do Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# Credenciais Z-API
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN")
ZAPI_BASE_URL = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"

# Dicionário para traduzir dia da semana
DIAS_MAPA = {
    "Segunda": 0, "Segunda-feira": 0, "Terça": 1, "Terça-feira": 1,
    "Quarta": 2, "Quarta-feira": 2, "Quinta": 3, "Quinta-feira": 3,
    "Sexta": 4, "Sexta-feira": 4, "Sábado": 5, "Sabado": 5, "Domingo": 6
}

MAPA_CURSOS = {
    "GAME PRO": "game-pro",
    "DESIGNER START": "designer-start",
    "GAME DEV": "game-dev",
    "STREAMING": "streaming"
}


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


def calcular_previsao(data_inicio_str: str, qtd: int):
    if not data_inicio_str or not qtd:
        return None
    try:
        dt_inicio = datetime.strptime(data_inicio_str, "%Y-%m-%d")
        dias_totais = (qtd - 1) * 7
        dt_fim = dt_inicio + timedelta(days=dias_totais)
        return dt_fim.strftime("%Y-%m-%d")
    except:
        return None


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
            "id_cargo": dados['id_cargo'],
            "nivel": dados['tb_cargos']['nivel_acesso']
        }
    except Exception as e:
        print(f"Erro contexto usuario: {e}")
        raise HTTPException(status_code=401, detail="Usuário não identificado.")


# --- ROTAS ---
# As rotas serão adicionadas abaixo


# === ROTAS ADMINISTRATIVAS ===

@router.get("/listar-cargos")
def admin_listar_cargos(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        return supabase.table("tb_cargos").select("*").order("nivel_acesso").execute().data
    except: return []


@router.get("/listar-equipe")
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
        

@router.post("/cadastrar-funcionario")
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


@router.put("/editar-funcionario/{id_colaborador}")
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

@router.get("/gerenciar-turmas")
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


@router.post("/salvar-turma")
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


@router.put("/editar-turma/{codigo_original}")
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

@router.get("/meus-dados")
def get_dados_funcionario(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id # UUID do Auth
        
        response = supabase.table("tb_colaboradores")\
            .select("id_colaborador, nome_completo, telefone, email, id_cargo, id_unidade, tb_cargos!fk_cargos(nome_cargo, nivel_acesso)")\
            .eq("user_id", user_id)\
            .eq("ativo", True)\
            .execute()
            
        if not response.data: raise HTTPException(status_code=403)
        funcionario = response.data[0]
        
        return {
            "id_colaborador": funcionario['id_colaborador'],
            "user_id_auth": user_id, # <--- NOVO CAMPO IMPORTANTE (UUID)
            "nome": funcionario['nome_completo'],
            "telefone": funcionario['telefone'],
            "email_contato": funcionario['email'],
            "cargo": funcionario['tb_cargos']['nome_cargo'],
            "nivel": funcionario['tb_cargos']['nivel_acesso'],
            "unidade": funcionario['id_unidade']
        }
    except Exception as e:
        raise HTTPException(status_code=403, detail="Erro interno")

@router.get("/conteudo-didatico/cursos")
def get_conteudo_didatico(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        # 1. Buscar Cursos
        cursos_resp = supabase.table("cursos").select("*").eq("ativo", True).order("ordem").execute()
        cursos = cursos_resp.data
        
        # 2. Para cada curso, buscar módulos e aulas
        for curso in cursos:
            modulos_resp = supabase.table("modulos").select("*").eq("curso_id", curso['id']).order("ordem").execute()
            modulos = modulos_resp.data
            
            for modulo in modulos:
                aulas_resp = supabase.table("aulas").select("*").eq("modulo_id", modulo['id']).order("ordem").execute()
                modulo['aulas'] = aulas_resp.data
            
            curso['modulos'] = modulos
            
        return cursos
    except Exception as e:
        print(f"Erro ao buscar conteúdo didático: {e}")
        raise HTTPException(status_code=500, detail="Erro ao carregar conteúdo didático")

@router.get("/meus-cursos-permitidos")
def get_cursos_permitidos(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        
        # 1. Buscar o aluno pelo user_id
        aluno_resp = supabase.table("tb_alunos").select("id_aluno").eq("user_id", user_id).execute()
        if not aluno_resp.data:
            # Se não encontrar aluno, retorna uma lista vazia ou padrão para teste
            return {"cursos": []}
            
        # 2. Por enquanto, como a tabela tb_matriculas está vazia, 
        # vamos retornar todos os cursos ativos como permitidos para não bloquear o aluno.
        # No futuro, aqui deve ser feita a filtragem por matrícula real.
        cursos_resp = supabase.table("cursos").select("id, titulo").eq("ativo", True).execute()
        
        # Mapear para o formato que o frontend espera (slugs)
        mapa_slugs = {
            "GAME PRO": "game-pro",
            "DESIGNER START": "designer-start",
            "GAME DEV": "game-dev",
            "STREAMING": "streaming"
        }
        
        cursos_permitidos = []
        for c in cursos_resp.data:
            slug = mapa_slugs.get(c['titulo'].upper(), c['titulo'].lower().replace(" ", "-"))
            cursos_permitidos.append({"id": slug, "data_inicio": "2024-01-01"})
            
        return {"cursos": cursos_permitidos}
    except Exception as e:
        print(f"Erro cursos permitidos: {e}")
        return {"cursos": []}

@router.get("/conteudo-aula")
def get_conteudo_aula(titulo: str):
    try:
        # Busca a aula pelo título
        res = supabase.table("aulas").select("*").ilike("titulo", f"%{titulo}%").execute()
        
        if not res.data:
            return {
                "titulo": titulo,
                "script": "Conteúdo em breve.",
                "codigo_exemplo": "",
                "desafio": "Aguarde o desafio desta aula.",
                "caminho": ""
            }
            
        aula = res.data[0]
        conteudo_raw = aula.get('conteudo') or ""
        
        # Lógica para separar Script, Código e Desafio
        # Esperamos marcadores no banco como [SCRIPT], [CODIGO], [DESAFIO]
        script = "Bem-vindos à aula!"
        codigo = conteudo_raw
        desafio = "Pratique o que aprendeu hoje."
        
        if "[SCRIPT]" in conteudo_raw and "[CODIGO]" in conteudo_raw:
            parts = conteudo_raw.split("[CODIGO]")
            script = parts[0].replace("[SCRIPT]", "").strip()
            if "[DESAFIO]" in parts[1]:
                sub_parts = parts[1].split("[DESAFIO]")
                codigo = sub_parts[0].strip()
                desafio = sub_parts[1].strip()
            else:
                codigo = parts[1].strip()
        
        return {
            "titulo": aula['titulo'],
            "script": script,
            "codigo_exemplo": codigo,
            "desafio": desafio,
            "caminho": aula.get('caminho_arquivo', '')
        }
    except Exception as e:
        print(f"Erro conteudo aula: {e}")
        return {"titulo": titulo, "script": "Erro", "codigo_exemplo": str(e), "desafio": "", "caminho": ""}
        
# 4. CADASTRO DE ALUNO

@router.post("/cadastrar-aluno")
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


@router.get("/listar-alunos")
def admin_listar_alunos(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        # Agora buscamos também o 'tipo_turma' dentro de tb_turmas, através da matrícula
        query = supabase.table("tb_alunos").select("*, tb_matriculas(codigo_turma, status_financeiro, tb_turmas(tipo_turma, dia_semana))")
        if ctx['nivel'] < 9: query = query.eq("id_unidade", ctx['id_unidade'])
        return query.execute().data
    except Exception as e: 
        print(f"Erro listar alunos: {e}")
        return []

# 5. REPOSIÇÕES E AGENDA

@router.delete("/reposicao/{id_repo}")
def deletar_reposicao(id_repo: str, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)

    # Verifica permissão (Nível 8+ ou Criador)
    if not verificar_permissao_repo(id_repo, ctx):
        raise HTTPException(status_code=403, detail="Você não tem permissão para excluir esta reposição.")

    try:
        supabase.table("tb_reposicoes").delete().eq("id", id_repo).execute()
        return {"message": "Reposição excluída com sucesso."}
    except Exception as e:
        print(f"Erro delete repo: {e}")
        raise HTTPException(status_code=500, detail="Erro ao excluir.")
        
    return False

@router.post("/agendar-reposicao")
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
        

@router.get("/agenda-geral")
def admin_agenda(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        eventos = []
        
        # 1. BUSCA REPOSIÇÕES
        if ctx['nivel'] < 9:
            # Filtra alunos da unidade para pegar os IDs
            alunos = supabase.table("tb_alunos").select("id_aluno").eq("id_unidade", ctx['id_unidade']).execute()
            ids = [a['id_aluno'] for a in alunos.data]
            
            # Busca reposições desses alunos
            if not ids: 
                resp_repo = None # Se não tem alunos, não tem reposição
            else:
                resp_repo = supabase.table("tb_reposicoes").select("*, tb_alunos(nome_completo), tb_colaboradores(nome_completo)").in_("id_aluno", ids).execute()
        else:
            # Diretor vê tudo
            resp_repo = supabase.table("tb_reposicoes").select("*, tb_alunos(nome_completo), tb_colaboradores(nome_completo)").execute()
        
        if resp_repo and resp_repo.data:
            for rep in resp_repo.data:
                # Extrai nomes com segurança
                nome_aluno = "Aluno?"
                if rep.get('tb_alunos'): 
                    nome_aluno = rep['tb_alunos'].get('nome_completo', 'Aluno?')
                
                nome_prof = "?"
                if rep.get('tb_colaboradores'): 
                    nome_prof = rep['tb_colaboradores'].get('nome_completo', '?')
                
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
                    "arquivo": rep['arquivo_assinatura'],
                    "extendedProps": { 
                        "conteudo": rep['conteudo_aula'],
                        "id_criador": rep['criado_por']
                    }
                })

        # 2. BUSCA TURMAS (Aulas Recorrentes)
        query_t = supabase.table("tb_turmas").select("*, tb_colaboradores(nome_completo)").in_("status", ["Em Andamento", "Planejada"])
        if ctx['nivel'] < 9: 
            query_t = query_t.eq("id_unidade", ctx['id_unidade'])
        
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
    except Exception as e:
        print(f"Erro agenda: {e}") 
        return []


@router.put("/reposicao-completa/{id_repo}")
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


@router.patch("/editar-reposicao/{id_repo}")
def atualizar_dados_reposicao(id_repo: str, dados: ReposicaoEdicaoData, authorization: str = Header(None)):
    # CORREÇÃO: Usamos ReposicaoEdicaoData para não exigir todos os campos (aluno, prof, etc)
    if not authorization: raise HTTPException(status_code=401)
    
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)

    if not verificar_permissao_repo(id_repo, ctx):
        raise HTTPException(status_code=403, detail="Sem permissão para editar.")

    try:
        updates = {}
        # Só adiciona no update se o dado foi enviado
        if dados.data_hora:
            updates["data_reposicao"] = dados.data_hora
        if dados.conteudo_aula:
            updates["conteudo_aula"] = dados.conteudo_aula
            
        if updates:
            supabase.table("tb_reposicoes").update(updates).eq("id", id_repo).execute()
            
        return {"message": "Atualizado!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        

@router.patch("/reposicao/{id_repo}")
def atualizar_reposicao_status(id_repo: str, dados: ReposicaoUpdate, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    
    # Adiciona a verificação aqui também
    if not verificar_permissao_repo(id_repo, ctx):
        raise HTTPException(status_code=403, detail="Apenas o criador ou gerência pode alterar.")

    try:
        supabase.table("tb_reposicoes").update({"presenca": dados.presenca, "observacoes": dados.observacoes}).eq("id", id_repo).execute()
        return {"message": "OK"}
    except: raise HTTPException(status_code=400)

# 6. CRM / LEADS

@router.get("/leads-crm")
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


@router.patch("/leads-crm/{id_inscricao}")
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


@router.patch("/meus-dados")
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


@router.get("/listar-turmas")
def admin_listar_turmas(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        query = supabase.table("tb_turmas").select("*")
        if ctx['nivel'] < 9: query = query.eq("id_unidade", ctx['id_unidade'])
        return query.execute().data
    except: return []


@router.get("/listar-professores")
def admin_listar_professores(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    try:
        query = supabase.table("tb_colaboradores").select("id_colaborador, nome_completo").in_("id_cargo", [6, 4])
        if ctx['nivel'] < 9: query = query.eq("id_unidade", ctx['id_unidade'])
        return query.execute().data
    except: return []


@router.get("/chat/conversas-ativas")
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


@router.get("/chat/mensagens/{id_aluno}")
def admin_ler_mensagens(id_aluno: int):
    msgs = supabase.table("tb_chat").select("*").eq("id_aluno", id_aluno).order("created_at").execute()
    return msgs.data


@router.post("/chat/responder")
def admin_responder(dados: ChatAdminReply, authorization: str = Header(None)):
    if not authorization: 
        raise HTTPException(status_code=401, detail="Token ausente")
    
    try:
        token = authorization.split(" ")[1]
        ctx = get_contexto_usuario(token) # Agora traz o 'id_cargo' corretamente
        
        id_colab_save = None
        
        # LÓGICA CORRIGIDA:
        # Se for Nível 4 (Coord), 5/6 (Prof) ou >= 8 (Gerente/Diretor),
        # salvamos o ID para a mensagem aparecer no chat privado (com foto e nome).
        # Se for Nível 3 (Vendedor) ou 2 (Secretaria), fica NULL (Suporte Geral).
        
        if ctx['nivel'] >= 4:
            id_colab_save = ctx['id_colaborador']
            
        supabase.table("tb_chat").insert({
            "id_aluno": dados.id_aluno,
            "mensagem": dados.mensagem,
            "enviado_por_admin": True,
            "id_colaborador": id_colab_save
        }).execute()
        
        return {"message": "Respondido"}
    except Exception as e:
        print(f"Erro ao responder: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard-stats")
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


@router.get("/chat/historico-unificado")
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



@router.get("/aula/{id_aula}/conteudo")
def get_aula_conteudo(id_aula: int, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    
    try:
        # 1. Se for Professor (Nível 5), tenta buscar a VERSÃO DELE primeiro
        if ctx['nivel'] == 5:
            try:
                # .maybe_single() retorna None se não achar, sem dar erro
                personalizado = supabase.table("conteudos_personalizados")\
                    .select("conteudo")\
                    .eq("id_aula", id_aula)\
                    .eq("id_professor", ctx['id_colaborador'])\
                    .maybe_single()\
                    .execute()
                
                # Se achou conteúdo personalizado, retorna ele
                if personalizado.data and personalizado.data.get('conteudo'):
                    return {"html": personalizado.data['conteudo'], "tipo": "personalizado"}
            except Exception as e:
                print(f"Erro ao buscar personalizado (ignorando): {e}")

        # 2. Se não achou personalizado (ou se é Coordenação), busca o CONTEÚDO BASE
        base = supabase.table("aulas").select("conteudo").eq("id", id_aula).maybe_single().execute()
        
        if base.data and base.data.get('conteudo'):
            return {"html": base.data['conteudo'], "tipo": "base"}
        
        # 3. Se não tem em lugar nenhum, retorna vazio para começar do zero
        return {"html": "", "tipo": "vazio"}

    except Exception as e:
        print(f"Erro buscar conteudo: {e}")
        return {"html": "", "tipo": "erro"}


@router.put("/aula/{id_aula}/salvar")
def salvar_aula_conteudo(id_aula: int, dados: AulaConteudoData, authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    
    token = authorization.split(" ")[1]
    ctx = get_contexto_usuario(token)
    
    try:
        # A. COORDENAÇÃO (Nível 8+): Edita a AULA BASE (Afeta todos que não tem cópia)
        if ctx['nivel'] >= 8:
            supabase.table("aulas").update({"conteudo": dados.conteudo}).eq("id", id_aula).execute()
            return {"message": "Conteúdo BASE atualizado (Modo Coordenação)."}

        # B. PROFESSOR (Nível 5): Salva na tabela PERSONALIZADA (Cópia dele)
        elif ctx['nivel'] == 5:
            payload = {
                "id_aula": id_aula,
                "id_professor": ctx['id_colaborador'],
                "conteudo": dados.conteudo
            }
            # Upsert garante que cria se não existe, ou atualiza se já existe
            # Requer que a tabela tenha constraint unique(id_aula, id_professor)
            supabase.table("conteudos_personalizados").upsert(payload, on_conflict="id_aula,id_professor").execute()
            
            return {"message": "Sua versão personalizada foi salva!"}
        
        else:
            raise HTTPException(status_code=403, detail="Sem permissão para editar.")

    except Exception as e:
        print(f"Erro ao salvar: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar: {str(e)}")
        
@router.get("/conteudo-didatico/cursos")
def admin_listar_cursos_didaticos(authorization: str = Header(None)):
    if not authorization: raise HTTPException(status_code=401)
    try:
        # Esta consulta busca os cursos, seus módulos e as aulas vinculadas
        # Certifique-se que as tabelas 'cursos', 'modulos' e 'aulas' existem com esses nomes
        resp = supabase.table("cursos")\
            .select("*, modulos(*, aulas(*))")\
            .order("ordem")\
            .execute()
        return resp.data
    except Exception as e:
        print(f"Erro ao listar cursos didáticos: {e}")
        return []

def calcular_progresso_automatico(data_inicio_str, total_aulas):
    if not data_inicio_str:
        return 0
    
    # Converte a data de início da turma (ex: "2023-10-01")
    inicio = datetime.strptime(data_inicio_str, "%Y-%m-%d")
    hoje = datetime.now()
    
    # Calcula a diferença de dias
    dias_passados = (hoje - inicio).days
    
    # Calcula quantas aulas foram liberadas (1 a cada 7 dias)
    aulas_liberadas = (dias_passados // 7) + 1
    
    # Garante que não ultrapasse o total de aulas do curso
    aulas_liberadas = min(aulas_liberadas, total_aulas)
    
    # Retorna a porcentagem
    return round((aulas_liberadas / total_aulas) * 100)

@router.get("/aluno/meus-contatos")
def get_contatos_aluno(authorization: str = Header(None)):
    if not authorization: 
        raise HTTPException(status_code=401)
    
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        user_id = user.user.id

        # 1. Busca o ID do aluno e a turma dele
        aluno_resp = supabase.table("tb_alunos").select("id_aluno, tb_matriculas(codigo_turma)").eq("user_id", user_id).single().execute()
        if not aluno_resp.data:
            return []
        
        id_aluno = aluno_resp.data['id_aluno']
        # Pega o primeiro código de turma da lista de matrículas
        matriculas = aluno_resp.data.get('tb_matriculas', [])
        codigo_turma = matriculas[0]['codigo_turma'] if matriculas else None

        contatos = []

        # 2. Busca o Professor da Turma para chat Privado e Grupo
        if codigo_turma:
            turma_resp = supabase.table("tb_turmas").select("codigo_turma, nome_curso, id_professor, tb_colaboradores(nome_completo)").eq("codigo_turma", codigo_turma).single().execute()
            
            if turma_resp.data:
                turma = turma_resp.data
                prof = turma.get('tb_colaboradores')
                
                # Card do Grupo da Turma
                contatos.append({
                    "id": f"grupo-{codigo_turma}",
                    "nome": f"Grupo {turma['nome_curso']}",
                    "cargo": turma['nome_curso'],
                    "tipo": "Professor",
                    "codigo_turma_grupo": codigo_turma
                })

                # Card do Professor (Privado)
                if prof:
                    contatos.append({
                        "id": turma['id_professor'],
                        "nome": prof['nome_completo'],
                        "cargo": f"Prof. {turma['nome_curso']}",
                        "tipo": "Professor",
                        "codigo_turma_grupo": None
                    })

        # 3. Card da Secretaria/Suporte Geral (Sempre aparece)
        contatos.append({
            "id": "geral",
            "nome": "Suporte Javis",
            "cargo": "Secretaria / Coordenação",
            "tipo": "Admin",
            "codigo_turma_grupo": None
        })

        return contatos
    except Exception as e:
        print(f"Erro ao buscar contatos: {e}")
        return []

