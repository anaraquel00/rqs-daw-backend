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

## 🐍 Motor de Masterização V2 (Python `mastering_v2.py` + `core_dsp.py`)

A arquitetura V2 separa o contrato de entrega e a orquestração do processamento criativo legado. `mastering_v2.py` constrói o plano de renderização a partir do destino, plataforma, Atmosphere e intensidade; `core_dsp.py` permanece como núcleo de compatibilidade para o processamento criativo quando o caráter é maior que zero.

*   **Preview V2 consistente com o render final:** o V2 seleciona os **15 segundos centrais** da fonte. Com intensidade de **0%** (`character_amount == 0.0`), o preview usa somente o finalizador de loudness/true-peak (*delivery-only*), sem entrar no núcleo criativo. Acima de 0%, o mesmo segmento pré-cortado segue para `core_dsp.py` mantendo `is_preview=True`. O WAV temporário em ponto flutuante é removido ao final do processamento.
*   **Intensidade contínua 0–100%:** a intensidade do pedido é convertida em `character_amount`. No V2 atual, esse valor escala diretamente a saturação do Side e a restauração de transientes; os demais blocos preservados da rota de compatibilidade usam a configuração V2 fixa. Em 0%, o núcleo criativo é completamente ignorado e somente o processamento de entrega é executado.
*   **Atmosphere desacoplada do legado:** Clear Sky, Thunder, Sunroof e Aurora permanecem como perfis do pedido. No DSP V2 atual, todos usam a mesma rota de compatibilidade (`clear_sky` / `media` / `blue`), evitando que os novos nomes de Atmosphere reativem regras históricas Red/Blue.
*   **Política V2 explícita no núcleo de compatibilidade:** saturação do Side e restauração de transientes seguem `character_amount`; o Side usa HPF de **100 Hz** e LPF de **15 kHz**; High Cleanup e High Compression ficam desativados; compressores Mid e Side ficam em bypass. O contrato de loudness e true-peak continua resolvido pela política de entrega (destino/plataforma, `soundcloud_mode` quando aplicável e `requested_lufs` dentro da faixa permitida), independentemente dessa rota criativa.

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

<!-- RQS_DOCS_INDEX_BEGIN -->
## RQS engineering documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Optimization baseline and decisions](docs/OPTIMIZATION.md)
- [Cleanup inventory](docs/CLEANUP.md)

Project-process truth remains in the external `PROJECT_STATE.md` checkpoint used by the RQS CORE Mastering workflow.
<!-- RQS_DOCS_INDEX_END -->
