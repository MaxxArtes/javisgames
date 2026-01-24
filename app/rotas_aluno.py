from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from supabase import create_client, Client

# Mantém a mesma estratégia do projeto: backend acessa Supabase com key do servidor
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    # Evita erro silencioso em deploy
    raise RuntimeError("Variáveis SUPABASE_URL/SUPABASE_KEY não configuradas")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

router = APIRouter(prefix="/aluno", tags=["aluno"])


def _get_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Token ausente")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Formato do token inválido")
    return parts[1].strip()


def _slugify(value: str) -> str:
    value = (value or "").strip()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_user_id_from_token(token: str) -> str:
    try:
        user = supabase.auth.get_user(token)
        return user.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")


def _get_aluno_context(token: str) -> Dict[str, Any]:
    user_id = _get_user_id_from_token(token)

    aluno_resp = supabase.table("tb_alunos")        .select("id_aluno, nome_completo")        .eq("user_id", user_id)        .execute()

    if not aluno_resp.data:
        raise HTTPException(status_code=403, detail="Conta não vinculada a um aluno")

    aluno = aluno_resp.data[0]

    # Matrícula mais recente (ou ativa, se quiser filtrar por status)
    matricula_resp = (
        supabase.table("tb_matriculas")
        .select("id_matricula, codigo_turma, status_financeiro, data_matricula")
        .eq("id_aluno", aluno["id_aluno"])
        .order("data_matricula", desc=True)
        .order("id_matricula", desc=True)
        .limit(1)
        .execute()
    )

    matricula = matricula_resp.data[0] if matricula_resp.data else None

    turma = None
    if matricula and matricula.get("codigo_turma"):
        turma_resp = supabase.table("tb_turmas")            .select("codigo_turma, nome_curso, id_professor, data_inicio, qtd_aulas, status, tipo_turma")            .eq("codigo_turma", matricula["codigo_turma"])            .limit(1)            .execute()
        if turma_resp.data:
            turma = turma_resp.data[0]

    return {
        "user_id": user_id,
        "id_aluno": aluno["id_aluno"],
        "nome": aluno.get("nome_completo") or "",
        "matricula": matricula,
        "turma": turma
    }


def _fetch_cursos_didaticos() -> List[Dict[str, Any]]:
    """
    Busca cursos com módulos e aulas aninhados, e normaliza a ordenação.
    """
    resp = supabase.table("cursos")        .select("*, modulos(*, aulas(*))")        .order("ordem")        .execute()

    cursos = resp.data or []
    for c in cursos:
        c["slug"] = _slugify(c.get("slug") or c.get("titulo") or "")
        for m in c.get("modulos", []) or []:
            m["aulas"] = sorted(m.get("aulas", []) or [], key=lambda x: x.get("ordem", 0))
        c["modulos"] = sorted(c.get("modulos", []) or [], key=lambda x: x.get("ordem", 0))
    return cursos


def _flatten_aulas(curso: Dict[str, Any]) -> List[Dict[str, Any]]:
    aulas = []
    for m in curso.get("modulos", []) or []:
        for a in m.get("aulas", []) or []:
            aulas.append({
                "id": a.get("id"),
                "titulo": a.get("titulo"),
                "modulo_id": m.get("id"),
                "modulo_titulo": m.get("titulo"),
                "ordem_modulo": m.get("ordem", 0),
                "ordem_aula": a.get("ordem", 0),
            })
    aulas.sort(key=lambda x: (x["ordem_modulo"], x["ordem_aula"]))
    # Index global para cálculo de liberação
    for idx, a in enumerate(aulas, start=1):
        a["ordem_global"] = idx
    return aulas


@router.get("/meus-cursos")
def meus_cursos(authorization: Optional[str] = Header(None)):
    """
    Retorna quais cursos o aluno pode acessar com base na matrícula.
    Mantém o formato que o frontend já usa (id = slug, data_inicio).
    """
    token = _get_bearer_token(authorization)
    ctx = _get_aluno_context(token)

    turma = ctx.get("turma")
    if not turma:
        return {"cursos": []}

    # O campo tb_turmas.curso tende a ser um texto como "DESIGNER START"
    curso_nome = (turma.get("nome_curso") or "").strip()
    curso_slug = _slugify(curso_nome)

    data_inicio = turma.get("data_inicio") or "2024-01-01"

    return {
        "cursos": [{
            "id": curso_slug,
            "data_inicio": data_inicio,
            "codigo_turma": turma.get("codigo_turma"),
            "curso_nome": curso_nome,
        }]
    }


