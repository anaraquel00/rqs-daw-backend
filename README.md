# ⚙️ RQS DAW Core - Backend & DSP Engine (AWS Serverless)

Este repositório abriga o coração de processamento digital de sinais (DSP) da **RaQuel Synths Digital Audio Workstation (RQS-DAW)**. Construído sob uma arquitetura serverless no **AWS Lambda**, o backend unifica uma API de alta performance em **Node.js (Express 5)** com um motor de áudio cirúrgico em **Python 3**.

---

## 🏢 Arquitetura e Decisões de Infraestrutura (SRE)

Para contornar as restrições físicas das funções Lambda e otimizar custos, o ecossistema foi projetado sob os seguintes pilares:

*   **🚀 S3 Presigned URLs (Bypass do Limite de 6MB):** O AWS Lambda possui um limite rígido de payload de 6 MB para envio e recepção de dados via gateway [1]. Para masterizar arquivos WAV gigantes de $100\text{ MB}$, o backend fornece links pré-assinados do S3 (`getSignedUrl`) para o navegador enviar o arquivo direto ao bucket `amzn-rqs-bunker-sa` [1.2.6]. O Lambda baixa o arquivo internamente em menos de 0.1s e o devolve ao S3 após o processamento, bypassando todas as barreiras físicas [1.2.6]!
*   **💾 Higiene do Disco Efêmero `/tmp`:** O contêiner Docker na AWS opera estritamente como *Read-Only* [1]. O único diretório de escrita permitido é o `/tmp` [1]. Migramos todos os destinos de uploads do Multer e execuções do Python para o `/tmp`, garantindo limpeza física compulsória (`fs.unlinkSync`) para evitar exaustão de disco em contêineres mornos (*warm starts*) [1.1.2].
*   **🧠 Otimização de RAM (Multer Disk Storage):** Substituímos o Multer Memory Storage por `diskStorage` direto no `/tmp/` [1.1.2]. Isso impede que o Node.js retenha buffers pesados na memória heap, reduzindo o uso de RAM do Express a estáveis $25\text{ MB}$ e evitando travamentos concorrentes de `JavaScript heap out of memory` [1.1.2].
*   **🛡️ Imunidade de Logout e Socket Zumbi:** Ativamos o comando `sudo loginctl enable-linger ubuntu` no servidor Lightsail para desvincular processos de conexões SSH ativas. Adicionamos o parâmetro global `-rw_timeout 15000000` no FFmpeg para forçar o fechamento e a auto-recuperação do processo caso a conexão RTMP com o YouTube congele por mais de 15 segundos [1.1.2, 1.1.9, 1.2.1].

---

## 🐍 O Motor DSP Adaptativo (Python `core_dsp.py`)

O reator acústico em Python realiza um polimento de masterização cirúrgica sintonizado especificamente para as características dinâmicas do Suno 5.5:

*   **ZLP (Zero Latency Preview) em Milissegundos:** Ao receber uma solicitação de teste (`is_preview = true`), o script usa o `sf.info` para ler apenas os metadados em 1ms e instrui o leitor a carregar estritamente apenas os 15s centrais diretamente do S3/HD [1]. O processamento dinâmico cai de 25s para insignificantes **300 milissegundos**!
*   **Complexidade $O(N)$ (lfilter):** Substituímos convoluções pesadas $O(N \cdot M)$ de envelope por filtros IIR de primeira ordem usando `scipy.signal.lfilter`, permitindo que o script processe faixas inteiras em menos de 4 segundos de CPU [1].
*   **STFT Harshness Tamer:** Executa Transformadas Rápidas de Fourier em janelas de tempo de 46ms para identificar picos de ressonância estática na faixa de $2.5\text{ kHz}$ a $5.0\text{ kHz}$ [1.1.2]. O sistema aplica atenuações cirúrgicas reativas nas frequências agressivas [1.1.2, 1.2.2].
*   **Aceleração Harmônica do Side:** Aplica uma função de transferência não-linear tangente hiperbólica (`tanh`) nas frequências laterais acima de $5\text{ kHz}$, gerando brilho sutil e largura estéreo analógica artificial [1.2, 1.2.2].

---

## 📦 Fluxo de Deploy e Atualização de Nuvem

Como estamos hospedados no data center local de **São Paulo (`sa-east-1`)**, as compilações e atualizações de código devem ser publicadas no repositório correspondente e o cache da AWS Lambda deve ser invalidado [1].

### Script de Deploy do Backend (Executado no notebook de desenvolvimento):

```bash
# 1. Autentique o Docker local na AWS do repositório de São Paulo
aws ecr get-login-password --region sa-east-1 | docker login --username AWS --password-stdin 861276090852.dkr.ecr.sa-east-1.amazonaws.com

# 2. Gere o Build do Docker forçando descarte de cache
docker build --no-cache -t 861276090852.dkr.ecr.sa-east-1.amazonaws.com/rqs-daw-backend:v03 .

# 3. Envie a nova imagem para o Amazon ECR de São Paulo
docker push 861276090852.dkr.ecr.sa-east-1.amazonaws.com/rqs-daw-backend:v03

# 4. Force a atualização e invalidação de cache no contêiner da AWS Lambda [1]
aws lambda update-function-code \
  --region sa-east-1 \
  --function-name rqs-daw-backend \
  --image-uri 861276090852.dkr.ecr.sa-east-1.amazonaws.com/rqs-daw-backend:v03

⚙️ Especificações de Infraestrutura do Lambda (AWS Console)
Runtime: Container Image (ECR: v03) [1].
Region: Leste da América do Sul (São Paulo) sa-east-1 [1].
Memory Size: 2048 MB (Garante CPU proporcional para cálculos rápidos) [1].
Timeout: 30 segundos (Múltipla margem de segurança) [1].
Ephemeral Storage (/tmp): 4096 MB (4 GB, ideal para o tráfego pesado de stems e WAVs) [1].
IAM Role: rqs-daw-backend-role-6rwy1xo5 (com políticas AWSLambdaBasicExecutionRole e AmazonS3FullAccess ativas) [1].


