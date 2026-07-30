import hashlib
from dataclasses import dataclass, field, asdict

CAMPOS = [
    "titulo", "instituicao", "classificacao_instituicao", "natureza", "area", "subarea",
    "departamento", "cidade", "estado", "pais", "modalidade",
    "titulacao_exigida", "regime", "remuneracao_ou_bolsa", "data_publicacao",
    "prazo_inscricao", "status", "link_oficial", "link_edital_pdf", "fonte",
    "trecho_comprovacao", "confianca", "observacoes",
]


@dataclass
class Vaga:
    titulo: str = ""
    instituicao: str = ""
    classificacao_instituicao: str = ""
    natureza: str = ""
    area: str = ""
    subarea: str = ""  # o que o edital declara: "Filosofia Política", "Lógica"
    departamento: str = ""
    cidade: str = ""
    estado: str = ""
    pais: str = "Brasil"
    modalidade: str = "não informado"
    titulacao_exigida: str = "não informado"
    regime: str = "não informado"
    remuneracao_ou_bolsa: str = "não informado"
    data_publicacao: str = ""
    prazo_inscricao: str = ""
    status: str = "sem prazo identificado"
    link_oficial: str = ""
    link_edital_pdf: str = ""
    fonte: str = ""
    trecho_comprovacao: str = ""
    confianca: str = "médio"
    observacoes: str = ""

    def chave(self) -> str:
        base = self.link_oficial or f"{self.instituicao}|{self.titulo}|{self.area}|{self.prazo_inscricao}"
        return hashlib.sha256(base.lower().encode()).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)
