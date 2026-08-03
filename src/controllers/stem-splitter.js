const express = require('express');
const router = express.Router();
const multer = require('multer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// 🟢 MÓDULO S3: SDKs oficiais da AWS para o fluxo de alta performance [1.3.0]
const { S3Client, GetObjectCommand, PutObjectCommand } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");

// Inicializa o S3Client apontando para São Paulo [1.3.0]
const s3Client = new S3Client({ region: "sa-east-1" });
const BUCKET_NAME = "amzn-rqs-bunker-sa";

const uploadDir = '/tmp/';

// Configuração do Multer antigo (Fail-Safe legado para compatibilidade)
const storage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, uploadDir),
    filename: (req, file, cb) => cb(null, `${Date.now()}-${file.originalname}`)
});
const upload = multer({ storage });

// ======================================================================================
// 🟢 ROTA S3 NOVA: POST /stems/split-s3 (Fluxo de Alta Performance com S3 Bypass) [1.1.2]
// ======================================================================================
router.post('/split-s3', async (req, res) => {
    const s3Key = req.body.s3Key;
    if (!s3Key) {
        console.error('[CRITICAL S3] Erro de validação: s3Key está ausente no payload.');
        return res.status(400).json({ error: 'Payload inválido: A propriedade "s3Key" é obrigatória.' });
    }

    console.log(`[STEM SPLITTER S3] Iniciando dissecação acústica baseada em S3 para: ${s3Key}`);
    
    const timestamp = Date.now();
    const baseName = path.basename(s3Key).replace(/^\d+_/, ""); // Ex: VIGNETTE_MAIN.wav
    const trackName = baseName.replace(/\.[^/.]+$/, ""); // Ex: VIGNETTE_MAIN
    
    const inputPath = path.join(uploadDir, `stems_in_${timestamp}_${baseName}`);
    const outputDir = uploadDir;
    const scriptPath = path.join(__dirname, 'core_demucs.py');

    let zipPath = '';
    let errorLog = '';

    // Função de Limpeza de Emergência (Higienização de Disco)
    const cleanup = (inFile, zipFile) => {
        if (inFile && fs.existsSync(inFile)) {
            try { fs.unlinkSync(inFile); } catch (e) { console.error('Erro de cleanup:', e); }
        }
        if (zipFile && fs.existsSync(zipFile)) {
            try { fs.unlinkSync(zipFile); } catch (e) { console.error('Erro de cleanup:', e); }
        }
    };

    try {
        // 1. BAIXAR O ARQUIVO ORIGINAL DO S3 BUNKER EM MILISSEGUNDOS [1.1.2]
        console.log(`[S3 PIPELINE] Baixando ${s3Key} para o disco efêmero...`);
        const downloadCommand = new GetObjectCommand({ Bucket: BUCKET_NAME, Key: s3Key });
        const s3Response = await s3Client.send(downloadCommand);

        await new Promise((resolve, reject) => {
            const fileStream = fs.createWriteStream(inputPath);
            s3Response.Body.pipe(fileStream);
            s3Response.Body.on("error", reject);
            fileStream.on("finish", resolve);
        });
        console.log('[S3 PIPELINE] Áudio original baixado com sucesso!');

        // 2. DISPARAR O MOTOR PYTHON DEMUCS
        const venvPython = '/opt/venv/bin/python3';
        const pyProcess = spawn(venvPython, [scriptPath, inputPath, outputDir]);

        pyProcess.stdout.on('data', (data) => {
            const output = data.toString();
            console.log(`[DEMUCS INFO]: ${output.trim()}`);
            if (output.includes('SUCCESS:')) {
                zipPath = output.split('SUCCESS:')[1].trim();
            }
        });

        pyProcess.stderr.on('data', (data) => {
            errorLog += data.toString();
            console.error(`[DEMUCS ERRO]: ${data.toString()}`);
        });

        pyProcess.on('close', async (code) => {
            if (code !== 0 || !zipPath) {
                cleanup(inputPath, zipPath);
                return res.status(500).json({ error: 'Falha crítica na matriz do Demucs.', log: errorLog });
            }

            console.log('[STEM SPLITTER] Processamento concluído. Enviando ZIP para o S3...');

            // 3. ENVIAR O ZIP RESULTANTE PARA O S3 BUNKER
            const zipFileName = path.basename(zipPath); // Ex: "VIGNETTE_MAIN_stems.zip"
            const masterS3Key = `stems/${Date.now()}_${zipFileName}`;
            
            const fileBuffer = fs.readFileSync(zipPath);
            const uploadCommand = new PutObjectCommand({
                Bucket: BUCKET_NAME,
                Key: masterS3Key,
                Body: fileBuffer,
                ContentType: "application/zip"
            });

            try {
                await s3Client.send(uploadCommand);
                console.log(`[STEM SPLITTER] ZIP de Stems enviado com sucesso: ${masterS3Key}`);

                // 4. GERAR URL DE DOWNLOAD ASSINADA COM NOME LIMPO DO USUÁRIO
                const getCommand = new GetObjectCommand({
                    Bucket: BUCKET_NAME,
                    Key: masterS3Key,
                    ResponseContentDisposition: `attachment; filename="${trackName}_stems.zip"`
                });
                const downloadUrl = await getSignedUrl(s3Client, getCommand, { expiresIn: 900 });

                // Limpeza local preventiva do /tmp
                cleanup(inputPath, zipPath);

                res.status(200).json({ success: true, downloadUrl });
            } catch (s3Err) {
                console.error("[CRITICAL] Falha ao enviar ou assinar o ZIP de Stems no S3:", s3Err);
                cleanup(inputPath, zipPath);
                if (!res.headersSent) res.status(500).json({ error: 'Falha ao salvar o ZIP no S3.' });
            }
        });

    } catch (error) {
        console.error('[CRITICAL S3] Falha geral no roteador de Stems S3:', error.message);
        cleanup(inputPath, zipPath);
        if (!res.headersSent) res.status(500).json({ error: 'Erro no roteamento interno S3.', details: error.message });
    }
});

