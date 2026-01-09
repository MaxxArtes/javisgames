"""
Modelos Pydantic para validação de dados
"""
from pydantic import BaseModel


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


class ReposicaoEdicaoData(BaseModel):
    data_hora: str | None = None
    conteudo_aula: str | None = None


class ReposicaoUpdate(BaseModel):
    presenca: bool | None = None  # True=Veio, False=Faltou, None=Pendente
    observacoes: str | None = None


class TurmaData(BaseModel):
    codigo: str
    id_professor: int | None = None
    curso: str
    dia_semana: str
    horario: str
    sala: str
    status: str
    tipo: str = "PARTICULAR"  # NOVO CAMPO: Padrão é Particular
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


class AlunoEdicaoData(BaseModel):
    nome: str | None = None
    email: str | None = None
    celular: str | None = None
    telefone: str | None = None
    cpf: str | None = None
    turma_codigo: str | None = None  # Para trocar de turma se precisar


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
