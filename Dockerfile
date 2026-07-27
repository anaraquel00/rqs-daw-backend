# 1. Usa um servidor Linux oficial já com Node.js instalado
FROM node:20-bookworm

# 2. Atualiza o sistema e instala o Python e a placa de som virtual (libsndfile)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    libsndfile1 \
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
CMD ["node", "--max-old-space-size=80", "server.js"]

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 /lambda-adapter /opt/extensions/lambda-adapter