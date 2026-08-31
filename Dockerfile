# 1. Usa um servidor Linux oficial já com Node.js instalado
FROM node:22-bookworm

# 2. Atualiza o sistema e instala o Python e a placa de som virtual (libsndfile)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 3. Define a pasta de trabalho do nosso app
WORKDIR /usr/src/app

# 4. Copia os arquivos do Node e instala
COPY package*.json ./
RUN npm install

# 5. Copia as dependências do Python e instala em um ambiente isolado na nuvem
COPY requirements.txt ./
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copia todo o resto do código da RQS-DAW
COPY . .

# 7. Libera a porta de comunicação
EXPOSE 8080

ENV PORT=8080

# 8. O Comando de Ignição Definitivo (Node estrangulado em 80MB de RAM máxima)
CMD ["node", "server.js"]

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 /lambda-adapter /opt/extensions/lambda-adapter

# 9. Copia os arquivos do Node e instala
COPY package*.json ./
RUN npm install

# 10. 🟢 FORÇA A INSTALAÇÃO DO SDK S3 DIRETAMENTE NO DOCKER (Ignora qualquer conflito de lockfile) [1]
RUN npm install @aws-sdk/client-s3 @aws-sdk/s3-request-presigner

# 11. 🟢 FORÇA A INSTALAÇÃO DO SDK S3, SUPABASE E STRIPE DIRETAMENTE NO DOCKER [1]
RUN npm install @aws-sdk/client-s3 @aws-sdk/s3-request-presigner @supabase/supabase-js stripe

# 12. Instala a versão leve do PyTorch e Torchaudio focada em CPU [1.1.2]
RUN /opt/venv/bin/pip3 install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# 13. Instala a biblioteca do Demucs logo em seguida [1.1.2]
RUN /opt/venv/bin/pip3 install --no-cache-dir demucs

# 14. 🟢 SRE PRE-BAKE: Define a pasta permanente de cache de pesos do PyTorch dentro da imagem
ENV TORCH_HOME=/usr/src/app/torch_cache

# 15. Força o download dos pesos do modelo (1 GB) durante o build do Docker na sua máquina
RUN /opt/venv/bin/python3 -c "import os; os.environ['TORCH_HOME']='/usr/src/app/torch_cache'; from demucs.pretrained import get_model; get_model('htdemucs_6s')"

# V1 CPU portability only: validated upstream 0.9.23 / -mavx (PR #466).
# Install last so dependency resolution cannot replace the approved native wheel.
COPY vendor/pedalboard/pedalboard-0.9.23-cp311-cp311-linux_x86_64.whl /opt/pedalboard-portable/
RUN echo 'd0175688816effb48878c84e0f626e31f735d5b21f338354762546e13b10bca9  /opt/pedalboard-portable/pedalboard-0.9.23-cp311-cp311-linux_x86_64.whl' | sha256sum -c - \
    && /opt/venv/bin/pip install --no-index --no-deps --force-reinstall /opt/pedalboard-portable/pedalboard-0.9.23-cp311-cp311-linux_x86_64.whl \
    && /opt/venv/bin/pip check
