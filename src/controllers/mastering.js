const express = require('express');
const router = express.Router();
const multer = require('multer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// MÓDULO S3: SDKs oficiais da AWS para bypassar o limite de 6MB de download [1.2.6]
const { S3Client, PutObjectCommand, GetObjectCommand } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");

// Inicializa o S3Client apontando para São Paulo e desativando checksums automáticos
const s3Client = new S3Client({ 
    region: "sa-east-1",
    requestChecksumCalculation: "WHEN_REQUIRED"
});
const BUCKET_NAME = "amzn-rqs-bunker-sa"; // Bucket de São Paulo

// Configuração do Multer em disco efêmero para arquivos pequenos de teste (Previews) [1.1.2]
const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, '/tmp/'),
    filename: (req, file, cb) => cb(null, `input_${Date.now()}_${file.originalname}`)
});
const upload = multer({ storage });

// ============================================================================
// ROTA 1: GET /mastering/presigned-url
// Solicita o link de upload seguro direto para o S3 (Bypass de 6MB) [1.2.6]
// ============================================================================
router.get('/presigned-url', async (req, res) => {
    try {
        const fileName = req.query.filename;
        if (!fileName) {
            return res.status(400).json({ error: "O parâmetro 'filename' é obrigatório." });
        }

        const s3Key = `uploads/${Date.now()}_${fileName}`;
        
        const fileExtension = path.extname(fileName).toLowerCase();
        let contentType;
        if (fileExtension === '.wav') {
            contentType = 'audio/wav';
        } else if (fileExtension === '.mp3') {
            contentType = 'audio/mpeg';
        } else {
            return res.status(400).json({ error: "Tipo de arquivo não suportado. Use .wav ou .mp3" });
        }

        const command = new PutObjectCommand({
            Bucket: BUCKET_NAME,
            Key: s3Key,
            ContentType: contentType
        });

        const uploadUrl = await getSignedUrl(s3Client, command, { expiresIn: 900 });
        res.status(200).json({ uploadUrl, s3Key });
    } catch (error) {
        console.error("Erro ao gerar presigned URL no S3:", error);
        res.status(500).json({ error: "Falha na nuvem S3 ao gerar link de upload." });
    }
});

