import sys
import os
os.environ['HOME'] = '/tmp'
os.environ['TORCH_HOME'] = '/tmp/torch_cache'
import subprocess
import zipfile
import shutil

def separate_and_zip(input_path, base_output_dir):
    print(f"INFO: Iniciando extração de 6 stems para {input_path}")
    
    # 1. Preparar as rotas de sistema
    # Remove a extensão do arquivo para criar o nome da pasta/zip
    track_name = os.path.splitext(os.path.basename(input_path))[0]
    demucs_out = os.path.join(base_output_dir, "demucs_extracted")
    
    # 2. Comando de Injeção no Demucs (Modelo de 6 Canais)
    # Executa o demucs CLI de forma assíncrona segura
    command = [
        sys.executable, "-m", "demucs.separate",
        "-n", "htdemucs_6s",  # O modelo nuclear de 6 stems
        "-o", demucs_out,
        input_path
    ]
    
    try:
        # Aciona o modelo pesado (Isso vai exigir bastante da CPU/GPU)
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # O Demucs cria a saída estruturada: demucs_extracted/htdemucs_6s/<nome_da_track>/
        stems_folder = os.path.join(demucs_out, "htdemucs_6s", track_name)
        
        if not os.path.exists(stems_folder):
            raise Exception(f"Falha crítica: Pasta de stems não foi gerada em {stems_folder}")

        # 3. Compactação (O Payload da Rota A)
        zip_filename = f"{track_name}_stems.zip"
        zip_filepath = os.path.join(base_output_dir, zip_filename)
        
        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(stems_folder):
                for file in files:
                    if file.endswith(".wav"):
                        file_path = os.path.join(root, file)
                        # Adiciona apenas o ficheiro .wav na raiz do zip, sem a árvore de pastas
                        zipf.write(file_path, file) 
                        
        # 4. Otimização de Servidor (Limpeza)
        # Apagamos os .wavs soltos e mantemos apenas o .zip para poupar HD
        shutil.rmtree(demucs_out)
        
        # 5. Telemetria de Retorno (O Node.js vai ler este print)
        print(f"SUCCESS:{zip_filepath}")
        
    except subprocess.CalledProcessError as e:
        # Extrai a mensagem de erro real que o Demucs cuspiu no terminal
        error_msg = e.stderr.decode('utf-8') if e.stderr else str(e)
        print(f"ERROR: Colapso no Motor Demucs -> {error_msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    # Trava de Segurança: Verifica se o Node passou os argumentos corretos
    if len(sys.argv) < 3:
        print("ERROR: Parâmetros de infraestrutura insuficientes.", file=sys.stderr)
        sys.exit(1)
        
    in_file = sys.argv[1]
    out_dir = sys.argv[2]
    
    separate_and_zip(in_file, out_dir)