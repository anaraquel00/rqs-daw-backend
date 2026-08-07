import sys
import os
import argparse
import json
import logging

# Redireciona todos os logs do Python estritamente para o stderr [14]
# Isso impede que mensagens informativas de depuração quebrem o parseador JSON do Node.js
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("core_dsp_entrypoint")

# Adiciona o diretório atual ao sys.path para garantir que localiza o pacote dsp [13]
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from mastering_engine.pipeline.mastering import MasteringPipeline


def main():
    parser = argparse.ArgumentParser(description="Ponto de entrada CLI do motor de masterização RQS [12]")
    parser.add_argument("input_path", type=str, help="Caminho físico para o WAV original de entrada")
    parser.add_argument("output_path", type=str, help="Caminho físico para salvar o WAV masterizado de saída")
    parser.add_argument("--task_id", type=str, default="cli_job", help="ID exclusivo da tarefa assíncrona")
    parser.add_argument("--profile", type=str, default="clear_sky", help="Perfil acústico de estúdio")
    parser.add_argument("--preview", action="store_true", help="Gera preview otimizado de 15 segundos (ZLP)")
    parser.add_argument("--params_json", type=str, default="{}", help="Parâmetros customizados de override do Angular em formato JSON")
    
    args = parser.parse_args()
    
    try:
        # Recupera as configurações de custom overrides do Angular
        custom_params = {}
        if args.params_json:
            try:
                custom_params = json.loads(args.params_json)
            except json.JSONDecodeError as jde:
                logger.error(f"Erro ao parsear params_json: {jde}")
                
        # Instancia e roda o pipeline
        pipeline = MasteringPipeline(task_id=args.task_id, profile_name=args.profile)
        
        report = pipeline.masterize(
            input_path=args.input_path,
            output_path=args.output_path,
            is_preview=args.preview,
            custom_overrides=custom_params
        )
        
        # Saída padrão (stdout) dedicada estrita e exclusivamente para o relatório JSON final [5.2]
        # O Node.js lerá exatamente este dump de texto para salvar no banco e enviar ao Frontend
        print(json.dumps(report, indent=2))
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Falha catastrófica na execução da CLI do core_dsp: {str(e)}", exc_info=True)
        # Retorna o status de erro e cospe a mensagem formatada para tratamento no Express
        error_payload = {
            "task_id": args.task_id,
            "status": "failed",
            "error": str(e)
        }
        print(json.dumps(error_payload))
        sys.exit(1)


if __name__ == "__main__":
    main()