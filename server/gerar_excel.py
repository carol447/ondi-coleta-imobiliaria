from pathlib import Path

from excel_utils import gerar_excel_final

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DADOS_DIR = ROOT_DIR / "Estados" / "SP" / "sao-paulo" / "dados"

ARQ_LISTA_CSV = DADOS_DIR / "urls_zap.csv"
ARQ_DETALHE_CSV = DADOS_DIR / "imoveis_zap_detalhes.csv"
ARQ_EXCEL_FINAL = DADOS_DIR / "dados_zap_sao_paulo.xlsx"

CAMPOS_LISTA = [
    "url",
    "preco",
    "metragem",
    "quartos",
    "localizacao",
    "descricao",
    "data_coleta",
    "hora_coleta",
]

CAMPOS_DETALHE = [
    "url",
    "preco",
    "metragem",
    "quartos",
    "anunciante",
    "localizacao",
    "descricao",
    "data_anuncio",
    "data_coleta",
    "hora_coleta",
]

if __name__ == "__main__":
    resultado = gerar_excel_final(
        arquivo_lista_csv=ARQ_LISTA_CSV,
        arquivo_detalhe_csv=ARQ_DETALHE_CSV,
        arquivo_excel_final=ARQ_EXCEL_FINAL,
        campos_lista=CAMPOS_LISTA,
        campos_detalhe=CAMPOS_DETALHE,
    )
    print("Excel final gerado com sucesso!")
    print("Pasta dos dados:", DADOS_DIR)
    print("Arquivo Excel:", resultado["arquivo_excel_final"])
    print("Total de detalhes:", resultado["total_detalhes"])
    print("Total de URLs:", resultado["total_lista"])