// 2. A Rota de Processamento (/api/v1/stems/split)
router.post('/split', upload.single('audio'), (req, res) => {
    if (!req.file) {
        return res.status(400).json({ error: 'Nenhum áudio recebido pela matriz.' });
    }

    const inputPath = req.file.path;
    const outputDir = uploadDir;
    const scriptPath = path.join(__dirname, 'core_demucs.py');

    console.log(`[STEM SPLITTER] Iniciando extração molecular para: ${inputPath}`);

    // ====================================================================
    // 3. Invoca o Motor Python com Roteamento Absoluto do Contêiner Docker
    // ====================================================================
    // 🟢 CORREÇÃO: Aponta exatamente para o venv definido na Linha 17 da sua Dockerfile!
    const venvPython = '/opt/venv/bin/python3'; 
    const pyProcess = spawn(venvPython, [scriptPath, inputPath, outputDir]);

    let zipPath = '';
    let errorLog = '';

    pyProcess.stdout.on('data', (data) => {
        const output = data.toString();
        console.log(`[DEMUCS INFO]: ${output.trim()}`);
        if (output.includes('SUCCESS:')) {
            zipPath = output.split('SUCCESS:')[1].trim();
        }
    });

    pyProcess.stderr.on('data', (data) => {
        errorLog += data.toString();
        console.error(`[DEMUCS ERRO]: ${data.toString()}`);
    });

    // 4. Fechamento do Processo e Envio do Payload
    pyProcess.on('close', (code) => {
        if (code !== 0 || !zipPath) {
            if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
            return res.status(500).json({ error: 'Falha crítica na matriz do Demucs.', log: errorLog });
        }

        console.log('[STEM SPLITTER] Pacote blindado pronto. Iniciando transmissão...');

        res.download(zipPath, 'rqs_6_stems.zip', (err) => {
            // 5. Rotina de limpeza pós-transmissão segura no /tmp [1]
            if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
            if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath);
            
            if (err) {
                console.error('[STEM SPLITTER] Erro ao transmitir o ZIP:', err);
            } else {
                console.log('[STEM SPLITTER] 6 Stems entregues com sucesso e área limpa!');
            }
        });
    });
});

module.exports = router;