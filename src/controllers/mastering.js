const express = require('express');
const router = express.Router();
const multer = require('multer');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// MÓDULO S3: SDKs oficiais da AWS para bypassar o limite de 6MB de download [1.2.6]
const { S3Client, PutObjectCommand, GetObjectCommand } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");

const s3Client = new S3Client({ region: "sa-east-1" }); // 🟢 Mapeado para São Paulo
const BUCKET_NAME = "amzn-rqs-bunker-sa";               // 🟢 Novo bucket de SP

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
        const command = new PutObjectCommand({
            Bucket: BUCKET_NAME,
            Key: s3Key,
            ContentType: "audio/wav"
        });

        const uploadUrl = await getSignedUrl(s3Client, command, { expiresIn: 900 });
        res.status(200).json({ uploadUrl, s3Key });
    } catch (error) {
        console.error("Erro ao gerar presigned URL no S3:", error);
        res.status(500).json({ error: "Falha na nuvem S3 ao gerar link de upload." });
    }
});

// ============================================================================
// ROTA 2: POST /mastering/process (Híbrida e Resiliente)
// ============================================================================
router.post('/process', upload.any(), async (req, res) => {
    try {
        console.log('[DSP ENGINE] Requisição HTTP recebida na AWS Lambda.');
        
        let inputPath = '';
        const uploadedFile = req.files && req.files.length > 0 ? req.files[0] : null;
        const s3Key = req.body.s3Key;

        // CASO A: Upload comum direto (ideal para arquivos pequenos/previews) [1.1.2]
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

        const venvPython = '/opt/venv/bin/python3';
        const pythonProcess = spawn(venvPython, [
            pythonScriptPath, 
            inputPath, 
            outputPath, 
            estilo, 
            intensidade,
            isPreview 
        ]);

        let pythonErrorOutput = '';

        pythonProcess.stdout.on('data', async (data) => {
            const output = data.toString().trim();
            console.log(`[PYTHON STDOUT]: ${output}`);
            if (output.startsWith('SUCESSO')) {
                console.log(`[DSP ENGINE] Masterização concluída com sucesso! Enviando resultado para o S3...`);
                
                // 🟢 ENVIANDO A FARE MASTERIZADA DE VOLTA PARA O S3 (Bypass do limite de 6MB de download!) [1.2.6]
                const cleanOriginalName = path.basename(inputPath).replace(/\.[^/.]+$/, "");
                const masterS3Key = `masters/RQS_MASTER_${estilo.toUpperCase()}_${Date.now()}_${cleanOriginalName}.wav`;
                const fileBuffer = fs.readFileSync(outputPath);

                const uploadMasterCommand = new PutObjectCommand({
                    Bucket: BUCKET_NAME,
                    Key: masterS3Key,
                    Body: fileBuffer,
                    ContentType: "audio/wav"
                });

                try {
                    await s3Client.send(uploadMasterCommand);
                    console.log(`[DSP ENGINE] Master enviada com sucesso para o S3: ${masterS3Key}`);

                    // Gera uma URL temporária de download direto do S3 válida por 15 minutos [1.2.6]
                    const getCommand = new GetObjectCommand({
                        Bucket: BUCKET_NAME,
                        Key: masterS3Key,
                        ResponseContentDisposition: `attachment; filename="RQS_MASTER_${estilo.toUpperCase()}_${cleanOriginalName}.wav"`
                    });
                    const downloadUrl = await getSignedUrl(s3Client, getCommand, { expiresIn: 900 });

                    // Limpeza preventiva de arquivos temporários do /tmp
                    if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                    if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);

                    // Retorna o JSON levíssimo (1 KB) com a URL de download do S3 (Sem erros de 413!) [1]
                    res.status(200).json({ 
                        success: true, 
                        downloadUrl: downloadUrl,
                        fileName: `RQS_MASTER_${estilo.toUpperCase()}_${cleanOriginalName}.wav`
                    });

                } catch (s3Err) {
                    console.error("[CRITICAL] Falha ao enviar ou gerar download URL no S3:", s3Err);
                    if (!res.headersSent) res.status(500).json({ error: "Erro ao salvar e exportar master do S3." });
                    if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                    if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                }
            } else if (output.startsWith('ERRO')) {
                console.error(`[CRITICAL] Python Reportou Erro: ${output}`);
                if (!res.headersSent) res.status(500).json({ error: output });
                if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
            }
        });

        pythonProcess.stderr.on('data', (data) => {
            pythonErrorOutput += data.toString();
            console.error(`[PYTHON STDERR]: ${data.toString()}`);
        });

        pythonProcess.on('close', (code) => {
            if (code !== 0) {
                console.error(`[CRITICAL] Processo Python finalizou com código de erro ${code}`);
                if (fs.existsSync(inputPath)) fs.unlinkSync(inputPath);
                if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
                
                if (!res.headersSent) {
                    res.status(500).json({ error: 'Falha interna no motor de DSP Python', details: pythonErrorOutput });
                }
            }
        });

    } catch (error) {
        console.error('[CRITICAL] Exceção crítica no roteador de DSP:', error);
        if (!res.headersSent) res.status(500).json({ error: 'Erro no roteamento interno' });
    }
});

module.exports = router;