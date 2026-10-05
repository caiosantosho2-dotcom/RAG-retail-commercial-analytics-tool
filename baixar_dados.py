"""Baixa a base completa do Dunnhumby "The Complete Journey" para data/raw/.

Requer credencial do Kaggle configurada pelo próprio usuário
(~/.kaggle/kaggle.json ou variáveis de ambiente). Este script nunca lê o conteúdo
da credencial: quem a usa é a CLI do Kaggle.

Uso: python baixar_dados.py
"""

import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent
TABELAS_ESPERADAS = [
    "transaction_data", "product", "hh_demographic", "campaign_table",
    "campaign_desc", "coupon", "coupon_redempt", "causal_data",
]


def main() -> int:
    cfg = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
    destino = RAIZ / cfg["dados"]["pasta_raw"]
    destino.mkdir(parents=True, exist_ok=True)

    faltando = [t for t in TABELAS_ESPERADAS if not (destino / f"{t}.csv").exists()]
    if not faltando:
        print(f"Os {len(TABELAS_ESPERADAS)} arquivos já estão em {destino}. Nada a baixar.")
        return 0

    print(f"Baixando {cfg['dados']['kaggle_dataset']} para {destino} ...")
    resultado = subprocess.run(
        [sys.executable, "-m", "kaggle", "datasets", "download",
         "-d", cfg["dados"]["kaggle_dataset"], "-p", str(destino), "--unzip"],
    )
    if resultado.returncode != 0:
        print("Falha no download. Confira a credencial do Kaggle (kaggle.json ou "
              "variáveis de ambiente) e se você aceitou os termos do dataset no site.")
        return resultado.returncode

    for zip_sobrando in destino.glob("*.zip"):
        with zipfile.ZipFile(zip_sobrando) as z:
            z.extractall(destino)
        zip_sobrando.unlink()

    ainda_faltando = [t for t in TABELAS_ESPERADAS if not (destino / f"{t}.csv").exists()]
    if ainda_faltando:
        print(f"Download concluído, mas faltam arquivos: {ainda_faltando}")
        return 1
    print("Download concluído.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