@router.get("/curso/{curso_slug}/estrutura")
def curso_estrutura(curso_slug: str, authorization: Optional[str] = Header(None)):
    """
    Retorna a estrutura do curso (módulos/aulas) + metadados úteis.
    """
    token = _get_bearer_token(authorization)
    ctx = _get_aluno_context(token)

    turma = ctx.get("turma")
    if not turma:
        raise HTTPException(status_code=404, detail="Aluno sem turma/matrícula ativa")

    # Garante que o aluno só pega o próprio curso
    slug_matricula = _slugify((turma.get("nome_curso") or "").strip())
    if _slugify(curso_slug) != slug_matricula:
        raise HTTPException(status_code=403, detail="Curso não permitido")

    cursos = _fetch_cursos_didaticos()

    # Encontra curso por slug (se existir em cursos) ou por título
    curso = next((c for c in cursos if _slugify(c.get("slug") or c.get("titulo") or "") == slug_matricula), None)
    if not curso:
        raise HTTPException(status_code=404, detail="Curso não encontrado no didático")

    aulas_flat = _flatten_aulas(curso)
    total_aulas = len(aulas_flat)

    # Progresso automático: 1 aula liberada a cada 7 dias a partir de data_inicio
    try:
        raw_inicio = turma.get("data_inicio") or "2024-01-01"
        if isinstance(raw_inicio, str):
            di = datetime.fromisoformat(raw_inicio.replace("Z", "+00:00"))
        else:
            # caso venha como date do driver
            di = datetime.combine(raw_inicio, datetime.min.time())
        if di.tzinfo is None:
            di = di.replace(tzinfo=timezone.utc)
        hoje = datetime.now(timezone.utc)
        dias_passados = max(0, (hoje - di).days)
    except Exception:
        dias_passados = 0

    aulas_liberadas = (dias_passados // 7) + 1
    if aulas_liberadas > total_aulas:
        aulas_liberadas = total_aulas

    # Marca aulas liberadas (sem remover conteúdo)
    for m in curso.get("modulos", []) or []:
        for a in m.get("aulas", []) or []:
            # calcula ordem global para esta aula
            ord_global = next((x["ordem_global"] for x in aulas_flat if x["id"] == a.get("id")), None)
            a["ordem_global"] = ord_global
            a["liberada"] = bool(ord_global and ord_global <= aulas_liberadas)

    curso_out = dict(curso)
    curso_out["aulas_total"] = total_aulas
    curso_out["aulas_liberadas"] = aulas_liberadas
    curso_out["dias_passados"] = dias_passados
    curso_out["data_inicio"] = turma.get("data_inicio")

    return curso_out


@router.get("/aula/{id_aula}")
def obter_aula(id_aula: int, authorization: Optional[str] = Header(None)):
    """
    Retorna o conteúdo da aula (HTML ou texto com tags).
    Se houver conteúdo personalizado do professor da turma, entrega esse.
    """
    token = _get_bearer_token(authorization)
    ctx = _get_aluno_context(token)
    turma = ctx.get("turma")
    if not turma:
        raise HTTPException(status_code=404, detail="Aluno sem turma/matrícula ativa")

    # Busca a aula base
    aula_resp = supabase.table("aulas")        .select("id, titulo, conteudo, modulo_id")        .eq("id", id_aula)        .limit(1)        .execute()

    if not aula_resp.data:
        raise HTTPException(status_code=404, detail="Aula não encontrada")

    aula = aula_resp.data[0]
    conteudo = aula.get("conteudo") or ""

    # Conteúdo personalizado (por professor)
    id_professor = turma.get("id_professor")
    if id_professor:
        pers_resp = supabase.table("conteudos_personalizados")            .select("conteudo")            .eq("id_aula", id_aula)            .eq("id_professor", id_professor)            .limit(1)            .execute()
        if pers_resp.data and pers_resp.data[0].get("conteudo"):
            conteudo = pers_resp.data[0]["conteudo"]

    return {
        "id": aula.get("id"),
        "titulo": aula.get("titulo"),
        "conteudo": conteudo,
        "updated_at": _now_iso()
    }