// ============================================================================
// ROTA 2: POST /mastering/process (Híbrida, Inteligente e Resiliente)
// ============================================================================
router.post('/process', upload.any(), async (req, res) => {
    try {
        console.log('[DSP ENGINE] Requisição HTTP recebida na AWS Lambda.');
        
        let inputPath = '';
        const uploadedFile = req.files && req.files.length > 0 ? req.files[0] : null;
        const s3Key = req.body.s3Key;

        // CASO A: Upload comum direto (ideal para arquivos pequenos/previews)
        if (uploadedFile) {
            inputPath = uploadedFile.path;
            console.log(`[DSP ENGINE] Processando via upload direto: ${inputPath}`);
        } 
        // CASO B: Upload via S3 (Bypass de 6MB para arquivos de grande porte) [1.2.6]
        else if (s3Key) {
            console.log(`[S3 PIPELINE] Baixando arquivo do S3 para o /tmp: ${s3Key}`);
            inputPath = path.join('/tmp', `input_${Date.now()}.wav`);
            
            const downloadCommand = new GetObjectCommand({
                Bucket: BUCKET_NAME,
                Key: s3Key
            });
            const s3Response = await s3Client.send(downloadCommand);
            
            const fileStream = fs.createWriteStream(inputPath);
            await new Promise((resolve, reject) => {
                s3Response.Body.pipe(fileStream);
                s3Response.Body.on("error", reject);
                fileStream.on("finish", resolve);
            });
            console.log('[S3 PIPELINE] Áudio baixado no disco efêmero com sucesso!');
        } else {
            console.error('[CRITICAL] Nenhum arquivo ou chave S3 encontrada no payload.');
            return res.status(400).json({ error: 'Nenhum áudio recebido.' });
        }

        const estilo = req.body.estilo || 'clear_sky';
        const intensidade = req.body.intensidade || 'media';
        const outputPath = path.join('/tmp', `output_${Date.now()}.wav`);
        const pythonScriptPath = path.join(__dirname, 'core_dsp.py');
        const isPreview = req.body.preview === 'true' ? 'true' : 'false';

        console.log(`[DSP ENGINE] Acionando Python para estilo: ${estilo}, intensidade: ${intensidade}, preview: ${isPreview}`);

        // --- MAPEAR INTENSIDADE EM PARÂMETROS DECIMAIS PARA OVERRIDES DO DSP ---
        // Sincroniza perfeitamente a sua interface reativa com os novos motores de transientes e saturação Mid/Side
        let transientIntensity = 0.15;
        let saturationAmount = 0.15;
        
        if (intensidade === 'suave') {
            transientIntensity = 0.08;
            saturationAmount = 0.08;
        } else if (intensidade === 'forte') {
            transientIntensity = 0.25;
            saturationAmount = 0.25;
        }
        
        const customParams = {
            transient_intensity: transientIntensity,
            saturation_amount: saturationAmount
        };

        const venvPython = '/opt/venv/bin/python3';
        
        // Formatação refinada de argumentos nomeados compatível com a nova CLI core_dsp.py
        const pythonArgs = [
            pythonScriptPath, 
            inputPath, 
            outputPath, 
            '--task_id', `task_${Date.now()}`,
            '--profile', estilo,
            '--params_json', JSON.stringify(customParams)
        ];
        
        if (isPreview === 'true') {
            pythonArgs.push('--preview');
        }

        const pythonProcess = spawn(venvPython, pythonArgs);

        let pythonStdoutOutput = '';
        let pythonErrorOutput = '';

        // Coleta o fluxo JSON de relatório final gerado no stdout pelo Python
        pythonProcess.stdout.on('data', (data) => {
            pythonStdoutOutput += data.toString();
        });

        // Desvia todos os logs operacionais informativos do DSP para o console de erro (CloudWatch)
        pythonProcess.stderr.on('data', (data) => {
            pythonErrorOutput += data.toString();
            console.error(`[PYTHON STDERR]: ${data.toString()}`);
        });

        // Orquestração atômica de saída baseada em eventos (Evita estouros de concorrência)
        pythonProcess.on('close', async (code) => {
            console.log(`[DSP ENGINE] Processo Python finalizou com código de saída: ${code}`);
            
            if (code !== 0) {
                console.error(`[CRITICAL] Processo Python falhou. Detalhes: ${pythonErrorOutput}`);
                if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                
                if (!res.headersSent) {
                    return res.status(500).json({ 
                        error: 'Falha interna no motor de DSP Python', 
                        details: pythonErrorOutput 
                    });
                }
                return;
            }

            try {
                // Parse seguro do relatório JSON Youlean-class final do stdout
                const report = JSON.parse(pythonStdoutOutput.trim());
                
                if (report.status === 'failed') {
                    console.error(`[CRITICAL] Motor Python reportou erro de sinal: ${report.error}`);
                    if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                    if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                    
                    if (!res.headersSent) {
                        return res.status(500).json({ error: report.error });
                    }
                    return;
                }

                if (isPreview === 'true') {
                    // CASO PREVIEW: Retorna o áudio de 15s direto por binário (Blob)
                    console.log(`[DSP ENGINE] Preview concluído com sucesso! Transmitindo binário direto...`);
                    res.download(outputPath, 'rqs_preview.wav', () => {
                        if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                        if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                    });
                } else {
                    console.log(`[DSP ENGINE] Masterização completa concluída! Enviando resultado para o S3...`);
                    
                    // EXTRAÇÃO CIRÚRGICA DO NOME ORIGINAL
                    let originalName = "RQS_Track";
                    if (s3Key) {
                        const s3BaseName = path.basename(s3Key); // Ex: "1785411823580_Different Roads..."
                        originalName = s3BaseName.replace(/^\d+_/, "").replace(/\.[^/.]+$/, "");
                    } else if (uploadedFile) {
                        originalName = uploadedFile.originalname.replace(/\.[^/.]+$/, "");
                    }

                    // 🟢 SANITIZAÇÃO CRÍTICA SRE: Remove acentuação e converte travessões (–, —) em hífens comuns (-) [1.1.2]
                    // Isso evita totalmente o erro "InvalidArgument: Header value cannot be represented using ISO-8859-1" no S3! [1.1.2]
                    const sanitizedOriginalName = originalName
                        .replace(/[\u2010-\u2015]/g, "-")   // Converte En-Dashes e Em-Dashes em hífens ASCII comuns [1.1.2]
                        .normalize("NFD")                   // Desmembra caracteres complexos (ã -> a + ~) [1.1.2]
                        .replace(/[\u0300-\u036f]/g, "")    // Remove os acentos soltos do UTF-8 [1.1.2]
                        .replace(/[^a-zA-Z0-9\s_,-]/g, "");   // Remove qualquer outro caractere proibido pelo padrão ISO-8859-1 [1.1.2]

                    // Nome limpo de estúdio para o download do usuário
                    const cleanMasterName = `RQS_MASTER_${estilo.toUpperCase()}_${sanitizedOriginalName}`;
                    
                    const masterS3Key = `masters/${cleanMasterName}_${Date.now()}.wav`;
                    const fileBuffer = fs.readFileSync(outputPath);

                    const uploadMasterCommand = new PutObjectCommand({
                        Bucket: BUCKET_NAME,
                        Key: masterS3Key,
                        Body: fileBuffer,
                        ContentType: "audio/wav"
                    });

                    await s3Client.send(uploadMasterCommand);
                    console.log(`[DSP ENGINE] Master enviada com sucesso para o S3: ${masterS3Key}`);

                    const getCommand = new GetObjectCommand({
                        Bucket: BUCKET_NAME,
                        Key: masterS3Key,
                        ResponseContentDisposition: `attachment; filename="${cleanMasterName}.wav"` // 🟢 Nome sanitizado e seguro contra falhas ISO-8859-1! [1.1.2]
                    });
                    const downloadUrl = await getSignedUrl(s3Client, getCommand, { expiresIn: 900 });

                    // Higiene compulsória do disco /tmp
                    if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                    if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);

                    // Retorna o download seguro do S3 acompanhado do relatório de conformidade técnica para o Angular!
                    res.status(200).json({ 
                        success: true, 
                        downloadUrl: downloadUrl,
                        fileName: `${cleanMasterName}.wav`,
                        report: report
                    });
                }

            } catch (s3Err) {
                console.error("[CRITICAL] Falha ao processar relatório JSON ou exportar para S3:", s3Err);
                if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                if (!res.headersSent) res.status(500).json({ error: "Erro ao salvar e exportar master do S3." });
            }
        });

    } catch (error) {
        console.error('[CRITICAL] Exceção crítica no roteador de DSP:', error);
        if (!res.headersSent) res.status(500).json({ error: 'Erro no roteamento interno' });
    }
});

module.exports = router;